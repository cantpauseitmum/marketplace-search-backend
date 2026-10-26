"""
Scraper serwisu Facebook Marketplace (facebook.com/marketplace)
Obsługuje wyszukiwanie z uwzględnieniem miasta oraz opcjonalnych ciasteczek sesyjnych.
"""
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Optional
from .base import BaseScraper, Offer, SearchQuery, ScraperResult
from .mock_data import generate_mock_offers
try:
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK, FACEBOOK_COOKIE, slugify_city
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK, FACEBOOK_COOKIE, slugify_city


class FacebookMarketplaceScraper(BaseScraper):
    name = "Facebook Marketplace"
    source_id = "facebook"
    badge_bg = "#1877f2"
    badge_color = "#ffffff"
    website_url = "https://www.facebook.com/marketplace"

    def build_url(self, query: SearchQuery) -> str:
        query_encoded = urllib.parse.quote(query.text.strip())
        city_slug = slugify_city(query.location) if query.location else ""

        if city_slug:
            base = f"https://www.facebook.com/marketplace/{city_slug}/search/?query={query_encoded}"
        else:
            base = f"https://www.facebook.com/marketplace/search/?query={query_encoded}"

        params = []
        if query.min_price is not None:
            params.append(f"minPrice={int(query.min_price)}")
        if query.max_price is not None:
            params.append(f"maxPrice={int(query.max_price)}")

        if params:
            base += "&" + "&".join(params)
        return base

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()
        url = self.build_url(query)

        headers = dict(DEFAULT_HEADERS)
        if FACEBOOK_COOKIE:
            headers["Cookie"] = FACEBOOK_COOKIE

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                html = response.read().decode("utf-8", errors="ignore")

            offers = self._parse_html(html, query)
            latency_ms = int((time.time() - start_time) * 1000)

            if offers:
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=offers,
                    latency_ms=latency_ms,
                    message=f"Pobrano {len(offers)} ofert z FB Marketplace",
                )
            else:
                if ENABLE_MOCK_FALLBACK:
                    mock_items = generate_mock_offers(self.name, query, count=5)
                    return ScraperResult(
                        source=self.name,
                        status="FALLBACK",
                        items=mock_items,
                        latency_ms=latency_ms,
                        message="Facebook wymaga logowania do pełnego API - tryb demonstracyjny",
                    )
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Facebook Marketplace",
                )

        except urllib.error.HTTPError as e:
            e.close()
            latency_ms = int((time.time() - start_time) * 1000)
            if ENABLE_MOCK_FALLBACK:
                mock_items = generate_mock_offers(self.name, query, count=5)
                return ScraperResult(
                    source=self.name,
                    status="FALLBACK",
                    items=mock_items,
                    latency_ms=latency_ms,
                    message=f"FB Marketplace (kod {e.code} - tryb demonstracyjny)",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd HTTP {e.code} Facebook Marketplace",
            )
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            if ENABLE_MOCK_FALLBACK:
                mock_items = generate_mock_offers(self.name, query, count=5)
                return ScraperResult(
                    source=self.name,
                    status="FALLBACK",
                    items=mock_items,
                    latency_ms=latency_ms,
                    message=f"FB Marketplace (sesja gościa: {str(e)[:45]})",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd FB Marketplace: {str(e)}",
            )

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []

        # Wyszukiwanie linków do ofert marketplace /item/
        item_matches = re.findall(
            r'href="(/marketplace/item/(\d+)/?[^"]*)"[^>]*>.*?<img[^>]+src="([^"]+)".*?</span>',
            html,
            re.DOTALL,
        )

        for match in item_matches:
            item_url = f"https://www.facebook.com{match[0]}"
            item_id = match[1]
            img_url = match[2]

            offer = Offer(
                source=self.name,
                external_id=f"fb-{item_id}",
                title=f"{query.text} - Facebook Marketplace",
                price=None,
                currency="PLN",
                price_formatted="Sprawdź na FB",
                url=item_url,
                image_url=img_url,
                location=query.location or "Polska",
                city=query.location,
                published_at="Niedawno",
            )
            if self.filter_offer(offer, query):
                offers.append(offer)

        return offers
