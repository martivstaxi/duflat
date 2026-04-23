"""Read-side queries powering the /cs/reviews route + stats panels.

Everything here is a thin filter over the Supabase `cs_reviews` /
`cs_poll_log` tables. No writes, no Haiku, no scraping."""

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


def get_available_dates(year=None, days=None):
    """Distinct YYYY-MM-DD dates that have at least one review, within the
    year/day window. Sorted most-recent first. Used by the archive navigator
    and calendar picker."""
    if year is None and days is None:
        year = datetime.now(timezone.utc).year
    try:
        q = _db().table('cs_reviews').select('review_date')
        if year:
            y = int(year)
            q = q.gte('review_date', f'{y}-01-01T00:00:00+00:00') \
                 .lt('review_date',  f'{y + 1}-01-01T00:00:00+00:00')
        elif days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
            q = q.gte('review_date', cutoff)
        res = q.limit(10000).execute()
        rows = res.data or []
    except Exception:
        return []
    seen = set()
    for r in rows:
        d = (r.get('review_date') or '')[:10]
        if d:
            seen.add(d)
    return sorted(seen, reverse=True)
