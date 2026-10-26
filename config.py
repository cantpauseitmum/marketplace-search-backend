"""
Konfiguracja aplikacji MarketplaceSearch
Zawiera nagłówki przeglądarek, mapowania lokalizacji oraz parametry scraperów.
"""
import os

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

# Baza danych
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "marketplace.db"))

# Klucze API (opcjonalne - dla oficjalnego API Allegro)
ALLEGRO_CLIENT_ID = os.environ.get("ALLEGRO_CLIENT_ID", "")
ALLEGRO_CLIENT_SECRET = os.environ.get("ALLEGRO_CLIENT_SECRET", "")

# Ciasteczka sesyjne FB Marketplace (opcjonalne)
FACEBOOK_COOKIE = os.environ.get("FACEBOOK_COOKIE", "")

# Tryb symulacji / fallbacku (domyślnie wyłączony, aby nigdy nie generować nieistniejących linków)
ENABLE_MOCK_FALLBACK = os.environ.get("ENABLE_MOCK_FALLBACK", "false").lower() == "true"

# Timeout dla zapytań HTTP do marketplace'ów w sekundach
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 8))

# Nagłówki udające nowoczesną przeglądarkę na systemie Mac/Windows
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Mapowanie polskich miast na slugi używane przez serwisy
CITY_SLUGS = {
    "warszawa": "warszawa",
    "krakow": "krakow",
    "kraków": "krakow",
    "wroclaw": "wroclaw",
    "wrocław": "wroclaw",
    "poznan": "poznan",
    "poznań": "poznan",
    "gdansk": "gdansk",
    "gdańsk": "gdansk",
    "lodz": "lodz",
    "łódź": "lodz",
    "katowice": "katowice",
    "szczecin": "szczecin",
    "lublin": "lublin",
    "bialystok": "bialystok",
    "białystok": "bialystok",
    "bydgoszcz": "bydgoszcz",
    "gdynia": "gdynia",
    "czestochowa": "czestochowa",
    "częstochowa": "czestochowa",
    "radom": "radom",
    "torun": "torun",
    "toruń": "torun",
    "sosnowiec": "sosnowiec",
    "kielce": "kielce",
    "gliwice": "gliwice",
    "olsztyn": "olsztyn",
    "zabrze": "zabrze",
    "bielsko-biala": "bielsko-biala",
    "bielsko-biała": "bielsko-biala",
    "bytom": "bytom",
    "zielona-gora": "zielona-gora",
    "zielona góra": "zielona-gora",
    "rybnik": "rybnik",
    "ruda-slaska": "ruda-slaska",
    "ruda śląska": "ruda-slaska",
    "opole": "opole",
    "tychy": "tychy",
    "gorzow-wielkopolski": "gorzow-wielkopolski",
    "gorzów wielkopolski": "gorzow-wielkopolski",
    "dabrowa-gornicza": "dabrowa-gornicza",
    "dąbrowa górnicza": "dabrowa-gornicza",
    "elblag": "elblag",
    "elbląg": "elblag",
    "plock": "plock",
    "płock": "plock",
    "walbrzych": "walbrzych",
    "wałbrzych": "walbrzych",
    "tarnow": "tarnow",
    "tarnów": "tarnow",
    "chorzow": "chorzow",
    "chorzów": "chorzow",
    "koszalin": "koszalin",
    "kalisz": "kalisz",
    "legnica": "legnica",
    "grudziadz": "grudziadz",
    "grudziądz": "grudziadz",
    "jaworzno": "jaworzno",
    "slupsk": "slupsk",
    "słupsk": "slupsk",
    "jastrzebie-zdroj": "jastrzebie-zdroj",
    "jastrzębie-zdrój": "jastrzebie-zdroj",
    "nowy-sacz": "nowy-sacz",
    "nowy sącz": "nowy-sacz",
    "jelenia-gora": "jelenia-gora",
    "jelenia góra": "jelenia-gora",
    "siedlce": "siedlce",
    "myslowice": "myslowice",
    "mysłowice": "myslowice",
    "konin": "konin",
    "piotrkow-trybunalski": "piotrkow-trybunalski",
    "piotrków trybunalski": "piotrkow-trybunalski",
    "pila": "pila",
    "piła": "pila",
    "inowroclaw": "inowroclaw",
    "inowrocław": "inowroclaw",
    "lubin": "lubin",
    "ostrow-wielkopolski": "ostrow-wielkopolski",
    "ostrów wielkopolski": "ostrow-wielkopolski",
    "suwalki": "suwalki",
    "suwałki": "suwalki",
    "stargard": "stargard",
    "gniezno": "gniezno",
    "pruszkow": "pruszkow",
    "pruszków": "pruszkow",
    "legionowo": "legionowo",
    "piaseczno": "piaseczno",
    "otwock": "otwock",
    "wolomin": "wolomin",
    "wołomin": "wolomin",
    "sopot": "sopot",
}


def slugify_city(city_name: str) -> str:
    """Konwertuje nazwę miasta do przyjaznego sluga."""
    if not city_name:
        return ""
    clean = city_name.strip().lower()
    if clean in CITY_SLUGS:
        return CITY_SLUGS[clean]
    # Usunięcie polskich znaków
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z", " ": "-",
    }
    for char, rep in replacements.items():
        clean = clean.replace(char, rep)
    # Usuń znaki niealfanumeryczne poza myślnikiem
    return "".join(c for c in clean if c.isalnum() or c == "-").strip("-")
