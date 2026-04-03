import csv
import re
import os
import time
import json
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from tkinter import Tk, filedialog
from urllib.parse import unquote, parse_qs, urlparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

# ============================================================
# AYARLAR
# ============================================================

DOWNLOADS_FOLDER = str(Path.home() / "Downloads")

OUTPUT_FILE = os.path.join(
    DOWNLOADS_FOLDER,
    f"youtube_channels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
)

# Tarayıcı yenileme aralığı - artırıldı (daha az restart = daha hızlı)
BROWSER_RESTART_INTERVAL = 100

# Bekleme süreleri
PAGE_LOAD_TIMEOUT = 10
IMPLICIT_WAIT = 0

# Paralel tarayıcı sayısı (1 = sıralı, 2-4 = paralel)
PARALLEL_BROWSERS = 3

# Thread-safe
write_lock = threading.Lock()
counter_lock = threading.Lock()
processed_counter = {'count': 0, 'success': 0, 'error': 0}

stats = {
    'total_emails': 0,    'total_instagram': 0, 'total_tiktok': 0,
    'total_twitter': 0,   'total_discord': 0,   'total_facebook': 0,
    'total_twitch': 0,    'total_mal': 0,        'total_last_video': 0,
}
stats_lock = threading.Lock()

# ============================================================
# ÖN-DERLENMİŞ REGEX PATTERN'LERİ
# ============================================================

# Kanal bilgileri
RE_SUBSCRIBER = re.compile(r'"subscriberCountText":\s*(?:\{\s*"simpleText":\s*"([^"]+)"|"([^"]+)")')
RE_HANDLE = re.compile(r'"vanityChannelUrl":\s*"https?://www\.youtube\.com/@([^"]+)"')
RE_COUNTRY = re.compile(r'"country":\s*"([^"]+)"')
RE_JOINED = re.compile(r'Joined\s+([A-Za-z]+\s+\d+,\s+\d{4})')
RE_VIEW_COUNT = re.compile(r'"viewCountText"[^}]*?"simpleText":\s*"([\d,\.]+)')

# Video sayısı - TÜM PATTERN'LER (JSON + HTML + metin)
RE_VIDEO_COUNT_PATTERNS = [
    # JSON - simpleText wraplı
    re.compile(r'"videosCountText":\s*\{\s*"simpleText":\s*"([\d,.\s]+)\s*video', re.I),
    # JSON - doğrudan string
    re.compile(r'"videosCountText":\s*"([\d,.\s]+)\s*video', re.I),
    # JSON - runs array
    re.compile(r'"videosCountText":\s*\{[^}]*"runs":\s*\[\s*\{\s*"text":\s*"([\d,.\s]+)"'),
    # videoCount string
    re.compile(r'"videoCount":\s*"(\d+)"'),
    # videoCount number
    re.compile(r'"videoCount":\s*(\d+)'),
    # videosText
    re.compile(r'"videosText":\s*(?:"([\d,.\s]+)"|\{[^}]*"simpleText":\s*"([\d,.\s]+))', re.I),
    # videoCountText
    re.compile(r'"videoCountText":\s*\{[^}]*"simpleText":\s*"([\d,.\s]+)', re.I),
    # aboutChannelViewModel
    re.compile(r'"aboutChannelViewModel"[^}]*"videoCountText":\s*"([\d,.\s]+)', re.I),
    # HTML pattern'leri
    re.compile(r'([\d,.\s]+)\s*videos?\s*</span>', re.I),
    re.compile(r'>([\d,.\s]+)\s*videos?<', re.I),
    re.compile(r'"text":\s*"([\d,.\s]+)\s*videos?"', re.I),
    re.compile(r'([\d,.\s]+)\s*video\s*</span>', re.I),
    # Tab header: "Videos\t123" veya "Videos  123" formatı
    re.compile(r'"title":\s*"Videos"[^}]*"count":\s*"?([\d,]+)"?', re.I),
]

# Body text regex (driver fallback)
RE_VIDEO_COUNT_BODY = [
    re.compile(r'([\d,]+)\s+videos?\b', re.I),
]

# Son video tarihi
RE_PUBLISHED_TIME = [
    re.compile(r'"publishedTimeText":\s*\{\s*"simpleText":\s*"([^"]+)"'),
    re.compile(r'"publishedTimeText":\s*"([^"]+)"'),
]

# Açıklama
RE_DESCRIPTION_PATTERNS = [
    re.compile(r'"description":\s*\{\s*"simpleText":\s*"([^"]{10,2000})"'),
    re.compile(r'"channelDescription":\s*"([^"]{10,2000})"'),
    re.compile(r'"description":\s*"([^"]{10,2000})"'),
    re.compile(r'"descriptionBodyText":\s*"([^"]{10,2000})"'),
]

# Email
RE_EMAIL_PATTERNS = [
    re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
    re.compile(r'"email":"([^"]+@[^"]+)"'),
    re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
]
EMAIL_BLACKLIST = {'example', 'test', 'noreply', 'google', 'gstatic', 'youtube'}

# Redirect URL'leri
RE_REDIRECT = re.compile(r'https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"\s<>\\]+(?:\\[^"\s<>\\][^"\s<>\\]*)*')

# Kanal bulma (video sayfasından)
RE_CHANNEL_FROM_VIDEO = [
    re.compile(r'"ownerProfileUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"channelUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"canonicalBaseUrl"\s*:\s*"(/@[^"]+)"'),
    re.compile(r'"vanityChannelUrl"\s*:\s*"(https://www\.youtube\.com/@[^"]+)"'),
    re.compile(r'"channelUrl"\s*:\s*"(https://www\.youtube\.com/channel/[^"]+)"'),
    re.compile(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"'),
]

# JSON link çıkarma
RE_JSON_LINKS = [
    re.compile(r'"channelExternalLinkViewModel"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"link"\s*:\s*\{[^}]*?"content"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"primaryLinkViewModel"(?:[^{}]|\{[^{}]*\})*?"url"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"url"\s*:\s*"(https?://(?:www\.)?youtube\.com(?:/|\\/)redirect\?[^"]+)"'),
    re.compile(r'"linkUrl"\s*:\s*"(https?://[^"]+)"'),
    re.compile(r'"headerLinks"[^\]]*?"url"\s*:\s*"(https?://[^"]+)"'),
]

RE_CLEAN_CHANNEL_SUFFIX = re.compile(r'/(about|videos|shorts|streams|playlists|community|channels|featured)/?$')
RE_EMBED = re.compile(r'youtube\.com/v/([a-zA-Z0-9_-]+)')

NAV_DOMAINS = (
    'developers.google.com', 'support.google.com', 'policies.google.com',
    'accounts.google.com', 'play.google.com', 'fonts.googleapis.com',
    'gstatic.com', 'googleapis.com', 'google.com/intl', 'ggpht.com',
    'ytimg.com', 'googleusercontent.com',
)

# ============================================================
# SOSYAL MEDYA FİLTRELERİ
# ============================================================

INVALID_USERNAMES = {
    'twitter': frozenset({
        'summary', 'intent', 'share', 'home', 'search', 'i', 'hashtag',
        'player', 'widgets', 'settings', 'privacy', 'tos', 'about',
        'explore', 'notifications', 'messages', 'login', 'signup',
        'card', 'cards', 'summary_large_image'
    }),
    'instagram': frozenset({
        'p', 'reel', 'reels', 'stories', 'explore', 'direct', 'accounts',
        'about', 'legal', 'privacy', 'terms', 'help', 'api', 'press',
        'jobs', 'blog', 'developer', 'tv', 'igtv'
    }),
    'facebook': frozenset({
        'sharer', 'share', 'dialog', 'plugins', 'login', 'help', 'pages',
        'groups', 'events', 'marketplace', 'gaming', 'watch', 'privacy',
        'policies', 'ad_campaign', 'ads', 'business', 'tr'
    }),
    'myanimelist': frozenset({
        'profile', 'login', 'register', 'about', 'news', 'featured',
        'forum', 'clubs', 'blog', 'reviews', 'recommendations', 'anime',
        'manga', 'character', 'people', 'top', 'search'
    }),
    'twitch': frozenset({
        'directory', 'videos', 'clips', 'following', 'settings', 'subscriptions',
        'inventory', 'drops', 'wallet', 'friends', 'messages', 'search',
        'downloads', 'jobs', 'turbo', 'products', 'prime', 'partners'
    }),
}

SOCIAL_PLATFORMS = {
    'instagram': {
        'regex': re.compile(r'instagram\.com/([a-zA-Z0-9._]{2,30})', re.I),
        'url_fmt': 'https://www.instagram.com/{}',
        'validator': 'instagram',
        'check': 'instagram.com/',
    },
    'tiktok': {
        'regex': re.compile(r'tiktok\.com/@?([a-zA-Z0-9._]{2,30})', re.I),
        'url_fmt': 'https://www.tiktok.com/@{}',
        'validator': None,
        'check': 'tiktok.com/',
    },
    'twitter': {
        'regex': re.compile(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{2,15})', re.I),
        'url_fmt': 'https://x.com/{}',
        'validator': 'twitter',
        'check': 'twitter.com/',
    },
    'facebook': {
        'regex': re.compile(r'facebook\.com/([a-zA-Z0-9.]{2,50})', re.I),
        'url_fmt': 'https://www.facebook.com/{}',
        'validator': 'facebook',
        'check': 'facebook.com/',
    },
    'discord': {
        'regex': re.compile(r'discord\.(?:gg|com/invite)/([a-zA-Z0-9]{2,20})', re.I),
        'url_fmt': 'https://discord.gg/{}',
        'validator': None,
        'check': 'discord.',
    },
    'myanimelist': {
        'regex': re.compile(r'myanimelist\.net/profile/([a-zA-Z0-9_-]{2,30})', re.I),
        'url_fmt': 'https://myanimelist.net/profile/{}',
        'validator': 'myanimelist',
        'check': 'myanimelist.net/',
    },
    'twitch': {
        'regex': re.compile(r'twitch\.tv/([a-zA-Z0-9_]{2,25})', re.I),
        'url_fmt': 'https://twitch.tv/{}',
        'validator': 'twitch',
        'check': 'twitch.tv/',
    },
}

SOCIAL_KEYS = list(SOCIAL_PLATFORMS.keys())
ALL_FIELDS = [
    'name', 'handle', 'subscribers', 'videos', 'views', 'last_video_date',
    'description', 'email', 'location', 'joined',
    'instagram', 'tiktok', 'twitter', 'facebook', 'discord',
    'twitch', 'myanimelist', 'all_links'
]
EMPTY_DATA = {k: '' for k in ALL_FIELDS}


# ============================================================
# DRIVER
# ============================================================

def setup_driver():
    """Chrome driver - Maksimum hız"""
    options = Options()
    options.add_argument('--headless=new')

    for arg in [
        '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage',
        '--disable-extensions', '--blink-settings=imagesEnabled=false',
        '--window-size=1280,720', '--disable-logging', '--log-level=3',
        '--disable-software-rasterizer', '--disable-background-networking',
        '--disable-default-apps', '--disable-sync', '--disable-translate',
        '--mute-audio', '--no-first-run', '--disable-features=TranslateUI',
        '--disable-ipc-flooding-protection', '--disable-renderer-backgrounding',
        '--disable-backgrounding-occluded-windows',
        '--disable-client-side-phishing-detection', '--disable-hang-monitor',
        '--disable-popup-blocking', '--disable-prompt-on-repost',
        '--disable-domain-reliability', '--disable-component-update',
        '--dns-prefetch-disable', '--no-pings',
        '--disable-blink-features=AutomationControlled',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-site-isolation-trials',
        '--disable-reading-from-canvas',
        '--aggressive-cache-discard',
        '--disable-notifications',
    ]:
        options.add_argument(arg)

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    ua = random.choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ])
    options.add_argument(f'--user-agent={ua}')

    prefs = {
        "profile.default_content_setting_values": {
            "notifications": 2, "images": 2, "media_stream": 2,
            "geolocation": 2, "javascript": 1,
        },
        "profile.managed_default_content_settings": {"images": 2},
        "disk-cache-size": 1,
    }
    options.add_experimental_option("prefs", prefs)

    options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        '''
    })

    driver.execute_cdp_cmd('Network.enable', {})
    driver.execute_cdp_cmd('Network.setBlockedURLs', {
        'urls': [
            '*.png', '*.jpg', '*.jpeg', '*.gif', '*.svg', '*.webp', '*.ico',
            '*.woff', '*.woff2', '*.ttf', '*.eot',
            '*google-analytics*', '*googletagmanager*', '*doubleclick*',
            '*googlesyndication*', '*googleadservices*',
            '*youtubei/v1/log*',
            '*play.google.com*',
        ]
    })

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.implicitly_wait(IMPLICIT_WAIT)
    return driver


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def create_output_file():
    os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        csv.writer(f).writerow([
            'Tarih/Saat', 'Kanal URL', 'Kanal Adı', 'Handle',
            'Abone Sayısı', 'Video Sayısı', 'Görüntülenme',
            'Son Video Tarihi', 'Açıklama', 'Email', 'Konum',
            'Katılma Tarihi', 'Instagram', 'TikTok', 'Twitter/X',
            'Facebook', 'Discord', 'Twitch', 'MyAnimeList',
            'Tüm Linkler', 'Durum'
        ])
    print(f"\n📁 Çıktı dosyası: {OUTPUT_FILE}")
    print(f"📂 Klasör: {DOWNLOADS_FOLDER}\n")


def save_result(data):
    with write_lock:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow([
                ts, data.get('url', ''), data.get('name', ''),
                data.get('handle', ''), data.get('subscribers', ''),
                data.get('videos', ''), data.get('views', ''),
                data.get('last_video_date', ''), data.get('description', ''),
                data.get('email', ''), data.get('location', ''),
                data.get('joined', ''), data.get('instagram', ''),
                data.get('tiktok', ''), data.get('twitter', ''),
                data.get('facebook', ''), data.get('discord', ''),
                data.get('twitch', ''), data.get('myanimelist', ''),
                data.get('all_links', ''), data.get('status', '')
            ])


def is_valid_username(username, platform):
    if not username or len(username) < 2 or '...' in username:
        return False
    inv = INVALID_USERNAMES.get(platform)
    return username.lower() not in inv if inv else True


def decode_redirect(url):
    if 'youtube.com/redirect' not in url and 'youtube.com\\/redirect' not in url and 'youtube.com\/redirect' not in url:
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

    url = url.replace('m.youtube.com', 'www.youtube.com').replace('mobile.youtube.com', 'www.youtube.com')

    m = RE_EMBED.search(url)
    if m:
        url = f'https://www.youtube.com/watch?v={m.group(1)}'

    if not url.startswith(('http://', 'https://')):
        if url.startswith('@'):
            url = f'https://www.youtube.com/{url}'
        elif url.startswith(('youtube.com', 'www.youtube.com')):
            url = f'https://{url}'
        elif 'UC' in url and len(url) == 24:
            url = f'https://www.youtube.com/channel/{url}'
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
# VİDEO SAYISI ÇIKARMA - ÇOK KATMANLI
# ============================================================

def _parse_video_count(val):
    """Sayı string'ini temizle ve doğrula"""
    if not val:
        return ''
    cs = val.strip().replace(',', '').replace('.', '').replace(' ', '').replace('\xa0', '')
    if cs.isdigit() and 0 < int(cs) < 10_000_000:
        return cs
    return ''


def extract_video_count_from_source(page_source, driver=None):
    """Video sayısını çıkar - 4 katmanlı arama"""

    # KATMAN 1: Regex pattern'lerinden (JSON + HTML)
    for pat in RE_VIDEO_COUNT_PATTERNS:
        m = pat.search(page_source)
        if m:
            for g in m.groups():
                result = _parse_video_count(g)
                if result:
                    return result

    # KATMAN 2: JavaScript ile ytInitialData'dan doğrudan çek
    if driver:
        try:
            js_result = driver.execute_script("""
                try {
                    // ytInitialData global objesi - YouTube'un tüm sayfa verisini tutar
                    var data = window.ytInitialData;
                    if (!data) return null;

                    // Yol 1: header -> videosCountText
                    var header = data.header;
                    if (header) {
                        var ch = header.c4TabbedHeaderRenderer || header.pageHeaderRenderer;
                        if (ch) {
                            // c4TabbedHeaderRenderer yolu
                            var vct = ch.videosCountText;
                            if (vct) {
                                var txt = vct.simpleText || (vct.runs && vct.runs.map(r => r.text).join(''));
                                if (txt) return txt;
                            }
                        }
                    }

                    // Yol 2: tabs içinden Videos tab'ının count'u
                    var tabs = null;
                    try {
                        tabs = data.contents.twoColumnBrowseResultsRenderer.tabs;
                    } catch(e) {}
                    if (tabs) {
                        for (var i = 0; i < tabs.length; i++) {
                            var tab = tabs[i].tabRenderer;
                            if (tab && tab.title && tab.title.toLowerCase().indexOf('video') !== -1) {
                                // Tab content'inden video sayısı
                                if (tab.content) {
                                    var section = tab.content.richGridRenderer || tab.content.sectionListRenderer;
                                    if (section) {
                                        // richGridRenderer header'ında bazen video count var
                                        var hdr = section.header;
                                        if (hdr && hdr.feedFilterChipBarRenderer) {
                                            // chip count
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Yol 3: metadata -> videoCountText veya videoCount
                    var metadata = data.metadata;
                    if (metadata) {
                        var cr = metadata.channelMetadataRenderer;
                        if (cr) {
                            if (cr.videoCount) return cr.videoCount;
                        }
                    }

                    // Yol 4: microformat
                    var micro = data.microformat;
                    if (micro) {
                        var mcr = micro.microformatDataRenderer;
                        if (mcr && mcr.videoCount) return mcr.videoCount;
                    }

                    // Yol 5: aboutChannelViewModel
                    var str = JSON.stringify(data);
                    var match = str.match(/"videoCountText"\\s*:\\s*"([^"]+)"/);
                    if (match) return match[1];
                    match = str.match(/"videoCount"\\s*:\\s*"?(\\d+)"?/);
                    if (match) return match[1];

                    return null;
                } catch(e) {
                    return null;
                }
            """)
            if js_result:
                result = _parse_video_count(str(js_result).split(' ')[0])
                if result:
                    return result
        except:
            pass

    # KATMAN 3: Body text'ten
    if driver:
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            for pat in RE_VIDEO_COUNT_BODY:
                matches = pat.findall(body_text)
                for m in matches:
                    result = _parse_video_count(m)
                    if result:
                        return result
        except:
            pass

    return ''


# ============================================================
# VIDEO → KANAL URL
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


# ============================================================
# TEK-GEÇİŞ BİLGİ ÇIKARMA
# ============================================================

def extract_all_from_source(page_source, driver=None):
    """Tek page_source'dan TÜM bilgileri çıkar. driver: video sayısı fallback için."""
    data = {}

    # Redirect URL'leri çöz
    redirect_urls = RE_REDIRECT.findall(page_source)
    decoded = [decode_redirect(u) for u in redirect_urls]
    combined = page_source + ' ' + ' '.join(decoded)

    # Abone
    m = RE_SUBSCRIBER.search(page_source)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            data['subscribers'] = val.replace(' subscribers', '').replace(' abone', '')

    # Handle
    m = RE_HANDLE.search(page_source)
    if m:
        data['handle'] = '@' + m.group(1)

    # Konum
    m = RE_COUNTRY.search(page_source)
    if m:
        data['location'] = m.group(1)

    # Katılma
    m = RE_JOINED.search(page_source)
    if m:
        data['joined'] = m.group(1)

    # Görüntülenme
    m = RE_VIEW_COUNT.search(page_source)
    if m:
        cs = m.group(1).replace(',', '').replace('.', '')
        if cs.isdigit() and int(cs) > 0:
            data['views'] = format(int(cs), ',')

    # Video sayısı - çok katmanlı
    video_count = extract_video_count_from_source(page_source, driver)
    if video_count:
        data['videos'] = video_count

    # Açıklama
    for pat in RE_DESCRIPTION_PATTERNS:
        m = pat.search(page_source)
        if m:
            desc = m.group(1)
            try:
                desc = json.loads('"' + desc.replace('"', '\\"') + '"')
            except Exception:
                try:
                    desc = re.sub(
                        r'\\u([0-9a-fA-F]{4})',
                        lambda x: chr(int(x.group(1), 16)),
                        desc
                    )
                except Exception:
                    pass
            desc = desc.replace('\\n', '\n').replace('\\r', '').replace('\\t', ' ')
            if len(desc) > 10:
                data['description'] = re.sub(r'\s+', ' ', desc[:500]).strip()
                break

    # Email
    for pat in RE_EMAIL_PATTERNS:
        emails = pat.findall(page_source)
        for email in emails:
            if '@' in email and '.' in email.split('@')[1]:
                if not any(x in email.lower() for x in EMAIL_BLACKLIST):
                    data['email'] = email
                    with stats_lock:
                        stats['total_emails'] += 1
                    break
        if 'email' in data:
            break

    # Sosyal medya: JSON linklerinden
    all_json_urls = []
    for pat in RE_JSON_LINKS:
        all_json_urls.extend(pat.findall(page_source))

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

        if (url.startswith('http') and 'youtube.com' not in url_lower
                and not any(d in url_lower for d in NAV_DOMAINS)
                and url not in json_ext_links):
            json_ext_links.append(url)

    for rurl in decoded:
        rurl = rurl.strip()
        rurl_lower = rurl.lower()
        if (rurl.startswith('http') and 'youtube.com' not in rurl_lower
                and not any(d in rurl_lower for d in NAV_DOMAINS)
                and rurl not in json_ext_links):
            json_ext_links.append(rurl)

    if json_ext_links:
        data['all_links'] = ' | '.join(json_ext_links[:20])

    # Sosyal medya: combined source'dan
    for key, info in SOCIAL_PLATFORMS.items():
        if key not in data:
            matches = info['regex'].findall(combined)
            for uname in matches:
                v = info.get('validator')
                if (v is None or is_valid_username(uname, v)) and len(uname) > 1 and '...' not in uname:
                    data[key] = info['url_fmt'].format(uname)
                    stat_key = f'total_{key}'
                    if stat_key in stats:
                        with stats_lock:
                            stats[stat_key] += 1
                    break

    # Son video tarihi (about sayfasında bazen var)
    for pat in RE_PUBLISHED_TIME:
        matches = pat.findall(page_source)
        if matches:
            data['last_video_date'] = matches[0]
            break

    return data


def extract_last_video_from_videos_page(driver, channel_base_url):
    """Son video tarihini ve video sayısını /videos sayfasından al"""
    try:
        videos_url = RE_CLEAN_CHANNEL_SUFFIX.sub('', channel_base_url.rstrip('/')) + '/videos'

        if not safe_get_page(driver, videos_url):
            return '', ''

        # ÖNEMLİ: Bekleme süresi artırıldı - YouTube JS'in render etmesi için zaman ver
        time.sleep(1.5)
        try:
            driver.execute_script("window.stop();")
        except:
            pass

        ps = driver.page_source

        # Son video tarihi
        last_video = ''
        for pat in RE_PUBLISHED_TIME:
            matches = pat.findall(ps)
            if matches:
                last_video = matches[0]
                with stats_lock:
                    stats['total_last_video'] += 1
                break

        if not last_video:
            if 'This channel has no videos' in ps or 'Bu kanalda video yok' in ps:
                last_video = 'Video yok'

        # Video sayısı - driver ile birlikte (JS fallback aktif)
        video_count = extract_video_count_from_source(ps, driver)

        return last_video, video_count

    except:
        return '', ''


# ============================================================
# ANA İŞLEME
# ============================================================

def extract_channel_info(driver, url):
    """Kanal bilgilerini çıkar - about + videos (gerekirse)"""
    data = {'url': url}

    try:
        try:
            driver.execute_script("window.stop();")
        except:
            pass

        page_source = driver.page_source

        # Kanal adı
        try:
            title = driver.title
            if ' - ' in title:
                parts = title.split(' - ')
                if len(parts) >= 2:
                    data['name'] = parts[1].strip()
            if not data.get('name'):
                try:
                    el = driver.find_element(By.XPATH, "//meta[@property='og:title']")
                    og = el.get_attribute('content')
                    if og:
                        data['name'] = og.strip()
                except:
                    pass
        except:
            pass

        # Handle - URL'den
        try:
            cur = driver.current_url
            if '/@' in cur:
                data['handle'] = '@' + cur.split('/@')[1].split('/')[0]
        except:
            pass

        # TEK GEÇİŞ: page source + driver
        extracted = extract_all_from_source(page_source, driver)

        # Handle regex fallback
        if 'handle' not in data and 'handle' in extracted:
            data['handle'] = extracted['handle']
        extracted.pop('handle', None)

        data.update({k: v for k, v in extracted.items() if k not in data or not data[k]})

        # Açıklama fallback: og:description
        if not data.get('description'):
            try:
                el = driver.find_element(By.XPATH, "//meta[@property='og:description']")
                og_desc = el.get_attribute('content')
                if og_desc and len(og_desc) > 20:
                    if not re.match(r'^[\d.,]+[KMB]?\s*(subscribers?|abone)', og_desc, re.I):
                        data['description'] = og_desc[:500]
            except:
                pass

        # DOM'daki harici linkler - JavaScript ile toplu
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
                existing = set(data.get('all_links', '').split(' | ')) if data.get('all_links') else set()
                dom_links = []
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
                        dom_links.append(href)

                if dom_links:
                    all_combined = list(existing - {''}) + dom_links
                    seen = []
                    for lnk in all_combined:
                        if lnk not in seen:
                            seen.append(lnk)
                    data['all_links'] = ' | '.join(seen[:20])
        except:
            pass

        # /videos sayfası: son video tarihi VEYA video sayısı eksikse
        needs_videos_page = not data.get('last_video_date') or not data.get('videos')
        if needs_videos_page:
            last_vid, vid_count = extract_last_video_from_videos_page(driver, url)
            if last_vid and not data.get('last_video_date'):
                data['last_video_date'] = last_vid
            if vid_count and not data.get('videos'):
                data['videos'] = vid_count

        # Hâlâ video sayısı bulunamadıysa: ana kanal sayfasından dene
        if not data.get('videos'):
            try:
                main_url = RE_CLEAN_CHANNEL_SUFFIX.sub('', url.rstrip('/'))
                if not safe_get_page(driver, main_url):
                    pass
                else:
                    time.sleep(1.0)
                    try:
                        driver.execute_script("window.stop();")
                    except:
                        pass
                    main_ps = driver.page_source
                    vid_count = extract_video_count_from_source(main_ps, driver)
                    if vid_count:
                        data['videos'] = vid_count
            except:
                pass

        # Varsayılan değerler
        for key in ALL_FIELDS:
            if not data.get(key):
                data[key] = ''

        # Durum
        found = sum(1 for k in ALL_FIELDS if data.get(k, '') != '')
        data['status'] = f'✓ {found}/{len(ALL_FIELDS)} bilgi bulundu'

        # Konsol
        name_d = data['name'][:30] if data['name'] else 'İsimsiz'
        subs_d = data['subscribers'] or '-'
        email_i = "📧" if data['email'] else ""
        vids_d = data['videos'] or '-'
        last_v = data['last_video_date'][:25] if data['last_video_date'] else '-'
        socials = [s for s, k in [('IG','instagram'),('X','twitter'),('TT','tiktok'),('DC','discord')] if data[k]]
        print(f"   ✓ {name_d} | {subs_d} {email_i} | 🎬 {vids_d} video | {', '.join(socials) or '-'} | 📅 {last_v}")

    except Exception as e:
        data['status'] = f'✗ Hata: {str(e)[:50]}'

    return data


def process_single_url(driver, url, index, total):
    normalized_url, url_type = normalize_url(url)
    if normalized_url is None:
        return {'url': url, 'status': '✗ Boş URL', **EMPTY_DATA}

    print(f"\n[{index}/{total}] 🔄 {normalized_url[:60]}...")

    try:
        channel_url = None

        if url_type in ('video', 'shorts', 'live'):
            print(f"   🎬 Video → kanal aranıyor...")
            channel_url = get_channel_url_from_video(driver, normalized_url)
            if channel_url:
                print(f"   ✓ Kanal: {channel_url}")
                normalized_url = channel_url
            else:
                return {'url': url, 'status': '✗ Kanal bulunamadı', **EMPTY_DATA}

        # About sayfasına git
        about_url = RE_CLEAN_CHANNEL_SUFFIX.sub('', normalized_url.rstrip('/')) + '/about'

        if not safe_get_page(driver, about_url):
            return {'url': normalized_url, 'status': '✗ Sayfa yüklenemedi', **EMPTY_DATA}

        # Bekleme - biraz artırıldı (video sayısı için JS render gerekiyor)
        time.sleep(0.8)

        data = extract_channel_info(driver, normalized_url)
        if channel_url:
            data['url'] = channel_url
        return data

    except Exception as e:
        return {'url': url, 'status': f'✗ {str(e)[:50]}', **EMPTY_DATA}


def restart_browser(driver):
    print("\n   🔄 Tarayıcı yenileniyor...")
    try:
        driver.quit()
    except:
        pass
    time.sleep(0.5)
    return setup_driver()


# ============================================================
# PARALEL İŞLEME
# ============================================================

def worker_process(urls_chunk, worker_id, total):
    driver = None
    results = []

    try:
        driver = setup_driver()

        try:
            driver.get("https://www.youtube.com")
            time.sleep(0.8)
        except:
            pass

        for local_idx, (global_idx, url) in enumerate(urls_chunk):
            if local_idx > 0 and local_idx % BROWSER_RESTART_INTERVAL == 0:
                driver = restart_browser(driver)
                try:
                    driver.get("https://www.youtube.com")
                    time.sleep(0.5)
                except:
                    pass

            data = process_single_url(driver, url, global_idx, total)
            save_result(data)

            with counter_lock:
                processed_counter['count'] += 1
                if '✓' in data.get('status', ''):
                    processed_counter['success'] += 1
                else:
                    processed_counter['error'] += 1

            results.append(data)

    except Exception as e:
        print(f"\n❌ Worker-{worker_id} hatası: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return results


def read_csv_safely(file_path):
    urls = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            rows = list(csv.reader(f))
            if not rows:
                return []
            start = 0
            if rows[0] and len(rows[0]) > 0:
                fc = rows[0][0].lower()
                if 'http' not in fc and 'youtube' not in fc and '@' not in fc:
                    start = 1
                    print(f"ℹ️ Başlık satırı atlandı: {rows[0][0]}")
            for row in rows[start:]:
                if row and row[0].strip():
                    urls.append(row[0].strip())
        return urls
    except Exception as e:
        print(f"❌ Dosya okuma hatası: {e}")
        return []


def process_csv(file_path):
    urls = read_csv_safely(file_path)
    if not urls:
        print("❌ İşlenecek URL bulunamadı!")
        return

    total = len(urls)
    video_count = sum(1 for u in urls if any(x in u for x in ['/watch?', 'youtu.be/', '/shorts/', '/live/']))
    channel_count = total - video_count

    parallel = min(PARALLEL_BROWSERS, max(1, total // 5))
    if total < 10:
        parallel = 1

    print(f"\n🚀 {total} URL bulundu")
    print(f"   📺 Kanal: {channel_count} | 🎬 Video: {video_count}")
    print(f"   ⚡ {parallel} paralel tarayıcı")
    print(f"   ⏱️ Tahmini süre: {total * 4 / parallel / 60:.1f} dakika")
    print(f"   🔄 Tarayıcı restart: her {BROWSER_RESTART_INTERVAL} kanalda")
    print("=" * 80)

    start_time = time.time()

    if parallel == 1:
        worker_process([(i + 1, url) for i, url in enumerate(urls)], 0, total)
    else:
        chunks = [[] for _ in range(parallel)]
        for i, url in enumerate(urls):
            chunks[i % parallel].append((i + 1, url))

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = []
            for wid, chunk in enumerate(chunks):
                if chunk:
                    futures.append(executor.submit(worker_process, chunk, wid, total))

            last_report = time.time()
            while any(not f.done() for f in futures):
                time.sleep(2)
                now = time.time()
                if now - last_report >= 10:
                    last_report = now
                    with counter_lock:
                        done = processed_counter['count']
                    if done > 0:
                        elapsed = now - start_time
                        rate = done / elapsed * 60
                        remaining = (total - done) / rate if rate > 0 else 0
                        print(f"\n   📊 İlerleme: {done}/{total} ({done/total*100:.1f}%) | Kalan: ~{remaining:.1f} dk")
                        with stats_lock:
                            print(f"   📧 Email: {stats['total_emails']} | IG: {stats['total_instagram']} | TT: {stats['total_tiktok']} | 📅 Son Video: {stats['total_last_video']}")

            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    print(f"❌ Worker hatası: {e}")

    elapsed = time.time() - start_time
    return elapsed


def main():
    print("=" * 80)
    print("📺 YOUTUBE KANAL BİLGİSİ TOPLAYICI v8.2 ULTRA")
    print("   ⚡⚡ Paralel tarayıcı + Eager loading")
    print("   🧠 Tek-geçiş regex çıkarma (pre-compiled)")
    print("   🎬 4 katmanlı video sayısı bulma (DÜZELTME)")
    print("   🛡️ Gelişmiş bot tespit atlatma")
    print("   📅 Son video yükleme tarihi")
    print("   🔍 Page Source + JSON + JavaScript + ytInitialData")
    print("   ✨ IG, TikTok, X, FB, Discord, Twitch, MAL")
    print("   📁 Sonuçlar: Downloads klasörü")
    print("=" * 80)
    print(f"\n⚙️ Ayarlar: {PARALLEL_BROWSERS} paralel tarayıcı | "
          f"Restart: {BROWSER_RESTART_INTERVAL} | "
          f"Timeout: {PAGE_LOAD_TIMEOUT}s")
    print("\n💡 Desteklenen formatlar:")
    print("   youtube.com/@kanal | /watch?v=xxx | /shorts/xxx | /live/xxx | @handle")
    print("=" * 80)

    try:
        root = Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.askopenfilename(
            title="CSV Dosyasını Seçin",
            initialdir=DOWNLOADS_FOLDER,
            filetypes=[("CSV", "*.csv"), ("Tüm Dosyalar", "*.*")]
        )
        root.destroy()
        if not file_path:
            print("❌ Dosya seçilmedi!")
            return
        print(f"✓ Dosya: {os.path.basename(file_path)}")
    except:
        file_path = input("CSV dosya yolu: ").strip().replace('"', '')
        if not os.path.exists(file_path):
            print("❌ Dosya bulunamadı!")
            return

    create_output_file()

    try:
        elapsed = process_csv(file_path)
    except Exception as e:
        print(f"\n❌ İşlem hatası: {e}")
        import traceback
        traceback.print_exc()
        elapsed = 0

    if elapsed:
        print("\n" + "=" * 80)
        print(f"✅ TAMAMLANDI!")
        print(f"⏱️ Süre: {elapsed / 60:.1f} dakika")
        print(f"📊 İşlenen: {processed_counter['count']} | "
              f"Başarılı: {processed_counter['success']} | "
              f"Hata: {processed_counter['error']}")
        if processed_counter['count'] > 0:
            print(f"🚀 Ortalama: {elapsed / processed_counter['count']:.1f} saniye/kanal")

        print(f"\n📈 BULUNAN VERİLER:")
        labels = [
            ('📧', 'Email', stats['total_emails']),
            ('📷', 'Instagram', stats['total_instagram']),
            ('🎵', 'TikTok', stats['total_tiktok']),
            ('🐦', 'Twitter/X', stats['total_twitter']),
            ('💬', 'Discord', stats['total_discord']),
            ('📘', 'Facebook', stats['total_facebook']),
            ('🎮', 'Twitch', stats['total_twitch']),
            ('🎌', 'MyAnimeList', stats['total_mal']),
            ('📅', 'Son Video Tarihi', stats['total_last_video']),
        ]
        for icon, label, count in labels:
            print(f"   {icon} {label}: {count}")

        print(f"\n📁 Sonuç dosyası: {OUTPUT_FILE}")
        print(f"📂 Klasör: {DOWNLOADS_FOLDER}")
        print("=" * 80)

    try:
        import subprocess
        import platform as pf
        if pf.system() == 'Windows':
            os.startfile(OUTPUT_FILE)
        elif pf.system() == 'Darwin':
            subprocess.run(['open', OUTPUT_FILE])
        else:
            subprocess.run(['xdg-open', OUTPUT_FILE])
    except:
        pass


if __name__ == "__main__":
    try:
        import selenium
    except ImportError:
        print("❌ Selenium kütüphanesi eksik!")
        print("Yüklemek için: pip install selenium")
        exit()

    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ İptal edildi")
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()

    input("\nKapatmak için Enter...")