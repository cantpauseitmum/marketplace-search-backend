"""
Moduł generujący realistyczne ogłoszenia testowe / fallback
dopasowane do zapytania użytkownika (tytuł, opis, miasto, cena, zdjęcia).
"""
import random
from typing import List
from .base import Offer, SearchQuery

DEFAULT_IMAGES = {
    "console": [
        "https://images.unsplash.com/photo-1578303512597-81e6cc155b3e?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1612287271162-265f7714ce3a?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=600&auto=format&fit=crop&q=80",
    ],
    "phone": [
        "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1592750475338-74b7b21085ab?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1565849904461-04a58ad377e0?w=600&auto=format&fit=crop&q=80",
    ],
    "laptop": [
        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=600&auto=format&fit=crop&q=80",
    ],
    "default": [
        "https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&auto=format&fit=crop&q=80",
    ],
}


def pick_image(query_text: str, idx: int) -> str:
    q = query_text.lower()
    if any(k in q for k in ["switch", "playstation", "ps5", "xbox", "konsola", "nintendo"]):
        category = "console"
    elif any(k in q for k in ["iphone", "samsung", "telefon", "xiaomi", "pixel"]):
        category = "phone"
    elif any(k in q for k in ["macbook", "laptop", "dell", "lenovo", "thinkpad"]):
        category = "laptop"
    else:
        category = "default"
    pool = DEFAULT_IMAGES[category]
    return pool[idx % len(pool)]


def generate_mock_offers(source: str, query: SearchQuery, count: int = 5) -> List[Offer]:
    """Generuje realistyczne oferty dla danego źródła i zapytania."""
    city = query.location.capitalize() if query.location else "Warszawa"
    district_list = {
        "Warszawa": ["Mokotów", "Śródmieście", "Ursynów", "Wola", "Praga-Południe", "Bielany", "Bemowo"],
        "Kraków": ["Krowodrza", "Stare Miasto", "Podgórze", "Dębniki", "Nowa Huta", "Grzegórzki"],
        "Wrocław": ["Krzyki", "Fabryczna", "Stare Miasto", "Śródmieście", "Psie Pole"],
        "Poznań": ["Jeżyce", "Grunwald", "Wilda", "Stare Miasto", "Rataje"],
        "Gdańsk": ["Wrzeszcz", "Oliwa", "Przymorze", "Śródmieście", "Morena"],
    }
    districts = district_list.get(city, ["Centrum", "Północ", "Południe", "Okolice"])

    titles_templates = {
        "OLX": [
            "{q} - Stan idealny, pełen komplet, gwarancja!",
            "{q} + dodatkowe akcesoria, mało używany",
            "Okazja! {q} jak nowy ze sklepu, dowód zakupu",
            "Sprzedam pilnie {q} odbiór osobisty w {city}",
            "{q} w super stanie, dorzucam gratis etui",
        ],
        "Allegro": [
            "{q} Nowy Oryginał F-VAT 23% Wysyłka 24h SMART",
            "Oficjalna Dystrybucja {q} Gwarancja Producenta 24m",
            "{q} Zestaw Premium + Akcesoria | Super Cena",
            "{q} Stan Sklepowy - Komplet Producenta",
            "Bestseller: {q} Ekspresowa dostawa kurierem",
        ],
        "Allegro Lokalnie": [
            "{q} kupiony 3 msc temu, użyty kilka razy",
            "Zadbany {q} polecam, możliwa wysyłka Paczkomat",
            "{q} od osoby prywatnej, bez wad, polecam!",
            "{q} komplet fabryczny, folia na ekranie",
            "Sprzedam {q} - stan jak na zdjęciach, odbiór {city}",
        ],
        "Facebook Marketplace": [
            "{q} stan bdb, szybka sprzedaż",
            "{q} z papierami i pudełkiem, możliwa negocjacja",
            "Cześć, mam do sprzedania {q}, wszystko sprawne",
            "{q} - preferowany odbiór osobisty {city}",
            "{q} leży nieużywany, stan igła",
        ],
    }

    descriptions = [
        "Sprzedaję swój prywatny egzemplarz {q}. Urządzenie jest w 100% sprawne, bez rys ani ukrytych wad. W zestawie oryginalne pudełko, kable oraz dowód zakupu uprawniający do gwarancji.",
        "Oferuję na sprzedaż {q}. Sprzęt kupiony w polskim elektromarkecie. Bardzo mało używany, bateria trzyma jak w nowym urządzeniu. Możliwy odbiór w {city} lub bezpieczna przesyłka.",
        "Na sprzedaż trafia {q}. Wszystko działa bez zarzutu, zadbany, noszony od nowości w etui ochronnym. Zapraszam do przetestowania na miejscu w {city}.",
        "Przedmiotem ogłoszenia jest {q}. Stan wizualny oraz techniczny oceniam na wzorowy. Sprzedaję wyłącznie z powodu braku czasu. Chętnie odpowiem na dodatkowe pytania.",
    ]

    base_prices = {
        "switch": 1750,
        "switch 2": 1850,
        "ps5": 1900,
        "xbox": 1600,
        "iphone": 2800,
        "laptop": 2500,
        "rower": 1400,
    }

    q_lower = query.text.lower()
    base_price = 1200
    for key, val in base_prices.items():
        if key in q_lower:
            base_price = val
            break

    # Jeśli podano widełki cenowe
    if query.min_price and query.max_price:
        base_price = (query.min_price + query.max_price) / 2
    elif query.min_price:
        base_price = max(base_price, query.min_price + 100)
    elif query.max_price:
        base_price = min(base_price, query.max_price - 100)

    url_templates = {
        "OLX": "https://www.olx.pl/d/oferta/{slug}-ID{id}.html",
        "Allegro": "https://allegro.pl/oferta/{slug}-{id}",
        "Allegro Lokalnie": "https://allegrolokalnie.pl/oferta/{slug}-{id}",
        "Facebook Marketplace": "https://www.facebook.com/marketplace/item/{id}/",
    }

    templates = titles_templates.get(source, titles_templates["OLX"])
    offers: List[Offer] = []

    for i in range(count):
        ext_id = str(random.randint(10000000, 99999999))
        price_variation = random.uniform(-0.15, 0.20)
        calculated_price = round((base_price * (1 + price_variation)) / 10) * 10

        # Filtrowanie po cenie min/max jeśli podano
        if query.min_price and calculated_price < query.min_price:
            calculated_price = query.min_price + 50
        if query.max_price and calculated_price > query.max_price:
            calculated_price = query.max_price - 50

        raw_title = templates[i % len(templates)].format(q=query.text.strip(), city=city)
        # Czasami fraza jest w tytule, a czasami w opisie (dla przetestowania wyszukiwania w opisie)
        if i == 3 and query.search_in_description:
            title = f"Świetny zestaw dla gracza / sprzęt multimedialny ({city})"
            desc = f"W skład zestawu wchodzi oryginalny {query.text}. " + descriptions[i % len(descriptions)].format(q=query.text, city=city)
            matches_desc = True
        else:
            title = raw_title
            desc = descriptions[i % len(descriptions)].format(q=query.text, city=city)
            matches_desc = False

        district = districts[i % len(districts)]
        distance = round(random.uniform(1.2, max(5.0, float(query.radius_km or 15))), 1)
        location_str = f"{city}, {district}" if city else "Cała Polska"

        slug = query.text.lower().replace(" ", "-")
        url = url_templates.get(source, "https://example.com").format(slug=slug, id=ext_id)
        img = pick_image(query.text, i)

        times = ["12 min temu", "45 min temu", "2 godz. temu", "Dzisiaj o 11:30", "Wczoraj o 19:40"]
        published_at = times[i % len(times)]

        offers.append(
            Offer(
                source=source,
                external_id=f"{source.lower()[:3]}-{ext_id}",
                title=title,
                price=calculated_price,
                currency="PLN",
                price_formatted=f"{calculated_price:,.0f} zł".replace(",", " "),
                url=url,
                image_url=img,
                location=location_str,
                city=city,
                distance_km=distance,
                description=desc,
                published_at=published_at,
                matches_description=matches_desc,
            )
        )

    return offers
