"""
Scraper serwisu Swapie (swapie.pl)
Pobiera rzeczywiste oferty z polskiej platformy wymiany i sprzedaży gier oraz książek.
Wszystkie oferty w serwisie Swapie są objęte ochroną kupującego i wysyłką (InPost Paczkomat / DPD),
dlatego wyświetlają się zawsze niezależnie od wybranej lokalizacji.
"""
import re
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


class SwapieScraper(BaseScraper):
    name = "Swapie"
    source_id = "swapie"
    badge_bg = "#6366f1"
    badge_color = "#ffffff"
    website_url = "https://swapie.pl"

    def __init__(self):
        super().__init__()
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def build_url(self, query: SearchQuery) -> str:
        """Buduje URL wyszukiwania w serwisie Swapie."""
        q_enc = urllib.parse.quote(query.text.strip())
        url = f"https://swapie.pl/przegladaj?q={q_enc}"
        if query.page > 1:
            url += f"&page={query.page}"
        return url

    def search(self, query: SearchQuery) -> ScraperResult:
        start_time = time.time()
        offers: List[Offer] = []
        url = self.build_url(query)

        headers = {
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://swapie.pl/",
        }

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=self._ssl_ctx) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                offers = self._parse_html(html, query)

            latency_ms = int((time.time() - start_time) * 1000)

            if offers:
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=offers,
                    latency_ms=latency_ms,
                    message=f"Pobrano {len(offers)} rzeczywistych ofert z Swapie.pl (strona {query.page})",
                )

            return ScraperResult(
                source=self.name,
                status="OK",
                items=[],
                latency_ms=latency_ms,
                message="Brak ogłoszeń na Swapie spełniających kryteria",
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return ScraperResult(
                source=self.name,
                status="WARNING",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd Swapie: {str(e)}",
            )

    def _parse_html(self, html: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []
        # Wyszukujemy karty ofert: linki prowadzące do kategorii gier, komiksów lub książek
        pattern = r'<a[^>]*href=[\"\'](/[^\"\']*(?:ksiazki|gry-[^\"\']+|komiksy)/[a-f0-9-]+[^\"\']*)[\"\'][^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        seen_urls = set()

        for href, content in matches:
            try:
                full_url = f"https://swapie.pl{href}"
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                # Wyciągnięcie ID oferty z URL
                id_match = re.search(r'/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', href)
                item_id = id_match.group(1) if id_match else href.split("/")[-1][:20]

                # Tytuł z atrybutu alt obrazka lub treści karty
                title_m = re.search(r'alt=[\"\']([^\"\']+)[\"\']', content)
                title = title_m.group(1).strip() if title_m else ""
                if not title:
                    texts = re.findall(r'>([^<]{3,80})<', content)
                    title = texts[0].strip() if texts else "Oferta na Swapie"

                # Cena w PLN
                price_m = re.search(r'(\d+(?:[\s,]\d+)?)\s*zł', content)
                price_val: Optional[float] = None
                if price_m:
                    raw_price = price_m.group(1).replace(" ", "").replace(",", ".")
                    try:
                        price_val = float(raw_price)
                    except ValueError:
                        pass

                price_formatted = f"{price_val:,.2f} zł".replace(",", " ").replace(".00", "") if price_val is not None else "Do negocjacji"

                # Zdjęcie
                img_m = re.search(r'src=[\"\'](https?://[^\"\']+)[\"\']', content)
                image_url = img_m.group(1) if img_m else ""

                offer = Offer(
                    source=self.name,
                    external_id=f"swapie-{item_id}",
                    title=title,
                    price=price_val,
                    currency="PLN",
                    price_formatted=price_formatted,
                    url=full_url,
                    image_url=image_url,
                    location="Wysyłka (InPost / DPD)",
                    city="",
                    description="",
                    published_at="Niedawno",
                    has_delivery=True,
                    delivery_label="Swapie (InPost / Ochrona)",
                )

                if self.filter_offer(offer, query):
                    offers.append(offer)

            except Exception:
                continue

        return offers
