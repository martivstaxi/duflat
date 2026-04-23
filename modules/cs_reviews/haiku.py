"""Haiku enrichment — language detection + English summary + Simplified
Chinese translation. Best-effort: failures (missing key, SDK, bad response)
leave rows untouched so the save/backfill pipeline never blocks."""

import json
import os

from .db import _db


# Max backfill attempts per row. Emoji-only / one-word reviews can't be
# enriched (Haiku returns empty), so we stop retrying after this many
# passes to avoid burning tokens on them forever.
MAX_HAIKU_ATTEMPTS = 2


# Languages Haiku may label reviews with. Free-form label; anything outside
# this set is stored verbatim (so new locales don't break the pipeline).
_HAIKU_LANG_OPTIONS = (
    '"English", "Spanish", "Portuguese", "French", "German", "Italian", '
    '"Dutch", "Polish", "Czech", "Slovak", "Hungarian", "Romanian", '
    '"Greek", "Swedish", "Norwegian", "Danish", "Finnish", '
    '"Japanese", "Korean", "Traditional Chinese", "Simplified Chinese", '
    '"Arabic", "Turkish", "Russian", "Ukrainian", "Hebrew", '
    '"Indonesian", "Malay", "Thai", "Vietnamese", "Hindi", "Bengali", '
    '"Tagalog", "Other"'
)


def _enrich_with_haiku(reviews, batch_size=15):
    """Populate language + English + Simplified Chinese versions in place.

    Each review gets: `language`, `content_english`, `title_english`,
    `content_chinese`, `title_chinese`. Skips rows whose relevant fields are
    already populated so backfill runs are idempotent."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return
    try:
        import anthropic
    except ImportError:
        return

    todo = []
    for i, r in enumerate(reviews):
        content = (r.get('content') or '').strip()
        title = (r.get('title') or '').strip()
        if not (content or title):
            continue
        needs_lang = not (r.get('language') or '').strip()
        needs_content_en = bool(content) and not (r.get('content_english') or '').strip()
        needs_title_en = bool(title) and not (r.get('title_english') or '').strip()
        needs_content_zh = bool(content) and not (r.get('content_chinese') or '').strip()
        needs_title_zh = bool(title) and not (r.get('title_chinese') or '').strip()
        if not (needs_lang or needs_content_en or needs_title_en
                or needs_content_zh or needs_title_zh):
            continue
        todo.append((i, title, content))
    if not todo:
        return

    client = anthropic.Anthropic(api_key=api_key)
    for start in range(0, len(todo), batch_size):
        slab = todo[start:start + batch_size]
        entries = []
        for local_i, (_, title, content) in enumerate(slab):
            e = {'idx': local_i}
            if title:
                e['title'] = title[:200]
            if content:
                e['text'] = content[:1500]
            entries.append(e)
        prompt = (
            "You process user reviews of the BiliBili app. For each review, "
            "detect its language and produce short English AND Simplified "
            "Chinese versions of its title and body that preserve the "
            "reviewer's tone (praise, complaint, bug report, feature request).\n\n"
            "For EACH item return:\n"
            f"- language: one of {_HAIKU_LANG_OPTIONS}.\n"
            "- content_english: ONE plain-English sentence, <=25 words. If the review "
            "is already English you may keep it as-is when short, otherwise tighten it. "
            "Never invent facts. Empty string if the item has no `text`.\n"
            "- title_english: ONE short English title, <=10 words. Keep it punchy and "
            "faithful to the original headline. Empty string if the item has no `title`.\n"
            "- content_chinese: Simplified Chinese translation of content_english, natural "
            "phrasing (not literal). Brand/product names stay in Latin script (BiliBili, "
            "iOS, Android). Empty if content_english is empty.\n"
            "- title_chinese: Simplified Chinese translation of title_english, same rules. "
            "Empty if title_english is empty.\n\n"
            'Return ONLY a JSON array: '
            '[{"idx":0,"language":"...","content_english":"...","title_english":"...",'
            '"content_chinese":"...","title_chinese":"..."}, ...]\n\n'
            "Reviews:\n"
            f"{json.dumps(entries, ensure_ascii=False)}"
        )
        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=3072,
                messages=[{'role': 'user', 'content': prompt}],
            )
            text = resp.content[0].text.strip()
            if '```' in text:
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
            results = json.loads(text)
        except Exception:
            continue

        for v in results:
            local_i = v.get('idx')
            if not isinstance(local_i, int) or local_i >= len(slab):
                continue
            review_idx, _, _ = slab[local_i]
            lang = (v.get('language') or '').strip()
            english = (v.get('content_english') or '').strip()
            title_en = (v.get('title_english') or '').strip()
            chinese = (v.get('content_chinese') or '').strip()
            title_zh = (v.get('title_chinese') or '').strip()
            if lang:
                reviews[review_idx]['language'] = lang[:64]
            if english:
                reviews[review_idx]['content_english'] = english[:1000]
            if title_en:
                reviews[review_idx]['title_english'] = title_en[:256]
            if chinese:
                reviews[review_idx]['content_chinese'] = chinese[:1000]
            if title_zh:
                reviews[review_idx]['title_chinese'] = title_zh[:256]


def backfill_translations(limit=200):
    """Populate language + English + Simplified Chinese fields for legacy rows
    that lack any of them. Returns {'scanned': N, 'enriched': M}. Safe to call
    repeatedly — rows that already have every field, or have hit
    MAX_HAIKU_ATTEMPTS without success, are skipped."""
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    # Pull a wider slice than `limit` so Python-side filtering has room to
    # yield `limit` enrichment candidates. Cheap for the current row count.
    try:
        res = (_db().table('cs_reviews')
               .select('id,title,content,language,content_english,title_english,'
                       'content_chinese,title_chinese,haiku_attempts')
               .order('id', desc=True)
               .limit(max(limit * 4, 400))
               .execute())
        all_rows = res.data or []
    except Exception as e:
        return {'scanned': 0, 'enriched': 0, 'error': f'select: {e}'}

    rows = []
    for r in all_rows:
        title = (r.get('title') or '').strip()
        content = (r.get('content') or '').strip()
        if not (title or content):
            continue
        if (r.get('haiku_attempts') or 0) >= MAX_HAIKU_ATTEMPTS:
            continue
        needs_lang = not (r.get('language') or '').strip()
        needs_content_en = bool(content) and not (r.get('content_english') or '').strip()
        needs_title_en = bool(title) and not (r.get('title_english') or '').strip()
        needs_content_zh = bool(content) and not (r.get('content_chinese') or '').strip()
        needs_title_zh = bool(title) and not (r.get('title_chinese') or '').strip()
        if not (needs_lang or needs_content_en or needs_title_en
                or needs_content_zh or needs_title_zh):
            continue
        rows.append(r)
        if len(rows) >= limit:
            break

    if not rows:
        return {'scanned': 0, 'enriched': 0}

    _enrich_with_haiku(rows)

    enriched = 0
    for r in rows:
        update = {'haiku_attempts': (r.get('haiku_attempts') or 0) + 1}
        filled_any = False
        for field in ('language', 'content_english', 'title_english',
                      'content_chinese', 'title_chinese'):
            val = (r.get(field) or '').strip()
            if val:
                update[field] = val
                filled_any = True
        try:
            _db().table('cs_reviews').update(update).eq('id', r['id']).execute()
            if filled_any:
                enriched += 1
        except Exception:
            pass
    return {'scanned': len(rows), 'enriched': enriched}
