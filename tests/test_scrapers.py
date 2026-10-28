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
        self.assertIn("warszawa", allok_url.lower())
        self.assertIn("distance=25", allok_url)

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

        # Oferty które NIE powinny pasować do 'Switch 2'
        offer_v2 = Offer(
            source="OLX",
            external_id="3",
            title="Nintendo switch v2",
            price=1000,
            description="Brak opisu",
        )
        self.assertFalse(scraper.filter_offer(offer_v2, q1))

        offer_oled = Offer(
            source="OLX",
            external_id="4",
            title="Nintendo Switch OLED 64 GB + 4 Joy-Cony + 2 gry + dodatki",
            price=1050,
            description="Brak opisu",
        )
        self.assertFalse(scraper.filter_offer(offer_oled, q1))

        offer_just_switch = Offer(
            source="OLX",
            external_id="5",
            title="Nintendo Switch",
            price=700,
            description="Brak opisu",
        )
        self.assertFalse(scraper.filter_offer(offer_just_switch, q1))

    def test_aggregator_search_and_db_persistence(self):
        res = self.aggregator.search_all(
            query_text="Switch 2",
            location="Warszawa",
            radius_km=25,
            sources=["OLX", "Allegro Lokalnie", "Facebook Marketplace"],
        )
        self.assertGreater(res["total_count"], 0)
        self.assertIn("OLX", res["stats_by_source"])
        self.assertIn("Allegro Lokalnie", res["stats_by_source"])
        self.assertIn("Facebook Marketplace", res["stats_by_source"])

        # Sprawdzenie bazy danych
        db_res = self.db.get_offers(query_id=res["query_id"])
        self.assertEqual(db_res["total"], res["total_count"])

        # Sprawdzenie zakładek
        first_id = res["items"][0]["id"]
        is_bookmarked = self.db.toggle_bookmark(first_id)
        self.assertTrue(is_bookmarked)

    def test_location_and_pagination(self):
        # 1. Cała Polska: OLX, Allegro Lokalnie, FB i Allegro nie powinny zawierać ograniczenia miastem
        q_polska = SearchQuery(text="switch 2", location="", radius_km=0, search_in_description=True, page=2)
        olx = OLXScraper()
        allok = AllegroLokalnieScraper()
        fb = FacebookMarketplaceScraper()

        olx_url = olx.build_url(q_polska)
        self.assertIn("/d/oferty/q-switch-2/", olx_url)
        self.assertIn("search[description]=1", olx_url)
        self.assertIn("page=2", olx_url)

        allok_url = allok.build_url(q_polska)
        self.assertIn("/oferty/q/switch-2", allok_url)
        self.assertIn("page=2", allok_url)

        fb_url = fb.build_url(q_polska)
        self.assertIn("/marketplace/warsaw/search/?query=switch%202", fb_url)

        # 2. Wrocław + 100km
        q_wroclaw = SearchQuery(text="switch 2", location="Wrocław", radius_km=100)
        olx_wroc = olx.build_url(q_wroclaw)
        self.assertIn("/wroclaw/", olx_wroc)
        self.assertIn("search[dist]=100", olx_wroc)

        allok_wroc = allok.build_url(q_wroclaw)
        self.assertIn("/oferty/wroclaw/q/switch-2", allok_wroc)
        self.assertIn("distance=100", allok_wroc)

        fb_wroc = fb.build_url(q_wroclaw)
        self.assertIn("/marketplace/wroclaw/search/", fb_wroc)
        self.assertIn("radius=100", fb_wroc)

    def test_currency_conversion_and_cross_border(self):
        from backend.currency import currency_converter

        # 1. Przeliczanie EUR -> PLN
        pln_val, fmt, orig_p, orig_c = currency_converter.format_price(80.0, "EUR")
        self.assertGreater(pln_val, 300)
        self.assertIn("zł", fmt)
        self.assertIn("80 €", fmt)
        self.assertEqual(orig_c, "EUR")

        # 2. Przeliczanie USD -> PLN
        pln_usd, fmt_usd, orig_p_u, orig_c_u = currency_converter.format_price(100.0, "USD")
        self.assertGreater(pln_usd, 350)
        self.assertIn("100 $", fmt_usd)

        # 3. Słubice -> Frankfurt URL anchor
        fb = FacebookMarketplaceScraper()
        q_slubice = SearchQuery(text="rower", location="Słubice", raw_location="Słubice")
        slubice_url = fb.build_url(q_slubice)
        self.assertIn("/marketplace/frankfurt/search/", slubice_url)


if __name__ == "__main__":
    unittest.main()

