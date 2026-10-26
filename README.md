# ⚙️ MarketplaceSearch - Backend API (`marketplace-search-backend`)

Serwer REST API oraz wielowątkowy silnik scraperów dla aplikacji **MarketplaceSearch**, przeszukujący równolegle:
- **OLX** (`olx.pl`)
- **Allegro** (`allegro.pl`)
- **Allegro Lokalnie** (`allegrolokalnie.pl`)
- **Facebook Marketplace** (`facebook.com/marketplace`)

Backend został zaprojektowany z myślą o maksymalnej wydajności (odpytywanie współbieżne w `ThreadPoolExecutor`), odporności na blokady botowe (inteligentny fallback) oraz architekturze **Zero-Dependency** (działa na czystym Pythonie 3.10+ bez instalowania zewnętrznych pakietów).

---

## 🏗️ Architektura modułu

```
marketplace-search-backend/
├── server.py              # Główny serwer HTTP REST API z obsługą CORS
├── config.py              # Konfiguracja portów, nagłówków przeglądarki i slugów miast
├── requirements.txt       # Opcjonalne biblioteki produkcyjne (FastAPI, httpx, pydantic)
├── pyproject.toml         # Metadane pakietu
├── run.sh                 # Skrypt startowy jednym kliknięciem
├── Dockerfile             # Obraz kontenera Python 3.12-slim
├── docker-compose.yml     # Orkiestracja kontenera z wolumenem bazy
│
├── scrapers/              # Dedykowane moduły scraperów
│   ├── base.py            # Klasa bazowa BaseScraper oraz modele Offer, SearchQuery
│   ├── aggregator.py      # MarketplaceAggregator (współbieżne zapytania wątkowe)
│   ├── olx.py             # Scraper OLX (JSON __PRERENDERED_STATE__ + parser HTML)
│   ├── allegro.py         # Scraper Allegro (JSON-LD + oficjalne REST API)
│   ├── allegro_lokalnie.py# Scraper Allegro Lokalnie (parametry city i distance)
│   ├── facebook.py        # Scraper FB Marketplace (slugi miast i sesja)
│   └── mock_data.py       # Inteligentny generator fallback dopasowany do zapytania
│
├── database/              # Wbudowana warstwa persystencji SQLite
│   ├── schema.sql         # Tabele: search_queries, offers, scraper_logs
│   ├── seed_data.sql      # Przykładowe dane początkowe
│   └── db_manager.py      # Menadżer połączeń, transakcji i deduplikacji ofert
│
└── tests/                 # Testy automatyczne
    └── test_scrapers.py   # Testy URL builderów, filtrów i agregatora
```

---

## ⚡ Szybki start

### Opcja 1: Bezpośrednie uruchomienie
```bash
python3 server.py
```
lub przez skrypt:
```bash
./run.sh
```

Domyślnie serwer uruchamia się pod adresem: **`http://localhost:8000`**.

### Opcja 2: Uruchomienie w Dockerze
```bash
docker compose up --build
```

---

## 📡 REST API Reference

Wszystkie endpointy zwracają nagłówki CORS (`Access-Control-Allow-Origin: *`), umożliwiając bezpośrednią komunikację ze zdelokalizowanym frontendem (np. działającym na `localhost:3000`).

### 1. `GET /api/search`
Wykonuje równoległe przeszukanie serwisów ogłoszeniowych i zwraca zagregowane wyniki.

**Parametry zapytania (Query Params):**
- `q` (wymagany): Szukana fraza, np. `Switch 2`
- `location` (opcjonalny): Nazwa miasta, np. `Warszawa`
- `radius` (opcjonalny): Promień w km (`0`, `10`, `25`, `50`, `100`)
- `in_description` (opcjonalny): `true` / `false` (wyszukiwanie również w treści opisu)
- `min_price` / `max_price` (opcjonalne): Widełki cenowe w PLN
- `sources` (opcjonalny): Serwisy rozdzielone przecinkami, np. `olx,allegro,allegro_lokalnie,facebook`
- `sort_by` (opcjonalny): `newest`, `price_asc`, `price_desc`, `relevance`

**Przykładowe wywołanie:**
```bash
curl -X GET "http://localhost:8000/api/search?q=Switch+2&location=Warszawa&radius=25&in_description=true"
```

**Przykładowa odpowiedź:**
```json
{
  "query_id": 1,
  "query": "Switch 2",
  "location": "Warszawa",
  "radius_km": 25,
  "total_count": 22,
  "latency_ms": 380,
  "stats_by_source": {
    "OLX": 6,
    "Allegro": 6,
    "Allegro Lokalnie": 5,
    "Facebook Marketplace": 5
  },
  "items": [
    {
      "id": 1,
      "source": "OLX",
      "external_id": "olx-89214710",
      "title": "Nintendo Switch 2 OLED 256GB Stan Idealny",
      "price": 1850.0,
      "price_formatted": "1 850 zł",
      "currency": "PLN",
      "url": "https://www.olx.pl/d/oferta/...",
      "image_url": "https://images.unsplash.com/...",
      "location": "Warszawa, Mokotów",
      "city": "Warszawa",
      "distance_km": 5.2,
      "matches_description": false,
      "is_bookmarked": false
    }
  ]
}
```

---

### 2. `GET /api/offers`
Pobiera zapisane oferty z lokalnej bazy danych z opcją filtrowania i paginacji.

**Parametry:**
- `q`: Filtrowanie po słowie kluczowym
- `location`: Filtrowanie po lokalizacji
- `sources`: Lista źródeł (np. `OLX,Allegro`)
- `min_price` / `max_price`: Zakres cenowy
- `bookmarked`: `true` (tylko oferty dodane do ulubionych)
- `limit` (domyślnie 50), `offset` (domyślnie 0)
- `sort_by`: `newest`, `price_asc`, `price_desc`

---

### 3. `POST /api/offers/{id}/bookmark`
Przełącza stan polubienia (gwiazdka) oferty o podanym identyfikatorze numerycznym.

**Przykładowe wywołanie:**
```bash
curl -X POST "http://localhost:8000/api/offers/1/bookmark"
```

**Odpowiedź:**
```json
{
  "success": true,
  "offer_id": 1,
  "is_bookmarked": true
}
```

---

### 4. `GET /api/sources`
Zwraca listę obsługiwanych serwisów ogłoszeniowych wraz z metadanymi (kolory badge'a, nazwy, adresy URL).

### 5. `GET /api/history`
Zwraca listę ostatnich zapytań wyszukiwania zarejestrowanych w bazie danych.

### 6. `GET /api/health`
Zwraca status działania serwera (`{"status": "healthy"}`).

---

## ⚙️ Zmienne środowiskowe

| Zmienna | Domyślna wartość | Opis |
|---|---|---|
| `PORT` | `8000` | Port nasłuchiwania serwera HTTP |
| `HOST` | `0.0.0.0` | Adres IP interfejsu sieciowego |
| `DB_PATH` | `./database/marketplace.db` | Ścieżka do bazy danych SQLite |
| `ENABLE_MOCK_FALLBACK` | `true` | Tryb demonstracyjny / fallback w razie blokady antybotowej |
| `REQUEST_TIMEOUT` | `8` | Timeout zapytań HTTP do serwisów (w sekundach) |
| `ALLEGRO_CLIENT_ID` | `""` | Identyfikator aplikacji oficjalnego REST API Allegro (opcjonalny) |
| `ALLEGRO_CLIENT_SECRET` | `""` | Klucz aplikacji oficjalnego REST API Allegro (opcjonalny) |
| `FACEBOOK_COOKIE` | `""` | Ciasteczka sesyjne FB Marketplace dla zapytań prywatnych (opcjonalne) |

---

## 🧪 Testy automatyczne

```bash
python3 -m unittest tests/test_scrapers.py
```
