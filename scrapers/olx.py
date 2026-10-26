"""
Scraper serwisu OLX (olx.pl)
Wyszukuje oferty po frazie, lokalizacji (miasto + promień) oraz w tytule/opisie.
"""
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Optional
from .base import BaseScraper, Offer, SearchQuery, ScraperResult
from .mock_data import generate_mock_offers
try:
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK, slugify_city
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT, ENABLE_MOCK_FALLBACK, slugify_city


class OLXScraper(BaseScraper):
    name = "OLX"
    source_id = "olx"
    badge_bg = "#002f34"
    badge_color = "#23e5db"
    website_url = "https://www.olx.pl"

    def build_url(self, query: SearchQuery) -> str:
        """Buduje URL wyszukiwania w OLX zgodny z parametrami."""
        query_slug = urllib.parse.quote(query.text.strip())
        city_slug = slugify_city(query.location) if query.location else ""

        if city_slug:
            base = f"https://www.olx.pl/d/{city_slug}/q-{query_slug}/"
        else:
            base = f"https://www.olx.pl/d/oferty/q-{query_slug}/"

        params = []
        if query.radius_km > 0 and city_slug:
            params.append(f"search[dist]={query.radius_km}")
        if query.search_in_description:
            params.append("search[description]=1")
        if query.min_price is not None:
            params.append(f"search[filter_float_price:from]={int(query.min_price)}")
        if query.max_price is not None:
            params.append(f"search[filter_float_price:to]={int(query.max_price)}")

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
                    message=f"Pobrano {len(offers)} ofert z OLX.pl",
                )
            else:
                # Jeśli scraper nie znalazł wyników w HTML, a fallback jest włączony
                if ENABLE_MOCK_FALLBACK:
                    mock_items = generate_mock_offers(self.name, query, count=6)
                    return ScraperResult(
                        source=self.name,
                        status="FALLBACK",
                        items=mock_items,
                        latency_ms=latency_ms,
                        message="Brak bezpośrednich wyników w OLX, wygenerowano oferty podglądowe",
                    )
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń spełniających kryteria na OLX",
                )

        except urllib.error.HTTPError as e:
            e.close()
            latency_ms = int((time.time() - start_time) * 1000)
            if ENABLE_MOCK_FALLBACK:
                mock_items = generate_mock_offers(self.name, query, count=6)
                return ScraperResult(
                    source=self.name,
                    status="FALLBACK",
                    items=mock_items,
                    latency_ms=latency_ms,
                    message=f"OLX (kod {e.code} - tryb demonstracyjny)",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd HTTP {e.code} OLX",
            )
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            if ENABLE_MOCK_FALLBACK:
                mock_items = generate_mock_offers(self.name, query, count=6)
                return ScraperResult(
                    source=self.name,
                    status="FALLBACK",
                    items=mock_items,
                    latency_ms=latency_ms,
                    message=f"OLX (tryb demonstracyjny / ochrona antybotowa: {str(e)[:60]})",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd połączenia z OLX: {str(e)}",
            )

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        """Ekstrakcja ofert z danych pre-renderowanych OLX (__PRERENDERED_STATE__) lub HTML."""
        offers: List[Offer] = []

        # 1. Próba parsowania stanu JSON z __PRERENDERED_STATE__
        match = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*(".*?"|\{.*?\});', html, re.DOTALL)
        if match:
            raw_json = match.group(1)
            try:
                # Czasami stan jest zakodowanym stringiem JSON
                if raw_json.startswith('"') and raw_json.endswith('"'):
                    raw_json = json.loads(raw_json)
                data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                ads = data.get("listing", {}).get("listing", {}).get("ads", [])
                for ad in ads:
                    offer = self._parse_ad_json(ad)
                    if offer and self.filter_offer(offer, query):
                        offers.append(offer)
                if offers:
                    return offers
            except Exception:
                pass

        # 2. Parsowanie kart HTML jako metoda zapasowa
        card_pattern = re.compile(r'<div[^>]*data-cy="l-card"[^>]*>.*?</div>\s*</div>\s*</div>', re.DOTALL)
        cards = card_pattern.findall(html)
        for card in cards:
            offer = self._parse_ad_card_html(card)
            if offer and self.filter_offer(offer, query):
                offers.append(offer)

        return offers

    def _parse_ad_json(self, ad: dict) -> Optional[Offer]:
        try:
            ad_id = str(ad.get("id"))
            title = ad.get("title", "").strip()
            if not title:
                return None

            # Cena
            price_data = ad.get("price", {})
            price_val = price_data.get("regularPrice", {}).get("value") or price_data.get("value")
            price = float(price_val) if price_val is not None else None
            price_formatted = price_data.get("displayValue") or (f"{price:.0f} zł" if price else "Do negocjacji")

            # Zdjęcie
            photos = ad.get("photos", [])
            image_url = ""
            if photos and isinstance(photos, list):
                first = photos[0]
                if isinstance(first, dict):
                    image_url = first.get("link", "").replace("{width}x{height}", "600x450")
                elif isinstance(first, str):
                    image_url = first

            # Lokalizacja
            loc = ad.get("location", {})
            city = loc.get("city", {}).get("name", "")
            district = loc.get("district", {}).get("name", "")
            location_str = f"{city}, {district}" if district else city

            # URL
            url = ad.get("url", "")
            if url and not url.startswith("http"):
                url = f"https://www.olx.pl{url}"

            # Data
            created_time = ad.get("createdTime", "")

            # Opis
            desc = ad.get("description", "")

            return Offer(
                source=self.name,
                external_id=f"olx-{ad_id}",
                title=title,
                price=price,
                currency="PLN",
                price_formatted=price_formatted,
                url=url,
                image_url=image_url,
                location=location_str,
                city=city,
                description=desc,
                published_at=created_time,
            )
        except Exception:
            return None

    def _parse_ad_card_html(self, card_html: str) -> Optional[Offer]:
        try:
            # Tytuł
            title_match = re.search(r'<h4[^>]*>(.*?)</h4>', card_html, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
            if not title:
                return None

            # Link
            link_match = re.search(r'href="([^"]+)"', card_html)
            url = link_match.group(1) if link_match else ""
            if url and not url.startswith("http"):
                url = f"https://www.olx.pl{url}"

            # Cena
            price_match = re.search(r'<p[^>]*data-testid="ad-price"[^>]*>(.*?)</p>', card_html)
            price_str = re.sub(r'<[^>]+>', '', price_match.group(1)).strip() if price_match else ""
            price_val = None
            if price_str:
                num = re.sub(r'[^\d,.]', '', price_str.replace(" ", "")).replace(",", ".")
                try:
                    price_val = float(num)
                except ValueError:
                    pass

            # Zdjęcie
            img_match = re.search(r'<img[^>]+src="([^"]+)"', card_html)
            image_url = img_match.group(1) if img_match else ""

            # Lokalizacja
            loc_match = re.search(r'<p[^>]*data-testid="location-date"[^>]*>(.*?)</p>', card_html)
            location_date = re.sub(r'<[^>]+>', '', loc_match.group(1)).strip() if loc_match else ""
            loc_parts = location_date.split(" - ")
            location_str = loc_parts[0] if loc_parts else ""
            date_str = loc_parts[1] if len(loc_parts) > 1 else ""

            return Offer(
                source=self.name,
                external_id=f"olx-{hash(url) % 100000000}",
                title=title,
                price=price_val,
                currency="PLN",
                price_formatted=price_str or (f"{price_val:.0f} zł" if price_val else "Do negocjacji"),
                url=url,
                image_url=image_url,
                location=location_str,
                city=location_str.split(",")[0].strip(),
                description="",
                published_at=date_str,
            )
        except Exception:
            return None
