"""
Moduł zarządzania bazą danych (SQLite / PostgreSQL)
Odpowiada za zapis zapytań, ofert oraz logów scraperów.
"""
import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "marketplace.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_data.sql")

def get_offer_list_paths() -> List[str]:
    curr = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(curr, "offer_list.json"),
        os.path.join(os.path.dirname(curr), "offer_list.json"),
        os.path.join(os.path.dirname(os.path.dirname(curr)), "offer_list.json"),
    ]
    # Check if there is a project root with database/ or backend/
    for c in list(candidates):
        folder = os.path.dirname(c)
        db_f = os.path.join(folder, "database", "offer_list.json")
        if os.path.exists(os.path.join(folder, "database")):
            candidates.append(db_f)
    seen = set()
    res = []
    for p in candidates:
        norm = os.path.normpath(p)
        if norm not in seen:
            seen.add(norm)
            res.append(norm)
    return res

OFFER_LIST_PATHS = get_offer_list_paths()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Inicjalizuje schemat bazy jeśli tabele nie istnieją oraz wykonuje migracje."""
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with self.get_connection() as conn:
            # 1. Migracja kolumny watched_search_id jeśli tabela offers już istnieje ze starszej wersji
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='offers'")
                if cursor.fetchone():
                    cursor.execute("PRAGMA table_info(offers)")
                    existing_cols = [row[1] for row in cursor.fetchall()]
                    if "watched_search_id" not in existing_cols:
                        conn.execute("ALTER TABLE offers ADD COLUMN watched_search_id INTEGER REFERENCES watched_searches(id) ON DELETE SET NULL")
            except Exception as e:
                print(f"[DB Migration] Informacja o migracji: {e}")

            # 2. Utworzenie tabel i indeksów ze schematu
            if os.path.exists(SCHEMA_PATH):
                with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                    schema_sql = f.read()
                conn.executescript(schema_sql)

        # 3. Jeśli baza jest świeża, a na dysku istnieje offer_list.json, załaduj z pliku
        self._import_offer_list_file_if_empty()

    def _import_offer_list_file_if_empty(self):
        """Importuje pozycje z pliku offer_list.json jeśli tabela jest pusta."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM watched_searches")
                count = cursor.fetchone()[0]
                if count > 0:
                    return

            for p in OFFER_LIST_PATHS:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list) and data:
                        for it in data:
                            self.add_watched_search(
                                query_text=it.get("query") or it.get("query_text") or "",
                                location=it.get("location", ""),
                                radius_km=int(it.get("radius_km", 0)),
                                search_in_description=bool(it.get("search_in_description", False)),
                                min_price=it.get("min_price"),
                                max_price=it.get("max_price"),
                                sources=it.get("sources"),
                                title=it.get("title"),
                                sort_by=it.get("sort_by", "newest"),
                                interval_seconds=int(it.get("interval_hours", 1)) * 3600,
                            )
                        break
        except Exception as e:
            print(f"[DB] Błąd importu z offer_list.json: {e}")

    def seed_initial_data(self):
        """Wypełnia bazę przykładowymi danymi do demonstracji."""
        if os.path.exists(SEED_PATH):
            with open(SEED_PATH, "r", encoding="utf-8") as f:
                seed_sql = f.read()
            with self.get_connection() as conn:
                conn.executescript(seed_sql)

    def record_search_query(
        self,
        query_text: str,
        location: str = "",
        radius_km: int = 0,
        search_in_description: bool = True,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sources: Optional[List[str]] = None,
        results_count: int = 0,
    ) -> int:
        """Zapisuje historię wyszukiwania w bazie danych i zwraca ID zapytania."""
        sources_str = ",".join(sources) if sources else "ALL"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO search_queries (
                    query_text, location, radius_km, search_in_description,
                    min_price, max_price, sources_used, results_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_text,
                    location,
                    radius_km,
                    1 if search_in_description else 0,
                    min_price,
                    max_price,
                    sources_str,
                    results_count,
                    utc_now_iso(),
                ),
            )
            return cursor.lastrowid

    def update_query_result_count(self, query_id: int, count: int):
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE search_queries SET results_count = ? WHERE id = ?",
                (count, query_id),
            )

    def upsert_offer(
        self,
        offer: Dict[str, Any],
        query_id: Optional[int] = None,
        watched_search_id: Optional[int] = None,
    ) -> int:
        """Wstawia ofertę lub aktualizuje istniejącą (deduplikacja po source + url)."""
        w_id = watched_search_id or offer.get("watched_search_id")
        q_id = query_id or offer.get("query_id")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO offers (
                    external_id, source, title, description, price, currency,
                    price_formatted, url, image_url, location, city, distance_km,
                    published_at, query_id, watched_search_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, url) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    price = excluded.price,
                    price_formatted = excluded.price_formatted,
                    image_url = excluded.image_url,
                    location = excluded.location,
                    city = excluded.city,
                    distance_km = excluded.distance_km,
                    published_at = excluded.published_at,
                    query_id = COALESCE(excluded.query_id, offers.query_id),
                    watched_search_id = COALESCE(excluded.watched_search_id, offers.watched_search_id),
                    updated_at = excluded.updated_at
                RETURNING id;
                """,
                (
                    offer.get("external_id") or "",
                    offer.get("source"),
                    offer.get("title"),
                    offer.get("description", ""),
                    offer.get("price"),
                    offer.get("currency", "PLN"),
                    offer.get("price_formatted", ""),
                    offer.get("url"),
                    offer.get("image_url", ""),
                    offer.get("location", ""),
                    offer.get("city", ""),
                    offer.get("distance_km"),
                    offer.get("published_at", ""),
                    q_id,
                    w_id,
                    utc_now_iso(),
                ),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def upsert_offers_batch(
        self,
        offers: List[Dict[str, Any]],
        query_id: Optional[int] = None,
        watched_search_id: Optional[int] = None,
    ) -> int:
        """Zapisuje partię ofert w transakcji i przypisuje ID do słowników."""
        inserted_or_updated = 0
        for offer in offers:
            try:
                db_id = self.upsert_offer(offer, query_id=query_id, watched_search_id=watched_search_id)
                offer["id"] = db_id
                inserted_or_updated += 1
            except Exception as e:
                print(f"[DB] Błąd zapisu oferty '{offer.get('title')}': {e}")
        return inserted_or_updated

    def get_offers(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        sources: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort_by: str = "newest",  # 'newest', 'price_asc', 'price_desc', 'title'
        limit: int = 100,
        offset: int = 0,
        only_bookmarked: bool = False,
        query_id: Optional[int] = None,
        watched_search_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Pobiera oferty z bazy na podstawie filtrów."""
        conditions = []
        params = []

        if query_id is not None:
            conditions.append("query_id = ?")
            params.append(query_id)

        if watched_search_id is not None:
            conditions.append("watched_search_id = ?")
            params.append(watched_search_id)

        if query:
            clean_q = query.strip()
            conditions.append("(title LIKE ? OR description LIKE ?)")
            params.extend([f"%{clean_q}%", f"%{clean_q}%"])

        if location:
            conditions.append("(location LIKE ? OR city LIKE ?)")
            params.extend([f"%{location}%", f"%{location}%"])

        if sources and len(sources) > 0:
            placeholders = ",".join("?" for _ in sources)
            conditions.append(f"source IN ({placeholders})")
            params.extend(sources)

        if min_price is not None:
            conditions.append("price >= ?")
            params.append(min_price)

        if max_price is not None:
            conditions.append("price <= ?")
            params.append(max_price)

        if only_bookmarked:
            conditions.append("is_bookmarked = 1")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        order_clauses = {
            "price_asc": "price ASC NULLS LAST, created_at DESC",
            "price_desc": "price DESC NULLS LAST, created_at DESC",
            "title": "title ASC",
            "newest": "created_at DESC",
        }
        order_by = order_clauses.get(sort_by, "created_at DESC")

        with self.get_connection() as conn:
            count_cursor = conn.cursor()
            count_cursor.execute(f"SELECT COUNT(*) FROM offers {where_clause}", params)
            total = count_cursor.fetchone()[0]

            cursor = conn.cursor()
            query_sql = f"""
                SELECT id, external_id, source, title, description, price, currency,
                       price_formatted, url, image_url, location, city, distance_km,
                       published_at, is_bookmarked, created_at
                FROM offers
                {where_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
            """
            cursor.execute(query_sql, params + [limit, offset])
            rows = [dict(row) for row in cursor.fetchall()]

            # Statystyki źródeł
            stat_sql = f"""
                SELECT source, COUNT(*) as count, MIN(price) as min_price, MAX(price) as max_price, AVG(price) as avg_price
                FROM offers
                {where_clause}
                GROUP BY source
            """
            cursor.execute(stat_sql, params)
            sources_stats = [dict(row) for row in cursor.fetchall()]

        return {
            "total": total,
            "items": rows,
            "sources_stats": sources_stats,
            "limit": limit,
            "offset": offset,
        }

    def toggle_bookmark(self, offer_id: int) -> bool:
        """Przełącza stan polubienia/zapisania oferty."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_bookmarked FROM offers WHERE id = ?", (offer_id,))
            row = cursor.fetchone()
            if not row:
                return False
            new_val = 0 if row["is_bookmarked"] == 1 else 1
            conn.execute("UPDATE offers SET is_bookmarked = ? WHERE id = ?", (new_val, offer_id))
            return bool(new_val)

    def log_scraper_run(
        self,
        source: str,
        query_id: Optional[int],
        status: str,
        items_found: int,
        latency_ms: int,
        message: str = "",
    ):
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scraper_logs (source, query_id, status, items_found, latency_ms, message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source, query_id, status, items_found, latency_ms, message),
            )

    def get_search_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, query_text, location, radius_km, search_in_description,
                       results_count, created_at
                FROM search_queries
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # OBSERWOWANE WYSZUKIWANIA (WATCHLIST / OFFER LIST - AUTO CO 1H)
    # =========================================================================

    def add_watched_search(
        self,
        query_text: str,
        location: str = "",
        radius_km: int = 0,
        search_in_description: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sources: Optional[List[str]] = None,
        title: Optional[str] = None,
        sort_by: str = "newest",
        interval_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """Dodaje nowe zapytanie do listy automatycznego monitorowania co godzinę."""
        title_clean = (title or query_text).strip()
        sources_json = json.dumps(sources or ["OLX", "Allegro", "Allegro Lokalnie", "Facebook Marketplace"])
        now = utc_now_iso()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO watched_searches (
                    title, query_text, location, radius_km, search_in_description,
                    min_price, max_price, sources, sort_by, is_active, interval_seconds,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    title_clean,
                    query_text.strip(),
                    location.strip(),
                    radius_km,
                    1 if search_in_description else 0,
                    min_price,
                    max_price,
                    sources_json,
                    sort_by,
                    interval_seconds,
                    now,
                    now,
                ),
            )
            watched_id = cursor.lastrowid

        self.save_offer_list_file()
        return self.get_watched_search(watched_id)

    def get_watched_searches(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Zwraca listę monitorowanych zapytań."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("SELECT * FROM watched_searches WHERE is_active = 1 ORDER BY created_at DESC")
            else:
                cursor.execute("SELECT * FROM watched_searches ORDER BY created_at DESC")
            rows = [dict(row) for row in cursor.fetchall()]

        for r in rows:
            if r.get("sources"):
                try:
                    r["sources"] = json.loads(r["sources"])
                except Exception:
                    r["sources"] = []
            else:
                r["sources"] = []
            r["search_in_description"] = bool(r.get("search_in_description"))
            r["is_active"] = bool(r.get("is_active"))

        return rows

    def get_watched_search(self, watched_id: int) -> Optional[Dict[str, Any]]:
        """Pobiera pojedyncze monitorowane zapytanie po ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watched_searches WHERE id = ?", (watched_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("sources"):
                try:
                    res["sources"] = json.loads(res["sources"])
                except Exception:
                    res["sources"] = []
            res["search_in_description"] = bool(res.get("search_in_description"))
            res["is_active"] = bool(res.get("is_active"))
            return res

    def delete_watched_search(self, watched_id: int) -> bool:
        """Usuwa pozycję z listy automatycznego wyszukiwania."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watched_searches WHERE id = ?", (watched_id,))
            deleted = cursor.rowcount > 0

        if deleted:
            self.save_offer_list_file()
        return deleted

    def update_watched_search_result(
        self,
        watched_id: int,
        count: int,
        checked_at: Optional[str] = None,
    ):
        """Aktualizuje statystykę ostatniego sprawdzenia w bazie i pliku offer_list.json."""
        ts = checked_at or utc_now_iso()
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE watched_searches
                SET last_results_count = ?, last_checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (count, ts, ts, watched_id),
            )
        self.save_offer_list_file()

    def save_offer_list_file(self):
        """Zapisuje aktualną listę do czytelnego pliku JSON (offer_list.json)."""
        items = self.get_watched_searches(active_only=True)
        clean_export = []
        for it in items:
            clean_export.append({
                "id": it["id"],
                "title": it["title"],
                "query": it["query_text"],
                "location": it["location"],
                "radius_km": it["radius_km"],
                "search_in_description": it["search_in_description"],
                "min_price": it["min_price"],
                "max_price": it["max_price"],
                "sources": it["sources"],
                "sort_by": it["sort_by"],
                "interval_hours": it["interval_seconds"] // 3600 if it.get("interval_seconds") else 1,
                "last_checked_at": it["last_checked_at"],
                "last_results_count": it["last_results_count"],
                "created_at": it["created_at"],
            })

        for p in OFFER_LIST_PATHS:
            try:
                dir_name = os.path.dirname(p)
                if dir_name and os.path.exists(dir_name):
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(clean_export, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[DB] Błąd zapisu do {p}: {e}")

    def get_offers_for_watched_search(
        self,
        watched_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Pobiera aktualne zapisane oferty powiązane z danym obserwowanym zapytaniem."""
        watched = self.get_watched_search(watched_id)
        if not watched:
            return {"total": 0, "items": [], "watched": None}

        # 1. Próba pobrania bezpośrednio po watched_search_id
        res = self.get_offers(watched_search_id=watched_id, limit=limit, offset=offset)
        if res["total"] > 0:
            res["watched"] = watched
            return res

        # 2. Jeśli oferty nie zostały otagowane id, wyszukaj po kryteriach zapytania
        res = self.get_offers(
            query=watched.get("query_text"),
            location=watched.get("location") or None,
            sources=watched.get("sources"),
            min_price=watched.get("min_price"),
            max_price=watched.get("max_price"),
            sort_by=watched.get("sort_by") or "newest",
            limit=limit,
            offset=offset,
        )
        res["watched"] = watched
        return res
