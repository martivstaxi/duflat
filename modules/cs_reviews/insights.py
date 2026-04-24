"""Insights — Haiku narrative over a review window.

Computes deterministic stats from the DB (totals, rating distribution,
top countries, top versions) for a period + its prior comparable period,
then asks Haiku for a short actionable read: summary, top issues to
address, what users praise, any anomaly.

Bilingual: `lang='en'` or `'zh'` controls Haiku's output language.

Supabase-backed cache (`cs_insights_cache`) so reloads inside CACHE_TTL_SEC
don't burn Haiku tokens — and so the cache survives Railway redeploys.
The poll pipeline calls `invalidate_insights_cache()` after a successful
scan (DELETE FROM cs_insights_cache) so fresh data is visible next click."""

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from .db import _db


CACHE_TTL_SEC = 12 * 60 * 60  # 12 hours


def _periods(period):
    """Return (current_start, current_end, prior_start, prior_end, label)
    as timezone-aware datetimes. Prior 'year' compares to previous year."""
    now = datetime.now(timezone.utc)
    if period == '7d':
        cur_start = now - timedelta(days=7)
        prior_start = now - timedelta(days=14)
        return cur_start, now, prior_start, cur_start, 'last 7 days'
    if period == '30d':
        cur_start = now - timedelta(days=30)
        prior_start = now - timedelta(days=60)
        return cur_start, now, prior_start, cur_start, 'last 30 days'
    year = now.year
    cur_start = datetime(year, 1, 1, tzinfo=timezone.utc)
    # Compare to the same YTD window in the prior year (fair apples-to-
    # apples delta). Using day-offset avoids Feb-29 edge cases.
    ytd_delta = now - cur_start
    prior_start = datetime(year - 1, 1, 1, tzinfo=timezone.utc)
    prior_end = prior_start + ytd_delta
    return cur_start, now, prior_start, prior_end, str(year)


def _fetch_rows(start, end):
    try:
        res = (_db().table('cs_reviews')
               .select('rating,platform,country,app_version,content_english,'
                       'title_english,language,review_date')
               .gte('review_date', start.isoformat())
               .lt('review_date', end.isoformat())
               .order('review_date', desc=True)
               .limit(5000)
               .execute())
        return res.data or []
    except Exception:
        return []


def _compute_stats(rows):
    base = {
        'total': len(rows),
        'avg_rating': None,
        'rating_dist': {str(i): 0 for i in range(1, 6)},
        'platforms': {},
        'top_countries': [],
        'top_versions': [],
    }
    if not rows:
        return base
    rating_dist = Counter()
    platforms = Counter()
    countries = Counter()
    versions = Counter()
    rating_sum = 0
    rating_n = 0
    for r in rows:
        rt = r.get('rating')
        if isinstance(rt, int) and 1 <= rt <= 5:
            rating_dist[str(rt)] += 1
            rating_sum += rt
            rating_n += 1
        p = r.get('platform') or ''
        if p:
            platforms[p] += 1
        c = (r.get('country') or '').lower()
        if c:
            countries[c] += 1
        v = (r.get('app_version') or '').strip()
        if v:
            versions[v] += 1
    base['avg_rating'] = round(rating_sum / rating_n, 2) if rating_n else None
    base['rating_dist'] = {str(i): rating_dist.get(str(i), 0) for i in range(1, 6)}
    base['platforms'] = dict(platforms)
    base['top_countries'] = [[c, n] for c, n in countries.most_common(5)]
    base['top_versions'] = [[v, n] for v, n in versions.most_common(5)]
    return base


def _haiku_narrative(period_label, cur_stats, prior_stats,
                     low_samples, praise_samples, lang):
    """Return narrative dict or {} on failure (missing key, SDK, bad JSON)."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {}
    try:
        import anthropic
    except ImportError:
        return {}

    lang_instr = (
        'Every string field in your JSON response (headline, summary, '
        'top_issues[*].theme, top_praise[*].theme, anomaly) MUST be in '
        'natural English.'
        if lang == 'en'
        else 'Every string field in your JSON response (headline, summary, '
             'top_issues[*].theme, top_praise[*].theme, anomaly) MUST be in '
             'natural Simplified Chinese (简体中文). Do NOT leave any field '
             'in English. Keep Latin product names (BiliBili, iOS, Android) '
             'and version numbers (8.91.0) unchanged, and keep country codes '
             'inside example_countries as-is (lowercase ISO).'
    )

    payload = {
        'period_label': period_label,
        'current': cur_stats,
        'prior': prior_stats,
        'low_rating_samples': low_samples[:60],
        'praise_samples': praise_samples[:30],
    }
    prompt = (
        "You are a CS analyst for the BiliBili app. Input: aggregate review "
        "stats for a period and the prior comparable period, plus samples of "
        "1-2-star complaints and 5-star praise (already summarized in English).\n\n"
        f"{lang_instr} Keep every field tight — no filler, no hedging. Don't "
        "restate raw numbers the UI already shows; surface what matters.\n\n"
        "Return ONLY JSON, no prose outside:\n"
        "{\n"
        '  "headline": "One-line takeaway, max 12 words.",\n'
        '  "summary": "2-3 sentence overview; mention the biggest change vs prior period.",\n'
        '  "top_issues": [{"theme":"...", "count":<int>, "example_countries":["us","jp"], "severity":"high|medium|low"}],\n'
        '  "top_praise": [{"theme":"...", "count":<int>}],\n'
        '  "anomaly": "One outlier worth flagging (country spike, version regression). Empty string if none."\n'
        "}\n\n"
        "Rules:\n"
        "- top_issues: up to 3, ordered by urgency. `count` = approx sample count.\n"
        "- top_praise: up to 2.\n"
        "- If low_rating_samples is empty, top_issues must be [].\n"
        '- Themes must be concrete ("login crashes after update to 8.91") '
        'not vague ("bugs"). Cite features, versions, or countries when present.\n'
        "- Never invent stats not in the input.\n\n"
        "Data:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = resp.content[0].text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        return json.loads(text)
    except Exception:
        return {}


def _cache_get(period, lang):
    """Return cached payload if a fresh (period, lang) row exists in
    cs_insights_cache. Returns None on miss, stale, or DB error."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SEC)
    try:
        res = (_db().table('cs_insights_cache')
               .select('payload,generated_at')
               .eq('period', period)
               .eq('lang', lang)
               .gte('generated_at', cutoff.isoformat())
               .order('generated_at', desc=True)
               .limit(1)
               .execute())
        rows = res.data or []
        if not rows:
            return None
        payload = rows[0].get('payload')
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None
        return payload
    except Exception:
        return None


def _cache_put(period, lang, payload):
    """Upsert the payload for (period, lang). Fail-soft — a DB error
    just means the next call will regenerate."""
    try:
        (_db().table('cs_insights_cache')
              .upsert({
                  'period': period,
                  'lang': lang,
                  'generated_at': datetime.now(timezone.utc).isoformat(),
                  'payload': payload,
              }, on_conflict='period,lang')
              .execute())
    except Exception:
        pass


def generate_insights(period='7d', lang='en'):
    """Return full insight payload. Cached in Supabase
    `cs_insights_cache` per (period, lang) for CACHE_TTL_SEC (12h).
    Fail-soft: if Haiku fails, stats-only payload still returned with
    `haiku_ok=false` — but we don't cache that so the next click retries."""
    if period not in ('7d', '30d', 'year'):
        period = '7d'
    if lang not in ('en', 'zh'):
        lang = 'en'

    hit = _cache_get(period, lang)
    if hit is not None:
        hit['cache_hit'] = True
        return hit

    cur_start, cur_end, prior_start, prior_end, label = _periods(period)
    cur_rows = _fetch_rows(cur_start, cur_end)
    prior_rows = _fetch_rows(prior_start, prior_end)
    cur_stats = _compute_stats(cur_rows)
    prior_stats = _compute_stats(prior_rows)

    low_samples = []
    for r in cur_rows:
        if (r.get('rating') or 0) <= 2:
            txt = (r.get('content_english') or '').strip()
            if not txt:
                continue
            low_samples.append({
                'rating': r.get('rating'),
                'country': r.get('country'),
                'version': r.get('app_version') or '',
                'text': txt[:200],
            })
    praise_samples = []
    for r in cur_rows:
        if (r.get('rating') or 0) == 5:
            txt = (r.get('content_english') or '').strip()
            if not txt:
                continue
            praise_samples.append({'country': r.get('country'), 'text': txt[:150]})

    narrative = _haiku_narrative(label, cur_stats, prior_stats,
                                 low_samples, praise_samples, lang)

    out = {
        'period': period,
        'period_label': label,
        'lang': lang,
        'current': cur_stats,
        'prior': prior_stats,
        'narrative': narrative or {
            'headline': '', 'summary': '',
            'top_issues': [], 'top_praise': [], 'anomaly': '',
        },
        'haiku_ok': bool(narrative),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'cache_hit': False,
    }
    # Only cache successful Haiku runs — a failed narrative shouldn't be
    # pinned for 12 hours when the next retry might succeed.
    if out['haiku_ok']:
        _cache_put(period, lang, out)
    return out


def invalidate_insights_cache():
    """Clear every cached row (called after a poll brings new reviews).
    Fail-soft."""
    try:
        # Supabase Python client requires a filter on delete; neq on a
        # sentinel value effectively targets every row without matching.
        _db().table('cs_insights_cache').delete().neq('id', 0).execute()
    except Exception:
        pass
