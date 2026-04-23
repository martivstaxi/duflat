"""Google Play — batchexecute RPC scraper.

Schema is undocumented; Google occasionally shifts field positions, so every
lookup is defensive. Last verified working 2026-04-21."""

import json
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from modules.constants import BROWSER_HEADERS

from .config import APP_CONFIG


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
