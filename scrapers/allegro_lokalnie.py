"""
Scraper serwisu Allegro Lokalnie (allegrolokalnie.pl)
Wyszukuje rzeczywiste oferty lokalne z uwzględnieniem miasta i promienia.
"""
import html
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
try:
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT, slugify_city
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT, slugify_city


class AllegroLokalnieScraper(BaseScraper):
    name = "Allegro Lokalnie"
    source_id = "allegro_lokalnie"
    badge_bg = "#ff7700"
    badge_color = "#ffffff"
    website_url = "https://allegrolokalnie.pl"

    def build_url(self, query: SearchQuery) -> str:
        query_encoded = urllib.parse.quote(query.text.strip().replace(" ", "-"))
        city_slug = slugify_city(query.location) if query.location else ""

        if city_slug:
            base = f"https://allegrolokalnie.pl/oferty/{city_slug}/q/{query_encoded}"
        else:
            base = f"https://allegrolokalnie.pl/oferty/q/{query_encoded}"

        params = []
        if city_slug and query.radius_km > 0:
            params.append(f"distance={query.radius_km}")
        if query.page > 1:
            params.append(f"page={query.page}")
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

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Referer": "https://allegrolokalnie.pl/",
        }

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
                    message=f"Pobrano {len(offers)} rzeczywistych ofert z Allegro Lokalnie",
                )
            else:
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Allegro Lokalnie",
                )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return ScraperResult(
                source=self.name,
                status="ERROR",
                items=[],
                latency_ms=latency_ms,
                message=f"Błąd Allegro Lokalnie: {str(e)}",
            )


    def _parse_html(self, html_content: str, query: SearchQuery) -> List[Offer]:
        offers: List[Offer] = []

        # Wyszukiwanie artykułów / kart ogłoszeń schema.org/Offer lub mlc-itembox
        articles = re.findall(
            r'<article[^>]*itemtype=[\"\']http://schema.org/Offer[\"\'][^>]*>(.*?)</article>',
            html_content,
            re.DOTALL,
        )
        if not articles:
            articles = re.findall(
                r'<article[^>]*class=[\"\'][^\"\']*mlc-item[^\"\']*[\"\'][^>]*>(.*?)</article>',
                html_content,
                re.DOTALL,
            )

        for art in articles:
            offer = self._parse_article(art)
            if offer and self.filter_offer(offer, query):
                offers.append(offer)

        return offers

    def _parse_article(self, art_html: str) -> Optional[Offer]:
        try:
            # Link do oferty
            link_match = re.search(r'href=[\"\'](/oferta/[^\"\']+)[\"\']', art_html)
            if not link_match:
                link_match = re.search(r'href=[\"\'](https?://allegrolokalnie\.pl/oferta/[^\"\']+)[\"\']', art_html)
            if not link_match:
                return None

            url = link_match.group(1)
            if not url.startswith("http"):
                url = f"https://allegrolokalnie.pl{url}"

            # Tytuł
            title_match = re.search(r'itemprop=[\"\']itemOffered[\"\'][^>]*>(.*?)</h3>', art_html, re.DOTALL)
            if not title_match:
                title_match = re.search(r'<h3[^>]*class=[\"\'][^\"\']*mlc-itembox__title[^\"\']*[\"\'][^>]*>(.*?)</h3>', art_html, re.DOTALL)
            if not title_match:
                title_match = re.search(r'<h3[^>]*class=[\"\'][^\"\']*title[^\"\']*[\"\'][^>]*>(.*?)</h3>', art_html, re.DOTALL)
            if not title_match:
                title_match = re.search(r'title=[\"\']([^\"\']+)[\"\']', art_html)

            title = ""
            if title_match:
                title = html.unescape(re.sub(r'<[^>]+>', '', title_match.group(1)).strip())

            if not title:
                return None

            # Cena
            dollars_match = re.search(r'class=[\"\']ml-offer-price__dollars[\"\'][^>]*>([^<]+)</span>', art_html)
            cents_match = re.search(r'class=[\"\']ml-offer-price__cents[\"\'][^>]*>([^<]+)</span>', art_html)

            price_val = None
            price_formatted = "Kup teraz"

            if dollars_match:
                dollars_clean = dollars_match.group(1).replace(" ", "").replace("\xa0", "")
                cents_clean = cents_match.group(1).replace(" ", "").replace("\xa0", "") if cents_match else ""
                num_str = dollars_clean + ("." + cents_clean if cents_clean else "")
                try:
                    price_val = float(num_str)
                    price_formatted = f"{price_val:,.2f} zł".replace(",", " ")
                except ValueError:
                    pass
            else:
                # Fallback ceny
                price_match = re.search(r'<span[^>]*class=[\"\'][^\"\']*price[^\"\']*[\"\'][^>]*>(.*?)</span>', art_html, re.DOTALL)
                if price_match:
                    raw_price = re.sub(r'<[^>]+>', '', price_match.group(1)).strip()
                    num = re.sub(r'[^\d,.]', '', raw_price.replace(" ", "").replace("\xa0", "")).replace(",", ".")
                    try:
                        price_val = float(num)
                        price_formatted = raw_price
                    except ValueError:
                        pass

            # Lokalizacja
            loc_match = re.search(r'<address[^>]*itemprop=[\"\']address[\"\'][^>]*>(.*?)</address>', art_html, re.DOTALL)
            if not loc_match:
                loc_match = re.search(r'<span[^>]*class=[\"\'][^\"\']*location[^\"\']*[\"\'][^>]*>(.*?)</span>', art_html, re.DOTALL)
            location_str = html.unescape(re.sub(r'<[^>]+>', '', loc_match.group(1)).strip()) if loc_match else "Polska"

            # Zdjęcie
            img_match = re.search(r'<img[^>]+(?:src|data-src)=[\"\']([^\"\']+)[\"\']', art_html)
            image_url = img_match.group(1) if img_match else ""

            # ID
            external_id = f"allok-{abs(hash(url)) % 100000000}"

            return Offer(
                source=self.name,
                external_id=external_id,
                title=title,
                price=price_val,
                currency="PLN",
                price_formatted=price_formatted,
                url=url,
                image_url=image_url,
                location=location_str,
                city=location_str.split(",")[0].strip() if location_str else "",
                description="",
                published_at="Niedawno dodane",
            )
        except Exception:
            return None

