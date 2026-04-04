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


def _build_prompt(channel_data: dict, titles: list[str]) -> str:
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

Generate a professional channel report with these exact 7 fields. Each value must be a SHORT, sharp phrase (not a full paragraph — 1 sentence max, no fluff).

Fields to fill:
1. content_language — Language(s) used in content. E.g. "Turkish", "English", "Bilingual (TR + EN subtitles)"
2. niche — Primary content category and topic. E.g. "Anime reviews & seasonal rankings"
3. audience — Who watches this channel. E.g. "Turkish-speaking anime fans, likely 16-28"
4. upload_frequency — Estimated posting rhythm inferred from titles/data. E.g. "~2 videos/week", "Irregular, burst uploads"
5. content_style — Format and tone. E.g. "Commentary-style rankings, community polls, event coverage"
6. brand_fit — Sponsorship/partnership potential and relevant brand categories. E.g. "High — anime streaming, gaming peripherals, digital products"
7. key_insight — One non-obvious insight a marketing researcher would find valuable. E.g. "Runs annual anime awards event, suggesting strong community ownership"

Rules:
- English only
- Be factual — infer only what the data clearly supports
- Do NOT repeat stats already shown (subscriber count, join date, video count, total views)
- key_insight must be genuinely insightful, not a generic statement

Also list 3–6 short topic tags.

Respond ONLY with valid JSON, no markdown:
{{
  "report": {{
    "content_language": "...",
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

    prompt = _build_prompt(channel_data, titles)

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
        return {'report': report, 'tags': tags}
    except Exception as e:
        return {'error': str(e)}
