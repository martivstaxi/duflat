"""
Duflat - YouTube Channel Investigator API
Çalıştır: python app.py
Aç: http://localhost:5000
"""

import re
import time
import json
import random
import threading
from urllib.parse import unquote, parse_qs, urlparse
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

app = Flask(__name__, static_folder='.')
CORS(app)

# ============================================================
# REGEX
# ============================================================

RE_SUBSCRIBER = re.compile(r'"subscriberCountText":\s*(?:\{\s*"simpleText":\s*"([^"]+)"|"([^"]+)")')
RE_HANDLE = re.compile(r'"vanityChannelUrl":\s*"https?://www\.youtube\.com/@([^"]+)"')
RE_COUNTRY = re.compile(r'"country":\s*"([^"]+)"')
RE_JOINED = re.compile(r'Joined\s+([A-Za-z]+\s+\d+,\s+\d{4})')
RE_VIEW_COUNT = re.compile(r'"viewCountText"[^}]*?"simpleText":\s*"([\d,\.]+)')
RE_REDIRECT = re.compile(r'https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"\s<>\\]+(?:\\[^"\s<>\\][^"\s<>\\]*)*')
RE_CLEAN_CHANNEL_SUFFIX = re.compile(r'/(about|videos|shorts|streams|playlists|community|channels|featured)/?$')
RE_EMBED = re.compile(r'youtube\.com/v/([a-zA-Z0-9_-]+)')

RE_VIDEO_COUNT_PATTERNS = [
    re.compile(r'"videosCountText":\s*\{\s*"simpleText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*"([\d,.\s]+)\s*video', re.I),
    re.compile(r'"videosCountText":\s*\{[^}]*"runs":\s*\[\s*\{\s*"text":\s*"([\d,.\s]+)"'),
    re.compile(r'"videoCount":\s*"(\d+)"'),
    re.compile(r'"videoCount":\s*(\d+)'),
]

RE_DESCRIPTION_PATTERNS = [
    re.compile(r'"description":\s*\{\s*"simpleText":\s*"([^"]{10,2000})"'),
    re.compile(r'"channelDescription":\s*"([^"]{10,2000})"'),
    re.compile(r'"description":\s*"([^"]{10,2000})"'),
]

RE_EMAIL_PATTERNS = [
    re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
    re.compile(r'"email":"([^"]+@[^"]+)"'),
    re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
]
EMAIL_BLACKLIST = {'example', 'test', 'noreply', 'google', 'gstatic', 'youtube'}

RE_CHANNEL_FROM_VIDEO = [
    re.compile(r'"ownerProfileUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"channelUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"canonicalBaseUrl"\s*:\s*"(/@[^"]+)"'),
    re.compile(r'"vanityChannelUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"channelUrl"\s*:\s*"(https://www\.youtube\.com/channel/[^"]+)"'),
    re.compile(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"'),
]

RE_JSON_LINKS = [
    re.compile(r'"channelExternalLinkViewModel"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"link"\s*:\s*\{[^}]*?"content"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"primaryLinkViewModel"(?:[^{}]|\{[^{}]*\})*?"url"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"url"\s*:\s*"(https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"]+)"'),
    re.compile(r'"linkUrl"\s*:\s*"(https?://[^"]+)"'),
]

RE_PUBLISHED_TIME = [
    re.compile(r'"publishedTimeText":\s*\{\s*"simpleText":\s*"([^"]+)"'),
    re.compile(r'"publishedTimeText":\s*"([^"]+)"'),
]

INVALID_USERNAMES = {
    'twitter': frozenset({'summary', 'intent', 'share', 'home', 'search', 'i', 'hashtag', 'player', 'widgets', 'settings', 'privacy', 'tos', 'about', 'explore', 'notifications', 'messages', 'login', 'signup', 'card', 'cards', 'summary_large_image'}),
    'instagram': frozenset({'p', 'reel', 'reels', 'stories', 'explore', 'direct', 'accounts', 'about', 'legal', 'privacy', 'terms', 'help', 'api', 'press', 'jobs', 'blog', 'developer', 'tv', 'igtv'}),
    'facebook': frozenset({'sharer', 'share', 'dialog', 'plugins', 'login', 'help', 'pages', 'groups', 'events', 'marketplace', 'gaming', 'watch', 'privacy', 'policies', 'ad_campaign', 'ads', 'business', 'tr'}),
    'twitch': frozenset({'directory', 'videos', 'clips', 'following', 'settings', 'subscriptions', 'inventory', 'drops', 'wallet', 'friends', 'messages', 'search', 'downloads', 'jobs', 'turbo', 'products', 'prime', 'partners'}),
}

SOCIAL_PLATFORMS = {
    'instagram': {'regex': re.compile(r'instagram\.com/([a-zA-Z0-9._]{2,30})', re.I), 'url_fmt': 'https://www.instagram.com/{}', 'validator': 'instagram', 'check': 'instagram.com/'},
    'tiktok':    {'regex': re.compile(r'tiktok\.com/@?([a-zA-Z0-9._]{2,30})', re.I), 'url_fmt': 'https://www.tiktok.com/@{}', 'validator': None, 'check': 'tiktok.com/'},
    'twitter':   {'regex': re.compile(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{2,15})', re.I), 'url_fmt': 'https://x.com/{}', 'validator': 'twitter', 'check': 'twitter.com/'},
    'facebook':  {'regex': re.compile(r'facebook\.com/([a-zA-Z0-9.]{2,50})', re.I), 'url_fmt': 'https://www.facebook.com/{}', 'validator': 'facebook', 'check': 'facebook.com/'},
    'discord':   {'regex': re.compile(r'discord\.(?:gg|com/invite)/([a-zA-Z0-9]{2,20})', re.I), 'url_fmt': 'https://discord.gg/{}', 'validator': None, 'check': 'discord.'},
    'twitch':    {'regex': re.compile(r'twitch\.tv/([a-zA-Z0-9_]{2,25})', re.I), 'url_fmt': 'https://twitch.tv/{}', 'validator': 'twitch', 'check': 'twitch.tv/'},
    'myanimelist': {'regex': re.compile(r'myanimelist\.net/profile/([a-zA-Z0-9_-]{2,30})', re.I), 'url_fmt': 'https://myanimelist.net/profile/{}', 'validator': None, 'check': 'myanimelist.net/'},
}

NAV_DOMAINS = ('developers.google.com', 'support.google.com', 'policies.google.com', 'accounts.google.com', 'play.google.com', 'fonts.googleapis.com', 'gstatic.com', 'googleapis.com', 'google.com/intl', 'ggpht.com', 'ytimg.com', 'googleusercontent.com')

# ============================================================
# DRIVER
# ============================================================

_driver_lock = threading.Lock()
_driver = None

def get_driver():
    global _driver
    if _driver is None:
        _driver = setup_driver()
    return _driver

def setup_driver():
    options = Options()
    options.add_argument('--headless=new')
    for arg in [
        '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage',
        '--disable-extensions', '--blink-settings=imagesEnabled=false',
        '--window-size=1280,720', '--disable-logging', '--log-level=3',
        '--disable-background-networking', '--disable-default-apps',
        '--disable-sync', '--mute-audio', '--no-first-run',
        '--disable-blink-features=AutomationControlled',
        '--disable-web-security', '--disable-notifications',
    ]:
        options.add_argument(arg)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    ua = random.choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    ])
    options.add_argument(f'--user-agent={ua}')
    prefs = {"profile.default_content_setting_values": {"notifications": 2, "images": 2, "media_stream": 2, "geolocation": 2, "javascript": 1}}
    options.add_experimental_option("prefs", prefs)
    options.page_load_strategy = 'eager'
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    })
    driver.set_page_load_timeout(15)
    driver.implicitly_wait(0)
    return driver

# ============================================================
# YARDIMCI
# ============================================================

def is_valid_username(username, platform):
    if not username or len(username) < 2 or '...' in username:
        return False
    inv = INVALID_USERNAMES.get(platform)
    return username.lower() not in inv if inv else True

def decode_redirect(url):
    if 'youtube.com/redirect' not in url and 'youtube.com\\/redirect' not in url:
        return url
    try:
        clean = url.replace('\\/', '/').replace('\\u0026', '&').replace('%5C/', '/')
        params = parse_qs(urlparse(clean).query)
        if 'q' in params:
            return unquote(params['q'][0])
    except:
        pass
    return url

def safe_get_page(driver, url):
    try:
        driver.get(url)
        return True
    except Exception as e:
        if "timeout" in str(e).lower():
            try:
                driver.execute_script("window.stop();")
                return True
            except:
                pass
        return False

def normalize_url(url):
    url = url.strip()
    if not url:
        return None, 'empty'
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
    if '/watch?' in url or 'youtu.be/' in url:
        return url, 'video'
    elif '/shorts/' in url:
        return url, 'shorts'
    elif '/live/' in url:
        return url, 'live'
    elif '/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url:
        return url, 'channel'
    return url, 'unknown'

# ============================================================
# ÇIKARMA
# ============================================================

def get_channel_url_from_video(driver, video_url):
    if not safe_get_page(driver, video_url):
        return None
    time.sleep(0.5)
    try:
        driver.execute_script("window.stop();")
    except:
        pass
    ps = driver.page_source
    for pat in RE_CHANNEL_FROM_VIDEO:
        m = pat.search(ps)
        if m:
            result = m.group(1)
            if result.startswith('/@'):
                return f'https://www.youtube.com{RE_CLEAN_CHANNEL_SUFFIX.sub("", result)}'
            elif result.startswith('UC'):
                return f'https://www.youtube.com/channel/{result}'
            return RE_CLEAN_CHANNEL_SUFFIX.sub('', result)
    return None

def extract_channel_info(driver, channel_url):
    data = {'channel_url': channel_url}

    # About sayfası
    about_url = RE_CLEAN_CHANNEL_SUFFIX.sub('', channel_url.rstrip('/')) + '/about'
    if not safe_get_page(driver, about_url):
        data['error'] = 'Sayfa yüklenemedi'
        return data

    time.sleep(1.0)
    try:
        driver.execute_script("window.stop();")
    except:
        pass

    ps = driver.page_source

    # Kanal adı
    try:
        title = driver.title
        if ' - ' in title:
            data['name'] = title.split(' - ')[1].strip()
        if not data.get('name'):
            el = driver.find_element(By.XPATH, "//meta[@property='og:title']")
            og = el.get_attribute('content')
            if og:
                data['name'] = og.strip()
    except:
        pass

    # Handle - URL'den
    try:
        cur = driver.current_url
        if '/@' in cur:
            data['handle'] = '@' + cur.split('/@')[1].split('/')[0]
    except:
        pass

    # Abone
    m = RE_SUBSCRIBER.search(ps)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            data['subscribers'] = val.replace(' subscribers', '').replace(' abone', '')

    # Handle regex fallback
    if not data.get('handle'):
        m = RE_HANDLE.search(ps)
        if m:
            data['handle'] = '@' + m.group(1)

    # Konum
    m = RE_COUNTRY.search(ps)
    if m:
        data['location'] = m.group(1)

    # Katılma
    m = RE_JOINED.search(ps)
    if m:
        data['joined'] = m.group(1)

    # Görüntülenme
    m = RE_VIEW_COUNT.search(ps)
    if m:
        cs = m.group(1).replace(',', '').replace('.', '')
        if cs.isdigit() and int(cs) > 0:
            data['views'] = format(int(cs), ',')

    # Açıklama
    for pat in RE_DESCRIPTION_PATTERNS:
        m = pat.search(ps)
        if m:
            desc = m.group(1)
            try:
                desc = re.sub(r'\\u([0-9a-fA-F]{4})', lambda x: chr(int(x.group(1), 16)), desc)
            except:
                pass
            desc = desc.replace('\\n', '\n').replace('\\r', '').replace('\\t', ' ')
            if len(desc) > 10:
                data['description'] = re.sub(r'\s+', ' ', desc[:500]).strip()
                break

    # Email
    for pat in RE_EMAIL_PATTERNS:
        emails = pat.findall(ps)
        for email in emails:
            if '@' in email and '.' in email.split('@')[1]:
                if not any(x in email.lower() for x in EMAIL_BLACKLIST):
                    data['email'] = email
                    break
        if 'email' in data:
            break

    # Redirect URL'leri çöz
    redirect_urls = RE_REDIRECT.findall(ps)
    decoded = [decode_redirect(u) for u in redirect_urls]
    combined = ps + ' ' + ' '.join(decoded)

    # JSON link çıkarma
    all_json_urls = []
    for pat in RE_JSON_LINKS:
        all_json_urls.extend(pat.findall(ps))

    json_ext_links = []
    for url in all_json_urls:
        url = url.replace('\\u0026', '&').replace('\\/', '/')
        if 'youtube.com/redirect' in url:
            url = decode_redirect(url)
        url = url.strip()
        url_lower = url.lower()
        for key, info in SOCIAL_PLATFORMS.items():
            if key not in data and info['check'] in url_lower:
                m = info['regex'].search(url)
                if m:
                    uname = m.group(1)
                    v = info.get('validator')
                    if (v is None or is_valid_username(uname, v)) and len(uname) > 1:
                        data[key] = info['url_fmt'].format(uname)
                        break
        if url.startswith('http') and 'youtube.com' not in url_lower and not any(d in url_lower for d in NAV_DOMAINS) and url not in json_ext_links:
            json_ext_links.append(url)

    for rurl in decoded:
        rurl = rurl.strip()
        rurl_lower = rurl.lower()
        if rurl.startswith('http') and 'youtube.com' not in rurl_lower and not any(d in rurl_lower for d in NAV_DOMAINS) and rurl not in json_ext_links:
            json_ext_links.append(rurl)

    if json_ext_links:
        data['all_links'] = json_ext_links[:20]

    # Sosyal medya fallback
    for key, info in SOCIAL_PLATFORMS.items():
        if key not in data:
            matches = info['regex'].findall(combined)
            for uname in matches:
                v = info.get('validator')
                if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                    data[key] = info['url_fmt'].format(uname)
                    break

    # DOM linkler
    try:
        all_hrefs = driver.execute_script("""
            var links = document.querySelectorAll('a[href]');
            var result = [];
            for(var i=0; i < links.length; i++) {
                var h = links[i].href;
                if(h && h.indexOf('youtube.com') === -1) result.push(h);
                else if(h && h.indexOf('redirect') !== -1) result.push(h);
            }
            return result;
        """)
        if all_hrefs:
            existing = set(data.get('all_links', []))
            for href in all_hrefs:
                if 'youtube.com/redirect' in href:
                    href = decode_redirect(href)
                href_lower = href.lower()
                if any(d in href_lower for d in NAV_DOMAINS):
                    continue
                for key, info in SOCIAL_PLATFORMS.items():
                    if key not in data and info['check'] in href_lower:
                        m = info['regex'].search(href)
                        if m:
                            uname = m.group(1)
                            v = info.get('validator')
                            if (v is None or is_valid_username(uname, v)) and len(uname) > 1:
                                data[key] = info['url_fmt'].format(uname)
                                break
                if 'http' in href and 'youtube.com' not in href_lower and href not in existing:
                    existing.add(href)
            if existing:
                data['all_links'] = list(existing)[:20]
    except:
        pass

    # Videos sayfası - son video + video sayısı
    try:
        videos_url = RE_CLEAN_CHANNEL_SUFFIX.sub('', channel_url.rstrip('/')) + '/videos'
        if safe_get_page(driver, videos_url):
            time.sleep(1.5)
            try:
                driver.execute_script("window.stop();")
            except:
                pass
            vps = driver.page_source
            for pat in RE_PUBLISHED_TIME:
                matches = pat.findall(vps)
                if matches:
                    data['last_video_date'] = matches[0]
                    break
            for pat in RE_VIDEO_COUNT_PATTERNS:
                m = pat.search(vps)
                if m:
                    for g in m.groups():
                        if g:
                            cs = g.strip().replace(',', '').replace('.', '').replace(' ', '')
                            if cs.isdigit() and 0 < int(cs) < 10_000_000:
                                data['videos'] = cs
                                break
                if data.get('videos'):
                    break
    except:
        pass

    return data

# ============================================================
# API ENDPOINT
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

    normalized_url, url_type = normalize_url(url)
    if normalized_url is None:
        return jsonify({'error': 'Geçersiz URL'}), 400

    with _driver_lock:
        driver = get_driver()
        try:
            channel_url = normalized_url
            if url_type in ('video', 'shorts', 'live'):
                found = get_channel_url_from_video(driver, normalized_url)
                if found:
                    channel_url = found
                else:
                    return jsonify({'error': 'Videodan kanal bulunamadı'}), 404

            data = extract_channel_info(driver, channel_url)
            return jsonify(data)
        except Exception as e:
            # Driver hata verdiyse yeniden oluştur
            global _driver
            try:
                driver.quit()
            except:
                pass
            _driver = None
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Duflat API başlatılıyor... port={port}")
    app.run(host='0.0.0.0', port=port, debug=False)
