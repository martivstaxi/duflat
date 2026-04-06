"""
Channel Analyst
---------------
Deep-analysis report of a YouTube channel for influencer marketing researchers.
Fetches recent video titles, analyzes all channel data, and returns a structured
professional report via Claude Haiku.

Public API:
    summarize_channel(channel_data: dict) -> dict
        {
          'report': {
            'content_language': str,
            'niche':            str,
            'audience':         str,
            'upload_frequency': str,
            'content_style':    str,
            'brand_fit':        str,
            'key_insight':      str,
          },
          'tags': [str, ...]
        }
     or {'error': 'reason'}
"""

import os
import re
import json


def _detect_language(text: str) -> str:
    """
    Detect primary content language from character distribution.
    No AI, no external library — counts distinctive Unicode chars.
    """
    if not text or len(text) < 10:
        return 'Unknown'

    # Count distinctive characters per language family
    turkish  = sum(text.count(c) for c in 'ğşıöüçîâûĞŞİÖÜÇ')
    arabic   = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    japanese = sum(1 for c in text if '\u3040' <= c <= '\u30FF' or '\u4E00' <= c <= '\u9FFF')
    korean   = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
    greek    = sum(1 for c in text if '\u0370' <= c <= '\u03FF')
    thai     = sum(1 for c in text if '\u0E00' <= c <= '\u0E7F')
    hindi    = sum(1 for c in text if '\u0900' <= c <= '\u097F')

    scores = {
        'Turkish':  turkish,
        'Arabic':   arabic,
        'Russian':  cyrillic,
        'Japanese': japanese,
        'Korean':   korean,
        'Greek':    greek,
        'Thai':     thai,
        'Hindi':    hindi,
    }
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score >= 3:
        return best_lang
    return 'English'  # default for Latin-script content


def _fetch_recent_titles(channel_url: str, n: int = 15) -> list[str]:
    """
    Fetch last N video titles via yt-dlp flat extraction (fast, no download).
    """
    if not channel_url:
        return []
    try:
        import yt_dlp
        opts = {
            'skip_download': True,
            'quiet':         True,
            'no_warnings':   True,
            'ignoreerrors':  True,
            'playlistend':   n,
            'extract_flat':  True,
        }
        target = channel_url.rstrip('/') + '/videos'
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            return []
        entries = info.get('entries') or []
        return [e.get('title', '').strip() for e in entries if e and e.get('title')][:n]
    except Exception:
        return []


def _build_prompt(channel_data: dict, titles: list[str], lang: str) -> str:
    lines = ['=== Channel Data ===']
    for field, label in [
        ('name',            'Channel name'),
        ('handle',          'Handle'),
        ('location',        'Location'),
        ('description',     'About text (raw)'),
        ('last_video_date', 'Last video uploaded'),
    ]:
        val = channel_data.get(field)
        if val:
            lines.append(f'{label}: {val}')

    for k in ('instagram', 'twitter', 'tiktok', 'facebook', 'linkedin'):
        if channel_data.get(k):
            lines.append(f'{k.capitalize()}: {channel_data[k]}')

    if channel_data.get('all_links'):
        lines.append('External links: ' + ', '.join(channel_data['all_links'][:8]))

    if titles:
        lines.append(f'\n=== Last {len(titles)} Video Titles ===')
        for i, t in enumerate(titles, 1):
            lines.append(f'{i}. {t}')

    context = '\n'.join(lines)

    return f"""You are a professional analyst at an influencer marketing agency. Analyze this YouTube channel and produce a structured intelligence report.

{context}

FACT (pre-detected, do not change): Content Language = {lang}

Generate a professional report with these exact 6 fields. Each value must be a SHORT, sharp phrase (1 sentence max, no fluff).

RULE: Base every field ONLY on evidence visible in the data above. Never speculate. If unsure, write "Unclear from data."

Fields:
1. niche — Primary content category from titles and description. E.g. "Anime reviews & seasonal rankings"
2. audience — Who watches this. Must be consistent with the content language ({lang}). E.g. "{lang}-speaking anime fans, likely 16–28"
3. upload_frequency — Infer from how many recent titles exist. E.g. "~1–2 videos/week", "Irregular bursts"
4. content_style — Format and tone from titles and description. E.g. "Commentary, rankings, community polls"
5. brand_fit — Relevant brand categories for sponsorship. E.g. "High — anime streaming platforms, gaming peripherals"
6. key_insight — One non-obvious insight specific to THIS channel that a marketing researcher would find valuable.

Also list 3–6 short topic tags.

Respond ONLY with valid JSON, no markdown:
{{
  "report": {{
    "niche": "...",
    "audience": "...",
    "upload_frequency": "...",
    "content_style": "...",
    "brand_fit": "...",
    "key_insight": "..."
  }},
  "tags": ["Tag1", "Tag2", "Tag3"]
}}"""


def summarize_channel(channel_data: dict) -> dict:
    """
    Generate a structured professional channel report using channel data + recent video titles.

    Returns:
        {'report': dict, 'tags': list}
     or {'error': str}
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {'error': 'ANTHROPIC_API_KEY not set'}

    channel_url = channel_data.get('channel_url', '')
    titles = _fetch_recent_titles(channel_url, n=15)

    # Detect language programmatically — no AI tokens needed
    detection_text = (channel_data.get('description') or '') + ' ' + ' '.join(titles)
    lang = _detect_language(detection_text)

    prompt = _build_prompt(channel_data, titles, lang)

    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text  = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return {'error': 'invalid AI response'}
        data   = json.loads(match.group())
        report = data.get('report') or {}
        tags   = [t for t in (data.get('tags') or []) if isinstance(t, str) and t.strip()]
        if not report:
            return {'error': 'empty report'}
        # Inject pre-detected language as first field
        report = {'content_language': lang, **report}
        return {'report': report, 'tags': tags}
    except Exception as e:
        return {'error': str(e)}
