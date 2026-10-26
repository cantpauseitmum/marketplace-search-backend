"""
Scraper serwisu Facebook Marketplace (facebook.com/marketplace)
Obsługuje wyszukiwanie rzeczywistych ofert z uwzględnieniem miasta oraz opcjonalnych ciasteczek sesyjnych.
"""
import json
import re
import time
import urllib.parse
from typing import List, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import urllib.request
    HAS_CURL_CFFI = False

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

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://www.facebook.com/",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
        }
        if FACEBOOK_COOKIE:
            headers["Cookie"] = FACEBOOK_COOKIE

        try:
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(
                    url,
                    impersonate="chrome",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                html_text = resp.text
            else:
                import urllib.request
                req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, **headers})
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                    html_text = response.read().decode("utf-8", errors="ignore")

            offers = self._parse_html(html_text, query)
            latency_ms = int((time.time() - start_time) * 1000)

            if offers:
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=offers,
                    latency_ms=latency_ms,
                    message=f"Pobrano {len(offers)} rzeczywistych ofert z FB Marketplace",
                )
            else:
                if ENABLE_MOCK_FALLBACK:
                    mock_items = generate_mock_offers(self.name, query, count=5)
                    return ScraperResult(
                        source=self.name,
                        status="FALLBACK",
                        items=mock_items,
                        latency_ms=latency_ms,
                        message="Brak bezpośrednich ofert na Facebook Marketplace (tryb demonstracyjny)",
                    )
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Facebook Marketplace",
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
                    message=f"FB Marketplace ({str(e)[:45]})",
                )
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd FB Marketplace: {str(e)}",
            )

    def _parse_html(self, html_content: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []
        seen_ids = set()

        # 1. Ekstrakcja zagnieżdżonych struktur JSON w znacznikach <script>
        scripts = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html_content)
        for s in scripts:
            if "marketplace_listing_title" not in s:
                continue
            try:
                data = json.loads(s)
                nodes = self._find_listing_nodes(data)
                for node in nodes:
                    item_id = str(node.get("id") or "")
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    offer = self._parse_json_node(node, query)
                    if offer and self.filter_offer(offer, query):
                        offers.append(offer)
            except Exception:
                continue

        # 2. Fallback: regex HTML dla linków /marketplace/item/
        if not offers:
            item_matches = re.findall(
                r'href="(/marketplace/item/(\d+)/?[^"]*)"[^>]*>.*?<img[^>]+src="([^"]+)".*?</span>',
                html_content,
                re.DOTALL,
            )
            for match in item_matches:
                item_url = f"https://www.facebook.com{match[0]}"
                item_id = match[1]
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
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

    def _find_listing_nodes(self, obj) -> list:
        """Rekurencyjne wyszukiwanie węzłów z ogłoszeniami w drzewie JSON Facebooka."""
        nodes = []
        if isinstance(obj, dict):
            if "marketplace_listing_title" in obj and "id" in obj:
                nodes.append(obj)
            for v in obj.values():
                nodes.extend(self._find_listing_nodes(v))
        elif isinstance(obj, list):
            for elem in obj:
                nodes.extend(self._find_listing_nodes(elem))
        return nodes

    def _parse_json_node(self, node: dict, query: SearchQuery) -> Optional[Offer]:
        try:
            item_id = str(node.get("id"))
            title = (node.get("marketplace_listing_title") or "").strip()
            if not title:
                return None

            price_data = node.get("listing_price", {})
            price_formatted = price_data.get("formatted_amount", "").replace("\xa0", " ")
            price_val = None
            if "amount" in price_data and price_data["amount"]:
                try:
                    price_val = float(price_data["amount"])
                except (ValueError, TypeError):
                    pass

            photo_obj = node.get("primary_listing_photo", {})
            image_url = ""
            if isinstance(photo_obj, dict):
                image_url = photo_obj.get("image", {}).get("uri", "")

            loc_obj = node.get("location", {})
            city = ""
            if isinstance(loc_obj, dict):
                rev = loc_obj.get("reverse_geocode", {})
                if isinstance(rev, dict):
                    city = rev.get("city") or rev.get("city_page", {}).get("display_name", "")

            location_str = city or query.location or "Polska"

            return Offer(
                source=self.name,
                external_id=f"fb-{item_id}",
                title=title,
                price=price_val,
                currency="PLN",
                price_formatted=price_formatted or (f"{price_val:.0f} zł" if price_val else "Zobacz na FB"),
                url=f"https://www.facebook.com/marketplace/item/{item_id}/",
                image_url=image_url,
                location=location_str,
                city=city,
                description="",
                published_at="Niedawno",
            )
        except Exception:
            return None

