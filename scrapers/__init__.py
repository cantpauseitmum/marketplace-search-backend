"""Pakiet scraperów dla MarketplaceSearch."""
from .base import BaseScraper, Offer, SearchQuery, ScraperResult
from .olx import OLXScraper
from .allegro_lokalnie import AllegroLokalnieScraper
from .facebook import FacebookMarketplaceScraper
from .aggregator import MarketplaceAggregator

__all__ = [
    "BaseScraper",
    "Offer",
    "SearchQuery",
    "ScraperResult",
    "OLXScraper",
    "AllegroLokalnieScraper",
    "FacebookMarketplaceScraper",
    "MarketplaceAggregator",
]
