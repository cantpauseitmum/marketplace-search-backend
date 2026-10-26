"""
Moduł zarządzania bazą danych (SQLite / PostgreSQL)
Odpowiada za zapis zapytań, ofert oraz logów scraperów.
"""
import os
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "marketplace.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed_data.sql")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        """Inicjalizuje schemat bazy jeśli tabele nie istnieją."""
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        if os.path.exists(SCHEMA_PATH):
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            with self.get_connection() as conn:
                conn.executescript(schema_sql)

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

    def upsert_offer(self, offer: Dict[str, Any], query_id: Optional[int] = None) -> int:
        """Wstawia ofertę lub aktualizuje istniejącą (deduplikacja po source + url)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO offers (
                    external_id, source, title, description, price, currency,
                    price_formatted, url, image_url, location, city, distance_km,
                    published_at, query_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    query_id,
                    utc_now_iso(),
                ),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def upsert_offers_batch(self, offers: List[Dict[str, Any]], query_id: Optional[int] = None) -> int:
        """Zapisuje partię ofert w transakcji i przypisuje ID do słowników."""
        inserted_or_updated = 0
        for offer in offers:
            try:
                db_id = self.upsert_offer(offer, query_id)
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
    ) -> Dict[str, Any]:
        """Pobiera oferty z bazy na podstawie filtrów."""
        conditions = []
        params = []

        if query:
            conditions.append("(title LIKE ? OR description LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

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
