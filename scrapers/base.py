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
        - Przedział cenowy (min_price, max_price)
        - Ścisłe dopasowanie frazy kluczowej z poszanowaniem granic słów.
          Np. dla frazy "switch 2":
          znajduje: "Nintendo Switch 2", "Konsola Switch 2", "Switch2"
          NIE znajduje: "Switch V2" (v2 != 2), "Switch OLED" (brak 2), "Switch" (brak 2),
          "Nintendo Switch OLED + 2 gry" (2 nie dotyczy modelu Switch).
        """
        # Sprawdzanie ceny
        if query.min_price is not None and offer.price is not None:
            if offer.price < query.min_price:
                return False
        if query.max_price is not None and offer.price is not None:
            if offer.price > query.max_price:
                return False

        # Sprawdzanie frazy wyszukiwania
        query_text = (query.text or "").strip()
        if not query_text:
            return True

        title = offer.title or ""
        desc = offer.description or ""

        # 1. Ścisłe sprawdzenie w tytule
        if self._matches_text(query_text, title):
            return True

        # 2. Sprawdzenie w opisie (tylko gdy użytkownik jawnie włączył szukanie w opisie)
        if query.search_in_description and desc:
            if self._matches_text(query_text, desc):
                offer.matches_description = True
                return True

        return False

    @staticmethod
    def _matches_text(query_text: str, text: str) -> bool:
        """
        Sprawdza czy zadana fraza występuje w tekście w sposób semantycznie spójny:
        - Zachowuje granice słów (np. '2' nie pasuje do 'v2', '2024', '12', 'd2')
        - Wymaga wystąpienia szukanej frazy (np. 'switch 2' jako spójnej całości, a nie 'switch' w tytule i '2 gry' na końcu)
        """
        if not query_text or not text:
            return False

        q_tokens = re.findall(r"[\w]+", query_text.lower())
        if not q_tokens:
            return True

        t_lower = text.lower()
        sep = r"[\s\-_/.:,+]"

        # 1. Cała fraza w sekwencji (np. 'switch 2' -> (?<![\w])switch[\s\-_/.:,+]*2(?![\w]))
        phrase_pattern = r"(?<![\w])" + (sep + r"*").join(re.escape(t) for t in q_tokens) + r"(?![\w])"
        if re.search(phrase_pattern, t_lower):
            return True

        # 2. Dla zapytań złożonych z 3+ tokenów (np. 'konsola switch 2' lub 'nintendo switch 2'):
        # Weryfikacja czy tokeny powiązane z numerem/modyfikatorem (np. 'switch 2', 'ps 5', 'iphone 15')
        # występują razem, a pozostałe słowa występują jako całe tokeny w tekście
        if len(q_tokens) >= 3:
            groups = []
            i = 0
            while i < len(q_tokens):
                tok = q_tokens[i]
                if i + 1 < len(q_tokens) and (
                    q_tokens[i + 1].isdigit()
                    or q_tokens[i + 1] in ("pro", "max", "ti", "plus", "ultra", "slim", "lite", "fe")
                ):
                    groups.append((tok, q_tokens[i + 1]))
                    i += 2
                else:
                    groups.append((tok,))
                    i += 1

            all_groups_match = True
            for grp in groups:
                if len(grp) == 2:
                    pat = r"(?<![\w])" + re.escape(grp[0]) + sep + r"*" + re.escape(grp[1]) + r"(?![\w])"
                else:
                    pat = r"(?<![\w])" + re.escape(grp[0]) + r"(?![\w])"
                if not re.search(pat, t_lower):
                    all_groups_match = False
                    break

            if all_groups_match:
                return True

        return False
