"""
Moduł obsługi walut i przeliczania kursów NBP.
Pobiera oficjalne średnie kursy walut z NBP (Tabela A) z pamięcią podręczną (TTL 12h)
oraz bezpiecznym fallbackiem na wypadek braku połączenia z siecią.
"""
import json
import re
import time
import urllib.request
from typing import Dict, Optional, Tuple

# Domyślne kursy walut (fallback gdyby NBP API było niedostępne)
STATIC_RATES: Dict[str, float] = {
    "PLN": 1.0,
    "EUR": 4.41,
    "USD": 3.95,
    "GBP": 5.27,
    "CHF": 4.77,
    "CZK": 0.181,
    "UAH": 0.095,
    "SEK": 0.385,
    "NOK": 0.375,
    "DKK": 0.591,
}

CURRENCY_SYMBOLS: Dict[str, str] = {
    "PLN": "zł",
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "CHF": "CHF",
    "CZK": "Kč",
    "UAH": "грн",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
}


class CurrencyConverter:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CurrencyConverter, cls).__new__(cls)
            cls._instance._rates = dict(STATIC_RATES)
            cls._instance._last_fetch_time = 0.0
            cls._instance._ttl_seconds = 12 * 3600  # 12 godzin
        return cls._instance

    def get_rates(self) -> Dict[str, float]:
        """Zwraca słownik kursów walut (względem PLN). Odświeża z NBP co 12h."""
        now = time.time()
        if now - self._last_fetch_time > self._ttl_seconds or len(self._rates) <= 1:
            try:
                req = urllib.request.Request(
                    "http://api.nbp.pl/api/exchangerates/tables/A/?format=json",
                    headers={"User-Agent": "MarketplaceSearch/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if isinstance(data, list) and len(data) > 0:
                            rates_list = data[0].get("rates", [])
                            for r in rates_list:
                                code = r.get("code")
                                mid = r.get("mid")
                                if code and mid:
                                    self._rates[code.upper()] = float(mid)
                            self._rates["PLN"] = 1.0
                            self._last_fetch_time = now
            except Exception:
                # W razie błędu sieci/timeoutu korzystamy ze statycznych kursów
                if not self._rates:
                    self._rates = dict(STATIC_RATES)
        return self._rates

    def detect_currency(self, text: str) -> str:
        """Rozpoznaje walutę na podstawie tekstu, symboli lub kodu ISO."""
        if not text:
            return "PLN"
        t = text.lower()

        if "€" in text or "eur" in t or "euro" in t:
            return "EUR"
        if "$" in text or "usd" in t:
            return "USD"
        if "£" in text or "gbp" in t:
            return "GBP"
        if "kč" in t or "kc" in t or "czk" in t:
            return "CZK"
        if "chf" in t or "frank" in t:
            return "CHF"
        if "грн" in t or "uah" in t:
            return "UAH"
        if "sek" in t:
            return "SEK"
        if "nok" in t:
            return "NOK"
        if "dkk" in t:
            return "DKK"
        if "zł" in t or "zl" in t or "pln" in t:
            return "PLN"
        return "PLN"

    def convert_to_pln(self, amount: float, from_currency: str) -> Tuple[float, float]:
        """
        Przelicza kwotę z zadanej waluty na PLN.
        Zwraca (kwota_w_pln, kurs_wymiany).
        """
        curr = from_currency.upper().strip()
        if curr == "PLN" or amount == 0:
            return float(amount), 1.0

        rates = self.get_rates()
        rate = rates.get(curr, STATIC_RATES.get(curr, 1.0))
        pln_amount = round(amount * rate, 2)
        return pln_amount, rate

    def format_price(
        self,
        amount: Optional[float],
        currency: str,
        original_formatted: str = "",
    ) -> Tuple[Optional[float], str, Optional[float], str]:
        """
        Zwraca spójne dane cenowe:
        (price_pln, price_formatted, original_price, original_currency)
        """
        if amount is None:
            label = original_formatted.strip() if original_formatted else "Do negocjacji"
            return None, label, None, currency

        curr = currency.upper().strip() or "PLN"
        symbol = CURRENCY_SYMBOLS.get(curr, curr)

        # Oferta darmowa lub 0
        if amount == 0:
            if curr == "PLN":
                return 0.0, "0 zł", 0.0, "PLN"
            return 0.0, f"0 zł (0 {symbol})", 0.0, curr

        # Waluta polska (PLN)
        if curr == "PLN":
            if amount % 1 == 0:
                fmt = f"{int(amount):,} zł".replace(",", " ")
            else:
                fmt = f"{amount:,.2f} zł".replace(",", " ").replace(".", ",")
            return amount, fmt, amount, "PLN"

        # Waluta obca - przeliczenie na PLN
        pln_amount, rate = self.convert_to_pln(amount, curr)

        # Formatowanie kwoty oryginalnej
        if amount % 1 == 0:
            orig_str = f"{int(amount):,} {symbol}".replace(",", " ")
        else:
            orig_str = f"{amount:,.2f} {symbol}".replace(",", " ").replace(".", ",")

        # Formatowanie kwoty w PLN
        if pln_amount % 1 == 0:
            pln_str = f"{int(pln_amount):,} zł".replace(",", " ")
        else:
            pln_str = f"{pln_amount:,.0f} zł".replace(",", " ")

        formatted = f"~{pln_str} ({orig_str})"
        return pln_amount, formatted, amount, curr


# Pojedyncza instancja konwertera dla całej aplikacji
currency_converter = CurrencyConverter()
