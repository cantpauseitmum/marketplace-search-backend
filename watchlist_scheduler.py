"""
Harmonogram automatycznego przeszukiwania obserwowanych ofert (Watchlist Scheduler).
Automatycznie odpytuje serwisy co 1 godzinę (lub określony interwał) dla każdego
zapisanego zapytania z offer_list.json / bazy danych.
"""
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set
from scrapers.aggregator import MarketplaceAggregator
from database.db_manager import DatabaseManager


class WatchlistScheduler:
    """
    Zarządza okresowym przeszukiwaniem obserwowanych zapytań w tle.
    """
    def __init__(
        self,
        db_manager: DatabaseManager,
        aggregator: MarketplaceAggregator,
        check_interval_seconds: int = 15,
        default_search_interval: int = 3600,
    ):
        self.db = db_manager
        self.aggregator = aggregator
        self.check_interval_seconds = check_interval_seconds
        self.default_search_interval = default_search_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._currently_checking: Set[int] = set()

    def start(self):
        """Uruchamia wątek monitorujący w tle."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name="WatchlistSchedulerThread", daemon=True)
            self._thread.start()
            print("[WatchlistScheduler] Uruchomiono automatyczny harmonogram przeszukiwania co 1h.")

    def stop(self):
        """Zatrzymuje wątek harmonogramu."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        print("[WatchlistScheduler] Zatrzymano harmonogram.")

    def _run_loop(self):
        """Główna pętla sprawdzająca, które zapytania są gotowe do odświeżenia."""
        # Początkowe opóźnienie 5 sekund, żeby serwer zdążył wstać
        time.sleep(5)

        while self._running:
            try:
                self._check_pending_items()
            except Exception as e:
                print(f"[WatchlistScheduler] Błąd w pętli sprawdzania: {e}")

            # Czekaj z tolerancją na wyłączenie
            for _ in range(self.check_interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def _check_pending_items(self):
        """Wyszukuje pozycje z listy, które wymagają odświeżenia."""
        active_items = self.db.get_watched_searches(active_only=True)
        now_dt = datetime.now(timezone.utc)

        for item in active_items:
            item_id = item["id"]
            with self._lock:
                if item_id in self._currently_checking:
                    continue

            interval = item.get("interval_seconds") or self.default_search_interval
            last_checked = item.get("last_checked_at")

            should_check = False
            if not last_checked:
                should_check = True
            else:
                try:
                    last_dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
                    elapsed = (now_dt - last_dt).total_seconds()
                    if elapsed >= interval:
                        should_check = True
                except Exception:
                    should_check = True

            if should_check:
                # Uruchom przeszukiwanie pozycji w osobnym wątku roboczym
                t = threading.Thread(
                    target=self.check_item_now,
                    args=(item_id,),
                    name=f"WatchlistWorker-{item_id}",
                    daemon=True,
                )
                t.start()

    def check_item_now(self, watched_id: int) -> Dict[str, Any]:
        """
        Natychmiast przeszukuje dany element z listy obserwowanych.
        Może być wywołane bezpośrednio z API (np. po dodaniu do listy lub kliknięciu 'Odśwież').
        """
        with self._lock:
            if watched_id in self._currently_checking:
                return {"status": "in_progress", "watched_id": watched_id}
            self._currently_checking.add(watched_id)

        try:
            item = self.db.get_watched_search(watched_id)
            if not item:
                return {"status": "not_found", "watched_id": watched_id}

            print(f"[WatchlistScheduler] Rozpoczynam automatyczne przeszukiwanie: '{item.get('title')}' (ID: {watched_id})...")

            location_raw = item.get("location", "")
            radius = item.get("radius_km", 0)
            sources = item.get("sources")
            if not sources:
                sources = ["OLX", "Allegro Lokalnie", "Facebook Marketplace"]

            results = self.aggregator.search_all(
                query_text=item.get("query_text", ""),
                location=location_raw,
                radius_km=radius,
                search_in_description=item.get("search_in_description", False),
                min_price=item.get("min_price"),
                max_price=item.get("max_price"),
                sources=sources,
                sort_by=item.get("sort_by", "newest"),
                raw_location=location_raw,
                watched_search_id=watched_id,
            )

            count = results.get("total_count", 0)
            print(f"[WatchlistScheduler] Zakończono dla '{item.get('title')}': znaleziono {count} aktualnych ofert.")
            return {"status": "success", "watched_id": watched_id, "results_count": count}

        except Exception as e:
            print(f"[WatchlistScheduler] Błąd podczas przeszukiwania '{watched_id}': {e}")
            return {"status": "error", "watched_id": watched_id, "error": str(e)}

        finally:
            with self._lock:
                self._currently_checking.discard(watched_id)
