"""Small internal helpers — dedup hash + ISO-date normalization."""

import hashlib
from datetime import datetime, timezone


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
