"""Insert-new-only: dedup by review_hash, drop rows before current year,
run Haiku enrichment before insert so the UI has localized fields on first
render."""

from datetime import datetime, timezone

from .db import _db
from .haiku import _enrich_with_haiku
from .utils import _review_hash


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

    # Haiku: detect language + produce English summary before the insert so
    # the UI has them on first render. Best-effort; failures don't block save.
    _enrich_with_haiku(to_insert)

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
