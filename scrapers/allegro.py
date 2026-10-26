"""
Scraper serwisu Allegro (allegro.pl)
Obsługuje bezpośrednie zapytania webowe oraz opcjonalną integrację z oficjalnym Allegro REST API.
"""
import re
import time
import base64
import json
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Optional
from .base import BaseScraper, Offer, SearchQuery, ScraperResult
from .mock_data import generate_mock_offers
try:
    from config import (
        DEFAULT_HEADERS,
        REQUEST_TIMEOUT,
        ENABLE_MOCK_FALLBACK,
        ALLEGRO_CLIENT_ID,
        ALLEGRO_CLIENT_SECRET,
    )
except (ImportError, ValueError):
    from backend.config import (
        DEFAULT_HEADERS,
        REQUEST_TIMEOUT,
        ENABLE_MOCK_FALLBACK,
        ALLEGRO_CLIENT_ID,
        ALLEGRO_CLIENT_SECRET,
    )


try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


class AllegroScraper(BaseScraper):
    name = "Allegro"
    source_id = "allegro"
    badge_bg = "#ff5a00"
    badge_color = "#ffffff"
    website_url = "https://allegro.pl"

    def build_url(self, query: SearchQuery) -> str:
        query_encoded = urllib.parse.quote(query.text.strip())
        base = f"https://allegro.pl/listing?string={query_encoded}"

        params = []
        if query.location:
            params.append(f"city={urllib.parse.quote(query.location.strip())}")
        if query.min_price is not None:
            params.append(f"price_from={int(query.min_price)}")
        if query.max_price is not None:
            params.append(f"price_to={int(query.max_price)}")

        if params:
            base += "&" + "&".join(params)
        return base

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()

        # Jeśli skonfigurowano klucze do oficjalnego API Allegro
        if ALLEGRO_CLIENT_ID and ALLEGRO_CLIENT_SECRET:
            try:
                offers = self._search_via_api(query)
                latency_ms = int((time.time() - start_time) * 1000)
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=offers,
                    latency_ms=latency_ms,
                    message=f"Pobrano {len(offers)} ofert przez oficjalne Allegro REST API",
                )
            except Exception as e:
                print(f"[Allegro API Error] {e}")

        # Wyszukiwanie przez standardowy listing Allegro
        url = self.build_url(query)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://allegro.pl/",
        }

        try:
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(url, impersonate="chrome", headers=headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 403 or "datadome" in resp.text.lower():
                    latency_ms = int((time.time() - start_time) * 1000)
                    if ENABLE_MOCK_FALLBACK:
                        mock_items = generate_mock_offers(self.name, query, count=6)
                        return ScraperResult(
                            source=self.name,
                            status="FALLBACK",
                            items=mock_items,
                            latency_ms=latency_ms,
                            message="Ochrona DataDome Allegro - tryb demonstracyjny",
                        )
                    return ScraperResult(
                        source=self.name,
                        status="WARNING",
                        items=[],
                        latency_ms=latency_ms,
                        message="Allegro.pl wymaga kluczy API (oferty lokalne pobierane z Allegro Lokalnie)",
                    )
                html = resp.text
            else:
                req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, **headers})
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
                    message=f"Pobrano {len(offers)} ofert z Allegro.pl",
                )
            else:
                if ENABLE_MOCK_FALLBACK:
                    mock_items = generate_mock_offers(self.name, query, count=6)
                    return ScraperResult(
                        source=self.name,
                        status="FALLBACK",
                        items=mock_items,
                        latency_ms=latency_ms,
                        message="Ochrona antybotowa Allegro (DataDome) - tryb demonstracyjny",
                    )
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Allegro",
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
                    message=f"Allegro (zabezpieczenie aktywne: {str(e)[:45]})",
                )
            return ScraperResult(
                source=self.name,
                status="WARNING",
                items=[],
                latency_ms=latency_ms,
                message="Allegro chronione przez DataDome (oferty C2C dostępne w Allegro Lokalnie)",
            )


    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []

        # Próba wyciągnięcia danych JSON-LD lub stanu zagnieżdżonego
        json_ld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for j_str in json_ld_matches:
            try:
                data = json.loads(j_str)
                if data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        prod = item.get("item", {})
                        title = prod.get("name", "")
                        url = prod.get("url", "")
                        offers_data = prod.get("offers", {})
                        price = float(offers_data.get("price", 0)) if offers_data.get("price") else None
                        img = prod.get("image", "")

                        offer = Offer(
                            source=self.name,
                            external_id=f"allegro-{hash(url) % 100000000}",
                            title=title,
                            price=price,
                            currency=offers_data.get("priceCurrency", "PLN"),
                            price_formatted=f"{price:.2f} zł" if price else "Kup teraz",
                            url=url,
                            image_url=img,
                            location=query.location or "Polska (wysyłka)",
                            city=query.location,
                            published_at="W ofercie",
                        )
                        if self.filter_offer(offer, query):
                            offers.append(offer)
            except Exception:
                pass

        return offers

    def _search_via_api(self, query: SearchQuery) -> List[Offer]:
        """Uwierzytelnienie OAuth2 i pobranie z oficjalnego API Allegro."""
        # Pobranie tokena
        auth_str = f"{ALLEGRO_CLIENT_ID}:{ALLEGRO_CLIENT_SECRET}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        token_req = urllib.request.Request(
            "https://allegro.pl/auth/oauth/token?grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {b64_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=b"",
        )
        with urllib.request.urlopen(token_req, timeout=REQUEST_TIMEOUT) as resp:
            token_data = json.loads(resp.read().decode())
            access_token = token_data.get("access_token")

        # Wyszukanie w API
        api_url = f"https://api.allegro.pl/offers/listing?phrase={urllib.parse.quote(query.text)}&limit=20"
        api_req = urllib.request.Request(
            api_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.allegro.public.v1+json",
            },
        )
        with urllib.request.urlopen(api_req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        offers: List[Offer] = []
        regular_items = data.get("items", {}).get("regular", [])
        for item in regular_items:
            price_val = float(item.get("sellingMode", {}).get("price", {}).get("amount", 0))
            images = item.get("images", [])
            img_url = images[0].get("url") if images else ""
            loc = item.get("location", {}).get("city", "")

            offer = Offer(
                source=self.name,
                external_id=f"allegro-{item.get('id')}",
                title=item.get("name", ""),
                price=price_val,
                currency=item.get("sellingMode", {}).get("price", {}).get("currency", "PLN"),
                price_formatted=f"{price_val:.2f} zł",
                url=f"https://allegro.pl/oferta/{item.get('id')}",
                image_url=img_url,
                location=loc or "Polska",
                city=loc,
                published_at="W sprzedaży",
            )
            if self.filter_offer(offer, query):
                offers.append(offer)

        return offers
