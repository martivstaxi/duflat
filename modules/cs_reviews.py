"""
CS Reviews Module — BiliBili review monitoring.

Scrapes Apple App Store (iTunes RSS JSON) and Google Play (batchexecute
RPC) across all major territories for the BiliBili app. Results land in
the Supabase `cs_reviews` table — completely separate from the
`social_*` tables used by the social listening module.

Public entry points:
    init_supabase(url, key)       → set up the Supabase client
    fetch_apple_reviews(cc)       → Apple RSS for one country
    fetch_gplay_reviews(cc, lg)   → Google Play for one country
    poll_all(platform=None)       → poll every country, save new rows
    get_reviews(**filters)        → frontend query
    get_stats(days=1)              → aggregate counts
"""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

from modules.constants import BROWSER_HEADERS


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

APP_CONFIG = {
    'name': 'BiliBili',
    'android_package': 'tv.danmaku.bili',
    'ios_id': '736536022',  # bilibili — "All Your Fav Videos" (bundle id tv.danmaku.bilianime)
}

# Country-state knobs — adjust here.
INACTIVE_THRESHOLD = 3   # consecutive empty polls → country marked inactive
DISCOVERY_DAYS = 30      # force a full re-scan of every country this often

# Scope rule: Mainland China excluded across all platforms. HK, TW, MO in scope.
EXCLUDED_COUNTRIES = {'cn'}

APPLE_COUNTRIES = [
    'us', 'gb', 'ca', 'au', 'nz', 'ie',
    'de', 'fr', 'it', 'es', 'nl', 'be', 'ch', 'at', 'se', 'no', 'dk', 'fi',
    'pl', 'cz', 'sk', 'hu', 'ro', 'bg', 'hr', 'si', 'rs', 'gr', 'pt',
    'lt', 'lv', 'ee', 'is', 'mt', 'lu', 'cy', 'md',
    'hk', 'mo', 'tw', 'jp', 'kr',
    'sg', 'my', 'id', 'ph', 'th', 'vn',
    'in', 'pk', 'bd', 'lk', 'np',
    'ru', 'ua', 'by', 'kz', 'uz', 'az', 'am', 'ge', 'kg', 'tj', 'tm',
    'tr', 'il', 'sa', 'ae', 'qa', 'kw', 'bh', 'om', 'jo', 'lb', 'eg',
    'za', 'ng', 'ke', 'gh', 'tz', 'ug', 'zw', 'ci', 'sn', 'cm',
    'dz', 'ma', 'tn',
    'br', 'mx', 'ar', 'cl', 'co', 'pe', 'uy', 'py', 'bo', 've', 'ec',
    'cr', 'pa', 'gt', 'sv', 'hn', 'ni', 'do',
]

# Google Play — country → primary UI language (hl, gl).
GPLAY_COUNTRIES = {
    'us': 'en', 'gb': 'en', 'ca': 'en', 'au': 'en', 'nz': 'en', 'ie': 'en',
    'de': 'de', 'at': 'de', 'ch': 'de',
    'fr': 'fr', 'be': 'fr', 'lu': 'fr',
    'it': 'it',
    'es': 'es', 'mx': 'es', 'ar': 'es', 'co': 'es', 'cl': 'es', 'pe': 'es',
    'uy': 'es', 've': 'es', 'ec': 'es', 'cr': 'es', 'pa': 'es', 'gt': 'es',
    'nl': 'nl',
    'se': 'sv', 'no': 'no', 'dk': 'da', 'fi': 'fi',
    'pl': 'pl', 'cz': 'cs', 'sk': 'sk', 'hu': 'hu', 'ro': 'ro', 'bg': 'bg',
    'hr': 'hr', 'si': 'sl', 'rs': 'sr', 'gr': 'el',
    'pt': 'pt', 'br': 'pt',
    'lt': 'lt', 'lv': 'lv', 'ee': 'et',
    'hk': 'zh-HK', 'mo': 'zh-HK', 'tw': 'zh-TW', 'sg': 'en',
    'jp': 'ja', 'kr': 'ko',
    'my': 'ms', 'id': 'id', 'ph': 'en', 'th': 'th', 'vn': 'vi',
    'in': 'en', 'pk': 'en', 'bd': 'bn', 'lk': 'si', 'np': 'ne',
    'ru': 'ru', 'ua': 'uk', 'by': 'ru', 'kz': 'ru', 'uz': 'uz',
    'tr': 'tr',
    'il': 'he', 'sa': 'ar', 'ae': 'ar', 'qa': 'ar', 'kw': 'ar',
    'bh': 'ar', 'om': 'ar', 'jo': 'ar', 'lb': 'ar',
    'eg': 'ar', 'ma': 'ar', 'dz': 'ar', 'tn': 'ar',
    'za': 'en', 'ng': 'en', 'ke': 'en', 'gh': 'en',
}


# ─────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────

_supabase = None

def init_supabase(url, key):
    global _supabase
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase


def _db():
    if not _supabase:
        raise RuntimeError('cs_reviews: Supabase not initialized — set SUPABASE_URL/KEY')
    return _supabase


# ─────────────────────────────────────────────
# HASHING / DEDUP
# ─────────────────────────────────────────────

def _review_hash(platform, platform_review_id, author, content):
    """Stable fingerprint for dedup. review_id alone is globally unique
    per-platform when the store exposes one; otherwise fall back to
    author+content digest so we still avoid duplicates across polls."""
    if platform_review_id:
        key = f'{platform}|{platform_review_id}'
    else:
        fp = hashlib.sha256(f'{author}|{content}'.encode()).hexdigest()[:16]
        key = f'{platform}|_|{fp}'
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).isoformat()
    except Exception:
        pass
    try:
        return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None


# ─────────────────────────────────────────────
# APPLE — iTunes RSS JSON
# ─────────────────────────────────────────────

def fetch_apple_reviews(country, page=1, timeout=10):
    """Fetch the most-recent reviews for the BiliBili iOS app in one country.

    Returns a list of normalized review dicts. Empty list on HTTP error
    or when the app isn't listed in that territory."""
    app_id = APP_CONFIG['ios_id']
    url = (f'https://itunes.apple.com/{country}/rss/customerreviews/'
           f'page={page}/id={app_id}/sortby=mostrecent/json')
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    entries = (data.get('feed') or {}).get('entry') or []
    if isinstance(entries, dict):
        entries = [entries]

    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        rating_field = e.get('im:rating')
        if not rating_field:
            continue
        try:
            rating = int((rating_field or {}).get('label') or 0)
        except Exception:
            rating = 0
        if rating < 1 or rating > 5:
            continue

        review_id = (e.get('id') or {}).get('label') or ''
        author = ((e.get('author') or {}).get('name') or {}).get('label') or ''
        title = (e.get('title') or {}).get('label') or ''
        content = (e.get('content') or {}).get('label') or ''
        version = (e.get('im:version') or {}).get('label') or ''
        updated = (e.get('updated') or {}).get('label') or ''

        out.append({
            'platform': 'apple',
            'app_id': app_id,
            'platform_review_id': str(review_id),
            'country': country,
            'language': '',
            'author': str(author)[:128],
            'rating': rating,
            'title': str(title)[:256],
            'content': str(content)[:8000],
            'app_version': str(version)[:32],
            'review_date': _parse_iso(updated),
            'raw': {},
        })
    return out


# ─────────────────────────────────────────────
# GOOGLE PLAY — batchexecute RPC
# ─────────────────────────────────────────────

_GPLAY_URL = 'https://play.google.com/_/PlayStoreUi/data/batchexecute'
_GPLAY_RPC_ID = 'UsvDTd'

def fetch_gplay_reviews(country, lang='en', count=40, sort=2, timeout=15):
    """Fetch reviews for the BiliBili Android app in one country.
    sort: 1=most_helpful, 2=newest, 3=rating."""
    app_id = APP_CONFIG['android_package']
    inner = json.dumps(
        [None, None, [sort, None, [count, None, None]], [app_id, 7]],
        separators=(',', ':'),
    )
    f_req = json.dumps([[[_GPLAY_RPC_ID, inner, None, 'generic']]], separators=(',', ':'))

    params = {'hl': lang, 'gl': country, 'rpcids': _GPLAY_RPC_ID}
    headers = {
        **BROWSER_HEADERS,
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Origin': 'https://play.google.com',
        'Referer': f'https://play.google.com/store/apps/details?id={app_id}&hl={lang}&gl={country}',
    }
    body = 'f.req=' + quote(f_req, safe='')
    try:
        r = requests.post(_GPLAY_URL, params=params, data=body,
                          headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        text = r.text
    except Exception:
        return []

    # XSSI prefix: )]}'
    if text.startswith(")]}'"):
        text = text.split('\n', 1)[1] if '\n' in text else text[5:]
    try:
        envelope = json.loads(text)
    except Exception:
        try:
            first_line = next(ln for ln in text.splitlines() if ln.strip().startswith('['))
            envelope = json.loads(first_line)
        except Exception:
            return []

    inner_json = None
    for frame in envelope:
        if (isinstance(frame, list) and len(frame) >= 3
                and frame[0] == 'wrb.fr' and frame[1] == _GPLAY_RPC_ID):
            inner_json = frame[2]
            break
    if not inner_json:
        return []
    try:
        payload = json.loads(inner_json)
    except Exception:
        return []

    reviews_raw = []
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        reviews_raw = payload[0]

    out = []
    for rv in reviews_raw:
        parsed = _parse_gplay_review(rv, country, app_id)
        if parsed:
            out.append(parsed)
    return out


def _safe_get(arr, *path):
    cur = arr
    for p in path:
        if isinstance(cur, list) and isinstance(p, int) and -len(cur) <= p < len(cur):
            cur = cur[p]
        elif isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _parse_gplay_review(rv, country, app_id):
    """Best-effort parser. Google occasionally shifts field positions
    in the batchexecute response, so every lookup is defensive."""
    if not isinstance(rv, list) or len(rv) < 3:
        return None

    review_id = _safe_get(rv, 0) or ''
    author = _safe_get(rv, 1, 0) or ''
    rating = _safe_get(rv, 2) or 0
    try:
        rating = int(rating)
    except Exception:
        rating = 0
    if rating < 1 or rating > 5:
        return None

    content = _safe_get(rv, 4)
    if not isinstance(content, str):
        content = ''

    ts = _safe_get(rv, 5, 0)
    if not isinstance(ts, (int, float)):
        ts = _safe_get(rv, 5)
    review_date = None
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            review_date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            review_date = None

    version = _safe_get(rv, 10)
    if not isinstance(version, str):
        version = ''

    return {
        'platform': 'google_play',
        'app_id': app_id,
        'platform_review_id': str(review_id),
        'country': country,
        'language': '',
        'author': str(author)[:128],
        'rating': rating,
        'title': '',
        'content': str(content)[:8000],
        'app_version': str(version)[:32],
        'review_date': review_date,
        'raw': {},
    }


# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

def save_reviews(reviews):
    """Insert new reviews, skipping duplicates by review_hash.
    Reviews from before the current calendar year are discarded
    (scope rule: keep only the active year)."""
    if not reviews:
        return {'saved': 0, 'skipped': 0}

    year_cutoff = f'{datetime.now(timezone.utc).year}-01-01'
    reviews = [r for r in reviews
               if (r.get('review_date') or '') >= year_cutoff]
    if not reviews:
        return {'saved': 0, 'skipped': 0}

    rows = []
    for rv in reviews:
        h = _review_hash(rv['platform'], rv.get('platform_review_id', ''),
                         rv.get('author', ''), rv.get('content', ''))
        rows.append({**rv, 'review_hash': h})

    # Dedupe within the batch first
    seen = set()
    unique = []
    for r in rows:
        if r['review_hash'] in seen:
            continue
        seen.add(r['review_hash'])
        unique.append(r)

    # Check which hashes already exist in DB (in chunks to avoid URL limits)
    existing_set = set()
    hashes = [r['review_hash'] for r in unique]
    CHUNK = 200
    for i in range(0, len(hashes), CHUNK):
        chunk = hashes[i:i + CHUNK]
        try:
            res = _db().table('cs_reviews').select('review_hash').in_('review_hash', chunk).execute()
            existing_set.update(e['review_hash'] for e in (res.data or []))
        except Exception:
            pass

    to_insert = [r for r in unique if r['review_hash'] not in existing_set]
    if not to_insert:
        return {'saved': 0, 'skipped': len(unique)}

    saved = 0
    # Batch insert (100 at a time) — fall back to single-row on failure
    for i in range(0, len(to_insert), 100):
        batch = to_insert[i:i + 100]
        try:
            _db().table('cs_reviews').insert(batch).execute()
            saved += len(batch)
        except Exception:
            for r in batch:
                try:
                    _db().table('cs_reviews').insert(r).execute()
                    saved += 1
                except Exception:
                    pass
    return {'saved': saved, 'skipped': len(unique) - saved}


# ─────────────────────────────────────────────
# COUNTRY STATE — active / inactive tracking
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# POLL ORCHESTRATOR
# ─────────────────────────────────────────────

def poll_all(platform=None, max_workers=10, log=True, full_scan=None):
    """Poll every configured country for the given platform(s).

    platform : 'apple' | 'google_play' | None (both)
    full_scan: True  → scan every country (including inactive ones)
               False → scan only active/unknown countries
               None  → auto: full scan if the last one was > DISCOVERY_DAYS ago."""
    started = time.time()
    stats = {
        'platforms': {}, 'total_fetched': 0, 'total_new': 0,
        'duration_sec': 0, 'full_scan': False,
        'countries_scanned': 0, 'countries_skipped': 0,
    }

    if full_scan is None:
        age = _last_full_scan_age_days()
        full_scan = (age is None) or (age >= DISCOVERY_DAYS)
    stats['full_scan'] = bool(full_scan)

    state = _load_country_state() if not full_scan else {}

    jobs, skipped = [], 0
    if platform in (None, 'apple'):
        for cc in APPLE_COUNTRIES:
            if cc in EXCLUDED_COUNTRIES:
                continue
            if _should_skip('apple', cc, state, full_scan):
                skipped += 1
            else:
                jobs.append(('apple', cc, None))
    if platform in (None, 'google_play'):
        for cc, lg in GPLAY_COUNTRIES.items():
            if cc in EXCLUDED_COUNTRIES:
                continue
            if _should_skip('google_play', cc, state, full_scan):
                skipped += 1
            else:
                jobs.append(('google_play', cc, lg))
    stats['countries_scanned'] = len(jobs)
    stats['countries_skipped'] = skipped

    gathered = {'apple': [], 'google_play': []}
    counts = []  # (platform, country, review_count) for state update
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_poll_one, plat, cc, lg): (plat, cc)
                for plat, cc, lg in jobs}
        for fut in as_completed(futs):
            plat, cc = futs[fut]
            try:
                revs = fut.result() or []
            except Exception:
                revs = []
            gathered[plat].extend(revs)
            counts.append((plat, cc, len(revs)))

    for plat, revs in gathered.items():
        if not revs and (platform and platform != plat):
            continue
        save = save_reviews(revs) if revs else {'saved': 0}
        stats['platforms'][plat] = {'fetched': len(revs), 'new': save.get('saved', 0)}
        stats['total_fetched'] += len(revs)
        stats['total_new'] += save.get('saved', 0)

    _update_country_state(counts)

    if log:
        try:
            _db().table('cs_poll_log').insert({
                'platform': platform or 'both',
                'country': 'ALL',
                'full_scan': bool(full_scan),
                'countries_scanned': stats['countries_scanned'],
                'countries_skipped': stats['countries_skipped'],
                'reviews_fetched': stats['total_fetched'],
                'reviews_new': stats['total_new'],
                'finished_at': datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    stats['duration_sec'] = round(time.time() - started, 1)
    return stats


def _poll_one(platform, country, lang):
    if platform == 'apple':
        return fetch_apple_reviews(country)
    if platform == 'google_play':
        return fetch_gplay_reviews(country, lang=lang or 'en')
    return []


# ─────────────────────────────────────────────
# READ (frontend queries)
# ─────────────────────────────────────────────

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
        # ilike for substring, case-insensitive
        q = q.ilike('content', f'%{search}%')
    q = q.order('review_date', desc=True).range(offset, offset + limit - 1)
    try:
        res = q.execute()
        return res.data or []
    except Exception:
        return []


def get_stats(days=1, year=None):
    """Aggregate counts for the given window.
    If year is given, use Jan 1..Dec 31 of that year and ignore days."""
    try:
        q = _db().table('cs_reviews').select('platform,country,rating,review_date')
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
        return {'total': 0, 'by_platform': {}, 'by_rating': {}, 'by_country': {}}

    by_platform, by_rating, by_country = {}, {}, {}
    for r in rows:
        p = r.get('platform', '') or ''
        rt = str(r.get('rating', 0) or 0)
        c = r.get('country', '') or ''
        by_platform[p] = by_platform.get(p, 0) + 1
        by_rating[rt] = by_rating.get(rt, 0) + 1
        by_country[c] = by_country.get(c, 0) + 1
    return {
        'total': len(rows),
        'by_platform': by_platform,
        'by_rating': by_rating,
        'by_country': by_country,
    }


def get_last_poll():
    """Return the most recent poll_log row (for 'last updated' UI hint)."""
    try:
        res = _db().table('cs_poll_log').select('*').order('started_at', desc=True).limit(1).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:
        return None
