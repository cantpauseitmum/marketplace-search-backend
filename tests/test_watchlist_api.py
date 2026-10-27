"""
Testy integracyjne dla REST API listy monitorowanych ofert (Watchlist) i pliku offer_list.json.
"""
import unittest
import os
import sys
import json
import urllib.request
import urllib.error
import threading
from http.server import HTTPServer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
for p in (PROJECT_ROOT, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.server import MarketplaceAPIHandler, db_manager, scheduler


class TestWatchlistAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_port = 8991
        cls.server = HTTPServer(("127.0.0.1", cls.test_port), MarketplaceAPIHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.test_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_watchlist_full_api_cycle(self):
        # 1. Dodanie nowego zapytania do listy przez POST /api/watchlist
        payload = {
            "title": "Konsola Switch 2",
            "query": "Switch 2",
            "location": "Poznań",
            "radius": "25",
            "in_description": True,
            "min_price": 800.0,
            "max_price": 1800.0,
            "sources": ["OLX", "Allegro Lokalnie"],
            "sort_by": "price_asc",
            "interval_seconds": 3600,
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/watchlist",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            self.assertEqual(response.status, 201)
            data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(data.get("success"))
            item = data.get("item")
            self.assertIsNotNone(item)
            watched_id = item["id"]
            self.assertEqual(item["title"], "Konsola Switch 2")
            self.assertEqual(item["query_text"], "Switch 2")
            self.assertEqual(item["location"], "Poznań")
            self.assertEqual(item["radius_km"], 25)

        # 2. Sprawdzenie czy plik offer_list.json został utworzony i zawiera pozycję
        offer_list_file = os.path.join(PROJECT_ROOT, "offer_list.json")
        self.assertTrue(os.path.exists(offer_list_file))
        with open(offer_list_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        found_in_file = any(it["id"] == watched_id for it in disk_data)
        self.assertTrue(found_in_file)

        # 3. Pobranie listy monitorowanych przez GET /api/watchlist
        with urllib.request.urlopen(f"{self.base_url}/api/watchlist", timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            items = data.get("watchlist", [])
            self.assertTrue(any(it["id"] == watched_id for it in items))

        # 4. Sprawdzenie pobierania ofert dla danego ID przez GET /api/watchlist/{id}/offers
        with urllib.request.urlopen(f"{self.base_url}/api/watchlist/{watched_id}/offers", timeout=5) as response:
            self.assertEqual(response.status, 200)
            offers_data = json.loads(response.read().decode("utf-8"))
            self.assertIn("items", offers_data)
            self.assertIn("watched", offers_data)
            self.assertEqual(offers_data["watched"]["title"], "Konsola Switch 2")

        # 5. Usunięcie z listy przez DELETE /api/watchlist/{id}
        del_req = urllib.request.Request(
            f"{self.base_url}/api/watchlist/{watched_id}",
            method="DELETE",
        )
        with urllib.request.urlopen(del_req, timeout=5) as response:
            self.assertEqual(response.status, 200)
            del_data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(del_data.get("success"))

        # 6. Sprawdzenie czy usunięto z bazy i pliku offer_list.json
        with urllib.request.urlopen(f"{self.base_url}/api/watchlist", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            items = data.get("watchlist", [])
            self.assertFalse(any(it["id"] == watched_id for it in items))

        with open(offer_list_file, "r", encoding="utf-8") as f:
            disk_data_after = json.load(f)
        self.assertFalse(any(it["id"] == watched_id for it in disk_data_after))


if __name__ == "__main__":
    unittest.main()
