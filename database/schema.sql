-- Schema bazy danych dla aplikacji MarketplaceSearch
-- Obsługuje SQLite oraz PostgreSQL

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    location TEXT DEFAULT '',
    radius_km INTEGER DEFAULT 0,
    search_in_description INTEGER DEFAULT 1,
    min_price REAL,
    max_price REAL,
    sources_used TEXT,
    results_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watched_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    query_text TEXT NOT NULL,
    location TEXT DEFAULT '',
    radius_km INTEGER DEFAULT 0,
    search_in_description INTEGER DEFAULT 0,
    min_price REAL,
    max_price REAL,
    sources TEXT, -- JSON lista: np. ["OLX", "Allegro Lokalnie"]
    sort_by TEXT DEFAULT 'newest',
    is_active INTEGER DEFAULT 1,
    interval_seconds INTEGER DEFAULT 3600,
    last_checked_at TIMESTAMP,
    last_results_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    source TEXT NOT NULL, -- 'OLX', 'Allegro', 'Allegro Lokalnie', 'Facebook Marketplace'
    title TEXT NOT NULL,
    description TEXT,
    price REAL,
    currency TEXT DEFAULT 'PLN',
    price_formatted TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    location TEXT,
    city TEXT,
    distance_km REAL,
    published_at TEXT,
    query_id INTEGER REFERENCES search_queries(id) ON DELETE SET NULL,
    watched_search_id INTEGER REFERENCES watched_searches(id) ON DELETE SET NULL,
    is_bookmarked INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_url UNIQUE (source, url)
);

CREATE TABLE IF NOT EXISTS scraper_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    query_id INTEGER REFERENCES search_queries(id) ON DELETE CASCADE,
    status TEXT NOT NULL, -- 'SUCCESS', 'WARNING', 'ERROR'
    items_found INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indeksy dla szybkiego wyszukiwania i filtrowania
CREATE INDEX IF NOT EXISTS idx_offers_source ON offers(source);
CREATE INDEX IF NOT EXISTS idx_offers_title ON offers(title);
CREATE INDEX IF NOT EXISTS idx_offers_price ON offers(price);
CREATE INDEX IF NOT EXISTS idx_offers_location ON offers(location);
CREATE INDEX IF NOT EXISTS idx_offers_created_at ON offers(created_at);
CREATE INDEX IF NOT EXISTS idx_offers_query_id ON offers(query_id);
CREATE INDEX IF NOT EXISTS idx_offers_watched_id ON offers(watched_search_id);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON search_queries(created_at);
CREATE INDEX IF NOT EXISTS idx_watched_active ON watched_searches(is_active);
CREATE INDEX IF NOT EXISTS idx_watched_created ON watched_searches(created_at);
