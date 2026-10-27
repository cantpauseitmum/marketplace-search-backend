"""
Główny serwer HTTP / REST API dla aplikacji MarketplaceSearch.
Działa natywnie bez zewnętrznych zależności (Python standard library http.server),
oraz udostępnia FastAPI jeśli jest zainstalowane w środowisku.
"""
import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Dict, Any

# Ścieżki projektu
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)

for p in (PARENT_DIR, CURRENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Lokalizacja katalogu frontend (MarketplaceSearch/frontend lub backend/frontend)
if os.path.exists(os.path.join(PARENT_DIR, "frontend", "index.html")):
    FRONTEND_DIR = os.path.join(PARENT_DIR, "frontend")
elif os.path.exists(os.path.join(CURRENT_DIR, "frontend", "index.html")):
    FRONTEND_DIR = os.path.join(CURRENT_DIR, "frontend")
else:
    FRONTEND_DIR = os.path.join(PARENT_DIR, "frontend")

import threading

try:
    from config import PORT, HOST
    from scrapers.aggregator import MarketplaceAggregator
    from database.db_manager import DatabaseManager
    from watchlist_scheduler import WatchlistScheduler
except ImportError:
    from backend.config import PORT, HOST
    from backend.scrapers.aggregator import MarketplaceAggregator
    from database.db_manager import DatabaseManager
    from backend.watchlist_scheduler import WatchlistScheduler

db_manager = DatabaseManager()
aggregator = MarketplaceAggregator(db_manager)
scheduler = WatchlistScheduler(db_manager, aggregator)


class MarketplaceAPIHandler(SimpleHTTPRequestHandler):
    """
    HTTP Handler obsługujący REST API oraz serwowanie plików frontendowych.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def _set_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        # 1. API: Wyszukiwanie we wszystkich serwisach
        if path == "/api/search":
            self._handle_search(query_params)
            return

        # 2. API: Pobieranie zapisanych ofert z bazy danych
        if path == "/api/offers":
            self._handle_get_offers(query_params)
            return

        # 3. API: Dostępne źródła ogłoszeń
        if path == "/api/sources":
            self._handle_get_sources()
            return

        # 4. API: Historia wyszukiwań
        if path == "/api/history":
            self._handle_get_history()
            return

        # 5. API: Lista obserwowanych (Watchlist)
        if path == "/api/watchlist":
            self._handle_get_watchlist()
            return

        # 6. API: Oferty dla konkretnego monitorowanego zapytania
        if path.startswith("/api/watchlist/") and path.endswith("/offers"):
            parts = path.strip("/").split("/")
            try:
                watched_id = int(parts[2])
                self._handle_get_watchlist_offers(watched_id, query_params)
            except Exception as e:
                self._send_json({"error": f"Niepoprawne ID zapytania: {e}"}, status=400)
            return

        # 7. API: Healthcheck
        if path in ("/health", "/api/health"):
            self._send_json({"status": "healthy", "service": "MarketplaceSearch Backend API", "version": "1.0.0"})
            return

        # 8. Obsługa favicon / ikon przeglądarki (żeby nie generować błędów 404 w logach)
        if path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            icon_file = os.path.join(FRONTEND_DIR, path.lstrip("/"))
            if not os.path.exists(icon_file):
                self._set_headers(status=204)
                return

        # 9. Serwowanie plików frontendowych (SPA)
        if os.path.exists(FRONTEND_DIR) and os.path.exists(os.path.join(FRONTEND_DIR, "index.html")):
            req_file = os.path.join(FRONTEND_DIR, path.lstrip("/"))
            if path == "/" or not os.path.exists(req_file):
                self.path = "/index.html"
            super().do_GET()
            return
        else:
            self._send_json({
                "service": "MarketplaceSearch REST API",
                "version": "1.0.0",
                "status": "running",
                "endpoints": [
                    "/api/search?q={query}&location={city}&radius={km}",
                    "/api/offers?q={query}",
                    "/api/watchlist",
                    "/api/watchlist/{id}/offers",
                    "/api/sources",
                    "/api/history",
                    "/api/health"
                ]
            })
            return

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API: Polubienie / zapisanie oferty
        if path.startswith("/api/offers/") and path.endswith("/bookmark"):
            parts = path.strip("/").split("/")
            try:
                offer_id = int(parts[2])
                new_state = db_manager.toggle_bookmark(offer_id)
                self._send_json({"success": True, "offer_id": offer_id, "is_bookmarked": new_state})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=400)
            return

        # API: Dodanie nowego zapytania do listy automatycznego przeszukiwania
        if path == "/api/watchlist":
            self._handle_add_watchlist()
            return

        # API: Usunięcie z listy obserwowanych przez POST
        if path.startswith("/api/watchlist/") and path.endswith("/delete"):
            parts = path.strip("/").split("/")
            try:
                watched_id = int(parts[2])
                self._handle_delete_watchlist(watched_id)
            except Exception as e:
                self._send_json({"error": f"Niepoprawne ID zapytania: {e}"}, status=400)
            return

        # API: Ręczne odświeżenie obserwowanego zapytania
        if path.startswith("/api/watchlist/") and path.endswith("/refresh"):
            parts = path.strip("/").split("/")
            try:
                watched_id = int(parts[2])
                self._handle_refresh_watchlist(watched_id)
            except Exception as e:
                self._send_json({"error": f"Niepoprawne ID zapytania: {e}"}, status=400)
            return

        self._send_json({"error": "Endpoint nie znaleziony"}, status=404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API: Usunięcie z listy obserwowanych przez DELETE
        if path.startswith("/api/watchlist/"):
            parts = path.strip("/").split("/")
            try:
                watched_id = int(parts[2])
                self._handle_delete_watchlist(watched_id)
            except Exception as e:
                self._send_json({"error": f"Niepoprawne ID zapytania: {e}"}, status=400)
            return

        self._send_json({"error": "Endpoint nie znaleziony"}, status=404)

    def _handle_search(self, params: Dict[str, list]):
        q = params.get("q", [""])[0].strip()
        if not q:
            self._send_json({"error": "Parametr 'q' (fraza wyszukiwania) jest wymagany"}, status=400)
            return

        location_raw = params.get("location", [""])[0].strip()
        radius_raw = params.get("radius", ["all"])[0].strip().lower()

        # Logika obszaru:
        # Wpisanie miasta daje punkt startowy, a obok wybierany jest obszar (+0km, +5km, Cała Polska).
        # Jeśli wybrano 'all' (Cała Polska) lub pole miasta jest puste -> szukamy w całej Polsce (Poznań + Cała Polska = Cała Polska)
        if radius_raw in ("all", "polska", "cala_polska", "-1", "none") or not location_raw:
            location = ""
            radius = 0
        else:
            location = location_raw
            try:
                radius = int(radius_raw)
            except ValueError:
                radius = 0

        # Paginacja
        page_raw = params.get("page", ["1"])[0]
        try:
            page = max(1, int(page_raw))
        except ValueError:
            page = 1

        in_desc_raw = params.get("in_description", ["false"])[0].lower()
        search_in_desc = in_desc_raw in ("true", "1", "yes")

        min_price = None
        if "min_price" in params and params["min_price"][0]:
            try:
                min_price = float(params["min_price"][0])
            except ValueError:
                pass

        max_price = None
        if "max_price" in params and params["max_price"][0]:
            try:
                max_price = float(params["max_price"][0])
            except ValueError:
                pass

        sources_raw = params.get("sources", [""])[0]
        sources = [s.strip() for s in sources_raw.split(",") if s.strip()] if sources_raw else None
        sort_by = params.get("sort_by", ["newest"])[0]

        try:
            results = aggregator.search_all(
                query_text=q,
                location=location,
                radius_km=radius,
                search_in_description=search_in_desc,
                min_price=min_price,
                max_price=max_price,
                sources=sources,
                sort_by=sort_by,
                page=page,
                raw_location=location_raw,
            )
            self._send_json(results)
        except Exception as e:
            self._send_json({"error": f"Wystąpił błąd podczas wyszukiwania: {str(e)}"}, status=500)

    def _handle_get_offers(self, params: Dict[str, list]):
        q = params.get("q", [None])[0]
        location = params.get("location", [None])[0]
        sources_raw = params.get("sources", [None])[0]
        sources = [s.strip() for s in sources_raw.split(",") if s.strip()] if sources_raw else None

        min_price = None
        if "min_price" in params and params["min_price"][0]:
            try:
                min_price = float(params["min_price"][0])
            except ValueError:
                pass

        max_price = None
        if "max_price" in params and params["max_price"][0]:
            try:
                max_price = float(params["max_price"][0])
            except ValueError:
                pass

        sort_by = params.get("sort_by", ["newest"])[0]
        limit = int(params.get("limit", ["50"])[0])
        offset = int(params.get("offset", ["0"])[0])
        only_bm = params.get("bookmarked", ["false"])[0].lower() in ("true", "1")

        data = db_manager.get_offers(
            query=q,
            location=location,
            sources=sources,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
            only_bookmarked=only_bm,
        )
        self._send_json(data)

    def _read_body_json(self) -> Dict[str, Any]:
        """Bezpiecznie odczytuje i parsuje ciało żądania POST/PUT jako JSON."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw_body)
        except Exception as e:
            print(f"[API] Błąd odczytu JSON: {e}")
        return {}

    def _handle_get_watchlist(self):
        """Zwraca listę wszystkich aktywnych monitorowanych wyszukiwań."""
        items = db_manager.get_watched_searches(active_only=True)
        self._send_json({"watchlist": items, "count": len(items)})

    def _handle_add_watchlist(self):
        """Dodaje nowe zapytanie do obserwowanych i uruchamia pierwsze wyszukiwanie w tle."""
        data = self._read_body_json()
        query_text = (data.get("query") or data.get("query_text") or data.get("q") or "").strip()
        if not query_text:
            self._send_json({"error": "Parametr 'query' lub 'q' jest wymagany"}, status=400)
            return

        location = (data.get("location") or "").strip()
        radius_raw = data.get("radius") or data.get("radius_km") or 0
        if str(radius_raw).lower() in ("all", "polska", "cala_polska", "-1", "none") or not location:
            radius_km = 0
            if str(radius_raw).lower() in ("all", "polska", "cala_polska", "-1", "none"):
                location = ""
        else:
            try:
                radius_km = int(radius_raw)
            except (ValueError, TypeError):
                radius_km = 0

        search_in_desc = bool(data.get("in_description") or data.get("search_in_description") or False)

        min_price = None
        if data.get("min_price") is not None and str(data.get("min_price")).strip():
            try:
                min_price = float(data.get("min_price"))
            except ValueError:
                pass

        max_price = None
        if data.get("max_price") is not None and str(data.get("max_price")).strip():
            try:
                max_price = float(data.get("max_price"))
            except ValueError:
                pass

        sources = data.get("sources")
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]

        title = (data.get("title") or query_text).strip()
        sort_by = data.get("sort_by") or "newest"
        interval_seconds = int(data.get("interval_seconds") or 3600)

        item = db_manager.add_watched_search(
            query_text=query_text,
            location=location,
            radius_km=radius_km,
            search_in_description=search_in_desc,
            min_price=min_price,
            max_price=max_price,
            sources=sources,
            title=title,
            sort_by=sort_by,
            interval_seconds=interval_seconds,
        )

        # Natychmiastowe uruchomienie pierwszego wyszukiwania w tle
        if scheduler:
            threading.Thread(
                target=scheduler.check_item_now,
                args=(item["id"],),
                name=f"InitialWatchlistCheck-{item['id']}",
                daemon=True,
            ).start()

        self._send_json({"success": True, "item": item}, status=201)

    def _handle_delete_watchlist(self, watched_id: int):
        """Usuwa pozycję z automatycznego przeszukiwania."""
        success = db_manager.delete_watched_search(watched_id)
        if success:
            self._send_json({
                "success": True,
                "message": f"Pomyślnie usunięto z automatycznego przeszukiwania (ID: {watched_id})",
                "watched_id": watched_id
            })
        else:
            self._send_json({"error": "Nie znaleziono monitorowanego wyszukiwania o podanym ID"}, status=404)

    def _handle_get_watchlist_offers(self, watched_id: int, params: Dict[str, list]):
        """Zwraca aktualnie zapisane oferty dla danego zapytania z listy."""
        limit = int(params.get("limit", ["100"])[0])
        offset = int(params.get("offset", ["0"])[0])
        data = db_manager.get_offers_for_watched_search(watched_id, limit=limit, offset=offset)
        self._send_json(data)

    def _handle_refresh_watchlist(self, watched_id: int):
        """Ręcznie wymusza natychmiastowe przeszukanie danej pozycji z listy."""
        if not scheduler:
            self._send_json({"error": "Harmonogram nie jest zainicjalizowany"}, status=500)
            return

        # Uruchom synchronicznie lub w tle zależnie od parametru
        result = scheduler.check_item_now(watched_id)
        self._send_json({"success": True, "result": result})

    def _handle_get_sources(self):
        sources = aggregator.get_available_sources()
        self._send_json({"sources": sources})

    def _handle_get_history(self):
        history = db_manager.get_search_history(limit=10)
        self._send_json({"history": history})

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._set_headers(status=status, content_type="application/json")
        self.wfile.write(body)


def run_server():
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, MarketplaceAPIHandler)

    if scheduler:
        scheduler.start()

    print("=" * 65)
    print(f"🚀 MarketplaceSearch Serwer uruchomiony!")
    print(f"👉 Adres aplikacji:  http://localhost:{PORT}")
    print(f"👉 API wyszukiwania: http://localhost:{PORT}/api/search?q=konsola")
    print(f"👉 API Watchlist:    http://localhost:{PORT}/api/watchlist")
    print(f"👉 Źródła:          OLX, Allegro, Allegro Lokalnie, FB Marketplace")
    print("=" * 65)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZamykanie serwera...")
        if scheduler:
            scheduler.stop()
        httpd.server_close()


if __name__ == "__main__":
    run_server()
