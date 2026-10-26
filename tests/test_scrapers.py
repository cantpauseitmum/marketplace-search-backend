"""
Testy jednostkowe i integracyjne dla MarketplaceSearch.
"""
import unittest
import os
import sys

# Dodanie ścieżki projektu
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from scrapers.base import Offer, SearchQuery
except ImportError:
    from backend.scrapers.base import Offer, SearchQuery
try:
    from scrapers.olx import OLXScraper
except ImportError:
    from backend.scrapers.olx import OLXScraper
try:
    from scrapers.allegro import AllegroScraper
except ImportError:
    from backend.scrapers.allegro import AllegroScraper
try:
    from scrapers.allegro_lokalnie import AllegroLokalnieScraper
except ImportError:
    from backend.scrapers.allegro_lokalnie import AllegroLokalnieScraper
try:
    from scrapers.facebook import FacebookMarketplaceScraper
except ImportError:
    from backend.scrapers.facebook import FacebookMarketplaceScraper
try:
    from scrapers.aggregator import MarketplaceAggregator
except ImportError:
    from backend.scrapers.aggregator import MarketplaceAggregator
from database.db_manager import DatabaseManager


class TestMarketplaceSearch(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(PROJECT_ROOT, "database", "test_run.db")
        self.db = DatabaseManager(self.test_db_path)
        self.aggregator = MarketplaceAggregator(self.db)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_url_builders(self):
        query = SearchQuery(text="Switch 2", location="Warszawa", radius_km=25)
        
        olx = OLXScraper()
        olx_url = olx.build_url(query)
        self.assertIn("warszawa", olx_url.lower())
        self.assertIn("switch", olx_url.lower())

        allok = AllegroLokalnieScraper()
        allok_url = allok.build_url(query)
        self.assertIn("allegrolokalnie.pl", allok_url)
        self.assertIn("city=Warszawa", allok_url)

        allegro = AllegroScraper()
        allegro_url = allegro.build_url(query)
        self.assertIn("allegro.pl", allegro_url)

        fb = FacebookMarketplaceScraper()
        fb_url = fb.build_url(query)
        self.assertIn("facebook.com", fb_url)

    def test_offer_filtering(self):
        scraper = OLXScraper()
        q1 = SearchQuery(text="Switch 2", search_in_description=True)

        offer_in_title = Offer(
            source="OLX",
            external_id="1",
            title="Nintendo Switch 2 OLED",
            price=1800,
            description="Krótki opis",
        )
        self.assertTrue(scraper.filter_offer(offer_in_title, q1))

        offer_in_desc = Offer(
            source="OLX",
            external_id="2",
            title="Konsola do gier stan bdb",
            price=1800,
            description="W zestawie konsola Switch 2 z grami",
        )
        self.assertTrue(scraper.filter_offer(offer_in_desc, q1))
        self.assertTrue(offer_in_desc.matches_description)

        q_no_desc = SearchQuery(text="Switch 2", search_in_description=False)
        self.assertFalse(scraper.filter_offer(offer_in_desc, q_no_desc))

    def test_aggregator_search_and_db_persistence(self):
        res = self.aggregator.search_all(
            query_text="Switch 2",
            location="Warszawa",
            radius_km=25,
            sources=["OLX", "Allegro", "Allegro Lokalnie", "Facebook Marketplace"],
        )
        self.assertGreater(res["total_count"], 0)
        self.assertIn("OLX", res["stats_by_source"])
        self.assertIn("Allegro", res["stats_by_source"])
        self.assertIn("Allegro Lokalnie", res["stats_by_source"])
        self.assertIn("Facebook Marketplace", res["stats_by_source"])

        # Sprawdzenie bazy danych
        db_res = self.db.get_offers(query="Switch 2")
        self.assertEqual(db_res["total"], res["total_count"])

        # Sprawdzenie zakładek
        first_id = res["items"][0]["id"]
        is_bookmarked = self.db.toggle_bookmark(first_id)
        self.assertTrue(is_bookmarked)


if __name__ == "__main__":
    unittest.main()
