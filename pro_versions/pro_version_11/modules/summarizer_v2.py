"""
Channel Analyst V2
------------------
Deep-analysis report that fetches and analyzes actual video transcripts.

Pipeline:
1. Fetch 30 recent videos (flat extract with view_count)
2. Select last 5 (recent) + top 5 by views (popular), deduplicated
3. Fetch transcripts via youtube-transcript-api
4. Send channel data + transcript excerpts to Claude Haiku
5. Return structured professional report

Public API:
    summarize_channel_v2(channel_data: dict) -> dict
"""

import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


def _detect_language(text: str) -> str:
    if not text or len(text) < 10:
        return 'Unknown'
    turkish  = sum(text.count(c) for c in 'ğşıöüçîâûĞŞİÖÜÇ')
    arabic   = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    japanese = sum(1 for c in text if '\u3040' <= c <= '\u30FF' or '\u4E00' <= c <= '\u9FFF')
    korean   = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
    greek    = sum(1 for c in text if '\u0370' <= c <= '\u03FF')
    thai     = sum(1 for c in text if '\u0E00' <= c <= '\u0E7F')
    hindi    = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    scores = {
        'Turkish': turkish, 'Arabic': arabic, 'Russian': cyrillic,
        'Japanese': japanese, 'Korean': korean, 'Greek': greek,
        'Thai': thai, 'Hindi': hindi,
    }
    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    return best_lang if best_score >= 3 else 'English'


def _fetch_videos(channel_url: str, n: int = 30) -> list[dict]:
    """
    Fetch last N videos with id, title, view_count via yt-dlp flat extraction.
    Returns list of dicts sorted by recency (newest first).
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
            'extract_flat':  'in_playlist',
        }
        target = channel_url.rstrip('/') + '/videos'
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            return []
        entries = info.get('entries') or []
        videos = []
        for e in entries:
            if not e or not e.get('id'):
                continue
            videos.append({
                'id':         e['id'],
                'title':      e.get('title', '').strip(),
                'view_count': e.get('view_count') or 0,
            })
        return videos[:n]
    except Exception:
        return []


def _select_videos(videos: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Select last 5 (recent) and top 5 by views (popular).
    Returns (recent, popular) — deduplicated.
    """
    recent = videos[:5]
    recent_ids = {v['id'] for v in recent}

    by_views = sorted(videos, key=lambda v: v['view_count'], reverse=True)
    popular = []
    for v in by_views:
        if v['id'] not in recent_ids:
            popular.append(v)
            if len(popular) >= 5:
                break

    # If not enough unique popular videos, just take what we have
    if len(popular) < 5:
        for v in by_views:
            if v['id'] not in recent_ids and v not in popular:
                popular.append(v)
                if len(popular) >= 5:
                    break

    return recent, popular


def _get_transcript(video_id: str, max_chars: int = 1500) -> str:
    """
    Fetch transcript via yt-dlp extract_info + urlopen on subtitle URL.
    Uses yt-dlp's session (cookies/consent handled) to download subtitle JSON.
    Returns truncated plain text or empty string on failure.
    """
    try:
        import yt_dlp

        url = f'https://www.youtube.com/watch?v={video_id}'
        opts = {
            'skip_download': True,
            'quiet':         True,
            'no_warnings':   True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return ''

            # Find English json3 subtitle URL (manual subs first, then auto-captions)
            sub_url = ''
            for source in [info.get('subtitles') or {}, info.get('automatic_captions') or {}]:
                for lang_key in ['en', 'en-orig']:
                    if lang_key in source:
                        for fmt in source[lang_key]:
                            if isinstance(fmt, dict) and fmt.get('ext') == 'json3':
                                sub_url = fmt.get('url', '')
                                break
                    if sub_url:
                        break
                # If no English, try first available language
                if not sub_url and source:
                    first_lang = list(source.keys())[0]
                    for fmt in source[first_lang]:
                        if isinstance(fmt, dict) and fmt.get('ext') == 'json3':
                            sub_url = fmt.get('url', '')
                            break
                if sub_url:
                    break

            if not sub_url:
                return ''

            # Download using yt-dlp's session (handles cookies/consent)
            raw = ydl.urlopen(sub_url).read().decode('utf-8', errors='ignore')

        if not raw:
            return ''

        data = json.loads(raw)
        events = data.get('events') or []
        parts = []
        for ev in events:
            for seg in (ev.get('segs') or []):
                t = seg.get('utf8', '').strip()
                if t and t != '\n':
                    parts.append(t)
        text = ' '.join(parts)
        if len(text.strip()) < 50:
            return ''
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return ''


def _fetch_transcripts(videos: list[dict]) -> dict[str, str]:
    """
    Fetch transcripts sequentially (yt-dlp not safe for concurrent use).
    Returns {video_id: transcript_text}.
    """
    results = {}
    for v in videos:
        results[v['id']] = _get_transcript(v['id'])
    return results


def _format_views(count: int) -> str:
    if count >= 1_000_000:
        return f'{count / 1_000_000:.1f}M'
    if count >= 1_000:
        return f'{count / 1_000:.0f}K'
    return str(count)


def _build_prompt(channel_data: dict, recent: list[dict], popular: list[dict],
                  transcripts: dict[str, str], lang: str) -> str:
    lines = ['=== Channel Data ===']
    for field, label in [
        ('name',            'Channel name'),
        ('handle',          'Handle'),
        ('subscribers',     'Subscribers'),
        ('views',           'Total views'),
        ('videos',          'Video count'),
        ('location',        'Location'),
        ('description',     'About text'),
        ('last_video_date', 'Last video uploaded'),
    ]:
        val = channel_data.get(field)
        if val:
            lines.append(f'{label}: {val}')

    # Recent videos with transcripts
    lines.append('\n=== Last 5 Videos (Recent Content) ===')
    for i, v in enumerate(recent, 1):
        t = transcripts.get(v['id'], '')
        lines.append(f'\n--- Video {i}: {v["title"]} ---')
        if t:
            lines.append(f'Transcript excerpt: {t}')
        else:
            lines.append('(No transcript available)')

    # Popular videos with transcripts
    lines.append('\n=== Top 5 Most Popular Videos ===')
    for i, v in enumerate(popular, 1):
        t = transcripts.get(v['id'], '')
        lines.append(f'\n--- Video {i}: {v["title"]} ({_format_views(v["view_count"])} views) ---')
        if t:
            lines.append(f'Transcript excerpt: {t}')
        else:
            lines.append('(No transcript available)')

    context = '\n'.join(lines)
    transcript_count = sum(1 for v in recent + popular if transcripts.get(v['id']))

    return f"""Analyze this YouTube channel based on its video transcripts and data.

{context}

Content Language = {lang}

Write everything in English. Translate non-English content. Do not mention subscriber/view counts or video titles. Do not mention transcript availability. Only state what you can verify from the data.

Fields 1-5: one short sentence each.
1. niche — What does this channel make?
2. content_themes — 3-5 recurring topics, comma-separated.
3. audience — Who watches? Must match content language ({lang}).
4. content_style — Format and tone.
5. brand_fit — 2-3 matching brand categories.

6. key_insight — Write 4-6 bullet points. Each bullet is one clear, specific observation. Use simple words.

BAD example (too corporate, vague):
"The channel positions itself as a quality-focused alternative, leveraging engagement-driven formats and building community trust through curated content experiences."

GOOD example (clear, specific, useful):
• "Most videos are about ranking and comparing things — best horror games, worst movie sequels, etc."
• "The creator keeps coming back to Nintendo and PlayStation in almost every video."
• "Older popular videos were calm reviews. Recent ones are louder, faster, more reaction-style."
• "They often joke about being broke — probably connects well with younger viewers."
• "A gaming peripherals or streaming service brand would fit naturally here."

Write key_insight like the GOOD example. Each bullet = one simple fact or observation.

Also list 3-5 topic tags (in English).

Respond ONLY with valid JSON:
{{
  "report": {{
    "niche": "...",
    "content_themes": "...",
    "audience": "...",
    "content_style": "...",
    "brand_fit": "...",
    "key_insight": "..."
  }},
  "tags": ["Tag1", "Tag2"]
}}"""


def summarize_channel_v2(channel_data: dict) -> dict:
    """
    V2 report: analyzes actual video transcripts.
    - Last 5 videos (recent content direction)
    - Top 5 most popular videos (what resonates with audience)

    Returns:
        {'report': dict, 'tags': list, 'videos_analyzed': dict}
     or {'error': str}
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {'error': 'ANTHROPIC_API_KEY not set'}

    channel_url = channel_data.get('channel_url', '')

    # Step 1: Fetch video list
    videos = _fetch_videos(channel_url, n=30)
    if not videos:
        return {'error': 'Could not fetch video list'}

    # Step 2: Select recent + popular
    recent, popular = _select_videos(videos)
    all_selected = recent + popular

    # Step 3: Fetch transcripts in parallel
    transcripts = _fetch_transcripts(all_selected)
    transcript_count = sum(1 for t in transcripts.values() if t)

    # Step 4: Detect language
    all_text = ' '.join(t for t in transcripts.values() if t)
    titles_text = ' '.join(v['title'] for v in all_selected)
    detection_text = (channel_data.get('description') or '') + ' ' + titles_text + ' ' + all_text[:3000]
    lang = _detect_language(detection_text)

    # Step 5: Build prompt and call Haiku
    prompt = _build_prompt(channel_data, recent, popular, transcripts, lang)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=900,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return {'error': 'Invalid AI response'}
        data = json.loads(match.group())
        report = data.get('report') or {}
        tags = [t for t in (data.get('tags') or []) if isinstance(t, str) and t.strip()]
        if not report:
            return {'error': 'Empty report'}

        # Inject pre-detected language as first field
        report = {'content_language': lang, **report}

        return {
            'report': report,
            'tags': tags,
            'videos_analyzed': {
                'recent': len(recent),
                'popular': len(popular),
                'transcripts_found': transcript_count,
                'total': len(all_selected),
            },
        }
    except Exception as e:
        return {'error': str(e)}
