"""
Scraper serwisu OLX (olx.pl)
Pobiera rzeczywiste, aktywne oferty z OLX (API + pre-renderowany stan HTML).
Obsługuje wyszukiwanie po słowach kluczowych, lokalizacji (miasto + promień) oraz cenie.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from typing import List, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

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
        query_slug = urllib.parse.quote(query.text.strip().replace(" ", "-"))
        city_slug = slugify_city(query.location) if query.location else ""

        if city_slug:
            base = f"https://www.olx.pl/d/{city_slug}/q-{query_slug}/"
        else:
            base = f"https://www.olx.pl/d/oferty/q-{query_slug}/"

        params = []
        if query.radius_km > 0 and city_slug:
            params.append(f"search[dist]={query.radius_km}")
        if query.min_price is not None:
            params.append(f"search[filter_float_price:from]={int(query.min_price)}")
        if query.max_price is not None:
            params.append(f"search[filter_float_price:to]={int(query.max_price)}")

        if params:
            base += "?" + "&".join(params)
        return base

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()
        offers: List[Offer] = []
        seen_urls = set()

        if query.location:
            # Gdy podano lokalizację, używamy widoku web ze stanem pre-renderowanym (obsługuje miasto i promień)
            web_offers = self._search_via_web(query)
            for o in web_offers:
                if o.url not in seen_urls:
                    seen_urls.add(o.url)
                    offers.append(o)
        else:
            # Wyszukiwanie ogólnokrajowe: łączymy API OLX oraz widok webowy
            api_offers = self._search_via_api(query)
            for o in api_offers:
                if o.url not in seen_urls:
                    seen_urls.add(o.url)
                    offers.append(o)

            web_offers = self._search_via_web(query)
            for o in web_offers:
                if o.url not in seen_urls:
                    seen_urls.add(o.url)
                    offers.append(o)

        latency_ms = int((time.time() - start_time) * 1000)

        # Weryfikacja filtrów
        filtered = [o for o in offers if self.filter_offer(o, query)]

        if filtered:
            return ScraperResult(
                source=self.name,
                status="OK",
                items=filtered,
                latency_ms=latency_ms,
                message=f"Pobrano {len(filtered)} rzeczywistych ofert z OLX.pl",
            )

        # Jeśli brak ofert
        if ENABLE_MOCK_FALLBACK:
            mock_items = generate_mock_offers(self.name, query, count=5)
            return ScraperResult(
                source=self.name,
                status="FALLBACK",
                items=mock_items,
                latency_ms=latency_ms,
                message="Brak bezpośrednich ofert na OLX (tryb demonstracyjny)",
            )

        return ScraperResult(
            source=self.name,
            status="OK",
            items=[],
            latency_ms=latency_ms,
            message="Brak ogłoszeń spełniających kryteria na OLX",
        )

    def _search_via_api(self, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []
        query_enc = urllib.parse.quote(query.text.strip())
        url = f"https://www.olx.pl/api/v1/offers/?query={query_enc}&offset=0&limit=50"
        if query.min_price is not None:
            url += f"&filter_float_price:from={int(query.min_price)}"
        if query.max_price is not None:
            url += f"&filter_float_price:to={int(query.max_price)}"

        headers = {
            "Referer": "https://www.olx.pl/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        }

        try:
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(url, impersonate="chrome", headers=headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    for item in data:
                        offer = self._parse_api_item(item, query)
                        if offer:
                            offers.append(offer)
            else:
                req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, **headers})
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                    data = json.loads(r.read().decode()).get("data", [])
                    for item in data:
                        offer = self._parse_api_item(item, query)
                        if offer:
                            offers.append(offer)
        except Exception:
            pass

        return offers

    def _parse_api_item(self, item: dict, query: SearchQuery) -> Optional[Offer]:
        try:
            item_id = str(item.get("id"))
            title = (item.get("title") or "").strip()
            url = item.get("url")
            if not title or not url:
                return None

            loc = item.get("location", {})
            city = loc.get("city", {}).get("name") or loc.get("cityName") or ""
            district = loc.get("district", {}).get("name") or loc.get("districtName") or ""
            location_str = f"{city}, {district}" if district else (city or "Polska")

            # Jeśli szukamy w konkretnym mieście, a oferta pochodzi z innego miasta i promień = 0
            if query.location and query.radius_km == 0:
                city_clean = city.lower().strip()
                target_clean = query.location.lower().strip()
                if target_clean not in city_clean and city_clean not in target_clean:
                    return None

            price_val = None
            price_formatted = "Do negocjacji"
            for p in item.get("params", []):
                if p.get("key") == "price":
                    val = p.get("value", {})
                    price_val = val.get("value")
                    price_formatted = val.get("label") or (f"{price_val} zł" if price_val else "Do negocjacji")
                    break

            photos = item.get("photos", [])
            image_url = ""
            if photos and isinstance(photos, list):
                first = photos[0]
                if isinstance(first, dict):
                    image_url = first.get("link", "").replace("{width}x{height}", "600x450")
                elif isinstance(first, str):
                    image_url = first

            desc = item.get("description", "")
            created_at = item.get("last_refresh_time") or item.get("created_time") or ""

            return Offer(
                source=self.name,
                external_id=f"olx-{item_id}",
                title=title,
                price=float(price_val) if price_val is not None else None,
                currency="PLN",
                price_formatted=price_formatted,
                url=url,
                image_url=image_url,
                location=location_str,
                city=city,
                description=desc,
                published_at=created_at[:10] if created_at else "Niedawno",
            )
        except Exception:
            return None

    def _search_via_web(self, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []
        url = self.build_url(query)

        headers = {
            "Referer": "https://www.olx.pl/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        }

        try:
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(url, impersonate="chrome", headers=headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    offers = self._parse_html(resp.text, query)
            else:
                req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, **headers})
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                    html = r.read().decode("utf-8", errors="ignore")
                    offers = self._parse_html(html, query)
        except Exception:
            pass

        return offers

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        """Ekstrakcja ofert z danych pre-renderowanych OLX (__PRERENDERED_STATE__) lub HTML."""
        offers: List[Offer] = []

        match = re.search(r'window\.__PRERENDERED_STATE__\s*=\s*(".*?"|\{.*?\});', html, re.DOTALL)
        if match:
            raw_json = match.group(1)
            try:
                if raw_json.startswith('"') and raw_json.endswith('"'):
                    raw_json = json.loads(raw_json)
                data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                ads = data.get("listing", {}).get("listing", {}).get("ads", [])
                for ad in ads:
                    offer = self._parse_ad_json(ad)
                    if offer:
                        offers.append(offer)
                if offers:
                    return offers
            except Exception:
                pass

        return offers

    def _parse_ad_json(self, ad: dict) -> Optional[Offer]:
        try:
            ad_id = str(ad.get("id"))
            title = (ad.get("title") or "").strip()
            url = ad.get("url") or ""
            if not title or not url:
                return None

            price_data = ad.get("price", {})
            price_val = price_data.get("regularPrice", {}).get("value")
            price = float(price_val) if price_val is not None else None
            price_formatted = price_data.get("displayValue") or (f"{price:.0f} zł" if price else "Do negocjacji")

            photos = ad.get("photos", [])
            image_url = ""
            if photos and isinstance(photos, list):
                first = photos[0]
                if isinstance(first, str):
                    image_url = first
                elif isinstance(first, dict):
                    image_url = first.get("link", "").replace("{width}x{height}", "600x450")

            loc = ad.get("location", {})
            city = loc.get("cityName") or loc.get("cityNormalizedName", "").capitalize()
            district = loc.get("districtName", "")
            location_str = f"{city}, {district}" if district else (city or "Polska")

            desc = ad.get("description", "")
            created_time = ad.get("createdTime", "")

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
                published_at=created_time[:10] if created_time else "Niedawno",
            )
        except Exception:
            return None
