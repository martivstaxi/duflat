"""Per-(platform, country) activity tracking.

Countries with INACTIVE_THRESHOLD consecutive empty polls are marked
inactive and skipped on subsequent non-full polls. full_scan re-enables
them for rediscovery."""

from datetime import datetime, timezone

from .config import INACTIVE_THRESHOLD
from .db import _db


def _load_country_state():
    """Return {(platform, country): row} — one entry per tracked pair."""
    try:
        res = _db().table('cs_country_state').select('*').execute()
        return {(r['platform'], r['country']): r for r in (res.data or [])}
    except Exception:
        return {}


def _last_full_scan_age_days():
    """Days since the most recent full_scan=True poll_log row.
    Returns None if we've never done one — which means we must do one now."""
    try:
        res = (_db().table('cs_poll_log')
               .select('started_at')
               .eq('full_scan', True)
               .order('started_at', desc=True)
               .limit(1).execute())
        rows = res.data or []
    except Exception:
        return None
    if not rows:
        return None
    try:
        s = rows[0]['started_at']
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        t = datetime.fromisoformat(s)
        return (datetime.now(timezone.utc) - t).total_seconds() / 86400
    except Exception:
        return None


def _should_skip(platform, country, state, full_scan):
    """Skip only inactive countries outside of discovery (full_scan) cycles."""
    if full_scan:
        return False
    s = state.get((platform, country))
    if not s:
        return False  # never polled — must try at least once
    return s.get('status') == 'inactive'


def _update_country_state(counts):
    """Upsert (platform, country, reviews_found) observations into state.
    Keeps the consecutive-empty counter and promotes status accordingly."""
    if not counts:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    prev_map = _load_country_state()
    rows = []
    for platform, country, count in counts:
        prev = prev_map.get((platform, country), {})
        prev_empty = prev.get('consecutive_empty_count') or 0
        prev_active_at = prev.get('last_active_at')
        if count > 0:
            status = 'active'
            empty = 0
            last_active = now_iso
        else:
            empty = prev_empty + 1
            status = 'inactive' if empty >= INACTIVE_THRESHOLD else 'unknown'
            last_active = prev_active_at
        rows.append({
            'platform': platform,
            'country': country,
            'status': status,
            'last_poll_at': now_iso,
            'last_active_at': last_active,
            'last_review_count': count,
            'consecutive_empty_count': empty,
        })
    try:
        _db().table('cs_country_state').upsert(rows, on_conflict='platform,country').execute()
    except Exception as e:
        print(f'[cs] country_state upsert failed: {e}')


def get_country_state(platform=None):
    """Read the full state table, optionally filtered by platform."""
    try:
        q = _db().table('cs_country_state').select('*')
        if platform:
            q = q.eq('platform', platform)
        res = q.order('platform').order('country').execute()
        return res.data or []
    except Exception:
        return []
