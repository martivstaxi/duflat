"""
Duflat - YouTube Channel Investigator API
"""

import re
import os
import random
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
}

RE_EMAIL = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
EMAIL_BLACKLIST = {'example', 'test', 'noreply', 'google', 'gstatic', 'youtube', 'sentry', 'wix', 'squarespace'}
NAV_DOMAINS = ('developers.google.com','support.google.com','policies.google.com','accounts.google.com','gstatic.com','googleapis.com','ggpht.com','ytimg.com','googleusercontent.com')

RE_EMBED   = re.compile(r'youtube\.com/v/([a-zA-Z0-9_-]+)')
RE_CLEAN   = re.compile(r'/(about|videos|shorts|streams|playlists|community|channels|featured)/?$')

# About sayfası regex'leri
RE_COUNTRY    = re.compile(r'"country":\s*"([^"]+)"')
RE_JOINED     = re.compile(r'Joined\s+([A-Za-z]+\s+\d+,\s+\d{4})')
RE_JOINED_JSON = re.compile(r'"joinedDateText"[^}]{0,300}"content":\s*"Joined\s+([^"]+)"')
RE_VIEW_COUNT = re.compile(r'"viewCountText"[^}]{0,200}"simpleText":\s*"([\d,\.]+)')
RE_VIDEO_COUNT_PATTERNS = [
    re.compile(r'"videosCountText":\s*\{\s*"simpleText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videoCount":\s*"(\d+)"'),
    re.compile(r'"videoCount":\s*(\d+)'),
    re.compile(r'"aboutChannelViewModel"[^}]{0,800}"videoCountText":\s*"([\d,.\s]+)', re.I | re.DOTALL),
    re.compile(r'"videoCountText":\s*\{\s*"runs"[^}]{0,200}"text":\s*"([\d,.\s]+)"'),
    re.compile(r'"text":\s*"([\d,.\s]+)\s*videos?"', re.I),
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


def fetch_about_page(channel_url):
    """About sayfasından email, sosyal medya, konum, katılım tarihi, görüntülenme, video sayısı çek"""
    base = RE_CLEAN.sub('', channel_url.rstrip('/'))
    about_url = base + '/about'
    try:
        session = requests.Session()
        session.cookies.set('CONSENT', 'YES+cb', domain='.youtube.com')
        r = session.get(about_url, headers=BROWSER_HEADERS, timeout=15)
        if r.status_code != 200:
            return {}, [], '', '', '', '', ''
        ps = r.text
    except Exception:
        return {}, [], '', '', '', '', ''

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
            if u.startswith('http') and 'youtube.com' not in u_lower and not any(d in u_lower for d in NAV_DOMAINS):
                if u not in json_ext_links:
                    json_ext_links.append(u)

    for u in decoded:
        u = u.strip()
        if u.startswith('http') and 'youtube.com' not in u.lower() and not any(d in u.lower() for d in NAV_DOMAINS):
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

    # Konum
    location = ''
    m = RE_COUNTRY.search(ps)
    if m:
        location = m.group(1)

    # Katılım tarihi
    joined = ''
    m = RE_JOINED_JSON.search(ps)
    if m:
        joined = m.group(1).strip()
    if not joined:
        m = RE_JOINED.search(ps)
        if m:
            joined = m.group(1).strip()

    # Toplam görüntülenme
    views = ''
    m = RE_VIEW_COUNT.search(ps)
    if m:
        cs = m.group(1).replace(',', '').replace('.', '')
        if cs.isdigit() and int(cs) > 0:
            views = format(int(cs), ',')

    # Video sayısı
    video_count = extract_video_count(ps)

    return socials, json_ext_links[:15], email, location, joined, views, video_count


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
        if 'youtube.com' not in u.lower() and not any(d in u.lower() for d in NAV_DOMAINS):
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

def scrape_channel(url):
    url = normalize_url(url)
    if not url:
        return {'error': 'Geçersiz URL'}

    # İlk geçiş: tam meta veri (extract_flat yok), sadece ilk 1 videoyu işle
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'playlistend': 1,   # Sadece son videoyu al (tarih için), kanal meta verisinin tamamı gelir
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return {'error': str(e)[:200]}

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
    about_socials, about_links, about_email, about_location, about_joined, about_views, about_video_count = fetch_about_page(channel_url)
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
        'ignoreerrors': True,
        'playlistend': 1,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if not info:
        return jsonify({'error': 'Boş sonuç döndü'}), 500

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

@app.route('/debug-about', methods=['GET'])
def debug_about():
    """About sayfası requests çıktısını göster — konum/katılım/views/videos testi için"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parametresi gerekli'}), 400
    url = normalize_url(url)
    base = RE_CLEAN.sub('', url.rstrip('/'))
    about_url = base + '/about'
    try:
        session = requests.Session()
        session.cookies.set('CONSENT', 'YES+cb', domain='.youtube.com')
        r = session.get(about_url, headers=BROWSER_HEADERS, timeout=15)
        ps = r.text
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    socials, links, email, location, joined, views, video_count = fetch_about_page(url)
    return jsonify({
        'status_code': r.status_code,
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Duflat API başlatılıyor... http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
