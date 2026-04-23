"""Poll orchestrator — fans out scrapers across countries, saves deduped
results, updates country state, and logs the run."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .apple import fetch_apple_reviews
from .config import (
    APPLE_COUNTRIES, DISCOVERY_DAYS, EXCLUDED_COUNTRIES, GPLAY_COUNTRIES,
)
from .country_state import (
    _last_full_scan_age_days, _load_country_state,
    _should_skip, _update_country_state,
)
from .db import _db
from .gplay import fetch_gplay_reviews
from .save import save_reviews


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
