"""
Shared constants, regex patterns, and pure utility functions.
Used by scraper.py, agency.py, and any future modules.
"""

import re
from urllib.parse import unquote, parse_qs, urlparse

# ─────────────────────────────────────────────
# SOCIAL MEDIA
# ─────────────────────────────────────────────

INVALID_USERNAMES = {
    'twitter':   frozenset({'summary','intent','share','home','search','i','hashtag','player','widgets','settings','privacy','tos','about','explore','notifications','messages','login','signup','card','cards','summary_large_image'}),
    'instagram': frozenset({'p','reel','reels','stories','explore','direct','accounts','about','legal','privacy','terms','help','api','press','jobs','blog','developer','tv','igtv'}),
    'facebook':  frozenset({'sharer','share','dialog','plugins','login','help','pages','groups','events','marketplace','gaming','watch','privacy','policies','ad_campaign','ads','business','tr'}),
    'twitch':    frozenset({'directory','videos','clips','following','settings','subscriptions','inventory','drops','wallet','friends','messages','search','downloads','jobs','turbo','products','prime','partners'}),
}

# Each platform: regex to extract username, URL format, optional validator key, substring check
SOCIAL_PLATFORMS = {
    'instagram':   {'regex': re.compile(r'instagram\.com/([a-zA-Z0-9._]{2,30})', re.I),                          'url_fmt': 'https://www.instagram.com/{}',        'validator': 'instagram', 'check': 'instagram.com/'},
    'tiktok':      {'regex': re.compile(r'tiktok\.com/@?([a-zA-Z0-9._]{2,30})', re.I),                           'url_fmt': 'https://www.tiktok.com/@{}',           'validator': None,        'check': 'tiktok.com/'},
    'twitter':     {'regex': re.compile(r'(?:twitter|x)\.com/([a-zA-Z0-9_]{2,15})', re.I),                       'url_fmt': 'https://x.com/{}',                    'validator': 'twitter',   'check': 'twitter.com/'},
    'facebook':    {'regex': re.compile(r'facebook\.com/([a-zA-Z0-9.]{2,50})', re.I),                            'url_fmt': 'https://www.facebook.com/{}',          'validator': 'facebook',  'check': 'facebook.com/'},
    'discord':     {'regex': re.compile(r'discord\.(?:gg|com/invite)/([a-zA-Z0-9]{2,20})', re.I),                'url_fmt': 'https://discord.gg/{}',               'validator': None,        'check': 'discord.'},
    'twitch':      {'regex': re.compile(r'twitch\.tv/([a-zA-Z0-9_]{2,25})', re.I),                               'url_fmt': 'https://twitch.tv/{}',                'validator': 'twitch',    'check': 'twitch.tv/'},
    'myanimelist': {'regex': re.compile(r'myanimelist\.net/profile/([a-zA-Z0-9_-]{2,30})', re.I),                'url_fmt': 'https://myanimelist.net/profile/{}',  'validator': None,        'check': 'myanimelist.net/'},
    'linkedin':    {'regex': re.compile(r'linkedin\.com/(?:company|in)/([a-zA-Z0-9._-]{2,80})', re.I),           'url_fmt': 'https://www.linkedin.com/company/{}', 'validator': None,        'check': 'linkedin.com/'},
}

RE_EMAIL       = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})')
EMAIL_BLACKLIST = {'example', 'test', 'noreply', 'google', 'gstatic', 'youtube', 'sentry', 'wix', 'squarespace'}

NAV_DOMAINS = ('developers.google.com', 'support.google.com', 'policies.google.com',
               'accounts.google.com', 'gstatic.com', 'googleapis.com',
               'ggpht.com', 'ytimg.com', 'googleusercontent.com')
YT_DOMAINS  = ('youtube.com', 'youtu.be', 'yt.be')

# ─────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────

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

# ─────────────────────────────────────────────
# MISC REGEX
# ─────────────────────────────────────────────

RE_EMBED  = re.compile(r'youtube\.com/v/([a-zA-Z0-9_-]+)')
RE_CLEAN  = re.compile(r'/(about|videos|shorts|streams|playlists|community|channels|featured)/?$')

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def is_valid_username(username: str, platform: str) -> bool:
    if not username or len(username) < 2 or '...' in username:
        return False
    inv = INVALID_USERNAMES.get(platform)
    return username.lower() not in inv if inv else True


def decode_redirect(url: str) -> str:
    """Resolve a YouTube /redirect?q=... URL to its destination."""
    if 'youtube.com/redirect' not in url and 'youtube.com\\/redirect' not in url:
        return url
    try:
        clean = url.replace('\\/', '/').replace('\\u0026', '&')
        params = parse_qs(urlparse(clean).query)
        if 'q' in params:
            return unquote(params['q'][0])
    except Exception:
        pass
    return url
