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

    # Video URL'si geldiyse önce kanalı bul, sonra kanal sayfasını çek
    if info.get('extractor') == 'youtube' and info.get('channel_url') and info.get('_type') != 'playlist':
        channel_url_found = info.get('channel_url') or info.get('uploader_url')
        if channel_url_found:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url_found, download=False) or info
            except:
                pass

    # ---- Yapıyı düzelt: YouTube tab playlist içinde iç içe entries var ----
    # info.entries[0] = "Videos" tab (playlist), info.entries[0].entries[0] = gerçek video
    entries = info.get('entries') or []
    tab_entry = None   # İlk tab (Videos sekmesi)
    first_video = None # İlk gerçek video

    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get('_type') == 'playlist' or e.get('entries') is not None:
            tab_entry = e
            sub = e.get('entries') or []
            for v in sub:
                if isinstance(v, dict) and v.get('upload_date'):
                    first_video = v
                    break
            break
        elif e.get('upload_date'):
            first_video = e
            break

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

    # Abone sayısı: üst seviyede null olabiliyor, tab_entry'de de dene
    sub_count = (info.get('channel_follower_count')
                 or info.get('subscriber_count')
                 or (tab_entry.get('channel_follower_count') if tab_entry else None))
    subscribers = f"{sub_count:,}" if sub_count else ''

    views = info.get('view_count') or (tab_entry.get('view_count') if tab_entry else None)
    views = f"{views:,}" if views else ''

    # Video sayısı: tab_entry.playlist_count gerçek sayıyı tutar
    video_count = (
        (tab_entry.get('playlist_count') if tab_entry else None)
        or info.get('playlist_count')
        or info.get('video_count')
    )
    # Sadece tabs sayısıysa (2-3 gibi küçük değerler) gösterme
    video_count = str(video_count) if (video_count and int(video_count) > 3) else ''

    description = (info.get('description') or info.get('channel_description') or '')[:1000]

    thumbnail = info.get('thumbnail') or ''

    # ---- Sosyal + email ----
    combined_text = description
    for field in ('tags', 'categories'):
        val = info.get(field)
        if isinstance(val, list):
            combined_text += ' ' + ' '.join(str(v) for v in val)

    socials, all_links, email = extract_socials_from_text(combined_text)

    # Son video tarihi: iç içe yapıdan gerçek videoyu bul
    last_video_date = ''
    if first_video:
        d = first_video.get('upload_date') or ''
        if d and len(d) == 8 and d.isdigit():
            last_video_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"

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
    return jsonify(safe)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Duflat API başlatılıyor... http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
