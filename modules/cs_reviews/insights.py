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
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from .db import _db


CACHE_TTL_SEC = 12 * 60 * 60  # 12 hours

# Bump whenever the Haiku prompt or payload shape changes — existing cached
# rows become invisible (filtered out on read) so the next click regenerates
# against the new prompt instead of returning 12h of stale output.
# v3 (2026-04-24): ZH prompt was producing Korean; added explicit script ban
# + post-generation validator.
PROMPT_VERSION = 3

# Script regexes for post-generation language validation
_RE_CJK_HAN = re.compile(r'[一-鿿㐀-䶿]')  # Han ideographs
_RE_HANGUL = re.compile(r'[가-힯ᄀ-ᇿ㄰-㆏]')  # Korean
_RE_KANA = re.compile(r'[぀-ゟ゠-ヿ]')  # Hiragana + Katakana


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
        'Write every string field (headline, summary, top_issues[*].theme, '
        'top_praise[*].theme, anomaly) in natural everyday English that a '
        'non-technical teammate would understand instantly.'
        if lang == 'en'
        else '**CRITICAL LANGUAGE REQUIREMENT** — Write every string field '
             '(headline, summary, top_issues[*].theme, top_praise[*].theme, '
             'anomaly) in **Simplified Chinese (简体中文)** ONLY. The target '
             'audience is Chinese-speaking CS staff in China.\n\n'
             'FORBIDDEN in narrative fields:\n'
             '- Korean (한국어 / 韩文 hangul): do NOT use. The correct script is 中文.\n'
             '- Japanese hiragana (ひらがな) or katakana (カタカナ): do NOT use.\n'
             '- Traditional Chinese characters when a Simplified one exists.\n'
             '- English words or phrases in the narrative text.\n\n'
             'ALLOWED unchanged: Latin product names (BiliBili, iOS, Android, '
             'Google Play), version numbers (8.91.0), and lowercase ISO '
             'country codes inside example_countries (us, jp, hk).\n\n'
             'Sanity check: headline & summary must be dominantly 汉字 with '
             'Chinese punctuation (，。：). If the output contains 한글 or '
             'ひらがな, you are using the wrong language.'
    )

    banned_words = (
        "'recovery', 'persist', 'persistent', 'concentration', 'regression', "
        "'mask', 'masks', 'masking', 'friction', 'elevated', 'notable', "
        "'baseline', 'cohort'"
    )

    payload = {
        'period_label': period_label,
        'current': cur_stats,
        'prior': prior_stats,
        'low_rating_samples': low_samples[:60],
        'praise_samples': praise_samples[:30],
    }
    prompt = (
        "You are a CS analyst for the BiliBili app writing a quick status "
        "for a teammate. Input: aggregate review stats for this period and "
        "the prior comparable period, plus samples of 1-2-star complaints "
        "and 5-star praise (already summarized in English).\n\n"
        f"{lang_instr}\n\n"
        "STYLE RULES (critical — the previous version sounded like a "
        "consulting deck, which was rejected):\n"
        "- Short plain sentences. Write like you're texting a coworker.\n"
        f"- AVOID business / consultant jargon: {banned_words}. Use ordinary "
        "verbs instead (e.g. 'still happening' not 'persistent', 'went up' "
        "not 'recovered').\n"
        "- Never restate numbers the UI already shows (total, average, "
        "1–2★ count). Explain WHAT users are saying, not the stats.\n"
        "- No hedging ('may', 'might', 'could suggest'). State it directly.\n\n"
        "Return ONLY JSON, no prose outside:\n"
        "{\n"
        '  "headline": "One plain sentence, max 12 words, no jargon. Examples: '
        "'Ratings are up but users still hit login bugs.' / "
        "'5-star praise is climbing, but 8.91.0 keeps crashing.'\",\n"
        '  "summary": "2-3 plain sentences. What users are actually '
        'complaining about and what they like. No stat recaps.",\n'
        '  "top_issues": [{"theme":"...", "count":<int>, "example_countries":["us","jp"], "severity":"high|medium|low"}],\n'
        '  "top_praise": [{"theme":"...", "count":<int>}],\n'
        '  "anomaly": "One plain sentence flagging an outlier (a specific '
        'country or version that got much worse). Empty string if none."\n'
        "}\n\n"
        "Field rules:\n"
        "- top_issues: up to 3, ordered by urgency. `count` = approx sample count.\n"
        "- top_praise: up to 2.\n"
        "- If low_rating_samples is empty, top_issues must be [].\n"
        '- Themes: concrete and concrete ("login crashes after updating to '
        '8.91.0" not "bugs"). Cite features, versions, or countries when visible.\n'
        "- Never invent stats not in the input.\n\n"
        "Data:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    client = anthropic.Anthropic(api_key=api_key)

    def _call(extra_reminder=''):
        messages = [{'role': 'user', 'content': prompt + extra_reminder}]
        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=2048,
                messages=messages,
            )
            text = resp.content[0].text.strip()
            if '```' in text:
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            return json.loads(text)
        except Exception:
            return {}

    narrative = _call()
    if narrative and not _narrative_matches_lang(narrative, lang):
        # Haiku produced the wrong script (e.g. Korean for lang=zh). Retry
        # once with a harsher reminder appended to the prompt.
        narrative = _call(
            '\n\nREMINDER: Your previous response used the wrong script. '
            + ('You MUST respond in Simplified Chinese (简体中文) only — '
               'no Korean 한글, no Japanese かな. Try again.'
               if lang == 'zh' else
               'You MUST respond in plain English only. Try again.')
        )
        if narrative and not _narrative_matches_lang(narrative, lang):
            return {}  # second attempt also wrong → fail-soft
    return narrative


def _narrative_text(narrative):
    """Concatenate all narrative string fields for language inspection."""
    if not isinstance(narrative, dict):
        return ''
    parts = [
        narrative.get('headline') or '',
        narrative.get('summary') or '',
        narrative.get('anomaly') or '',
    ]
    for i in (narrative.get('top_issues') or []):
        if isinstance(i, dict):
            parts.append(i.get('theme') or '')
    for p in (narrative.get('top_praise') or []):
        if isinstance(p, dict):
            parts.append(p.get('theme') or '')
    return ' '.join(parts)


def _narrative_matches_lang(narrative, lang):
    """Return True if the narrative's script matches the requested language.

    zh: must contain Han ideographs AND must NOT contain Korean Hangul or
        Japanese kana (Haiku occasionally drifts to Korean).
    en: must be mostly ASCII — >70% of characters should be in the
        basic Latin range.
    """
    text = _narrative_text(narrative)
    if not text.strip():
        return False
    if lang == 'zh':
        if not _RE_CJK_HAN.search(text):
            return False
        if _RE_HANGUL.search(text) or _RE_KANA.search(text):
            return False
        return True
    # English
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_ratio = sum(1 for c in letters if ord(c) < 128) / len(letters)
    return ascii_ratio > 0.7


def _cache_get(period, lang):
    """Return cached payload if a fresh (period, lang) row exists in
    cs_insights_cache AND its prompt_version matches the current one.
    Returns None on miss, stale, version-mismatch, or DB error."""
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
        if not isinstance(payload, dict):
            return None
        if payload.get('prompt_version') != PROMPT_VERSION:
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
        'prompt_version': PROMPT_VERSION,
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
