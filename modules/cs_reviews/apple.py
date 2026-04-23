"""Apple App Store — iTunes RSS JSON scraper.

Pagination + transient-error retry:
- Normal polls pull up to 2 pages (~100 reviews) to absorb traffic spikes.
- full_scan pulls up to 5 pages (~250) for historical catch-up.
- 429/503 get one retry (~2s backoff) before giving up on a page.
- Pagination short-circuits when a page overlaps heavily with prior ones
  (saturation — no point fetching older stuff we've already seen).
"""

import time

import requests

from modules.constants import BROWSER_HEADERS

from .config import APP_CONFIG
from .utils import _parse_iso


def fetch_apple_reviews(country, max_pages=2, timeout=10):
    """Fetch most-recent reviews across pages, deduped within this call."""
    out = []
    seen = set()
    for page in range(1, max_pages + 1):
        batch = _fetch_page(country, page, timeout)
        if not batch:
            break
        fresh = [r for r in batch if r['platform_review_id'] not in seen]
        for r in fresh:
            seen.add(r['platform_review_id'])
        out.extend(fresh)
        # Saturation: if this page overlaps heavily with prior pages, stop.
        if len(fresh) < max(5, len(batch) // 2):
            break
    return out


def _fetch_page(country, page, timeout):
    """Fetch one page; one retry on 429/503. Returns parsed list or []."""
    app_id = APP_CONFIG['ios_id']
    url = (f'https://itunes.apple.com/{country}/rss/customerreviews/'
           f'page={page}/id={app_id}/sortby=mostrecent/json')
    for attempt in range(2):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        except Exception:
            return []
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                return []
            return _parse_entries(data, country, app_id)
        if r.status_code in (429, 503) and attempt == 0:
            time.sleep(2)
            continue
        return []
    return []


def _parse_entries(data, country, app_id):
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
        })
    return out
