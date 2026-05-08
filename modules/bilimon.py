"""
modules/bilimon.py — Bilibili posting monitor

Compares each managed creator's recent YouTube uploads against their recent
Bilibili uploads. A YouTube upload in the last `window_days` whose title has no
fuzzy match on Bilibili is flagged so the manager can remind the creator to
cross-post.

Public API:
    list_managers()                       -> [str]
    creators_for(manager)                 -> [dict]
    check_creator(creator, window_days)   -> dict
"""

import hashlib
import json
import os
import random
import re
import string
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests
import yt_dlp

# When an Apify proxy password is set, all Bilibili requests are routed
# through Apify's residential proxy. A per-creator session-id keeps the same
# IP across the space-page warmup and the WBI API call (cookies stay
# consistent), and rotates across creators and days to avoid pattern
# detection.
#
# Apify uses two different secrets; the proxy needs APIFY_PROXY_PASSWORD,
# not the actor-API token. We accept either, preferring the proxy-specific
# one, so existing Railway setups (APIFY_API_TOKEN already populated by the
# social-listening actor flow) keep working as a fallback.
APIFY_PROXY_PASSWORD = (
    os.environ.get('APIFY_PROXY_PASSWORD')
    or os.environ.get('APIFY_API_TOKEN')
    or os.environ.get('APIFY_TOKEN')
    or ''
).strip()

# Apify proxy username supports either `auto` (default group), an explicit
# `groups-X,session-Y` spec, or just `session-Y` (no group spec). Specifying
# a group the account is not entitled to returns 407, even with the right
# password. Default to no group spec so the account's default group is used;
# set APIFY_PROXY_GROUPS only if a specific group is required.
APIFY_PROXY_GROUPS = os.environ.get('APIFY_PROXY_GROUPS', '').strip()

# Apify Actor token — used to call zhorex/bilibili-scraper which handles the
# WAF/IP problem internally. Direct WBI calls fail because Bilibili blocks
# all non-CN/HK datacenter ASNs (and our $29 Apify plan only ships datacenter
# proxies), so we offload the fetch to an actor that has working IP rotation.
APIFY_API_TOKEN = (
    os.environ.get('APIFY_API_TOKEN')
    or os.environ.get('APIFY_TOKEN')
    or ''
).strip()
BB_ACTOR_ID    = 'zhorex~bilibili-scraper'
BB_ACTOR_LIMIT = 15  # videos per creator — covers ~30 days for most creators

DATA_FILE = Path(__file__).resolve().parent.parent / 'data' / 'creators.json'
WINDOW_DAYS_DEFAULT = 30
TITLE_MATCH_THRESHOLD = 0.55  # below this counts as "missing on Bilibili"


# ─────────────────────────────────────────────
# Roster
# ─────────────────────────────────────────────

def _load() -> dict:
    return json.loads(DATA_FILE.read_text(encoding='utf-8'))


def list_managers() -> list:
    return _load().get('managers', [])


def creators_for(manager: str, youtube_only: bool = False) -> list:
    rows = [c for c in _load().get('creators', []) if c.get('manager') == manager]
    if youtube_only:
        rows = [c for c in rows if c.get('youtube_url')]
    return rows


# ─────────────────────────────────────────────
# YouTube — recent uploads
# ─────────────────────────────────────────────
# yt-dlp extract_flat does not surface upload dates for channel listings, so
# we resolve the channel_id (one yt-dlp call when the URL is a handle) and
# then read the public RSS feed which carries <published> for each entry.

_RE_CHANNEL_ID = re.compile(r'/channel/(UC[A-Za-z0-9_-]{22})')
# Match channelId in the JSON blob YouTube embeds in every channel page.
# Covers both "channelId":"UC..." (browse pages) and "externalId":"UC..."
# (microformat). One of the two is always present even after consent redirect.
_RE_CID_INPAGE = re.compile(r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"')
_YT_NS = {
    'a':     'http://www.w3.org/2005/Atom',
    'media': 'http://search.yahoo.com/mrss/',
    'yt':    'http://www.youtube.com/xml/schemas/2015',
}

# Browser-shaped headers + consent cookie, copied from modules/scraper.py's
# pattern. The CONSENT=YES+ cookie short-circuits YouTube's EU consent wall
# that Railway datacenter IPs otherwise get redirected into.
_YT_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36'),
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
_YT_COOKIES = {'CONSENT': 'YES+cb', 'SOCS': 'CAI'}


def _resolve_channel_id(channel_url: str) -> str:
    m = _RE_CHANNEL_ID.search(channel_url)
    if m:
        return m.group(1)
    # Direct HTTP scrape — much faster than yt-dlp and avoids the consent
    # redirect that breaks plain extract_info on Railway. Falls back to
    # yt-dlp only if the HTML scrape can't find a channelId pattern.
    try:
        r = requests.get(channel_url.rstrip('/'),
                         headers=_YT_HEADERS, cookies=_YT_COOKIES,
                         timeout=15, allow_redirects=True)
        if r.status_code == 200 and r.text:
            m = _RE_CID_INPAGE.search(r.text)
            if m:
                return m.group(1)
    except Exception:
        pass
    try:
        opts = {'skip_download': True, 'quiet': True, 'no_warnings': True,
                'ignoreerrors': True, 'extract_flat': True, 'playlistend': 1}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url.rstrip('/'), download=False)
        return (info or {}).get('channel_id') or ''
    except Exception:
        return ''


def yt_resolve_debug(channel_url: str) -> dict:
    """Diagnostic for /bili/debug-yt — returns each step of the YT resolve
    so we can pinpoint where Railway is losing the channel_id."""
    out = {'input': channel_url}
    m = _RE_CHANNEL_ID.search(channel_url or '')
    if m:
        out['from_url_regex'] = m.group(1)
        out['cid'] = m.group(1)
        return out
    try:
        r = requests.get(channel_url.rstrip('/'),
                         headers=_YT_HEADERS, cookies=_YT_COOKIES,
                         timeout=15, allow_redirects=True)
        out['http_status']     = r.status_code
        out['final_url']       = r.url
        out['len_html']        = len(r.text or '')
        out['has_consent_kw']  = 'consent.youtube' in (r.text or '').lower()
        out['head_snippet']    = (r.text or '')[:400]
        m2 = _RE_CID_INPAGE.search(r.text or '')
        out['from_html_regex'] = m2.group(1) if m2 else None
        if m2:
            out['cid'] = m2.group(1)
            return out
    except Exception as e:
        out['http_error'] = f'{type(e).__name__}: {str(e)[:200]}'
    try:
        opts = {'skip_download': True, 'quiet': True, 'no_warnings': True,
                'ignoreerrors': True, 'extract_flat': True, 'playlistend': 1}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url.rstrip('/'), download=False) or {}
        out['ytdlp_channel_id'] = info.get('channel_id')
        out['ytdlp_keys']       = list(info.keys())[:20]
        if info.get('channel_id'):
            out['cid'] = info.get('channel_id')
    except Exception as e:
        out['ytdlp_error'] = f'{type(e).__name__}: {str(e)[:200]}'
    if out.get('cid'):
        # Probe both routes so we can see exactly what Railway sees vs what
        # the proxy sees. If direct returns empty/blocked but proxy returns
        # a real feed, that's the smoking gun for IP-based rate limiting.
        for label, proxies in (('direct', {}), ('proxy', _yt_proxies())):
            if label == 'proxy' and not proxies:
                continue
            try:
                rr = requests.get(
                    f'https://www.youtube.com/feeds/videos.xml?channel_id={out["cid"]}',
                    headers=_YT_HEADERS, cookies=_YT_COOKIES, timeout=15,
                    proxies=proxies,
                )
                out[f'rss_{label}_status'] = rr.status_code
                out[f'rss_{label}_len']    = len(rr.text or '')
                out[f'rss_{label}_head']   = (rr.text or '')[:200]
                try:
                    root = ET.fromstring(rr.text)
                    entries = root.findall('a:entry', _YT_NS)
                    out[f'rss_{label}_entries'] = len(entries)
                except Exception as pe:
                    out[f'rss_{label}_parse_error'] = f'{type(pe).__name__}: {str(pe)[:200]}'
            except Exception as e:
                out[f'rss_{label}_error'] = f'{type(e).__name__}: {str(e)[:200]}'
    return out


def _yt_proxies() -> dict:
    """Route YouTube fetches via Apify proxy when configured. Railway
    datacenter IPs get throttled/blocked from YouTube's RSS endpoints,
    but Apify residential pool reaches them fine."""
    if not APIFY_PROXY_PASSWORD:
        return {}
    sess_id = f'yt{datetime.now(timezone.utc).strftime("%Y%m%d%H")}'
    proxy = _proxy_for(sess_id)
    return {'http': proxy, 'https': proxy} if proxy else {}


def _fetch_yt_uploads(channel_url: str, limit: int = 15) -> list:
    if not channel_url:
        return []
    cid = _resolve_channel_id(channel_url)
    if not cid:
        return []
    try:
        r = requests.get(
            f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}',
            headers=_YT_HEADERS, cookies=_YT_COOKIES, timeout=15,
            proxies=_yt_proxies(),
        )
    except Exception:
        return []
    if r.status_code != 200 or not r.text:
        return []
    try:
        root = ET.fromstring(r.text)
    except Exception:
        return []
    out = []
    for entry in root.findall('a:entry', _YT_NS)[:limit]:
        vid = (entry.findtext('yt:videoId', default='', namespaces=_YT_NS) or '').strip()
        if not vid:
            continue
        title = (entry.findtext('a:title', default='', namespaces=_YT_NS) or '').strip()
        published_iso = (entry.findtext('a:published', default='', namespaces=_YT_NS) or '').strip()
        published = published_iso[:10] if len(published_iso) >= 10 else ''
        thumb = ''
        media_group = entry.find('media:group', _YT_NS)
        if media_group is not None:
            mt = media_group.find('media:thumbnail', _YT_NS)
            if mt is not None:
                thumb = mt.get('url') or ''
        out.append({
            'video_id':  vid,
            'title':     title,
            'url':       f'https://www.youtube.com/watch?v={vid}',
            'published': published,
            'thumbnail': thumb or f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',
        })
    return out


# ─────────────────────────────────────────────
# Bilibili — recent uploads via WBI-signed space.arc/search
# ─────────────────────────────────────────────

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_BB_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36'),
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8',
    'Origin':          'https://space.bilibili.com',
    'Sec-Ch-Ua':         '"Not A(Brand";v="99", "Google Chrome";v="120", "Chromium";v="120"',
    'Sec-Ch-Ua-Mobile':  '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest':    'empty',
    'Sec-Fetch-Mode':    'cors',
    'Sec-Fetch-Site':    'same-site',
}

# Bilibili rate-limits aggressively (-412 / -799) when traffic from one IP
# looks bot-like. With Apify residential proxy each creator gets its own IP
# so per-IP rate-limit pressure goes away; without proxy we still pace
# requests at ≥3s apart from a single IP.
_BB_MIN_GAP_SEC = 3.0
_bb_state = {'keys': None, 'keys_ts': 0.0, 'last_call': 0.0}


def _proxy_for(session_id: str) -> str:
    """Build an Apify proxy URL pinned to a session-id (=stable IP).

    Username layout depends on APIFY_PROXY_GROUPS:
      - empty (default) → "session-{id}" — uses account's default group
      - set            → "groups-{X},session-{id}" — explicit group spec

    Specifying a group the account isn't entitled to returns 407, so we
    leave it off unless the operator opted in. The password is URL-encoded
    because Apify passwords can contain @ / : + which break URL parsing."""
    if not APIFY_PROXY_PASSWORD or not session_id:
        return ''
    pwd = urllib.parse.quote(APIFY_PROXY_PASSWORD, safe='')
    if APIFY_PROXY_GROUPS:
        username = f'groups-{APIFY_PROXY_GROUPS},session-{session_id}'
    else:
        username = f'session-{session_id}'
    return f'http://{username}:{pwd}@proxy.apify.com:8000'


def _new_bb_session(session_id: str = '') -> requests.Session:
    s = requests.Session()
    s.headers.update(_BB_HEADERS)
    proxy = _proxy_for(session_id)
    if proxy:
        s.proxies = {'http': proxy, 'https': proxy}
    return s


def proxy_diagnostic() -> dict:
    """Test whether the configured proxy actually reaches the public internet.
    Returns a dict suitable for /bili/proxy-status.

    Tests multiple username formats so we can tell whether 407 is caused by
    a wrong password, wrong group syntax, or wrong plan entitlement."""
    pwd_fp = ''
    pwd_char_check = {}
    if APIFY_PROXY_PASSWORD:
        p = APIFY_PROXY_PASSWORD
        pwd_fp = f'len={len(p)} starts={p[:2]}… ends=…{p[-2:]}'
        # Detect hidden chars that .strip() doesn't catch.
        non_alnum = [c for c in p if not c.isalnum()]
        suspicious = [hex(ord(c)) for c in p
                      if not (32 < ord(c) < 127)]
        pwd_char_check = {
            'all_alphanumeric':       len(non_alnum) == 0,
            'non_alnum_chars':        ''.join(non_alnum)[:40],
            'non_printable_codepoints': suspicious[:20],
            # Raw env value length BEFORE strip — exposes trailing whitespace
            # that strip() would silently eat.
            'raw_env_len_pre_strip': len(os.environ.get('APIFY_PROXY_PASSWORD', '')),
        }
    info = {
        'proxy_password_set':   bool(APIFY_PROXY_PASSWORD),
        'proxy_password_fp':    pwd_fp,
        'proxy_password_check': pwd_char_check,
        'proxy_groups':         APIFY_PROXY_GROUPS,
        'actor_token_set':      bool(APIFY_API_TOKEN),
        'actor_id':             BB_ACTOR_ID,
        'fetch_route': 'apify_actor' if APIFY_API_TOKEN else (
                       'apify_proxy_direct_wbi' if APIFY_PROXY_PASSWORD else 'direct_wbi'),
        'env_seen': {
            'APIFY_PROXY_PASSWORD': bool(os.environ.get('APIFY_PROXY_PASSWORD')),
            'APIFY_API_TOKEN':      bool(os.environ.get('APIFY_API_TOKEN')),
            'APIFY_TOKEN':          bool(os.environ.get('APIFY_TOKEN')),
        },
    }
    if not APIFY_PROXY_PASSWORD:
        info['mode'] = 'direct'
        return info
    info['mode'] = 'proxy'

    sess_id = f'diag{int(time.time())}'
    pwd_enc = urllib.parse.quote(APIFY_PROXY_PASSWORD, safe='')

    variants = [
        ('auto',           'auto'),
        ('current',        f'groups-{APIFY_PROXY_GROUPS},session-{sess_id}'),
        ('plus_encoded',   f'groups-{APIFY_PROXY_GROUPS.replace("+", "%2B")},'
                           f'session-{sess_id}'),
        ('no_groups',      f'session-{sess_id}'),
    ]
    results = {}
    for name, username in variants:
        proxy_url = f'http://{username}:{pwd_enc}@proxy.apify.com:8000'
        try:
            r = requests.get(
                'https://api.ipify.org?format=json',
                proxies={'http': proxy_url, 'https': proxy_url},
                timeout=15,
            )
            results[name] = {'status': r.status_code,
                             'body': r.text[:120]}
        except Exception as e:
            results[name] = {'error': f'{type(e).__name__}: {str(e)[:200]}'}
    info['variant_tests'] = results
    return info


def _wbi_session() -> requests.Session:
    """Lightweight session used only to fetch wbi keys (any IP works for this)."""
    s = requests.Session()
    s.headers.update(_BB_HEADERS)
    return s


def _wbi_keys() -> tuple:
    if _bb_state['keys'] and (time.time() - _bb_state['keys_ts']) < 1800:
        return _bb_state['keys']
    s = _wbi_session()
    try:
        r = s.get('https://api.bilibili.com/x/web-interface/nav', timeout=10)
        wbi_img = (r.json().get('data') or {}).get('wbi_img') or {}
        img_url = wbi_img.get('img_url') or ''
        sub_url = wbi_img.get('sub_url') or ''
        img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]
        if not img_key or not sub_key:
            return ('', '')
        _bb_state['keys'] = (img_key, sub_key)
        _bb_state['keys_ts'] = time.time()
        return _bb_state['keys']
    except Exception:
        return ('', '')


def _mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return ''.join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def _wbi_sign(params: dict) -> dict:
    img_key, sub_key = _wbi_keys()
    if not img_key:
        return params
    mk = _mixin_key(img_key, sub_key)
    p = dict(params)
    p['wts'] = int(time.time())
    items = sorted((str(k), str(v)) for k, v in p.items())
    raw = '&'.join(f'{urllib.parse.quote(k, safe="")}={urllib.parse.quote(v, safe="")}'
                   for k, v in items)
    p['w_rid'] = hashlib.md5((raw + mk).encode('utf-8')).hexdigest()
    return p


def _bb_pace():
    """Sleep just enough to keep ≥_BB_MIN_GAP_SEC between consecutive calls.
    Only meaningful when proxy is OFF — with proxy each call gets its own IP."""
    if APIFY_PROXY_PASSWORD:
        return
    delta = time.time() - _bb_state['last_call']
    if delta < _BB_MIN_GAP_SEC:
        time.sleep(_BB_MIN_GAP_SEC - delta)
    _bb_state['last_call'] = time.time()


def _bb_session_id_for(mid: str) -> str:
    """Stable per-creator-per-day session id: same IP for warmup + API call,
    rotates daily to avoid pattern detection."""
    return f'bili{mid}{datetime.now(timezone.utc).strftime("%Y%m%d")}'


def _gen_uuid_cookie() -> str:
    """Generate a Bilibili-style _uuid cookie. Format observed in browser:
    8-4-4-4-12 hex blocks then `infoc`. Bilibili's WAF checks the literal
    `infoc` suffix and length, not cryptographic correctness."""
    parts = []
    for n in (8, 4, 4, 4, 12):
        parts.append(''.join(random.choice(string.hexdigits[:16]) for _ in range(n)))
    ms = str(int(time.time() * 1000) % 100000).zfill(5)
    return f"{'-'.join(parts)}{ms}infoc"


def _gen_b_lsid() -> str:
    """b_lsid = 8 hex chars + '_' + 13-digit hex of unix-ms."""
    head = ''.join(random.choice(string.hexdigits[:16]).upper() for _ in range(8))
    tail = format(int(time.time() * 1000), 'X')
    return f'{head}_{tail}'


def _warmup_cookies(s: requests.Session) -> None:
    """Populate buvid3/buvid4/_uuid/b_nut/b_lsid cookies on the session.

    The space page sets these via JavaScript so a plain GET doesn't surface
    them as Set-Cookie headers. Bilibili's WAF rejects API calls without
    buvid3 with code -412. We hit the public fingerprint endpoint to get
    server-issued b_3/b_4 values, then synthesise the rest the same way the
    browser JS would. Failures are non-fatal — we still try the API call."""
    try:
        r = s.get('https://api.bilibili.com/x/frontend/finger/spi', timeout=15)
        j = r.json()
        data = j.get('data') or {}
        b3 = data.get('b_3') or ''
        b4 = data.get('b_4') or ''
        if b3:
            s.cookies.set('buvid3', b3, domain='.bilibili.com')
        if b4:
            s.cookies.set('buvid4', b4, domain='.bilibili.com')
    except Exception:
        pass
    s.cookies.set('b_nut', str(int(time.time())), domain='.bilibili.com')
    s.cookies.set('_uuid', _gen_uuid_cookie(), domain='.bilibili.com')
    s.cookies.set('b_lsid', _gen_b_lsid(), domain='.bilibili.com')
    s.cookies.set('CURRENT_FNVAL', '4048', domain='.bilibili.com')
    # Visiting the homepage gives the WAF a realistic referer trail.
    try:
        s.get('https://www.bilibili.com/', timeout=15)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Apify actor route (preferred — direct WBI is blocked from datacenter IPs)
# ─────────────────────────────────────────────

# Tiny in-process cache keyed by mid so repeated Refresh clicks within the
# TTL don't re-bill the actor. Keeps cost down without adding Redis.
_BB_ACTOR_CACHE_TTL = 300  # seconds
_bb_actor_cache: dict = {}


def _apify_token_param() -> str:
    return urllib.parse.quote(APIFY_API_TOKEN, safe='')


def _map_actor_item(v: dict) -> dict:
    bvid = v.get('bvid') or ''
    if not bvid:
        return {}
    ts = v.get('publishTimestamp') or v.get('created') or 0
    if ts:
        published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
    else:
        pd = v.get('publishDate') or v.get('published') or ''
        published = pd[:10] if len(pd) >= 10 else ''
    pic = v.get('thumbnailUrl') or v.get('pic') or ''
    if pic.startswith('//'):
        pic = 'https:' + pic
    return {
        'bvid':      bvid,
        'title':     v.get('title') or '',
        'url':       f'https://www.bilibili.com/video/{bvid}',
        'published': published,
        'thumbnail': pic,
    }


def _fetch_bb_uploads_via_actor(mid: str, limit: int) -> tuple:
    """Start the actor, poll until it finishes (or we run out of budget),
    then fetch the dataset. Async pattern is mandatory because the actor
    cold-start regularly exceeds Apify's run-sync wait window — that's what
    the actor_http_201 errors were."""
    cached = _bb_actor_cache.get(str(mid))
    if cached and (time.time() - cached['ts']) < _BB_ACTOR_CACHE_TTL:
        return cached['videos'], ''

    tok = _apify_token_param()

    # 1. Start the run.
    start_url = f'https://api.apify.com/v2/acts/{BB_ACTOR_ID}/runs?token={tok}'
    body = {
        'mode':       'user_videos',
        'userIds':    [str(mid)],
        'maxResults': limit,
    }
    try:
        r = requests.post(start_url, json=body, timeout=30)
    except Exception as e:
        return [], f'actor_start_error_{type(e).__name__}'
    if r.status_code not in (200, 201):
        return [], f'actor_start_http_{r.status_code}'
    try:
        run = (r.json() or {}).get('data') or {}
    except Exception:
        return [], 'actor_start_parse_error'
    run_id     = run.get('id') or ''
    dataset_id = run.get('defaultDatasetId') or ''
    if not run_id or not dataset_id:
        return [], 'actor_no_run_id'

    # 2. Poll. Budget = ~90s so we stay inside gunicorn's 120s request limit
    # with margin for the dataset fetch + response serialization. 3s gap
    # keeps Apify request count low (~30 calls per cold creator worst case).
    status_url = f'https://api.apify.com/v2/actor-runs/{run_id}?token={tok}'
    deadline = time.time() + 90
    status = ''
    while time.time() < deadline:
        try:
            sr = requests.get(status_url, timeout=15)
            status = ((sr.json() or {}).get('data') or {}).get('status') or ''
        except Exception:
            status = ''
        if status in ('SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED'):
            break
        time.sleep(3)
    if status != 'SUCCEEDED':
        # Surface the terminal status so we know whether to retry, look at
        # the actor's logs, or chase a billing/auth issue.
        return [], f'actor_status_{status or "timeout"}'

    # 3. Fetch dataset items. `clean=1` strips Apify metadata fields.
    items_url = (f'https://api.apify.com/v2/datasets/{dataset_id}/items'
                 f'?token={tok}&clean=1&format=json')
    try:
        ir = requests.get(items_url, timeout=30)
        items = ir.json() or []
    except Exception as e:
        return [], f'actor_dataset_error_{type(e).__name__}'
    if not isinstance(items, list):
        return [], 'actor_dataset_shape_error'

    out = [m for m in (_map_actor_item(v) for v in items) if m]
    _bb_actor_cache[str(mid)] = {'ts': time.time(), 'videos': out}
    return out, ''


def _fetch_bb_uploads(mid: str, limit: int = 30) -> tuple:
    """Returns (videos, error_code). error_code='' on success or
    'rate_limited'/'banned_<code>'/'fetch_error_<exc>'/'api_error_<code>'."""
    if not mid:
        return [], 'no_mid'
    # Prefer the Apify actor when configured — it handles Bilibili's WAF/IP
    # block internally. Fall back to direct WBI only if the token is missing
    # (e.g. local dev without Apify credentials).
    if APIFY_API_TOKEN:
        return _fetch_bb_uploads_via_actor(mid, min(limit, BB_ACTOR_LIMIT))
    s = _new_bb_session(_bb_session_id_for(mid))
    _warmup_cookies(s)
    # Then visit the creator's space page so the API call has a matching
    # Referer fingerprint. Failures here are non-fatal.
    try:
        s.get(f'https://space.bilibili.com/{mid}', timeout=15)
    except Exception:
        pass
    _bb_pace()
    # The dm_img_* params are Bilibili's 2024 anti-bot fingerprint set,
    # normally computed by browser JS from canvas/WebGL state. They MUST be
    # included before WBI signing — the server validates that w_rid was
    # computed over a body that includes them, and returns -352 otherwise.
    # Static "looks like a browser" values are accepted; only their presence
    # in the signature is checked.
    params = {
        'mid': str(mid), 'ps': limit, 'pn': 1,
        'order': 'pubdate', 'platform': 'web',
        'web_location': '1550101',
        'dm_img_list':      '[]',
        'dm_img_str':       'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
        'dm_cover_img_str': 'V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ',
        'dm_img_inter':     '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
    }
    signed = _wbi_sign(params)
    headers = {'Referer': f'https://space.bilibili.com/{mid}'}
    try:
        r = s.get('https://api.bilibili.com/x/space/wbi/arc/search',
                  params=signed, headers=headers, timeout=30)
        j = r.json()
    except Exception as e:
        # Surface the exception class so the UI/log shows ProxyError vs Timeout
        # vs JSONDecodeError instead of a generic "network error".
        return [], f'fetch_error_{type(e).__name__}'
    code = j.get('code')
    if code in (-412, -352):
        # Include the exact subcode so we can tell -412 (bot block) from -352
        # (WAF flag) without re-running the diagnostic.
        return [], f'banned_{code}'
    if code == -799:
        return [], 'rate_limited'
    if code != 0:
        return [], f'api_error_{code}'
    vlist = ((j.get('data') or {}).get('list') or {}).get('vlist') or []
    out = []
    for v in vlist[:limit]:
        bvid = v.get('bvid') or ''
        if not bvid:
            continue
        ts = v.get('created') or 0
        published = (datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
                     if ts else '')
        pic = v.get('pic') or ''
        if pic.startswith('//'):
            pic = 'https:' + pic
        out.append({
            'bvid':      bvid,
            'title':     v.get('title') or '',
            'url':       f'https://www.bilibili.com/video/{bvid}',
            'published': published,
            'thumbnail': pic,
        })
    return out, ''


# ─────────────────────────────────────────────
# Compare
# ─────────────────────────────────────────────

_PUNCT = re.compile(r'[\s\W_]+', re.UNICODE)


def _norm(s: str) -> str:
    return _PUNCT.sub('', (s or '').lower())


def _title_match(yt_title: str, bb_titles: list) -> tuple:
    yn = _norm(yt_title)
    if not yn:
        return ('', 0.0)
    best = ('', 0.0)
    for bt in bb_titles:
        bn = _norm(bt)
        if not bn:
            continue
        if yn in bn or bn in yn:
            return (bt, 1.0)
        r = SequenceMatcher(None, yn, bn).ratio()
        if r > best[1]:
            best = (bt, r)
    return best


def _within(published: str, days: int) -> bool:
    if not published:
        return False
    try:
        d = datetime.strptime(published, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return d >= datetime.now(timezone.utc) - timedelta(days=days)


def _summary(creator: dict) -> dict:
    return {
        'name':          creator.get('name'),
        'handle':        creator.get('handle'),
        'manager':       creator.get('manager'),
        'youtube_url':   creator.get('youtube_url'),
        'bilibili_url':  creator.get('bilibili_url'),
        'bilibili_mid':  creator.get('bilibili_mid'),
        'instagram_url': creator.get('instagram_url'),
        'followers':     creator.get('followers'),
    }


def check_creator(creator: dict, window_days: int = WINDOW_DAYS_DEFAULT) -> dict:
    yt_url = creator.get('youtube_url') or ''
    bb_mid = creator.get('bilibili_mid') or ''
    base   = _summary(creator)

    if not yt_url and not bb_mid:
        return {**base, 'status': 'no_platforms', 'comparable': False}
    if not yt_url:
        return {**base, 'status': 'no_youtube', 'comparable': False}
    if not bb_mid:
        return {**base, 'status': 'no_bilibili', 'comparable': False}

    yt = _fetch_yt_uploads(yt_url, limit=15)
    bb, bb_err = _fetch_bb_uploads(bb_mid, limit=30)

    yt_recent = [v for v in yt if _within(v['published'], window_days)]
    bb_recent = [v for v in bb if _within(v['published'], window_days)]
    bb_titles = [v['title'] for v in bb]  # match against full BB list, not just window

    # When BB fetch failed (rate-limited/banned), don't pretend everything is
    # missing — flag the result as partial so the UI can prompt a retry.
    missing = []
    if not bb_err:
        for v in yt_recent:
            match_title, ratio = _title_match(v['title'], bb_titles)
            if ratio >= TITLE_MATCH_THRESHOLD:
                continue
            missing.append({**v, 'best_bb_match': match_title,
                            'match_ratio': round(ratio, 2)})

    return {
        **base,
        'status':              'ok' if not bb_err else 'bb_unavailable',
        'comparable':          True,
        'window_days':         window_days,
        'youtube_recent':      yt_recent,
        'bilibili_recent':     bb_recent,
        'missing_on_bilibili': missing,
        'youtube_count':       len(yt),
        'bilibili_count':      len(bb),
        'bb_error':            bb_err,
    }
