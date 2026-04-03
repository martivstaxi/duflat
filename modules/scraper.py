"""
YouTube Channel Scraper
-----------------------
Extracts channel metadata via yt-dlp + about-page monkey-patch.

Public API:
    scrape_channel(url)          → dict  (main entry point)
    normalize_url(url)           → str
    fetch_about_page(channel_url)→ tuple (socials, links, email, location, joined, views, video_count, last_video_date)
    _extract_about_via_ytdlp(channel_url) → (html_str, parsed_dict)
"""

import re
import json
import base64
import threading
import requests
from datetime import date
from urllib.parse import urlparse

import yt_dlp

from .constants import (
    SOCIAL_PLATFORMS, RE_EMAIL, EMAIL_BLACKLIST,
    NAV_DOMAINS, YT_DOMAINS, BROWSER_HEADERS,
    RE_EMBED, RE_CLEAN,
    is_valid_username, decode_redirect,
)

# ─────────────────────────────────────────────
# ABOUT PAGE REGEX
# ─────────────────────────────────────────────

RE_REDIRECT    = re.compile(r'https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"\s<>\\]+')
RE_JSON_LINKS  = [
    re.compile(r'"channelExternalLinkViewModel"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"link"\s*:\s*\{[^}]*?"content"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"primaryLinkViewModel"(?:[^{}]|\{[^{}]*\})*?"url"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"url"\s*:\s*"(https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"]+)"'),
    re.compile(r'"linkUrl"\s*:\s*"(https?://[^"]+)"'),
]
RE_EMAIL_PAGE  = [
    re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
    # YouTube channelExternalLinkViewModel stores email as plain "content" value
    re.compile(r'"channelExternalLinkViewModel"[^}]{0,400}"content"\s*:\s*"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"'),
    # YouTube channelAboutFullMetadataRenderer businessEmail (sometimes base64)
    re.compile(r'"businessEmail"\s*:\s*"([^"]{5,200})"'),
    re.compile(r'"email"\s*:\s*"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"'),
    re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
]

def _try_decode_b64_email(s: str) -> str:
    """If s is base64-encoded and decodes to an email, return the email."""
    try:
        decoded = base64.b64decode(s + '==').decode('utf-8', errors='ignore').strip()
        if '@' in decoded and '.' in decoded.split('@')[1] and len(decoded) < 120:
            return decoded
    except Exception:
        pass
    return ''


def _find_email_in_obj(obj, depth: int = 0) -> str:
    """Recursively search any dict/list/str for a valid email address."""
    if depth > 6:
        return ''
    if isinstance(obj, str):
        # Try base64 decode first
        if '@' not in obj and 8 <= len(obj) <= 200:
            decoded = _try_decode_b64_email(obj)
            if decoded:
                return decoded
        for m in RE_EMAIL.finditer(obj):
            e = m.group(1)
            if '@' in e and '.' in e.split('@')[1]:
                if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                    return e
    elif isinstance(obj, dict):
        # Priority fields
        for key in ('businessEmail', 'email', 'channel_email', 'business_email',
                    'uploader_email', 'emailText'):
            v = obj.get(key)
            if v:
                found = _find_email_in_obj(v, depth + 1)
                if found:
                    return found
        # All other fields
        for k, v in obj.items():
            if k in ('thumbnails', 'avatar', 'thumbnail', 'banner', 'tvBanner'):
                continue
            found = _find_email_in_obj(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj[:20]:
            found = _find_email_in_obj(item, depth + 1)
            if found:
                return found
    return ''


# YouTube InnerTube API — about tab params (base64 of protobuf \x12\x05about)
_INNERTUBE_ABOUT_PARAMS = 'EgVhYm91dA=='
_INNERTUBE_CONTEXT = {
    'client': {
        'hl': 'en', 'gl': 'US',
        'clientName': 'WEB',
        'clientVersion': '2.20240701.09.00',
        'platform': 'DESKTOP',
        'userAgent': BROWSER_HEADERS['User-Agent'],
    }
}


def _fetch_email_innertube(channel_id: str) -> str:
    """
    Call YouTube's InnerTube browse API for the channel's about tab.
    Searches the JSON response recursively for any email address.
    Works even when the email is behind YouTube's 'View email address' button.
    """
    if not channel_id:
        return ''
    try:
        payload = {
            'browseId':  channel_id,
            'params':    _INNERTUBE_ABOUT_PARAMS,
            'context':   _INNERTUBE_CONTEXT,
        }
        headers = {
            **BROWSER_HEADERS,
            'X-YouTube-Client-Name':    '1',
            'X-YouTube-Client-Version': '2.20240701.09.00',
            'Content-Type':             'application/json',
            'Origin':                   'https://www.youtube.com',
            'Referer':                  'https://www.youtube.com/',
        }
        r = requests.post(
            'https://www.youtube.com/youtubei/v1/browse',
            json=payload,
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            return ''

        data = r.json()

        # 1. Direct recursive search (handles businessEmail base64 decode)
        email = _find_email_in_obj(data)
        if email:
            return email

        # 2. Regex fallback on raw JSON text
        raw = r.text
        m = re.search(r'"businessEmail"\s*:\s*"([^"]{6,200})"', raw)
        if m:
            decoded = _try_decode_b64_email(m.group(1))
            if decoded:
                return decoded
            if '@' in m.group(1):
                return m.group(1)

        for m in RE_EMAIL.finditer(raw):
            e = m.group(1)
            if '@' in e and '.' in e.split('@')[1]:
                if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                    return e

    except Exception:
        pass
    return ''
RE_COUNTRY     = re.compile(r'"country":\s*"([^"]+)"')
RE_JOINED      = re.compile(r'Joined\s+([A-Za-z]+\s+\d+,\s+\d{4})')
RE_JOINED_JSON = re.compile(r'"joinedDateText"[^}]{0,300}"content":\s*"Joined\s+([^"]+)"')
RE_VIEW_COUNT  = re.compile(
    r'"subscriberCountText":[^}]{0,200}"viewCountText":\s*"([\d,\.]+)\s*views?"'
    r'|"viewCountText":\s*"([\d,\.]+)\s*views?(?:",|\s*})',
    re.I,
)
RE_VIDEO_COUNT_PATTERNS = [
    re.compile(r'"videoCountText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*\{\s*"simpleText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videoCount":\s*"(\d+)"'),
    re.compile(r'"videoCount":\s*(\d+)'),
    re.compile(r'"videoCountText":\s*\{\s*"runs"[^}]{0,200}"text":\s*"([\d,.\s]+)"'),
]
RE_PUBLISHED_TIME = re.compile(
    r'"publishedTimeText":\s*\{\s*"simpleText":\s*"([^"]+)"\s*\}'
    r'|"publishedTimeText":\s*"([^"]+)"'
)

_about_patch_lock = threading.Lock()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def normalize_url(url: str) -> str | None:
    url = url.strip()
    if not url:
        return None
    url = url.replace('m.youtube.com', 'www.youtube.com')
    m = RE_EMBED.search(url)
    if m:
        url = f'https://www.youtube.com/watch?v={m.group(1)}'
    if not url.startswith(('http://', 'https://')):
        if url.startswith('@'):
            url = f'https://www.youtube.com/{url}'
        elif url.startswith(('youtube.com', 'www.youtube.com')):
            url = f'https://{url}'
        else:
            url = f'https://www.youtube.com/@{url}'
    return url


def extract_video_count(ps: str) -> str:
    for pat in RE_VIDEO_COUNT_PATTERNS:
        m = pat.search(ps)
        if m:
            grp = next((g for g in m.groups() if g), None) if m.lastindex and m.lastindex > 1 else m.group(1)
            if grp:
                cleaned = grp.strip().replace(',', '').replace('.', '').split()[0]
                if cleaned.isdigit() and int(cleaned) > 0:
                    return cleaned
    return ''


def _oembed_channel_url(video_url: str) -> tuple[str | None, str]:
    """Get channel URL from video URL via YouTube oEmbed (no bot detection)."""
    try:
        r = requests.get(
            'https://www.youtube.com/oembed',
            params={'url': video_url, 'format': 'json'},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            author_url = data.get('author_url', '')
            if author_url and 'youtube.com' in author_url:
                return author_url, data.get('author_name', '')
    except Exception:
        pass
    return None, ''

# ─────────────────────────────────────────────
# ABOUT PAGE EXTRACTION (yt-dlp monkey-patch)
# ─────────────────────────────────────────────

def _extract_about_via_ytdlp(channel_url: str) -> tuple[str, dict]:
    """
    Intercept yt-dlp's _download_webpage to capture ytInitialData HTML
    from the channel's /about and /videos tabs.

    This works around Railway datacenter IPs being blocked by YouTube's
    consent.youtube.com — yt-dlp handles consent internally.

    Returns: (about_html, parsed_dict)
    """
    base      = RE_CLEAN.sub('', channel_url.rstrip('/'))
    about_url  = base + '/about'
    videos_url = base + '/videos'
    captured  = {'about': '', 'videos': ''}

    try:
        from yt_dlp.extractor.common import InfoExtractor
        original_dw = InfoExtractor._download_webpage

        def patched_dw(self, url_or_request, *args, **kwargs):
            result = original_dw(self, url_or_request, *args, **kwargs)
            if result and isinstance(result, str) and 'ytInitialData' in result:
                if not captured['about']:
                    captured['about'] = result
                elif not captured['videos']:
                    captured['videos'] = result
            return result

        ydl_opts = {'skip_download': True, 'quiet': True, 'no_warnings': True,
                    'ignoreerrors': True, 'extract_flat': True}

        with _about_patch_lock:
            InfoExtractor._download_webpage = patched_dw
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(about_url, download=False)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(videos_url, download=False)
            finally:
                InfoExtractor._download_webpage = original_dw
    except Exception:
        pass

    about_html = captured['about']
    videos_html = captured['videos']
    parsed = _parse_about_from_html(about_html)

    if not parsed.get('last_video_date'):
        m = RE_PUBLISHED_TIME.search(videos_html)
        if m:
            parsed['last_video_date'] = (m.group(1) or m.group(2) or '').strip()

    return about_html, parsed


def _parse_about_from_html(html: str) -> dict:
    """Extract location, joined, views, video_count from raw ytInitialData HTML."""
    if not html:
        return {}
    result = {}

    m = RE_COUNTRY.search(html)
    if m:
        result['location'] = m.group(1)

    m = RE_JOINED_JSON.search(html)
    if m:
        result['joined'] = m.group(1).strip()
    if not result.get('joined'):
        m = RE_JOINED.search(html)
        if m:
            result['joined'] = m.group(1).strip()

    m = RE_VIEW_COUNT.search(html)
    if m:
        raw_val = m.group(1) or m.group(2) or ''
        cs = raw_val.replace(',', '').replace('.', '').strip()
        if cs.isdigit() and int(cs) > 0:
            result['views'] = format(int(cs), ',')

    vc = extract_video_count(html)
    if vc:
        result['video_count'] = vc

    return result


def fetch_about_page(channel_url: str, channel_id: str = '') -> tuple:
    """
    Scrape the channel about page.

    Returns:
        (socials, ext_links, email, location, joined, views, video_count, last_video_date)
    """
    ps, extra = _extract_about_via_ytdlp(channel_url)
    if not ps:
        return {}, [], '', extra.get('location',''), extra.get('joined',''), extra.get('views',''), extra.get('video_count',''), extra.get('last_video_date','')

    redirect_urls = RE_REDIRECT.findall(ps)
    decoded = [decode_redirect(u) for u in redirect_urls]
    combined = ps + ' ' + ' '.join(decoded)

    socials = {}
    json_ext_links = []

    for pat in RE_JSON_LINKS:
        for raw_url in pat.findall(ps):
            u = raw_url.replace('\\u0026', '&').replace('\\/', '/')
            if 'youtube.com/redirect' in u:
                u = decode_redirect(u)
            u = u.strip()
            u_lower = u.lower()
            for key, info in SOCIAL_PLATFORMS.items():
                if key not in socials and info['check'] in u_lower:
                    m = info['regex'].search(u)
                    if m:
                        uname = m.group(1)
                        v = info.get('validator')
                        if (v is None or is_valid_username(uname, v)) and len(uname) > 1:
                            socials[key] = info['url_fmt'].format(uname)
                            break
            if u.startswith('http') and not any(d in u_lower for d in YT_DOMAINS) and not any(d in u_lower for d in NAV_DOMAINS):
                if u not in json_ext_links:
                    json_ext_links.append(u)

    for u in decoded:
        u = u.strip()
        if u.startswith('http') and not any(d in u.lower() for d in YT_DOMAINS) and not any(d in u.lower() for d in NAV_DOMAINS):
            if u not in json_ext_links:
                json_ext_links.append(u)

    for key, info in SOCIAL_PLATFORMS.items():
        if key not in socials:
            for uname in info['regex'].findall(combined):
                v = info.get('validator')
                if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                    socials[key] = info['url_fmt'].format(uname)
                    break

    email = ''
    for pat in RE_EMAIL_PAGE:
        for e in pat.findall(ps):
            e = e.strip()
            # Try base64 decode first (YouTube's businessEmail obfuscation)
            if '@' not in e and len(e) > 8:
                decoded = _try_decode_b64_email(e)
                if decoded:
                    e = decoded
            if '@' in e and '.' in e.split('@')[1]:
                if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                    email = e
                    break
        if email:
            break

    # If still no email, try YouTube InnerTube API (bypasses 'View email' button)
    if not email and channel_id:
        email = _fetch_email_innertube(channel_id)

    return (
        socials,
        json_ext_links[:15],
        email,
        extra.get('location', ''),
        extra.get('joined', ''),
        extra.get('views', ''),
        extra.get('video_count', ''),
        extra.get('last_video_date', ''),
    )


def extract_socials_from_text(text: str) -> tuple[dict, list, str]:
    """Extract social media accounts, URLs, and email from free text."""
    result = {}
    all_links = []

    if not text:
        return result, all_links, ''

    for key, info in SOCIAL_PLATFORMS.items():
        for uname in info['regex'].findall(text):
            v = info.get('validator')
            if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                result[key] = info['url_fmt'].format(uname)
                break

    url_pat = re.compile(r'https?://[^\s<>"\']+', re.I)
    for u in url_pat.findall(text):
        u = u.rstrip('.,)')
        if not any(d in u.lower() for d in YT_DOMAINS) and not any(d in u.lower() for d in NAV_DOMAINS):
            if u not in all_links:
                all_links.append(u)

    email = ''
    for m in RE_EMAIL.finditer(text):
        e = m.group(1)
        if not any(x in e.lower() for x in EMAIL_BLACKLIST):
            email = e
            break

    return result, all_links, email

# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def scrape_channel(url: str) -> dict:
    """
    Full channel scrape. Accepts any YouTube URL (video, channel, handle, @username).

    Returns a flat dict with keys:
        channel_url, name, handle, subscribers, views, videos, description,
        email, location, joined, last_video_date, thumbnail,
        instagram, tiktok, twitter, facebook, discord, twitch, myanimelist, linkedin,
        all_links

    On error returns: {'error': 'message'}
    """
    url = normalize_url(url)
    if not url:
        return {'error': 'Invalid URL'}

    ydl_opts = {'skip_download': True, 'quiet': True, 'no_warnings': True,
                'ignoreerrors': True, 'playlistend': 1}

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        pass

    # oEmbed fallback for video URLs when yt-dlp fails
    if not info:
        is_video_url = any(x in url for x in ['/watch?', 'youtu.be/', '/shorts/', '/live/'])
        if is_video_url:
            channel_url_fb, name_fb = _oembed_channel_url(url)
            if channel_url_fb:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(channel_url_fb, download=False)
                except Exception:
                    pass
                if not info:
                    url = channel_url_fb
                    info = {'extractor': 'youtube:tab', '_type': 'playlist',
                            'uploader': name_fb, 'channel': name_fb,
                            'channel_url': channel_url_fb, 'uploader_url': channel_url_fb}
        if not info:
            return {'error': 'Could not retrieve channel info'}

    is_video = info.get('extractor') == 'youtube' and info.get('_type') != 'playlist'

    name      = info.get('uploader') or info.get('channel') or info.get('title') or ''
    handle_raw = info.get('uploader_id') or ''
    handle    = ('@' + handle_raw.lstrip('@')) if handle_raw and not handle_raw.startswith('UC') else ''

    channel_url = RE_CLEAN.sub('', (
        info.get('channel_url') or info.get('uploader_url') or info.get('webpage_url') or url
    ).rstrip('/'))

    sub_count   = info.get('channel_follower_count') or info.get('subscriber_count')
    subscribers = f"{sub_count:,}" if sub_count else ''
    views       = '' if is_video else (f"{info['view_count']:,}" if info.get('view_count') else '')

    last_video_date = ''
    if is_video:
        d = info.get('upload_date') or ''
        if d and len(d) == 8 and d.isdigit():
            last_video_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"

    video_count = ''
    if not is_video:
        entries   = info.get('entries') or []
        tab_entry = next((e for e in entries if isinstance(e, dict) and
                          (e.get('_type') == 'playlist' or e.get('entries') is not None)), None)
        vc = (tab_entry.get('playlist_count') if tab_entry else None) or info.get('playlist_count')
        if vc and int(vc) > 3:
            video_count = str(vc)
        if not last_video_date and tab_entry:
            for v in (tab_entry.get('entries') or []):
                if isinstance(v, dict) and v.get('upload_date'):
                    d = v['upload_date']
                    if len(d) == 8 and d.isdigit():
                        last_video_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                    break

    description = (info.get('description') or '')[:1000]
    thumbnail   = info.get('thumbnail') or ''

    # yt-dlp may directly expose channel email in the info dict
    ydl_email = ''
    for field in ('email', 'channel_email', 'uploader_email'):
        v = info.get(field, '')
        if v and '@' in v and not any(x in v.lower() for x in EMAIL_BLACKLIST):
            ydl_email = v
            break
    # Also check first entry's channel metadata
    if not ydl_email:
        entries = info.get('entries') or []
        first = entries[0] if entries and isinstance(entries[0], dict) else {}
        for field in ('email', 'channel_email'):
            v = first.get(field, '')
            if v and '@' in v and not any(x in v.lower() for x in EMAIL_BLACKLIST):
                ydl_email = v
                break

    combined_text = description
    for field in ('tags', 'categories'):
        val = info.get(field)
        if isinstance(val, list):
            combined_text += ' ' + ' '.join(str(v) for v in val)

    socials, all_links, email = extract_socials_from_text(combined_text)

    # Extract channel ID (UCxxx) for InnerTube API
    channel_id = info.get('channel_id') or ''
    if not channel_id:
        m_id = re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', channel_url)
        if m_id:
            channel_id = m_id.group(1)

    about_socials, about_links, about_email, about_location, about_joined, about_views, about_video_count, about_last_video = fetch_about_page(channel_url, channel_id)

    for k, v in about_socials.items():
        if k not in socials:
            socials[k] = v
    if not email and ydl_email:
        email = ydl_email
    if not email and about_email:
        email = about_email
    for lnk in about_links:
        if lnk not in all_links:
            all_links.append(lnk)
    if not video_count and about_video_count:
        video_count = about_video_count
    if not views and about_views:
        views = about_views
    if about_last_video:
        last_video_date = about_last_video

    # Deduplicate links (ignore trailing slash differences)
    seen, deduped = set(), []
    for lnk in all_links:
        norm = lnk.rstrip('/')
        if norm not in seen:
            seen.add(norm)
            deduped.append(lnk)
    all_links = deduped

    # Convert YYYY-MM-DD → "X time ago"
    if last_video_date and len(last_video_date) == 10 and last_video_date[4] == '-':
        try:
            upload = date(int(last_video_date[:4]), int(last_video_date[5:7]), int(last_video_date[8:]))
            days   = (date.today() - upload).days
            if   days == 0:       last_video_date = 'today'
            elif days < 7:        last_video_date = f'{days} day{"s" if days>1 else ""} ago'
            elif days < 30:       last_video_date = f'{days//7} week{"s" if days//7>1 else ""} ago'
            elif days < 365:      last_video_date = f'{days//30} month{"s" if days//30>1 else ""} ago'
            else:                 last_video_date = f'{days//365} year{"s" if days//365>1 else ""} ago'
        except Exception:
            pass

    return {
        'channel_url':    channel_url,
        'name':           name,
        'handle':         handle,
        'subscribers':    subscribers,
        'views':          views,
        'videos':         video_count,
        'description':    description,
        'email':          email,
        'location':       about_location or info.get('location') or '',
        'joined':         about_joined or '',
        'last_video_date': last_video_date,
        'thumbnail':      thumbnail,
        **socials,
        'all_links':      all_links[:15],
    }
