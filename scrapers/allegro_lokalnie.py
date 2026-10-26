"""
Scraper serwisu Allegro Lokalnie (allegrolokalnie.pl)
Wyszukuje oferty lokalne z uwzględnieniem miasta i promienia.
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
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK


class AllegroLokalnieScraper(BaseScraper):
    name = "Allegro Lokalnie"
    source_id = "allegro_lokalnie"
    badge_bg = "#ff7700"
    badge_color = "#ffffff"
    website_url = "https://allegrolokalnie.pl"

    def build_url(self, query: SearchQuery) -> str:
        query_encoded = urllib.parse.quote(query.text.strip())
        base = f"https://allegrolokalnie.pl/oferty/q/{query_encoded}"

        params = []
        if query.location:
            params.append(f"city={urllib.parse.quote(query.location.strip())}")
            if query.radius_km > 0:
                params.append(f"distance={query.radius_km}")
        if query.min_price is not None:
            params.append(f"price_from={int(query.min_price)}")
        if query.max_price is not None:
            params.append(f"price_to={int(query.max_price)}")

        if params:
            base += "?" + "&".join(params)
        return base

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()
        url = self.build_url(query)

        try:
            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
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
                    message=f"Pobrano {len(offers)} ofert z Allegro Lokalnie",
                )
            else:
                if ENABLE_MOCK_FALLBACK:
                    mock_items = generate_mock_offers(self.name, query, count=5)
                    return ScraperResult(
                        source=self.name,
                        status="FALLBACK",
                        items=mock_items,
                        latency_ms=latency_ms,
                        message="Brak bezpośrednich ofert na Allegro Lokalnie, tryb demonstracyjny",
                    )
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Allegro Lokalnie",
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
                    message=f"Allegro Lokalnie (kod {e.code} - tryb demonstracyjny)",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd HTTP {e.code} Allegro Lokalnie",
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
                    message=f"Allegro Lokalnie (tryb demonstracyjny: {str(e)[:50]})",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd Allegro Lokalnie: {str(e)}",
            )

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []

        # Wyszukiwanie artykułów / kart ogłoszeń
        article_pattern = re.compile(r'<article[^>]*class="[^"]*mlc-item[^"]*"[^>]*>(.*?)</article>', re.DOTALL)
        articles = article_pattern.findall(html)

        for art in articles:
            offer = self._parse_article(art)
            if offer and self.filter_offer(offer, query):
                offers.append(offer)

        return offers

    def _parse_article(self, art_html: str) -> Optional[Offer]:
        try:
            # Tytuł i link
            title_match = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h3>', art_html, re.DOTALL)
            if not title_match:
                title_match = re.search(r'title="([^"]+)"', art_html)
                title = title_match.group(1).strip() if title_match else ""
            else:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()

            if not title:
                return None

            link_match = re.search(r'href="([^"]+)"', art_html)
            url = link_match.group(1) if link_match else ""
            if url and not url.startswith("http"):
                url = f"https://allegrolokalnie.pl{url}"

            # Cena
            price_match = re.search(r'<span[^>]*class="[^"]*price[^"]*"[^>]*>(.*?)</span>', art_html, re.DOTALL)
            price_str = re.sub(r'<[^>]+>', '', price_match.group(1)).strip() if price_match else ""
            price_val = None
            if price_str:
                num = re.sub(r'[^\d,.]', '', price_str.replace(" ", "")).replace(",", ".")
                try:
                    price_val = float(num)
                except ValueError:
                    pass

            # Lokalizacja
            loc_match = re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', art_html, re.DOTALL)
            loc_str = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip() if loc_match else ""

            # Zdjęcie
            img_match = re.search(r'<img[^>]+(?:src|data-src)="([^"]+)"', art_html)
            image_url = img_match.group(1) if img_match else ""

            return Offer(
                source=self.name,
                external_id=f"allok-{hash(url) % 10000000}",
                title=title,
                price=price_val,
                currency="PLN",
                price_formatted=price_str or (f"{price_val:.0f} zł" if price_val else "Kup teraz"),
                url=url,
                image_url=image_url,
                location=loc_str,
                city=loc_str.split(",")[0].strip() if loc_str else "",
                description="",
                published_at="Niedawno dodane",
            )
        except Exception:
            return None
