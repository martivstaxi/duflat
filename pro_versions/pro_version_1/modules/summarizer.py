"""
Channel Summarizer
------------------
Generates a clean English summary of a YouTube creator using channel data
and recent video titles, via Claude Haiku.

Public API:
    summarize_channel(channel_data: dict) -> dict
        {'summary': 'Clean English text...', 'topics': ['Gaming', 'Turkish creator', ...]}
     or {'error': 'reason'}
"""

import os
import re
import json

# ─────────────────────────────────────────────
# RECENT VIDEO TITLES
# ─────────────────────────────────────────────

def _fetch_recent_titles(channel_url: str, n: int = 8) -> list[str]:
    """
    Fetch last N video titles from the channel using yt-dlp flat extraction.
    Uses extract_flat=True so it's fast — no full video metadata download.
    """
    if not channel_url:
        return []
    try:
        import yt_dlp
        opts = {
            'skip_download':  True,
            'quiet':          True,
            'no_warnings':    True,
            'ignoreerrors':   True,
            'playlistend':    n,
            'extract_flat':   True,
        }
        target = channel_url.rstrip('/') + '/videos'
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            return []
        entries = info.get('entries') or []
        titles = [e.get('title', '').strip() for e in entries if e and e.get('title')]
        return titles[:n]
    except Exception:
        return []


# ─────────────────────────────────────────────
# AI SUMMARY
# ─────────────────────────────────────────────

def _build_prompt(channel_data: dict, titles: list[str]) -> str:
    lines = ['=== Channel Data ===']
    for field, label in [
        ('name',        'Name'),
        ('handle',      'Handle'),
        ('description', 'About (raw)'),
        ('location',    'Location'),
        ('joined',      'Joined'),
        ('subscribers', 'Subscribers'),
        ('views',       'Total views'),
        ('videos',      'Video count'),
        ('last_video_date', 'Last video'),
    ]:
        val = channel_data.get(field)
        if val:
            lines.append(f'{label}: {val}')

    for k in ('instagram', 'twitter', 'tiktok', 'facebook', 'linkedin'):
        if channel_data.get(k):
            lines.append(f'{k.capitalize()}: {channel_data[k]}')

    if titles:
        lines.append('\n=== Recent Video Titles ===')
        for i, t in enumerate(titles, 1):
            lines.append(f'{i}. {t}')

    context = '\n'.join(lines)

    return f"""You are summarizing a YouTube channel for an influencer marketing researcher.

{context}

Write a concise English summary (3–5 sentences) about this creator covering:
- What type of content they make and their main niche
- Who their audience is (language/country if clear)
- Their scale / activity level
- Any notable facts visible from the data

Rules:
- Always write in English regardless of the original channel language
- Be factual — only state what the data supports
- Do not start with "This channel" or the channel name — vary the opening
- No filler phrases like "Overall" or "In summary"

Then list 3–5 short topic tags that describe this channel.

Respond ONLY with valid JSON:
{{
  "summary": "3-5 sentence English summary here.",
  "topics": ["Tag1", "Tag2", "Tag3"]
}}"""


def summarize_channel(channel_data: dict) -> dict:
    """
    Generate a clean English creator summary using channel data + recent video titles.

    Args:
        channel_data: dict from scraper.scrape_channel()

    Returns:
        {'summary': str, 'topics': list[str]}
     or {'error': str}
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {'error': 'ANTHROPIC_API_KEY not set'}

    channel_url = channel_data.get('channel_url', '')
    titles = _fetch_recent_titles(channel_url)

    prompt = _build_prompt(channel_data, titles)

    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return {'error': 'invalid response from AI'}
        data = json.loads(match.group())
        summary = (data.get('summary') or '').strip()
        topics  = [t for t in (data.get('topics') or []) if isinstance(t, str) and t.strip()]
        if not summary:
            return {'error': 'empty summary'}
        return {'summary': summary, 'topics': topics}
    except Exception as e:
        return {'error': str(e)}
