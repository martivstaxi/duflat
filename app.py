"""
Duflat - YouTube Channel Investigator API
"""

import re
import os
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

    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,          # Playlist içeriğini indirme, sadece meta
        'playlist_items': '0',         # Video listesini getirme
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return {'error': str(e)[:200]}

    if not info:
        return {'error': 'Kanal bilgisi alınamadı'}

    # Video URL'si gelirse channel_url'ye yönlendir
    if info.get('_type') == 'url' or (info.get('extractor') == 'youtube' and 'entries' not in info and info.get('channel_url')):
        channel_url = info.get('channel_url') or info.get('uploader_url')
        if channel_url:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False) or info
            except:
                pass

    # ---- Temel alanlar ----
    name = info.get('uploader') or info.get('channel') or info.get('title') or ''
    handle_raw = info.get('uploader_id') or info.get('channel_id') or ''
    handle = ('@' + handle_raw.lstrip('@')) if handle_raw and not handle_raw.startswith('UC') else ''

    channel_url = (
        info.get('channel_url')
        or info.get('uploader_url')
        or info.get('webpage_url')
        or url
    )
    channel_url = RE_CLEAN.sub('', channel_url.rstrip('/'))

    subscribers = info.get('channel_follower_count') or info.get('subscriber_count')
    if subscribers:
        subscribers = f"{subscribers:,}"

    views = info.get('view_count')
    if views:
        views = f"{views:,}"

    video_count = info.get('playlist_count') or info.get('video_count') or ''
    if video_count:
        video_count = str(video_count)

    description = (info.get('description') or '')[:600]

    # Thumbnail → avatar için ilk harf yeterli, ama thumbnail URL'ini de verelim
    thumbnail = info.get('thumbnail') or ''

    # ---- Sosyal + email ----
    # yt-dlp bazen channel_url'nin tags'larında ya da description'da verir
    combined_text = description

    # yt-dlp'nin tags, categories, availability alanlarını da tara
    for field in ('tags', 'categories'):
        val = info.get(field)
        if isinstance(val, list):
            combined_text += ' ' + ' '.join(str(v) for v in val)

    socials, all_links, email = extract_socials_from_text(combined_text)

    # yt-dlp bazen 'entries' içindeki ilk videonun upload_date'ini verir
    last_video_date = ''
    entries = info.get('entries') or []
    if entries:
        first = entries[0] if isinstance(entries[0], dict) else {}
        last_video_date = first.get('upload_date') or first.get('timestamp') or ''
        if last_video_date and len(last_video_date) == 8:
            last_video_date = f"{last_video_date[:4]}-{last_video_date[4:6]}-{last_video_date[6:]}"

    data = {
        'channel_url': channel_url,
        'name': name,
        'handle': handle,
        'subscribers': subscribers or '',
        'views': views or '',
        'videos': video_count,
        'description': description,
        'email': email,
        'location': info.get('location') or '',
        'joined': '',
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Duflat API başlatılıyor... http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
