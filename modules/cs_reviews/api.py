"""Read-side queries powering the /cs/reviews route.

Thin filters over the Supabase `cs_reviews` / `cs_poll_log` tables.
No writes, no Haiku, no scraping."""

from datetime import datetime, timedelta, timezone

from .db import _db


def get_reviews(platform=None, country=None, rating=None,
                days=None, year=None, limit=200, offset=0, search=None):
    q = _db().table('cs_reviews').select('*')
    if platform:
        q = q.eq('platform', platform)
    if country:
        q = q.eq('country', country.lower())
    if rating:
        try:
            q = q.eq('rating', int(rating))
        except Exception:
            pass
    if year:
        try:
            y = int(year)
            q = q.gte('review_date', f'{y}-01-01T00:00:00+00:00') \
                 .lt('review_date',  f'{y + 1}-01-01T00:00:00+00:00')
        except Exception:
            pass
    elif days:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
            q = q.gte('review_date', cutoff)
        except Exception:
            pass
    if search:
        q = q.ilike('content', f'%{search}%')
    q = q.order('review_date', desc=True).range(offset, offset + limit - 1)
    try:
        res = q.execute()
        return res.data or []
    except Exception:
        return []


def get_last_poll():
    """Return the most recent poll_log row (for 'last updated' UI hint)."""
    try:
        res = _db().table('cs_poll_log').select('*').order('started_at', desc=True).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None
