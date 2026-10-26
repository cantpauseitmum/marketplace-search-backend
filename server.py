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

try:
    from config import PORT, HOST
    from scrapers.aggregator import MarketplaceAggregator
    from database.db_manager import DatabaseManager
except ImportError:
    from backend.config import PORT, HOST
    from backend.scrapers.aggregator import MarketplaceAggregator
    from database.db_manager import DatabaseManager

db_manager = DatabaseManager()
aggregator = MarketplaceAggregator(db_manager)


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

        # 5. API: Healthcheck
        if path in ("/health", "/api/health"):
            self._send_json({"status": "healthy", "service": "MarketplaceSearch Backend API", "version": "1.0.0"})
            return

        # 6. Obsługa favicon / ikon przeglądarki (żeby nie generować błędów 404 w logach)
        if path in ("/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            icon_file = os.path.join(FRONTEND_DIR, path.lstrip("/"))
            if not os.path.exists(icon_file):
                self._set_headers(status=204)
                return

        # 7. Serwowanie plików frontendowych (SPA)
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

        self._send_json({"error": "Endpoint nie znaleziony"}, status=404)

    def _handle_search(self, params: Dict[str, list]):
        q = params.get("q", [""])[0].strip()
        if not q:
            self._send_json({"error": "Parametr 'q' (fraza wyszukiwania) jest wymagany"}, status=400)
            return

        location = params.get("location", [""])[0].strip()
        radius_raw = params.get("radius", ["0"])[0]
        try:
            radius = int(radius_raw)
        except ValueError:
            radius = 0

        in_desc_raw = params.get("in_description", ["true"])[0].lower()
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
    print("=" * 65)
    print(f"🚀 MarketplaceSearch Serwer uruchomiony!")
    print(f"👉 Adres aplikacji:  http://localhost:{PORT}")
    print(f"👉 API wyszukiwania: http://localhost:{PORT}/api/search?q=konsola")
    print(f"👉 Źródła:          OLX, Allegro, Allegro Lokalnie, FB Marketplace")
    print("=" * 65)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZamykanie serwera...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
