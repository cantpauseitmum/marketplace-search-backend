"""
Bazowe struktury danych i klasa bazowa dla scraperów.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import re


@dataclass
class Offer:
    source: str  # 'OLX', 'Allegro', 'Allegro Lokalnie', 'Facebook Marketplace'
    external_id: str
    title: str
    price: Optional[float]
    currency: str = "PLN"
    price_formatted: str = ""
    url: str = ""
    image_url: str = ""
    location: str = ""
    city: str = ""
    distance_km: Optional[float] = None
    description: str = ""
    published_at: str = ""
    matches_description: bool = False
    is_bookmarked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not self.price_formatted:
            if self.price is not None:
                data["price_formatted"] = f"{self.price:,.2f} {self.currency}".replace(",", " ").replace(".00", "")
            else:
                data["price_formatted"] = "Do negocjacji"
        return data


@dataclass
class SearchQuery:
    text: str
    location: str = ""
    radius_km: int = 0
    search_in_description: bool = True
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    sources: List[str] = field(default_factory=lambda: ["OLX", "Allegro", "Allegro Lokalnie", "Facebook Marketplace"])


@dataclass
class ScraperResult:
    source: str
    status: str  # 'OK', 'ERROR', 'WARNING', 'FALLBACK'
    items: List[Offer] = field(default_factory=list)
    latency_ms: int = 0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "count": len(self.items),
            "items": [item.to_dict() for item in self.items],
            "latency_ms": self.latency_ms,
            "message": self.message,
        }


class BaseScraper(ABC):
    name: str = "Base"
    source_id: str = "base"
    badge_bg: str = "#6c757d"
    badge_color: str = "#ffffff"
    website_url: str = ""

    @abstractmethod
    def search(self, query: SearchQuery) -> ScraperResult:
        """Wykonuje wyszukiwanie w danym serwisie ogłoszeniowym."""
        pass

    def filter_offer(self, offer: Offer, query: SearchQuery) -> bool:
        """
        Weryfikuje czy oferta spełnia kryteria wyszukiwania:
        - Fraza w tytule LUB (jeśli zaznaczono) w opisie
        - Przedział cenowy
        """
        # Sprawdzanie ceny
        if query.min_price is not None and offer.price is not None:
            if offer.price < query.min_price:
                return False
        if query.max_price is not None and offer.price is not None:
            if offer.price > query.max_price:
                return False

        # Sprawdzanie słów kluczowych
        query_words = [w.lower() for w in re.split(r"\s+", query.text.strip()) if w]
        if not query_words:
            return True

        title_lower = (offer.title or "").lower()
        desc_lower = (offer.description or "").lower()

        # Sprawdzenie czy wszystkie słowa zapytania pasują do tytułu
        all_in_title = all(word in title_lower for word in query_words)
        if all_in_title:
            return True

        # Jeśli szukamy w opisie - sprawdzamy czy pozostałe słowa są w opisie
        if query.search_in_description:
            full_text = f"{title_lower} {desc_lower}"
            all_in_full = all(word in full_text for word in query_words)
            if all_in_full:
                offer.matches_description = True
                return True

        return False
