"""
Scraper serwisu Vinted (vinted.pl)
Pobiera rzeczywiste oferty z oficjalnego katalogu REST API Vinted (api.vinted.com).
Wszystkie oferty na Vinted posiadają bezpieczną formę przesyłki oraz ochronę kupującego,
dlatego zgodnie z logiką biznesową są prezentowane zawsze niezależnie od wybranej odległości.
"""
import gzip
import json
import ssl
import time
import urllib.parse
import urllib.request
from typing import List, Optional, Dict, Any

from .base import BaseScraper, Offer, SearchQuery, ScraperResult
try:
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT


class VintedScraper(BaseScraper):
    name = "Vinted"
    source_id = "vinted"
    badge_bg = "#007782"
    badge_color = "#ffffff"
    website_url = "https://www.vinted.pl"

    def __init__(self):
        super().__init__()
        self._cached_cookies: Dict[str, str] = {}
        self._cached_at: float = 0.0
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _get_session_cookies(self) -> Dict[str, str]:
        """Pobiera i buforuje tokeny sesyjne oraz ciasteczka z vinted.pl (ważne przez 10 min)."""
        now = time.time()
        if self._cached_cookies and (now - self._cached_at) < 600:
            return self._cached_cookies

        headers = {
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        }
        req = urllib.request.Request("https://www.vinted.pl", headers=headers)
        cookies: Dict[str, str] = {}

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=self._ssl_ctx) as resp:
                for c in resp.headers.get_all("Set-Cookie") or []:
                    parts = c.split(";")[0].split("=", 1)
                    if len(parts) == 2:
                        cookies[parts[0].strip()] = parts[1].strip()

            if cookies:
                self._cached_cookies = cookies
                self._cached_at = now
        except Exception:
            pass

        return self._cached_cookies

    def build_url(self, query: SearchQuery) -> str:
        """Zwraca URL podglądu wyników w serwisie webowym Vinted."""
        q_enc = urllib.parse.quote(query.text.strip())
        url = f"https://www.vinted.pl/catalog?search_text={q_enc}"
        if query.min_price is not None:
            url += f"&price_from={int(query.min_price)}"
        if query.max_price is not None:
            url += f"&price_to={int(query.max_price)}"
        if query.page > 1:
            url += f"&page={query.page}"
        return url

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()
        offers: List[Offer] = []
        cookies = self._get_session_cookies()

        q_enc = urllib.parse.quote(query.text.strip())
        per_page = 40
        api_url = (
            f"https://api.vinted.com/svc-catalogue/items?search_text={q_enc}"
            f"&page={query.page}&per_page={per_page}&order=newest_first"
        )
        if query.min_price is not None:
            api_url += f"&price_from={int(query.min_price)}"
        if query.max_price is not None:
            api_url += f"&price_to={int(query.max_price)}"

        req_headers = {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Accept-Encoding": "identity",
            "Referer": f"https://www.vinted.pl/catalog?search_text={q_enc}",
        }

        if cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
            req_headers["Cookie"] = cookie_str
            if "access_token_web" in cookies and cookies["access_token_web"]:
                req_headers["Authorization"] = f"Bearer {cookies['access_token_web']}"

        req = urllib.request.Request(api_url, headers=req_headers)

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=self._ssl_ctx) as resp:
                raw_bytes = resp.read()
                if resp.info().get("Content-Encoding") == "gzip" or raw_bytes.startswith(b"\x1f\x8b"):
                    raw_bytes = gzip.decompress(raw_bytes)
                data = json.loads(raw_bytes.decode("utf-8"))
                raw_items = data.get("items", [])
                for item in raw_items:
                    offer = self._parse_vinted_item(item, query)
                    if offer and self.filter_offer(offer, query):
                        offers.append(offer)

            latency_ms = int((time.time() - start_time) * 1000)

            if offers:
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=offers,
                    latency_ms=latency_ms,
                    message=f"Pobrano {len(offers)} rzeczywistych ofert z Vinted (strona {query.page})",
                )

            return ScraperResult(
                source=self.name,
                status="OK",
                items=[],
                latency_ms=latency_ms,
                message="Brak ogłoszeń na Vinted spełniających kryteria",
            )

        except Exception as e:
            # W razie błędu wyczyść bufor sesji na wypadek przedawnienia tokenu
            self._cached_cookies = {}
            self._cached_at = 0.0
            latency_ms = int((time.time() - start_time) * 1000)
            return ScraperResult(
                source=self.name,
                status="WARNING",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd Vinted: {str(e)}",
            )

    def _parse_vinted_item(self, item: Dict[str, Any], query: SearchQuery) -> Optional[Offer]:
        try:
            item_id = str(item.get("id"))
            title = (item.get("title") or "").strip()
            if not title or not item_id:
                return None

            raw_url = item.get("url") or f"/items/{item_id}"
            full_url = raw_url if raw_url.startswith("http") else f"https://www.vinted.pl{raw_url}"

            price_info = item.get("price")
            price_val: Optional[float] = None
            currency = "PLN"

            if isinstance(price_info, dict):
                amount_str = price_info.get("amount")
                if amount_str:
                    price_val = float(amount_str)
                currency = price_info.get("currency_code", "PLN")
            elif price_info is not None:
                try:
                    price_val = float(price_info)
                except ValueError:
                    pass

            price_formatted = f"{price_val:,.2f} {currency}".replace(",", " ").replace(".00", "") if price_val is not None else "Do negocjacji"

            photos = item.get("photos", [])
            image_url = ""
            if photos and isinstance(photos, list):
                first_photo = photos[0]
                if isinstance(first_photo, dict):
                    image_url = first_photo.get("url") or first_photo.get("full_size_url") or ""
                elif isinstance(first_photo, str):
                    image_url = first_photo

            user = item.get("user") or {}
            user_city = user.get("city") or ""
            user_country = user.get("country_title") or ""
            if user_city and user_country:
                location_str = f"{user_city}, {user_country}"
            elif user_city:
                location_str = user_city
            elif user_country:
                location_str = user_country
            else:
                location_str = "Wysyłka (Vinted)"

            return Offer(
                source=self.name,
                external_id=f"vinted-{item_id}",
                title=title,
                price=price_val,
                currency=currency,
                price_formatted=price_formatted,
                url=full_url,
                image_url=image_url,
                location=location_str,
                city=user_city,
                description=item.get("description", "") or "",
                published_at="Niedawno",
                has_delivery=True,
                delivery_label="Vinted (Ochrona Kupującego)",
            )
        except Exception:
            return None
