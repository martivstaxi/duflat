"""
Duflat - YouTube Channel Investigator API
"""

import re
import os
import json
import random
import threading
import requests
from urllib.parse import unquote, parse_qs, urlparse
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__, static_folder='.')
CORS(app)

# ============================================================
# SOSYAL MEDYA REGEX
# ============================================================

INVALID_USERNAMES = {
    'twitter':   frozenset({'summary','intent','share','home','search','i','hashtag','player','widgets','settings','privacy','tos','about','explore','notifications','messages','login','signup','card','cards','summary_large_image'}),
    'instagram': frozenset({'p','reel','reels','stories','explore','direct','accounts','about','legal','privacy','terms','help','api','press','jobs','blog','developer','tv','igtv'}),
    'facebook':  frozenset({'sharer','share','dialog','plugins','login','help','pages','groups','events','marketplace','gaming','watch','privacy','policies','ad_campaign','ads','business','tr'}),
    'twitch':    frozenset({'directory','videos','clips','following','settings','subscriptions','inventory','drops','wallet','friends','messages','search','downloads','jobs','turbo','products','prime','partners'}),
}

SOCIAL_PLATFORMS = {
    'instagram':   {'regex': re.compile(r'instagram\.com/([a-zA-Z0-9._]{2,30})', re.I), 'url_fmt': 'https://www.instagram.com/{}',     'validator': 'instagram', 'check': 'instagram.com/'},
    'tiktok':      {'regex': re.compile(r'tiktok\.com/@?([a-zA-Z0-9._]{2,30})', re.I),  'url_fmt': 'https://www.tiktok.com/@{}',        'validator': None,        'check': 'tiktok.com/'},
    'twitter':     {'regex': re.compile(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{2,15})', re.I),'url_fmt': 'https://x.com/{}',               'validator': 'twitter',   'check': 'twitter.com/'},
    'facebook':    {'regex': re.compile(r'facebook\.com/([a-zA-Z0-9.]{2,50})', re.I),   'url_fmt': 'https://www.facebook.com/{}',       'validator': 'facebook',  'check': 'facebook.com/'},
    'discord':     {'regex': re.compile(r'discord\.(?:gg|com/invite)/([a-zA-Z0-9]{2,20})', re.I),'url_fmt': 'https://discord.gg/{}',   'validator': None,        'check': 'discord.'},
    'twitch':      {'regex': re.compile(r'twitch\.tv/([a-zA-Z0-9_]{2,25})', re.I),      'url_fmt': 'https://twitch.tv/{}',              'validator': 'twitch',    'check': 'twitch.tv/'},
    'myanimelist': {'regex': re.compile(r'myanimelist\.net/profile/([a-zA-Z0-9_-]{2,30})', re.I),'url_fmt': 'https://myanimelist.net/profile/{}','validator': None,'check': 'myanimelist.net/'},
    'linkedin':    {'regex': re.compile(r'linkedin\.com/(?:company|in)/([a-zA-Z0-9._-]{2,80})', re.I),'url_fmt': 'https://www.linkedin.com/company/{}','validator': None,'check': 'linkedin.com/'},
}

RE_EMAIL = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
EMAIL_BLACKLIST = {'example', 'test', 'noreply', 'google', 'gstatic', 'youtube', 'sentry', 'wix', 'squarespace'}
NAV_DOMAINS = ('developers.google.com','support.google.com','policies.google.com','accounts.google.com','gstatic.com','googleapis.com','ggpht.com','ytimg.com','googleusercontent.com')
YT_DOMAINS = ('youtube.com', 'youtu.be', 'yt.be')

RE_EMBED   = re.compile(r'youtube\.com/v/([a-zA-Z0-9_-]+)')
RE_CLEAN   = re.compile(r'/(about|videos|shorts|streams|playlists|community|channels|featured)/?$')

# About sayfası regex'leri
RE_COUNTRY    = re.compile(r'"country":\s*"([^"]+)"')
RE_JOINED     = re.compile(r'Joined\s+([A-Za-z]+\s+\d+,\s+\d{4})')
RE_JOINED_JSON = re.compile(r'"joinedDateText"[^}]{0,300}"content":\s*"Joined\s+([^"]+)"')
# Kanal toplam görüntülenme: aboutChannelViewModel içinde doğrudan string ("viewCountText":"33,974,997 views")
# Video view count'ı değil, kanal total'ı — subscriberCountText yakınında olur
RE_VIEW_COUNT = re.compile(
    r'"subscriberCountText":[^}]{0,200}"viewCountText":\s*"([\d,\.]+)\s*views?"'
    r'|"viewCountText":\s*"([\d,\.]+)\s*views?(?:",|\s*})',
    re.I
)
RE_VIDEO_COUNT_PATTERNS = [
    re.compile(r'"videoCountText":\s*"([\d,.\s]+)\s*video', re.I),   # aboutChannelViewModel format
    re.compile(r'"videosCountText":\s*\{\s*"simpleText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videoCount":\s*"(\d+)"'),
    re.compile(r'"videoCount":\s*(\d+)'),
    re.compile(r'"videoCountText":\s*\{\s*"runs"[^}]{0,200}"text":\s*"([\d,.\s]+)"'),
]

# ============================================================
# YARDIMCI
# ============================================================

def is_valid_username(username, platform):
    if not username or len(username) < 2 or '...' in username:
        return False
    inv = INVALID_USERNAMES.get(platform)
    return username.lower() not in inv if inv else True

def normalize_url(url):
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

RE_REDIRECT = re.compile(r'https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"\s<>\\]+')
RE_JSON_LINKS = [
    re.compile(r'"channelExternalLinkViewModel"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"link"\s*:\s*\{[^}]*?"content"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"primaryLinkViewModel"(?:[^{}]|\{[^{}]*\})*?"url"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"url"\s*:\s*"(https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"]+)"'),
    re.compile(r'"linkUrl"\s*:\s*"(https?://[^"]+)"'),
]
RE_EMAIL_PAGE = [
    re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
    re.compile(r'"email":"([^"]+@[^"]+)"'),
    re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
]

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Cache-Control': 'max-age=0',
}

def decode_redirect(url):
    if 'youtube.com/redirect' not in url and 'youtube.com\\/redirect' not in url:
        return url
    try:
        clean = url.replace('\\/', '/').replace('\\u0026', '&')
        params = parse_qs(urlparse(clean).query)
        if 'q' in params:
            return unquote(params['q'][0])
    except:
        pass
    return url

def extract_video_count(ps):
    """Page source'dan video sayısını çıkar"""
    for pat in RE_VIDEO_COUNT_PATTERNS:
        m = pat.search(ps)
        if m:
            grp = next((g for g in m.groups() if g), None) if m.lastindex and m.lastindex > 1 else m.group(1)
            if grp:
                cleaned = grp.strip().replace(',', '').replace('.', '').split()[0]
                if cleaned.isdigit() and int(cleaned) > 0:
                    return cleaned
    return ''


_about_patch_lock = threading.Lock()


RE_PUBLISHED_TIME = re.compile(
    r'"publishedTimeText":\s*\{\s*"simpleText":\s*"([^"]+)"\s*\}'
    r'|"publishedTimeText":\s*"([^"]+)"'
)


def _extract_about_via_ytdlp(channel_url):
    """
    yt-dlp'nin _download_webpage'ini intercept ederek:
    - /about HTML'den: location, joined, views, video_count
    - /videos HTML'den: son video tarihi (publishedTimeText)
    yt-dlp consent'i otomatik handle ettiği için Railway IP sorunu olmaz.
    """
    base = RE_CLEAN.sub('', channel_url.rstrip('/'))
    about_url = base + '/about'
    videos_url = base + '/videos'
    captured = {'about': '', 'videos': ''}

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

        with _about_patch_lock:
            InfoExtractor._download_webpage = patched_dw
            try:
                ydl_opts = {'skip_download': True, 'quiet': True, 'no_warnings': True,
                            'ignoreerrors': True, 'extract_flat': True}
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

    # Son video tarihi: /videos sayfasından publishedTimeText
    if not parsed.get('last_video_date'):
        m = RE_PUBLISHED_TIME.search(videos_html)
        if m:
            parsed['last_video_date'] = (m.group(1) or m.group(2) or '').strip()

    return about_html, parsed


def _parse_about_from_html(html):
    """Raw HTML'den location, joined, views, video_count çıkar"""
    if not html:
        return {}
    result = {}

    # Location
    m = RE_COUNTRY.search(html)
    if m:
        result['location'] = m.group(1)

    # Joined date
    m = RE_JOINED_JSON.search(html)
    if m:
        result['joined'] = m.group(1).strip()
    if not result.get('joined'):
        m = RE_JOINED.search(html)
        if m:
            result['joined'] = m.group(1).strip()

    # Total views (kanal toplam — aboutChannelViewModel'den)
    m = RE_VIEW_COUNT.search(html)
    if m:
        raw_val = m.group(1) or m.group(2) or ''
        cs = raw_val.replace(',', '').replace('.', '').strip()
        if cs.isdigit() and int(cs) > 0:
            result['views'] = format(int(cs), ',')

    # Video count
    vc = extract_video_count(html)
    if vc:
        result['video_count'] = vc

    return result


def fetch_about_page(channel_url):
    """About sayfasından email, sosyal medya, konum, katılım tarihi, görüntülenme, video sayısı çek"""
    ps, extra = _extract_about_via_ytdlp(channel_url)
    if not ps:
        return {}, [], '', extra.get('location',''), extra.get('joined',''), extra.get('views',''), extra.get('video_count',''), extra.get('last_video_date','')

    # Redirect URL'leri çöz
    redirect_urls = RE_REDIRECT.findall(ps)
    decoded = [decode_redirect(u) for u in redirect_urls]
    combined = ps + ' ' + ' '.join(decoded)

    socials = {}
    json_ext_links = []

    # JSON link kartları
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

    # Sosyal medya fallback: combined text'ten
    for key, info in SOCIAL_PLATFORMS.items():
        if key not in socials:
            for uname in info['regex'].findall(combined):
                v = info.get('validator')
                if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                    socials[key] = info['url_fmt'].format(uname)
                    break

    # Email
    email = ''
    for pat in RE_EMAIL_PAGE:
        for e in pat.findall(ps):
            if '@' in e and '.' in e.split('@')[1]:
                if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                    email = e
                    break
        if email:
            break

    return socials, json_ext_links[:15], email, extra.get('location',''), extra.get('joined',''), extra.get('views',''), extra.get('video_count',''), extra.get('last_video_date','')


def extract_socials_from_text(text):
    """Metin (açıklama + linkler) içinden sosyal medya hesaplarını çıkar"""
    result = {}
    all_links = []

    if not text:
        return result, all_links

    for key, info in SOCIAL_PLATFORMS.items():
        matches = info['regex'].findall(text)
        for uname in matches:
            v = info.get('validator')
            if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                result[key] = info['url_fmt'].format(uname)
                break

    # Genel URL'ler
    url_pat = re.compile(r'https?://[^\s<>"\']+', re.I)
    for u in url_pat.findall(text):
        u = u.rstrip('.,)')
        if not any(d in u.lower() for d in YT_DOMAINS) and not any(d in u.lower() for d in NAV_DOMAINS):
            if u not in all_links:
                all_links.append(u)

    # Email
    email = ''
    for m in RE_EMAIL.finditer(text):
        e = m.group(1)
        if not any(x in e.lower() for x in EMAIL_BLACKLIST):
            email = e
            break

    return result, all_links, email

# ============================================================
# ANA ÇIKARMA (yt-dlp)
# ============================================================

def _oembed_channel_url(video_url):
    """Video URL'sinden oEmbed ile kanal URL'si al (bot tespiti yok)"""
    try:
        r = requests.get(
            'https://www.youtube.com/oembed',
            params={'url': video_url, 'format': 'json'},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            author_url = data.get('author_url', '')
            if author_url and 'youtube.com' in author_url:
                return author_url, data.get('author_name', '')
    except Exception:
        pass
    return None, ''


def scrape_channel(url):
    url = normalize_url(url)
    if not url:
        return {'error': 'Geçersiz URL'}

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'playlistend': 1,
    }

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        pass

    # yt-dlp başarısız olduysa ve video URL ise: oEmbed fallback
    if not info:
        is_video_url = any(x in url for x in ['/watch?', 'youtu.be/', '/shorts/', '/live/'])
        if is_video_url:
            channel_url_fb, name_fb = _oembed_channel_url(url)
            if channel_url_fb:
                # Kanal URL'si ile tekrar dene
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(channel_url_fb, download=False)
                except Exception:
                    pass
                # Kanal URL'si de başarısız olduysa sadece about page çek
                if not info:
                    url = channel_url_fb
                    # Minimal info dict oluştur, about page'den dolduracağız
                    info = {
                        'extractor': 'youtube:tab',
                        '_type': 'playlist',
                        'uploader': name_fb,
                        'channel': name_fb,
                        'channel_url': channel_url_fb,
                        'uploader_url': channel_url_fb,
                    }
        if not info:
            return {'error': 'Kanal bilgisi alınamadı'}

    is_video = info.get('extractor') == 'youtube' and info.get('_type') != 'playlist'

    # ---- Temel alanlar ----
    name = info.get('uploader') or info.get('channel') or info.get('title') or ''
    handle_raw = info.get('uploader_id') or ''
    handle = ('@' + handle_raw.lstrip('@')) if handle_raw and not handle_raw.startswith('UC') else ''

    channel_url = RE_CLEAN.sub('', (
        info.get('channel_url') or info.get('uploader_url') or info.get('webpage_url') or url
    ).rstrip('/'))

    sub_count = info.get('channel_follower_count') or info.get('subscriber_count')
    subscribers = f"{sub_count:,}" if sub_count else ''

    # Video URL'si için: view_count videonun görüntülenmesi, kanal için boş bırak
    views = '' if is_video else (f"{info['view_count']:,}" if info.get('view_count') else '')

    # Son video tarihi: video URL'sinden direkt upload_date gelir
    last_video_date = ''
    if is_video:
        d = info.get('upload_date') or ''
        if d and len(d) == 8 and d.isdigit():
            last_video_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"

    # Video sayısı: kanal tab'ından gelir, video URL'sinde yok
    video_count = ''
    if not is_video:
        entries = info.get('entries') or []
        tab_entry = next((e for e in entries if isinstance(e, dict) and
                          (e.get('_type') == 'playlist' or e.get('entries') is not None)), None)
        vc = (tab_entry.get('playlist_count') if tab_entry else None) or info.get('playlist_count')
        if vc and int(vc) > 3:
            video_count = str(vc)
        # Son video tarihini kanal tabından bul
        if not last_video_date and tab_entry:
            for v in (tab_entry.get('entries') or []):
                if isinstance(v, dict) and v.get('upload_date'):
                    d = v['upload_date']
                    if len(d) == 8 and d.isdigit():
                        last_video_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                    break

    # Açıklama: video URL'sinde video açıklaması (sosyal linkler burada olur)
    description = (info.get('description') or '')[:1000]
    thumbnail = info.get('thumbnail') or ''

    # ---- Sosyal + email ----
    combined_text = description
    for field in ('tags', 'categories'):
        val = info.get(field)
        if isinstance(val, list):
            combined_text += ' ' + ' '.join(str(v) for v in val)

    socials, all_links, email = extract_socials_from_text(combined_text)

    # About sayfasından link kartları + email + konum + katılım + views + video sayısı
    about_socials, about_links, about_email, about_location, about_joined, about_views, about_video_count, about_last_video = fetch_about_page(channel_url)
    for k, v in about_socials.items():
        if k not in socials:
            socials[k] = v
    if not email and about_email:
        email = about_email
    for lnk in about_links:
        if lnk not in all_links:
            all_links.append(lnk)
    if not video_count and about_video_count:
        video_count = about_video_count
    if not views and about_views:
        views = about_views
    # /videos tab'ından gelen tarih her zaman öncelikli — aranan video eski olabilir
    if about_last_video:
        last_video_date = about_last_video
    # Fallback: yt-dlp'den gelen (searched video's date) — sadece about_last_video yoksa


    # Duplicate link temizle: trailing slash farkını normalize et
    seen_normalized = set()
    deduped = []
    for lnk in all_links:
        norm = lnk.rstrip('/')
        if norm not in seen_normalized:
            seen_normalized.add(norm)
            deduped.append(lnk)
    all_links = deduped

    # Tarih formatı: YYYY-MM-DD → "X time ago"
    if last_video_date and len(last_video_date) == 10 and last_video_date[4] == '-':
        try:
            from datetime import date
            upload = date(int(last_video_date[:4]), int(last_video_date[5:7]), int(last_video_date[8:]))
            today = date.today()
            days = (today - upload).days
            if days == 0:
                last_video_date = 'today'
            elif days < 7:
                last_video_date = f'{days} day{"s" if days > 1 else ""} ago'
            elif days < 30:
                weeks = days // 7
                last_video_date = f'{weeks} week{"s" if weeks > 1 else ""} ago'
            elif days < 365:
                months = days // 30
                last_video_date = f'{months} month{"s" if months > 1 else ""} ago'
            else:
                years = days // 365
                last_video_date = f'{years} year{"s" if years > 1 else ""} ago'
        except Exception:
            pass

    data = {
        'channel_url': channel_url,
        'name': name,
        'handle': handle,
        'subscribers': subscribers or '',
        'views': views or '',
        'videos': video_count,
        'description': description,
        'email': email,
        'location': about_location or info.get('location') or '',
        'joined': about_joined or '',
        'last_video_date': last_video_date,
        'thumbnail': thumbnail,
        **socials,
        'all_links': all_links[:15],
    }

    return data

# ============================================================
# API
# ============================================================

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    body = request.get_json(silent=True) or {}
    url = body.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL boş'}), 400

    result = scrape_channel(url)
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(result)

@app.route('/debug', methods=['GET'])
def debug():
    """Ham yt-dlp çıktısını göster — sorun tespiti için"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parametresi gerekli: /debug?url=...'}), 400

    url = normalize_url(url)
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'playlistend': 1,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if not info:
        return jsonify({'error': 'Boş sonuç döndü (info=None)'}), 500

    # Sadece skaler alanları döndür (entries vs. çok büyük)
    safe = {k: v for k, v in info.items()
            if isinstance(v, (str, int, float, bool, type(None))) or
               (isinstance(v, list) and k in ('tags', 'categories'))}
    safe['entries_count'] = len(info.get('entries') or [])
    if info.get('entries'):
        first = info['entries'][0]
        if isinstance(first, dict):
            safe['first_entry_keys'] = list(first.keys())
            safe['first_entry_upload_date'] = first.get('upload_date')
            safe['first_entry_playlist_count'] = first.get('playlist_count')
            safe['first_entry_channel_follower_count'] = first.get('channel_follower_count')
            safe['first_entry_type'] = first.get('_type')
            # İç içe entries var mı?
            sub = first.get('entries') or []
            safe['first_entry_sub_entries_count'] = len(sub)
            if sub and isinstance(sub[0], dict):
                safe['first_video_upload_date'] = sub[0].get('upload_date')
                safe['first_video_title'] = sub[0].get('title')
    return jsonify(safe)

@app.route('/debug-deep', methods=['GET'])
def debug_deep():
    """yt-dlp'nin tam info dict'ini göster — tüm nested alanlar dahil"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parametresi gerekli'}), 400
    url = normalize_url(url)
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'playlistend': 1,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    if not info:
        return jsonify({'error': 'Boş sonuç'}), 500

    def safe_val(v, depth=0):
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        if isinstance(v, list) and depth < 2:
            return [safe_val(i, depth+1) for i in v[:3]]
        if isinstance(v, dict) and depth < 2:
            return {k2: safe_val(v2, depth+1) for k2, v2 in list(v.items())[:30]}
        return f'<{type(v).__name__}>'

    result = safe_val(info)

    # İlk entry'nin tüm alanları (scalar)
    entries = info.get('entries') or []
    if entries and isinstance(entries[0], dict):
        first = entries[0]
        result['_first_entry_all_scalars'] = {
            k: v for k, v in first.items()
            if isinstance(v, (str, int, float, bool, type(None))) and 'channel' in k.lower() or
               k in ('view_count', 'subscriber_count', 'playlist_count', 'video_count', 'location', 'joined', 'country')
        }
    return jsonify(result)


@app.route('/debug-rawpage', methods=['GET'])
def debug_rawpage():
    """About sayfasının ham içeriğinden snippet'lar göster"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url gerekli'}), 400
    url = normalize_url(url)
    ps, extra = _extract_about_via_ytdlp(url)
    if not ps:
        return jsonify({'error': 'fetch başarısız', 'extra': extra}), 500

    checks = [
        'ytInitialData', 'ytcfg', 'ytInitialPlayerResponse',
        '"country"', '"viewCountText"', '"joinedDateText"', '"videoCountText"',
        '"subscriberCountText"', 'channelMetadataRenderer', 'aboutChannelViewModel',
        'c4TabbedHeaderRenderer', 'channelHeaderTabsRenderer',
        'INNERTUBE_API_KEY',
    ]
    snippets = {}
    for key in checks:
        idx = ps.find(key)
        if idx >= 0:
            snippets[key] = ps[max(0, idx-20):idx+100]

    return jsonify({
        'page_length': len(ps),
        'first_500_chars': ps[:500],
        'found_keys': snippets,
        'extra_parsed': extra,
    })


@app.route('/debug-about', methods=['GET'])
def debug_about():
    """About sayfası requests çıktısını göster — konum/katılım/views/videos testi için"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parametresi gerekli'}), 400
    url = normalize_url(url)
    ps, _ = _extract_about_via_ytdlp(url)
    socials, links, email, location, joined, views, video_count = fetch_about_page(url)
    return jsonify({
        'page_length': len(ps),
        'has_ytInitialData': 'ytInitialData' in ps,
        'has_country': '"country"' in ps,
        'has_viewCountText': '"viewCountText"' in ps,
        'has_joinedDateText': '"joinedDateText"' in ps,
        'has_videoCountText': '"videoCountText"' in ps or '"videosCountText"' in ps,
        'extracted': {
            'location': location,
            'joined': joined,
            'views': views,
            'video_count': video_count,
            'email': email,
            'socials': socials,
            'all_links': links,
        }
    })


# ============================================================
# AGENCY FINDER
# ============================================================

# Ajans aramasında atlanacak domain'ler
_AGENCY_SKIP_DOMAINS = (
    'youtube.com', 'youtu.be', 'instagram.com', 'twitter.com', 'x.com',
    'facebook.com', 'tiktok.com', 'discord.gg', 'discord.com', 'twitch.tv',
    'reddit.com', 'wikipedia.org', 'linktr.ee', 'bio.link', 'linkin.bio',
    'beacons.ai', 'allmylinks.com', 'myanimelist.net',
)
# Kişisel email provider'ları
_PERSONAL_EMAIL_DOMAINS = (
    'gmail.', 'yahoo.', 'hotmail.', 'outlook.', 'icloud.',
    'protonmail.', 'live.', 'msn.', 'aol.', 'mail.',
)

# Description'dan ajans ipuçları
_AGENCY_DESC_RE = [
    re.compile(r'(?:management|managed by|booking|talent agency|mcn|multi.?channel network|production company|produced by|partner(?:ship)?s?)\s*[:\-]?\s*([A-Za-z0-9&\s\.]{3,60})', re.I),
    re.compile(r'(?:for business(?: inquiries)?|business contact|business email|work with us)\s*[:\-]?\s*[\w\s]{0,20}?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.I),
    re.compile(r'(?:network|agency|label|studio|entertainment)\s*[:\-]?\s*([A-Za-z0-9&\s\.]{3,50})', re.I),
]


def _ddg_search(query, max_results=5):
    """DuckDuckGo HTML search — API anahtarı gerektirmez."""
    try:
        r = requests.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query, 'b': '', 'kl': 'en-us'},
            headers={**BROWSER_HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        urls = []
        # DDG HTML'de sonuç URL'leri .result__url span içinde gösterilir (text olarak)
        for el in soup.select('.result__url'):
            url_text = el.get_text(strip=True)
            if not url_text:
                continue
            if not url_text.startswith('http'):
                url_text = 'https://' + url_text
            if url_text not in urls:
                urls.append(url_text)
        return urls[:max_results]
    except Exception:
        return []


def _extract_company_info(html, page_url):
    """HTML'den şirket adı, email, açıklama, sosyal medya çıkar."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return None

    result = {'website': page_url}

    # Şirket adı: OG title > title tag
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        raw = og_title['content'].strip()
        result['name'] = re.sub(r'\s*[-|–|·]\s*(home|official|welcome|website).*$', '', raw, flags=re.I).strip()
    elif soup.title and soup.title.string:
        raw = soup.title.string.strip()
        result['name'] = re.sub(r'\s*[-|–|·]\s*(home|official|welcome|website).*$', '', raw, flags=re.I).strip()

    # Description
    for attr in [{'property': 'og:description'}, {'name': 'description'}]:
        tag = soup.find('meta', attrs=attr)
        if tag and tag.get('content'):
            result['description'] = tag['content'].strip()[:300]
            break

    # Email — önce mailto: linkleri, sonra genel regex
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('mailto:'):
            e = href[7:].split('?')[0].strip()
            if e and not any(x in e.lower() for x in EMAIL_BLACKLIST):
                result['email'] = e
                break
    if not result.get('email'):
        for m in RE_EMAIL.finditer(html):
            e = m.group(1)
            if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                result['email'] = e
                break

    # Telefon (basit)
    phone_m = re.search(r'(?:tel|phone|call)[\s:]*(\+?[\d\s\-().]{7,20})', html, re.I)
    if phone_m:
        result['phone'] = phone_m.group(1).strip()

    # Sosyal medya
    socials = {}
    for key, info in SOCIAL_PLATFORMS.items():
        for m in info['regex'].finditer(html):
            uname = m.group(1)
            v = info.get('validator')
            if (v is None or is_valid_username(uname, v)) and len(uname) > 1:
                socials[key] = info['url_fmt'].format(uname)
                break
    if socials:
        result['socials'] = socials

    return result


def _investigate_url(url):
    """
    URL'yi scrape et, şirket bilgilerini çıkar.
    Ana sayfa + /contact + /about sub-page'leri de dener.
    """
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=10, allow_redirects=True)
        if r.status_code not in (200,):
            return None
        result = _extract_company_info(r.text, r.url)
        if not result:
            return None

        # Contact / About sub-page'leri de tara — eksik alanları doldur
        base = r.url.rstrip('/')
        for sub in ('/contact', '/about'):
            if result.get('email') and result.get('name'):
                break
            try:
                r2 = requests.get(base + sub, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
                if r2.status_code == 200:
                    sub_info = _extract_company_info(r2.text, r2.url)
                    if sub_info:
                        if not result.get('email') and sub_info.get('email'):
                            result['email'] = sub_info['email']
                        if not result.get('description') and sub_info.get('description'):
                            result['description'] = sub_info['description']
                        for k, v in sub_info.get('socials', {}).items():
                            result.setdefault('socials', {})[k] = v
            except Exception:
                pass

        # Yeterli bilgi var mı?
        has_name = bool(result.get('name'))
        has_contact = bool(result.get('email') or result.get('socials'))
        if has_name or has_contact:
            return result
    except Exception:
        pass
    return None


def _search_and_investigate(query):
    """DDG'de ara, sosyal medya dışı ilk uygun sonucu araştır."""
    urls = _ddg_search(query, max_results=6)
    for url in urls:
        u_lower = url.lower()
        if any(d in u_lower for d in _AGENCY_SKIP_DOMAINS):
            continue
        result = _investigate_url(url)
        if result:
            return result
    return None


def _try_linktree(url):
    """Linktree sayfasından şirket linklerini çıkarmayı dene."""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and not any(d in href.lower() for d in _AGENCY_SKIP_DOMAINS):
                if href not in links:
                    links.append(href)
        return links[:5]
    except Exception:
        return []


def find_agency(channel_data):
    """
    Channel verilerinden ajans/şirket araştırması yapar.
    Sırayla her ipucunu dener, bulana kadar devam eder.
    Döndürür: {'found': True, 'name': ..., 'website': ..., ...} veya {'found': False}
    """
    channel_name = channel_data.get('name', '')
    email = channel_data.get('email', '')
    description = channel_data.get('description', '')
    all_links = channel_data.get('all_links', [])

    # --- İpuçlarını topla ---

    # Email domain
    email_domain = None
    if email and '@' in email:
        domain = email.split('@')[1].lower()
        if not any(domain.startswith(g) for g in _PERSONAL_EMAIL_DOMAINS):
            email_domain = domain

    # Description'dan ajans regex
    desc_hints = []
    for pat in _AGENCY_DESC_RE:
        m = pat.search(description)
        if m:
            val = m.group(1).strip().rstrip('.').strip()
            if len(val) > 3 and val not in desc_hints:
                desc_hints.append(val)

    # External links: sosyal medya dışı
    company_links = []
    linktree_links = []
    for lnk in all_links:
        u_lower = lnk.lower()
        if 'linktr.ee' in u_lower or 'linkin.bio' in u_lower or 'beacons.ai' in u_lower:
            linktree_links.append(lnk)
        elif not any(d in u_lower for d in _AGENCY_SKIP_DOMAINS):
            company_links.append(lnk)

    # --- Araştırma Pipeline ---

    def _make_result(info, source):
        enriched = enrich_agency(channel_data, info)
        return {'found': True, 'source': source, **enriched}

    # 1. Email domain → corporate site
    if email_domain:
        r = _investigate_url(f'https://{email_domain}')
        if not r:
            r = _investigate_url(f'https://www.{email_domain}')
        if r:
            return _make_result(r, 'email_domain')

        # Scraping başarısız — DDG ile domain adını ara
        r = _search_and_investigate(f'site:{email_domain} OR "{email_domain}"')
        if r:
            return _make_result(r, 'email_domain')

        # Hâlâ bulunamadı — domain'i minimal lead olarak döndür
        # (scraping çalışmasa da email domain değerli bir ipucu)
        domain_brand = email_domain.rsplit('.', 1)[0]  # "iamxlive.com" → "iamxlive"
        # Camel-case veya dash'leri boşluğa çevir
        domain_brand = re.sub(r'[-_]', ' ', domain_brand).title()
        return _make_result({
            'website': f'https://{email_domain}',
            'name': domain_brand,
            'note': 'Website could not be scraped — identified from email domain.',
        }, 'email_domain')

    # 2. External company links
    for lnk in company_links[:3]:
        r = _investigate_url(lnk)
        if r:
            return _make_result(r, 'external_link')

    # 3. Linktree → içindeki şirket linklerini çıkar
    for lt in linktree_links[:2]:
        extracted = _try_linktree(lt)
        for lnk in extracted:
            r = _investigate_url(lnk)
            if r:
                return _make_result(r, 'linktree')

    # 4. Description regex → DDG arama
    for hint in desc_hints[:2]:
        r = _search_and_investigate(f'"{hint}" official site')
        if r:
            return _make_result(r, 'description_regex')

    # 5. Channel adı + agency → DDG arama
    if channel_name:
        r = _search_and_investigate(f'{channel_name} management agency booking contact')
        if r:
            return _make_result(r, 'web_search')

    # 6. Claude Haiku fallback — tüm diğer yöntemler başarısız olduysa
    r = _llm_find_agency(channel_data)
    if r:
        return _make_result(r, 'ai_analysis')

    return {'found': False}


def _deep_scrape_agency_site(website):
    """Agency websitesinin birden fazla sayfasını scrape et, temiz metin döndür."""
    from bs4 import BeautifulSoup
    parsed = urlparse(website.rstrip('/'))
    base = f"{parsed.scheme}://{parsed.netloc}"
    pages = {}
    for path in ['', '/about', '/about-us', '/contact', '/contact-us', '/team', '/roster', '/talent', '/services']:
        if len(pages) >= 5:
            break
        try:
            r = requests.get(base + path, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''):
                soup = BeautifulSoup(r.text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                    tag.decompose()
                text = ' '.join(soup.get_text(' ', strip=True).split())
                if len(text) > 100:
                    pages[path or '/'] = text[:1800]
        except Exception:
            pass
    return pages


def _llm_enrich_agency(channel_data, basic_info, scraped_content):
    """Claude Haiku ile kapsamlı ajans profili oluştur."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = ['=== YouTube Channel ===']
        for f, l in [('name', 'Channel'), ('handle', 'Handle'), ('email', 'Email'),
                     ('description', 'Description'), ('location', 'Location')]:
            if channel_data.get(f):
                parts.append(f'{l}: {channel_data[f]}')
        social_keys = ['instagram', 'twitter', 'tiktok', 'facebook', 'linkedin']
        socials_text = [f"{k}: {channel_data[k]}" for k in social_keys if channel_data.get(k)]
        if socials_text:
            parts.append('Social: ' + ', '.join(socials_text))
        if channel_data.get('all_links'):
            parts.append('Links: ' + ', '.join(channel_data['all_links'][:8]))

        parts.append('\n=== Agency (found so far) ===')
        for f, l in [('name', 'Name'), ('website', 'Website'), ('email', 'Email')]:
            if basic_info.get(f):
                parts.append(f'{l}: {basic_info[f]}')

        if scraped_content:
            parts.append('\n=== Agency Website Content ===')
            for path, text in list(scraped_content.items())[:5]:
                parts.append(f'[{path or "/"}]\n{text}')

        context = '\n'.join(parts)[:6000]

        prompt = f"""Analyze this data and extract a detailed profile of the management company / talent agency behind the YouTube channel.

{context}

Return ONLY a valid JSON object. Use null for unknown fields. Extract only what is actually supported by the data:
{{
  "name": "official company name",
  "website": "main website URL",
  "description": "2-3 sentences describing what this company does",
  "summary": "one paragraph executive summary about this agency",
  "services": ["talent management", "content production", ...],
  "contact_email": "primary business contact email",
  "contact_phone": "phone number or null",
  "address": "city/country or full address or null",
  "founded": "founding year or null",
  "socials": {{
    "instagram": "URL or null",
    "twitter": "URL or null",
    "linkedin": "URL or null",
    "facebook": "URL or null"
  }},
  "notable_clients": ["channel or artist names managed by this agency"],
  "reasoning": "one sentence explaining how you identified this as the agency"
}}"""

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            # null ve boş değerleri filtrele
            return {k: v for k, v in data.items() if v and v != 'null'}
    except Exception:
        pass
    return None


def enrich_agency(channel_data, basic_info):
    """Agency hakkında derin araştırma: web scraping + AI analizi."""
    website = basic_info.get('website', '')
    scraped = _deep_scrape_agency_site(website) if website else {}
    enriched = _llm_enrich_agency(channel_data, basic_info, scraped)
    if enriched:
        merged = {**basic_info}
        for k, v in enriched.items():
            if v:
                merged[k] = v
        return merged
    return basic_info


def _llm_find_agency(channel_data):
    """
    Claude Haiku ile ajans/şirket tespiti.
    Sadece ANTHROPIC_API_KEY ortam değişkeni varsa çalışır.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None

    try:
        import anthropic

        # Channel verisini prompt'a ekle
        parts = []
        for field, label in [('name', 'Channel name'), ('handle', 'Handle'),
                              ('description', 'Description'), ('email', 'Email'),
                              ('location', 'Location'), ('joined', 'Joined')]:
            val = channel_data.get(field, '')
            if val:
                parts.append(f"{label}: {val}")

        social_keys = ['instagram', 'twitter', 'tiktok', 'facebook', 'linkedin', 'twitch']
        socials = [f"{k}: {channel_data[k]}" for k in social_keys if channel_data.get(k)]
        if socials:
            parts.append("Social media: " + ", ".join(socials))

        ext_links = channel_data.get('all_links', [])
        if ext_links:
            parts.append("External links: " + ", ".join(ext_links[:10]))

        context = "\n".join(parts)

        prompt = f"""Analyze this YouTube channel data and identify the management company, talent agency, MCN, or production company behind it.

{context}

Respond ONLY with a JSON object. Use null for unknown fields.
If an agency/company can be identified:
{{"found": true, "name": "company name", "website": "URL or domain", "email": "contact email or null", "reasoning": "one sentence"}}

If no agency can be identified:
{{"found": false}}"""

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()

        # JSON bloğunu çıkar
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())

        if not data.get('found'):
            return None

        result = {}
        for key in ('name', 'website', 'email', 'reasoning'):
            val = data.get(key)
            if val and val != 'null':
                result[key] = val

        return result if (result.get('name') or result.get('website')) else None

    except Exception:
        return None


# ============================================================
# AGENCY API
# ============================================================

@app.route('/agency', methods=['POST'])
def agency_endpoint():
    body = request.get_json(silent=True) or {}

    # Frontend zaten scrape etmişse channel_data direkt gönderir
    channel_data = body.get('channel_data')
    if not channel_data:
        url = body.get('url', '').strip()
        if not url:
            return jsonify({'error': 'channel_data or url required'}), 400
        channel_data = scrape_channel(url)
        if 'error' in channel_data:
            return jsonify({'error': channel_data['error']}), 400

    result = find_agency(channel_data)
    return jsonify(result)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Duflat API başlatılıyor... http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
