"""
Agregator zapytań do wielu serwisów ogłoszeniowych równolegle.
Zarządza uruchamianiem scraperów, deduplikacją i zapisem do bazy.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

from .base import BaseScraper, Offer, SearchQuery, ScraperResult
from .olx import OLXScraper
from .allegro import AllegroScraper
from .allegro_lokalnie import AllegroLokalnieScraper
from .facebook import FacebookMarketplaceScraper
import os
import sys

# Upewnij się, że katalog projektu jest w sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.db_manager import DatabaseManager


class MarketplaceAggregator:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.scrapers: Dict[str, BaseScraper] = {
            "olx": OLXScraper(),
            "allegro": AllegroScraper(),
            "allegro_lokalnie": AllegroLokalnieScraper(),
            "facebook": FacebookMarketplaceScraper(),
        }

    def get_available_sources(self) -> List[Dict[str, Any]]:
        """Zwraca listę dostępnych serwisów ogłoszeniowych i ich metadane."""
        return [
            {
                "id": scraper.source_id,
                "name": scraper.name,
                "badge_bg": scraper.badge_bg,
                "badge_color": scraper.badge_color,
                "website_url": scraper.website_url,
                "enabled": True,
            }
            for scraper in self.scrapers.values()
        ]

    def search_all(
        self,
        query_text: str,
        location: str = "",
        radius_km: int = 0,
        search_in_description: bool = True,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sources: Optional[List[str]] = None,
        sort_by: str = "newest",  # 'newest', 'price_asc', 'price_desc', 'relevance'
    ) -> Dict[str, Any]:
        """
        Współbieżnie przeszukuje wszystkie wybrane serwisy i łączy wyniki.
        """
        start_overall = time.time()

        # Filtrowanie źródeł
        target_scrapers: List[BaseScraper] = []
        normalized_sources = [s.lower().strip() for s in (sources or [])]

        for s_id, scraper in self.scrapers.items():
            if not normalized_sources or s_id in normalized_sources or scraper.name.lower() in normalized_sources:
                target_scrapers.append(scraper)

        search_query = SearchQuery(
            text=query_text,
            location=location,
            radius_km=radius_km,
            search_in_description=search_in_description,
            min_price=min_price,
            max_price=max_price,
            sources=[s.name for s in target_scrapers],
        )

        # Rejestracja wyszukiwania w bazie danych
        query_id = self.db.record_search_query(
            query_text=query_text,
            location=location,
            radius_km=radius_km,
            search_in_description=search_in_description,
            min_price=min_price,
            max_price=max_price,
            sources=[s.name for s in target_scrapers],
        )

        all_offers: List[Offer] = []
        scraper_results: List[Dict[str, Any]] = []

        # Równoległe wykonanie scraperów
        with ThreadPoolExecutor(max_workers=len(target_scrapers) or 1) as executor:
            future_to_scraper = {
                executor.submit(scraper.search, search_query): scraper
                for scraper in target_scrapers
            }

            for future in as_completed(future_to_scraper):
                scraper = future_to_scraper[future]
                try:
                    result: ScraperResult = future.result()
                    all_offers.extend(result.items)
                    scraper_results.append(result.to_dict())

                    # Logowanie do bazy danych
                    self.db.log_scraper_run(
                        source=result.source,
                        query_id=query_id,
                        status=result.status,
                        items_found=len(result.items),
                        latency_ms=result.latency_ms,
                        message=result.message,
                    )
                except Exception as e:
                    scraper_results.append({
                        "source": scraper.name,
                        "status": "ERROR",
                        "count": 0,
                        "items": [],
                        "latency_ms": 0,
                        "message": str(e),
                    })
                    self.db.log_scraper_run(
                        source=scraper.name,
                        query_id=query_id,
                        status="ERROR",
                        items_found=0,
                        latency_ms=0,
                        message=str(e),
                    )

        # Deduplikacja ofert po (źródło, url)
        seen = set()
        unique_offers: List[Offer] = []
        for offer in all_offers:
            key = (offer.source, offer.url)
            if key not in seen:
                seen.add(key)
                unique_offers.append(offer)

        # Sortowanie wyników
        if sort_by == "price_asc":
            unique_offers.sort(key=lambda o: (o.price is None, o.price or 0))
        elif sort_by == "price_desc":
            unique_offers.sort(key=lambda o: (o.price is not None, o.price or 0), reverse=True)
        elif sort_by == "relevance":
            # Oferty z frazą w tytule wyżej niż te tylko w opisie
            unique_offers.sort(key=lambda o: (not o.matches_description, o.published_at), reverse=True)

        # Zapis do bazy danych
        offers_dicts = [o.to_dict() for o in unique_offers]
        self.db.upsert_offers_batch(offers_dicts, query_id=query_id)
        self.db.update_query_result_count(query_id, len(unique_offers))

        total_time_ms = int((time.time() - start_overall) * 1000)

        # Statystyki per źródło
        stats_by_source = {}
        for s in target_scrapers:
            stats_by_source[s.name] = sum(1 for o in unique_offers if o.source == s.name)

        return {
            "query_id": query_id,
            "query": query_text,
            "location": location,
            "radius_km": radius_km,
            "total_count": len(unique_offers),
            "stats_by_source": stats_by_source,
            "scraper_statuses": scraper_results,
            "latency_ms": total_time_ms,
            "items": offers_dicts,
        }
