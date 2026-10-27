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
try:
    from config import DEFAULT_HEADERS, REQUEST_TIMEOUT, FACEBOOK_COOKIE, slugify_city
except (ImportError, ValueError):
    from backend.config import DEFAULT_HEADERS, REQUEST_TIMEOUT, FACEBOOK_COOKIE, slugify_city

try:
    from currency import currency_converter
except (ImportError, ValueError):
    from backend.currency import currency_converter


FB_CITY_SLUGS = {
    # Huby bezpośrednio wspierane przez FB Marketplace w Polsce
    "warszawa": "warsaw",
    "warsaw": "warsaw",
    "krakow": "krakow",
    "kraków": "krakow",
    "poznan": "poznan",
    "poznań": "poznan",
    "lodz": "lodz",
    "łódź": "lodz",
    "lublin": "lublin",

    # Regiony przygraniczne (np. Słubice <-> Frankfurt nad Odrą, Zgorzelec, Cieszyn)
    "slubice": "frankfurt",
    "słubice": "frankfurt",
    "frankfurt": "frankfurt",
    "kostrzyn": "frankfurt",
    "gorzow": "frankfurt",
    "gorzów": "frankfurt",
    "zgorzelec": "dresden",
    "szczecin": "berlin",
    "swinoujscie": "berlin",
    "świnoujście": "berlin",
    "berlin": "berlin",
    "cieszyn": "prague",
    "prague": "prague",
    "praha": "prague",

    # Śląsk i Małopolska -> krakow
    "katowice": "krakow",
    "gliwice": "krakow",
    "sosnowiec": "krakow",
    "zabrze": "krakow",
    "bytom": "krakow",
    "bielsko": "krakow",
    "bielsko-biala": "krakow",
    "bielsko-biała": "krakow",
    "rybnik": "krakow",
    "tychy": "krakow",
    "czestochowa": "krakow",
    "częstochowa": "krakow",
    "rzeszow": "krakow",
    "rzeszów": "krakow",
    "tarnow": "krakow",
    "tarnów": "krakow",

    # Dolny Śląsk i Wielkopolska -> wroclaw / poznan
    "wroclaw": "wroclaw",
    "wrocław": "wroclaw",
    "legnica": "poznan",
    "opole": "poznan",
    "walbrzych": "poznan",
    "wałbrzych": "poznan",
    "zielona gora": "poznan",
    "zielonagora": "poznan",
    "zielona góra": "poznan",
    "kalisz": "poznan",
    "leszno": "poznan",
    "pila": "poznan",
    "piła": "poznan",

    # Pomorze i Północ -> warsaw
    "gdansk": "warsaw",
    "gdańsk": "warsaw",
    "gdynia": "warsaw",
    "sopot": "warsaw",
    "trojmiasto": "warsaw",
    "trójmiasto": "warsaw",
    "bydgoszcz": "warsaw",
    "torun": "warsaw",
    "toruń": "warsaw",
    "olsztyn": "warsaw",
    "elblag": "warsaw",
    "elbląg": "warsaw",
    "bialystok": "warsaw",
    "białystok": "warsaw",
    "kielce": "warsaw",
    "radom": "warsaw",
    "plock": "warsaw",
    "płock": "warsaw",
}


class FacebookMarketplaceScraper(BaseScraper):
    name = "Facebook Marketplace"
    source_id = "facebook"
    badge_bg = "#1877f2"
    badge_color = "#ffffff"
    website_url = "https://www.facebook.com/marketplace"

    def get_city_slug(self, query: SearchQuery) -> str:
        # 1. Sprawdź czy podano lokalizację
        loc = (query.location or "").strip().lower()
        # 2. Jeśli wybrano 'Cała Polska', użyj punktu startowego wpisanego przez użytkownika (np. Poznań, Słubice)
        if not loc:
            loc = (query.raw_location or "").strip().lower()
        # 3. Jeśli użytkownik nie podał żadnego miasta, użyj Warszawy jako centralnego polskiego punktu
        if not loc:
            loc = "warsaw"

        # Bezpośrednie lub częściowe dopasowanie do znanych hubów regionalnych
        loc_clean = re.sub(r"[^\w\s-]", "", loc).strip()
        if loc_clean in FB_CITY_SLUGS:
            return FB_CITY_SLUGS[loc_clean]

        for k, v in FB_CITY_SLUGS.items():
            if k in loc_clean:
                return v

        # Zabezpieczenie: jeśli slug nie jest wspierany bezpośrednio przez FB, użyj najbliższego hubu (domyślnie 'warsaw')
        # Zapobiega to przekierowaniu przez FB na /category/search/ (które domyślnie ląduje w Kalifornii)
        VALID_HUBS = {"warsaw", "poznan", "krakow", "lodz", "lublin", "frankfurt", "berlin", "prague"}
        slug = slugify_city(loc_clean)
        if slug in VALID_HUBS:
            return slug
        return "warsaw"

    def build_url(self, query: SearchQuery) -> str:
        query_encoded = urllib.parse.quote(query.text.strip())
        city_slug = self.get_city_slug(query)
        base = f"https://www.facebook.com/marketplace/{city_slug}/search/?query={query_encoded}"

        params = []
        if query.radius_km == 0 and query.location:
            params.append("exact=true")
        elif query.radius_km > 0:
            params.append(f"radius={query.radius_km}")

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
                return ScraperResult(
                    source=self.name,
                    status="OK",
                    items=[],
                    latency_ms=latency_ms,
                    message="Brak ogłoszeń na Facebook Marketplace",
                )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
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

            # Waluta i cena (obsługuje PLN oraz waluty obce np. EUR, USD, CZK, GBP)
            price_data = node.get("listing_price", {})
            raw_fmt = price_data.get("formatted_amount", "").replace("\xa0", " ")
            currency = currency_converter.detect_currency(raw_fmt)

            raw_amount = None
            if "amount" in price_data and price_data["amount"] is not None:
                try:
                    raw_amount = float(price_data["amount"])
                except (ValueError, TypeError):
                    pass

            # Przeliczenie walut obcych na PLN z zachowaniem oryginalnej ceny i waluty
            price_pln, price_formatted, orig_price, orig_curr = currency_converter.format_price(
                raw_amount, currency, original_formatted=raw_fmt
            )

            # Informacje o lokalizacji (nie ukrywamy ofert zagranicznych ani przygranicznych, np. Frankfurt, Görlitz)
            loc_obj = node.get("location", {})
            city = ""
            state = ""
            display_name = ""
            if isinstance(loc_obj, dict):
                rev = loc_obj.get("reverse_geocode", {})
                if isinstance(rev, dict):
                    city = rev.get("city") or ""
                    state = rev.get("state") or ""
            # Odrzucenie serwerowego fallbacku Meta z USA (gdy FB przekieruje zapytanie na /category/search/)
            # Wyniki europejskie (Polska, Niemcy/Frankfurt/Görlitz, Czechy, Słowacja itd.) są zachowywane i przeliczane na PLN
            us_states = {
                "CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
                "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
                "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
                "IA", "NV", "AR", "MS", "KS", "NM", "NE", "WV", "ID", "HI"
            }
            if state.upper() in us_states or "california" in display_name.lower() or "united states" in display_name.lower():
                return None

            if display_name:
                location_str = display_name
            elif city and state:
                location_str = f"{city}, {state}"
            elif city:
                location_str = city
            else:
                location_str = query.location or query.raw_location or "Polska"

            photo_obj = node.get("primary_listing_photo", {})
            image_url = ""
            if isinstance(photo_obj, dict):
                image_url = photo_obj.get("image", {}).get("uri", "")

            return Offer(
                source=self.name,
                external_id=f"fb-{item_id}",
                title=title,
                price=price_pln,
                currency="PLN",
                price_formatted=price_formatted,
                original_price=orig_price,
                original_currency=orig_curr,
                url=f"https://www.facebook.com/marketplace/item/{item_id}/",
                image_url=image_url,
                location=location_str,
                city=city or location_str,
                description="",
                published_at="Niedawno",
            )
        except Exception:
            return None


