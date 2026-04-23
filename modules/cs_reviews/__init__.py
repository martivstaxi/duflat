"""CS Reviews — BiliBili app-store review monitoring.

Package layout (no business logic lives here — just re-exports so
`from modules import cs_reviews` keeps working):

    config.py          constants — app IDs, country lists, thresholds
    db.py              Supabase client singleton
    utils.py           internal helpers — review_hash, iso parsing
    apple.py           Apple RSS scraper
    gplay.py           Google Play batchexecute scraper
    haiku.py           Haiku enrichment + backfill
    save.py            dedup + year-scoped insert
    country_state.py   per-(platform, country) activity tracking
    poll.py            orchestrator (fan-out + save + log)
    api.py             read-side queries for Flask routes
"""

# Constants / config — consumed directly by app.py
from .config import (
    APP_CONFIG,
    APPLE_COUNTRIES,
    DISCOVERY_DAYS,
    EXCLUDED_COUNTRIES,
    GPLAY_COUNTRIES,
    INACTIVE_THRESHOLD,
)

# Supabase init
from .db import init_supabase

# Scraping primitives (debug endpoint uses these directly)
from .apple import fetch_apple_reviews
from .gplay import fetch_gplay_reviews

# Orchestration + write side
from .poll import poll_all
from .save import save_reviews
from .haiku import backfill_translations

# Country state (debug / UI surface)
from .country_state import get_country_state

# Read side (Flask routes)
from .api import (
    get_available_dates,
    get_last_poll,
    get_reviews,
)

__all__ = [
    'APP_CONFIG', 'APPLE_COUNTRIES', 'DISCOVERY_DAYS', 'EXCLUDED_COUNTRIES',
    'GPLAY_COUNTRIES', 'INACTIVE_THRESHOLD',
    'init_supabase',
    'fetch_apple_reviews', 'fetch_gplay_reviews',
    'poll_all', 'save_reviews', 'backfill_translations',
    'get_country_state',
    'get_available_dates', 'get_last_poll', 'get_reviews',
]
