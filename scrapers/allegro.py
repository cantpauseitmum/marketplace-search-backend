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
try:
    from config import (
        DEFAULT_HEADERS,
        REQUEST_TIMEOUT,
        ALLEGRO_CLIENT_ID,
        ALLEGRO_CLIENT_SECRET,
    )
except (ImportError, ValueError):
    from backend.config import (
        DEFAULT_HEADERS,
        REQUEST_TIMEOUT,
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

    def build_url(self, query: SearchQuery, mobile: bool = False) -> str:
        query_encoded = urllib.parse.quote(query.text.strip())
        host = "m.allegro.pl" if mobile else "allegro.pl"
        base = f"https://{host}/listing?string={query_encoded}"

        params = []
        if query.location:
            params.append(f"city={urllib.parse.quote(query.location.strip())}")
        if query.page > 1:
            params.append(f"p={query.page}")
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
        api_error_msg = ""
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
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
                if e.code == 403:
                    api_error_msg = "Wymagana weryfikacja aplikacji w Allegro Developer dla /offers/listing (oferty są w Allegro Lokalnie)"
                else:
                    api_error_msg = f"Błąd Allegro API: {e.code}"
            except Exception as e:
                api_error_msg = f"Błąd Allegro API: {str(e)[:45]}"

        # Wyszukiwanie przez listing Allegro (najpierw mobile m.allegro.pl, potem allegro.pl)
        mobile_url = self.build_url(query, mobile=True)
        desktop_url = self.build_url(query, mobile=False)

        mobile_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://m.allegro.pl/",
        }

        desktop_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://allegro.pl/",
        }

        html = ""
        try:
            if HAS_CURL_CFFI:
                # Próba 1: m.allegro.pl z profilem safari iOS
                resp = cffi_requests.get(mobile_url, impersonate="safari17_2_ios", headers=mobile_headers, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200 and "datadome" not in resp.text.lower():
                    html = resp.text
                else:
                    # Próba 2: allegro.pl z profilem chrome
                    resp_desk = cffi_requests.get(desktop_url, impersonate="chrome", headers=desktop_headers, timeout=REQUEST_TIMEOUT)
                    if resp_desk.status_code == 200 and "datadome" not in resp_desk.text.lower():
                        html = resp_desk.text
            else:
                req = urllib.request.Request(desktop_url, headers={**DEFAULT_HEADERS, **desktop_headers})
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                    html = response.read().decode("utf-8", errors="ignore")

            if html:
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
                    return ScraperResult(
                        source=self.name,
                        status="OK",
                        items=[],
                        latency_ms=latency_ms,
                        message="Brak ogłoszeń na Allegro",
                    )

        except Exception as e:
            pass

        # Jeśli Allegro zablokowało zapytanie (DataDome 403 / 429 lub brak autoryzacji API)
        latency_ms = int((time.time() - start_time) * 1000)
        return ScraperResult(
            source=self.name,
            status="WARNING",
            items=[],
            latency_ms=latency_ms,
            message=api_error_msg or "Ochrona DataDome (oferty C2C są w Allegro Lokalnie)",
        )

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []
        seen_urls = set()

        # 1. Parsowanie zagnieżdżonego __listing_StoreState (m.allegro.pl i Allegro SPA)
        for s in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            text = s.group(1).strip()
            if '__listing_StoreState' in text:
                try:
                    d = json.loads(text)
                    elems = d.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
                    for el in elems:
                        if el.get('type') not in ('product', 'offer', 'regular', 'standard'):
                            continue
                        title_obj = el.get('title')
                        title = title_obj.get('text', '') if isinstance(title_obj, dict) else str(title_obj or '')
                        if not title:
                            continue
                        raw_url = el.get('url', '')
                        if not raw_url:
                            continue

                        # Oczyszczenie linku z redirectów trackingowych
                        if 'redirect=' in raw_url:
                            qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                            clean_url = qs['redirect'][0].split('?')[0] if ('redirect' in qs and qs['redirect']) else raw_url
                        else:
                            clean_url = raw_url.split('?')[0]

                        if clean_url in seen_urls:
                            continue
                        seen_urls.add(clean_url)

                        price_val = None
                        price_data = el.get('price', {})
                        if isinstance(price_data, dict):
                            main_p = price_data.get('mainPrice', {})
                            if isinstance(main_p, dict) and 'amount' in main_p:
                                try:
                                    price_val = float(main_p['amount'])
                                except (ValueError, TypeError):
                                    pass

                        photos = el.get('photos', [])
                        img_url = ''
                        if photos and isinstance(photos, list):
                            first_p = photos[0]
                            if isinstance(first_p, dict):
                                img_url = first_p.get('medium') or first_p.get('small') or ''

                        loc = el.get('location', {})
                        city = loc.get('city') if isinstance(loc, dict) else (query.location or '')

                        offer = Offer(
                            source=self.name,
                            external_id=f"allegro-{abs(hash(clean_url)) % 100000000}",
                            title=title,
                            price=price_val,
                            currency="PLN",
                            price_formatted=f"{price_val:.2f} zł" if price_val else "Kup teraz",
                            url=clean_url,
                            image_url=img_url,
                            location=city or query.location or "Polska",
                            city=city or query.location,
                            published_at="W sprzedaży",
                        )
                        if self.filter_offer(offer, query):
                            offers.append(offer)

                    if offers:
                        return offers
                except Exception:
                    pass

        # 2. Próba wyciągnięcia danych JSON-LD
        json_ld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        for j_str in json_ld_matches:
            try:
                data = json.loads(j_str)
                if data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        prod = item.get("item", {})
                        title = prod.get("name", "")
                        url = prod.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        offers_data = prod.get("offers", {})
                        price = float(offers_data.get("price", 0)) if offers_data.get("price") else None
                        img = prod.get("image", "")

                        offer = Offer(
                            source=self.name,
                            external_id=f"allegro-{abs(hash(url)) % 100000000}",
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

        # Wyszukanie w API z uwzględnieniem paginacji
        offset = (query.page - 1) * 20
        api_url = f"https://api.allegro.pl/offers/listing?phrase={urllib.parse.quote(query.text)}&limit=20&offset={offset}"
        if query.location:
            api_url += f"&location.city={urllib.parse.quote(query.location.strip())}"
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
