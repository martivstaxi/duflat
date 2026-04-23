"""Apple App Store — iTunes RSS JSON scraper."""

import requests

from modules.constants import BROWSER_HEADERS

from .config import APP_CONFIG
from .utils import _parse_iso


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
