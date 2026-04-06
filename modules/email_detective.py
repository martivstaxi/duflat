"""
Email Detective v2 — AI Agent with Tool-Use
--------------------------------------------
An iterative AI investigator that uses Claude Sonnet with tools to find
YouTube creator contact emails. Unlike the linear pipeline in email_finder.py,
this agent decides what to investigate next based on evidence found so far.

Tools available to the AI:
    - web_search(query)        — DuckDuckGo + Bing search
    - scrape_url(url)          — Fetch URL, extract emails + visible text
    - scrape_deep(url)         — Fetch URL + /contact /about subpages
    - extract_linktree(url)    — Pull all external links from link aggregator
    - report_email(email, ...) — Report found email (ends investigation)

Max 6 rounds of tool calls. Each round the AI analyzes results and decides
the next investigative step.

Public API:
    find_email_v2(channel_data: dict) -> dict
"""

import re
import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from .constants import BROWSER_HEADERS, RE_EMAIL, EMAIL_BLACKLIST
from .scraper import _fetch_email_innertube, _fetch_email_ydl_about

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

_SKIP_DOMAINS = (
    'youtube.com', 'youtu.be', 'google.com', 'gstatic.com',
    'googleapis.com', 'apple.com', 'microsoft.com', 'amazon.com',
    'bing.com', 'duckduckgo.com', 'wikipedia.org',
)

_SOCIAL_DOMAINS = (
    'instagram.com', 'twitter.com', 'x.com', 'facebook.com',
    'tiktok.com', 'discord.gg', 'discord.com', 'twitch.tv',
    'reddit.com', 'snapchat.com', 'pinterest.com', 'tumblr.com',
    'threads.net', 'linkedin.com',
)

_LINK_AGGREGATORS = ('linktr.ee', 'bio.link', 'beacons.ai', 'allmylinks.com',
                     'linkin.bio', 'lnk.bio', 'msha.ke', 'campsite.bio')

_FAKE_TLDS = frozenset({
    'on', 'at', 'in', 'or', 'to', 'be', 'we', 'my', 'me', 'by', 'do',
    'go', 'up', 'us', 'it', 'if', 'as', 'so', 'no', 'an', 'of', 'is',
    'he', 'she', 'her', 'him', 'his', 'had', 'has', 'was', 'did', 'may',
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
    'one', 'our', 'out', 'day', 'get', 'how', 'new', 'now', 'old',
    'see', 'two', 'way', 'who', 'its', 'let', 'put', 'say', 'too',
    'use', 'from', 'have', 'this', 'will', 'your', 'that', 'with', 'they',
    'been', 'more', 'when', 'come', 'here', 'just', 'know', 'like', 'look',
    'make', 'most', 'over', 'than', 'them', 'well', 'were',
    'also', 'back', 'even', 'give', 'good', 'into', 'last', 'long',
    'much', 'must', 'name', 'only', 'some', 'such', 'take', 'very',
    'what', 'work', 'year', 'each', 'many', 'then', 'want',
})

_RE_OBFUSCATED = re.compile(
    r'([a-zA-Z0-9._%+\-]+)'
    r'\s*(?:\[at\]|\(at\)|@| at )\s*'
    r'([a-zA-Z0-9.\-]+)'
    r'\s*(?:\[dot\]|\(dot\)|\. | dot |\.)?\s*'
    r'([a-zA-Z]{2,})',
    re.I
)

# Known valid TLDs — used to reject false positives from obfuscated regex
_KNOWN_TLDS = frozenset({
    'com', 'net', 'org', 'io', 'co', 'edu', 'gov', 'info', 'biz', 'me',
    'us', 'uk', 'de', 'fr', 'tr', 'ru', 'jp', 'kr', 'cn', 'au', 'ca',
    'in', 'br', 'it', 'es', 'nl', 'be', 'ch', 'at', 'pl', 'se', 'no',
    'dk', 'fi', 'pt', 'cz', 'ro', 'hu', 'gr', 'bg', 'hr', 'si', 'sk',
    'lt', 'lv', 'ee', 'ie', 'lu', 'mt', 'cy', 'is', 'pro', 'app', 'dev',
    'xyz', 'online', 'site', 'tech', 'store', 'live', 'club', 'space',
    'tv', 'cc', 'gg', 'fm', 'ly', 'to', 'mx', 'za', 'nz', 'ar', 'cl',
    'pe', 'co', 've', 'ua', 'il', 'ae', 'sa', 'sg', 'hk', 'tw', 'th',
    'ph', 'id', 'vn', 'my', 'pk', 'bd', 'np',
})

MAX_ROUNDS = 8
MODEL = 'claude-haiku-4-5-20251001'
CC_API_URL = 'https://api.channelcrawler.com'

_CONTACT_PREFIXES = (
    'contact', 'info', 'hello', 'business', 'collab', 'collaboration',
    'booking', 'management', 'press', 'media', 'partnerships',
    'brand', 'sponsor', 'work',
)

# ─────────────────────────────────────────────
# TOOL IMPLEMENTATIONS (executed server-side)
# ─────────────────────────────────────────────

def _is_valid_email(email: str) -> bool:
    """Check if email looks like a real business/creator contact email."""
    e = email.lower().strip()
    if len(e) < 6 or '@' not in e:
        return False
    if any(x in e for x in EMAIL_BLACKLIST):
        return False
    parts = e.split('@')
    if len(parts) != 2:
        return False
    local, domain = parts
    if len(local) < 2:
        return False
    # Reject double dots in domain (e.g. com..tr)
    if '..' in domain:
        return False
    tld_match = re.search(r'\.([a-z]{2,12})$', domain)
    if not tld_match:
        return False
    tld = tld_match.group(1)
    if tld in _FAKE_TLDS:
        return False
    # For TLDs > 3 chars, require them to be in the known list
    # (catches fake TLDs like .sosyal, .official, .channel etc.)
    if len(tld) > 3 and tld not in _KNOWN_TLDS:
        return False
    # Domain body before TLD must be at least 2 chars (reject "t.he", "a.co" etc.)
    domain_body = domain[:domain.rfind('.')].lstrip('www.')
    if len(domain_body) < 2:
        return False
    return True


def _extract_emails_from_text(text: str) -> list[str]:
    """Extract all valid emails from text (regex + obfuscated)."""
    results = []
    for m in RE_EMAIL.finditer(text):
        e = m.group(1).lower().strip().rstrip('.')
        if _is_valid_email(e) and e not in results:
            results.append(e)
    for m in _RE_OBFUSCATED.finditer(text):
        local, domain_part, tld = m.group(1), m.group(2), m.group(3)
        e = f'{local}@{domain_part}.{tld}'.lower()
        if _is_valid_email(e) and e not in results:
            results.append(e)
    return results


def _fetch_html(url: str, timeout: int = 10) -> str | None:
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200 and 'text' in r.headers.get('content-type', ''):
            return r.text
    except Exception:
        pass
    return None


def _page_text(html: str, max_chars: int = 1500) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'noscript']):
            tag.decompose()
        return ' '.join(soup.get_text(' ', strip=True).split())[:max_chars]
    except Exception:
        return ''


def _extract_links(html: str, base_url: str = '') -> list[str]:
    """Extract external links from HTML."""
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/') and base_url:
                href = urljoin(base_url, href)
            if href.startswith('http') and href not in links:
                links.append(href)
        return links[:20]
    except Exception:
        return []


def _search_serper(query: str, num: int = 10) -> list[dict]:
    """Google search via Serper.dev API (2500 free searches, no credit card)."""
    api_key = os.environ.get('SERPER_API_KEY', '')
    if not api_key:
        return []
    try:
        r = requests.post(
            'https://google.serper.dev/search',
            headers={'X-API-KEY': api_key, 'Content-Type': 'application/json'},
            json={'q': query, 'num': num},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for item in data.get('organic', []):
            results.append({
                'url': item.get('link', ''),
                'title': item.get('title', ''),
                'snippet': item.get('snippet', ''),
            })
        # Also check knowledgeGraph and peopleAlsoAsk
        kg = data.get('knowledgeGraph', {})
        if kg.get('description'):
            results.append({
                'url': kg.get('website', ''),
                'title': kg.get('title', ''),
                'snippet': kg.get('description', ''),
            })
        for paa in data.get('peopleAlsoAsk', [])[:3]:
            if paa.get('snippet'):
                results.append({
                    'url': paa.get('link', ''),
                    'title': paa.get('question', ''),
                    'snippet': paa.get('snippet', ''),
                })
        return results
    except Exception:
        return []



def _search_ddg(query: str) -> list[dict]:
    """DuckDuckGo HTML search (free, no API key, but rate-limited)."""
    results = []
    try:
        r = requests.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query, 'b': '', 'kl': 'en-us'},
            headers={**BROWSER_HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for el in soup.select('.result'):
                url_el = el.select_one('.result__url')
                title_el = el.select_one('.result__title')
                snippet_el = el.select_one('.result__snippet')
                url_text = url_el.get_text(strip=True) if url_el else ''
                if url_text and not url_text.startswith('http'):
                    url_text = 'https://' + url_text
                results.append({
                    'url': url_text,
                    'title': title_el.get_text(strip=True) if title_el else '',
                    'snippet': snippet_el.get_text(strip=True) if snippet_el else '',
                })
    except Exception:
        pass
    return results


def _search_bing(query: str) -> list[dict]:
    """Bing HTML search (free, no API key)."""
    results = []
    try:
        r = requests.get(
            'https://www.bing.com/search',
            params={'q': query, 'count': 8},
            headers={**BROWSER_HEADERS, 'Accept-Language': 'en-US,en;q=0.9'},
            timeout=15,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for li in soup.select('.b_algo'):
                a = li.select_one('h2 a')
                snippet = li.select_one('.b_caption p')
                if a and a.get('href'):
                    results.append({
                        'url': a['href'],
                        'title': a.get_text(strip=True),
                        'snippet': snippet.get_text(strip=True) if snippet else '',
                    })
    except Exception:
        pass
    return results


def _search_yahoo(query: str) -> list[dict]:
    """Yahoo HTML search (free, no API key)."""
    results = []
    try:
        r = requests.get(
            'https://search.yahoo.com/search',
            params={'p': query, 'n': 8},
            headers={**BROWSER_HEADERS, 'Accept-Language': 'en-US,en;q=0.9'},
            timeout=15,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for item in soup.select('.algo-sr'):
                a = item.select_one('h3 a') or item.select_one('a')
                snippet_el = item.select_one('.compText') or item.select_one('p')
                if a and a.get('href'):
                    results.append({
                        'url': a['href'],
                        'title': a.get_text(strip=True),
                        'snippet': snippet_el.get_text(strip=True) if snippet_el else '',
                    })
    except Exception:
        pass
    return results


def _search_ecosia(query: str) -> list[dict]:
    """Ecosia HTML search (free, no API key)."""
    results = []
    try:
        r = requests.get(
            'https://www.ecosia.org/search',
            params={'method': 'index', 'q': query},
            headers={**BROWSER_HEADERS, 'Accept-Language': 'en-US,en;q=0.9'},
            timeout=15,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for item in soup.select('.result'):
                a = item.select_one('a.result-title') or item.select_one('a[href]')
                snippet_el = item.select_one('.result-snippet') or item.select_one('p')
                if a and a.get('href') and a['href'].startswith('http'):
                    results.append({
                        'url': a['href'],
                        'title': a.get_text(strip=True),
                        'snippet': snippet_el.get_text(strip=True) if snippet_el else '',
                    })
    except Exception:
        pass
    return results


def _search_startpage(query: str) -> list[dict]:
    """Startpage HTML search (Google proxy, free, no API key)."""
    results = []
    try:
        r = requests.post(
            'https://www.startpage.com/sp/search',
            data={'query': query, 'cat': 'web'},
            headers={**BROWSER_HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            for item in soup.select('.w-gl__result'):
                a = item.select_one('a.w-gl__result-title') or item.select_one('a[href]')
                snippet_el = item.select_one('.w-gl__description') or item.select_one('p')
                if a and a.get('href') and a['href'].startswith('http'):
                    results.append({
                        'url': a['href'],
                        'title': a.get_text(strip=True),
                        'snippet': snippet_el.get_text(strip=True) if snippet_el else '',
                    })
    except Exception:
        pass
    return results


def _tool_web_search(query: str) -> dict:
    """
    Multi-engine web search — all engines run in PARALLEL.
    Engines: Serper.dev (if API key set), DuckDuckGo, Bing.
    Merges results from all engines, deduplicates by URL.
    """
    results = []
    seen_urls: set[str] = set()

    def _merge(items: list[dict]):
        for item in items:
            url = item.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(item)

    # Run all search engines in parallel
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_search_ddg, query): 'ddg',
            executor.submit(_search_bing, query): 'bing',
            executor.submit(_search_yahoo, query): 'yahoo',
            executor.submit(_search_ecosia, query): 'ecosia',
            executor.submit(_search_startpage, query): 'startpage',
        }
        if os.environ.get('SERPER_API_KEY', ''):
            futures[executor.submit(_search_serper, query)] = 'serper'

        for future in as_completed(futures):
            try:
                _merge(future.result())
            except Exception:
                pass

    # Extract emails from snippets, filtering out site-owned emails
    # (e.g. iletisim@aksutv.com.tr found on aksutv.com.tr is the site's own email)
    snippet_emails = []
    for r_item in results:
        item_url = r_item.get('url', '')
        for text_field in (r_item.get('snippet', ''), r_item.get('title', '')):
            for e in _extract_emails_from_text(text_field):
                if not _is_site_own_email(e, item_url):
                    snippet_emails.append(e)

    return {
        'results': results[:15],
        'emails_in_snippets': list(set(snippet_emails))[:5],
        'count': len(results),
    }


def _tool_scrape_url(url: str) -> dict:
    """Scrape a single URL — return emails found + page text."""
    html = _fetch_html(url)
    if not html:
        return {'error': f'Could not fetch {url}', 'emails': [], 'text': '', 'links': []}

    emails = _extract_emails_from_text(html)

    # Also check mailto: links
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            if a['href'].startswith('mailto:'):
                e = a['href'][7:].split('?')[0].strip().lower()
                if _is_valid_email(e) and e not in emails:
                    emails.append(e)
    except Exception:
        pass

    text = _page_text(html)
    links = _extract_links(html, url)

    return {
        'emails': emails[:10],
        'text': text,
        'links': links[:15],
        'url': url,
    }


def _tool_scrape_deep(url: str) -> dict:
    """Scrape URL + /contact, /about, /team subpages."""
    all_emails = []
    all_text = []

    main = _tool_scrape_url(url)
    all_emails += main.get('emails', [])
    all_text.append(main.get('text', ''))

    base = url.rstrip('/')
    for sub in ('/contact', '/about', '/about-us', '/contact-us', '/team'):
        if all_emails:
            break
        sub_result = _tool_scrape_url(base + sub)
        if not sub_result.get('error'):
            all_emails += sub_result.get('emails', [])
            all_text.append(sub_result.get('text', '')[:500])

    seen = set()
    unique_emails = []
    for e in all_emails:
        if e not in seen:
            seen.add(e)
            unique_emails.append(e)

    return {
        'emails': unique_emails[:10],
        'text': ' '.join(t for t in all_text if t)[:2000],
        'links': main.get('links', []),
        'url': url,
        'subpages_checked': ['/contact', '/about', '/about-us', '/contact-us', '/team'],
    }


def _tool_extract_linktree(url: str) -> dict:
    """Extract all external links from a link aggregator page."""
    html = _fetch_html(url)
    if not html:
        return {'error': f'Could not fetch {url}', 'links': [], 'emails': []}

    links = _extract_links(html, url)
    emails = _extract_emails_from_text(html)

    # Filter out known platform links
    external = [l for l in links if not any(d in l.lower() for d in _SKIP_DOMAINS)]

    return {
        'links': external[:12],
        'emails': emails[:5],
        'url': url,
    }


# ─────────────────────────────────────────────
# CHANNELCRAWLER API
# ─────────────────────────────────────────────

def _channelcrawler_lookup(channel_id: str, api_key: str) -> str | None:
    """
    Look up a YouTube channel's email via ChannelCrawler API.
    Uses POST /v1/channels/email endpoint.
    Returns email string or None.
    """
    try:
        r = requests.post(
            f'{CC_API_URL}/v1/channels/email',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={'channel_id': channel_id},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            # Try common response field names
            email = (data.get('email') or data.get('business_email')
                     or data.get('contact_email') or '')
            if email and '@' in email and _is_valid_email(email):
                return email.lower().strip()
            # Maybe nested under 'data' or 'channel'
            inner = data.get('data') or data.get('channel') or {}
            if isinstance(inner, dict):
                email = (inner.get('email') or inner.get('business_email') or '')
                if email and '@' in email and _is_valid_email(email):
                    return email.lower().strip()
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# APIFY — YouTube hidden email (two actors)
# ─────────────────────────────────────────────

def _apify_exporter24(channel_url: str, channel_id: str, api_token: str) -> tuple[str | None, str]:
    """
    Primary Apify actor: exporter24/youtube-email-scraper ($0.03/result).
    Accepts channel URL. Returns email list.
    """
    try:
        from apify_client import ApifyClient

        target_url = f'https://www.youtube.com/channel/{channel_id}' if channel_id else channel_url

        client = ApifyClient(token=api_token)
        run = client.actor('exporter24/youtube-email-scraper').call(
            run_input={'url': target_url},
            timeout_secs=120,
        )

        items = client.dataset(run['defaultDatasetId']).list_items().items
        if not items:
            return None, 'exporter24: 0 items'

        item = items[0]
        debug = json.dumps(item, ensure_ascii=False, default=str)[:500]

        # email field can be a list or string
        email_field = item.get('email', '')
        if isinstance(email_field, list):
            for e in email_field:
                if isinstance(e, str) and _is_valid_email(e):
                    return e.lower().strip(), debug
        elif isinstance(email_field, str) and _is_valid_email(email_field):
            return email_field.lower().strip(), debug

        return None, debug

    except Exception as e:
        return None, f'exporter24 error: {e}'


def _apify_endspec_instant(handle: str, api_token: str) -> tuple[str | None, str]:
    """
    Fallback Apify actor: endspec/youtube-instant-email-scraper ($0.075/result).
    Only works with channelHandle (not channelId).
    """
    if not handle:
        return None, 'endspec: no handle available'

    try:
        from apify_client import ApifyClient

        if not handle.startswith('@'):
            handle = '@' + handle

        client = ApifyClient(token=api_token)
        run = client.actor('endspec/youtube-instant-email-scraper').call(
            run_input={'channelHandle': handle},
            timeout_secs=120,
        )

        items = client.dataset(run['defaultDatasetId']).list_items().items
        if not items:
            return None, 'endspec: 0 items'

        item = items[0]
        debug = json.dumps(item, ensure_ascii=False, default=str)[:500]

        if item.get('found') and item.get('email'):
            email = item['email']
            if _is_valid_email(email):
                return email.lower().strip(), debug

        return None, debug

    except Exception as e:
        return None, f'endspec error: {e}'


# ─────────────────────────────────────────────
# TOOL DEFINITIONS FOR CLAUDE
# ─────────────────────────────────────────────

_TOOLS = [
    {
        'name': 'web_search',
        'description': (
            'Search the web using DuckDuckGo + Bing. Returns URLs, titles, snippets, '
            'and any emails found directly in snippets. Use targeted queries like: '
            '"CreatorName email contact", "CreatorName business inquiry", '
            '"@handle email", "site:domain.com contact"'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Search query'}
            },
            'required': ['query'],
        },
    },
    {
        'name': 'scrape_url',
        'description': (
            'Fetch a URL and extract emails + visible text + links from the page. '
            'Use for: social media profiles, personal websites, portfolio pages, '
            'search result pages. Returns any emails found, page text, and outgoing links.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'url': {'type': 'string', 'description': 'URL to scrape'}
            },
            'required': ['url'],
        },
    },
    {
        'name': 'scrape_deep',
        'description': (
            'Deep-scrape a website: fetches the main URL plus /contact, /about, /about-us, '
            '/contact-us, and /team subpages. Use for personal/agency/management websites '
            'where the email might be on a subpage.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'url': {'type': 'string', 'description': 'Base URL to deep-scrape'}
            },
            'required': ['url'],
        },
    },
    {
        'name': 'extract_linktree',
        'description': (
            'Extract all external links from a link aggregator (Linktree, bio.link, '
            'beacons.ai, etc.). Returns the list of links the creator has listed. '
            'You can then scrape interesting links individually.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'url': {'type': 'string', 'description': 'Link aggregator URL'}
            },
            'required': ['url'],
        },
    },
    {
        'name': 'report_email',
        'description': (
            'Report that you found the creator\'s contact email. Call this when you are '
            'confident you found the right email. This ends the investigation.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'email': {'type': 'string', 'description': 'The email address found'},
                'confidence': {
                    'type': 'string',
                    'enum': ['high', 'medium', 'low'],
                    'description': 'How confident you are this is the right contact email',
                },
                'reasoning': {
                    'type': 'string',
                    'description': 'Brief explanation of how you found/verified this email',
                },
            },
            'required': ['email', 'confidence', 'reasoning'],
        },
    },
]

# ─────────────────────────────────────────────
# TOOL DISPATCHER
# ─────────────────────────────────────────────

def _execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool and return JSON string result."""
    try:
        if name == 'web_search':
            result = _tool_web_search(input_data['query'])
        elif name == 'scrape_url':
            result = _tool_scrape_url(input_data['url'])
        elif name == 'scrape_deep':
            result = _tool_scrape_deep(input_data['url'])
        elif name == 'extract_linktree':
            result = _tool_extract_linktree(input_data['url'])
        elif name == 'report_email':
            result = {'reported': True, **input_data}
        else:
            result = {'error': f'Unknown tool: {name}'}
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({'error': str(e)})


# ─────────────────────────────────────────────
# FREE WEB PIPELINE — deterministic, no paid APIs
# ─────────────────────────────────────────────

def _og_desc(html: str) -> str:
    """Extract og:description meta tag content."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        tag = soup.find('meta', property='og:description')
        if tag and tag.get('content'):
            return tag['content']
    except Exception:
        pass
    return ''


def _is_site_own_email(email: str, page_url: str) -> bool:
    """Return True if email belongs to the scraped site itself (not the creator)."""
    try:
        from urllib.parse import urlparse
        site_domain = urlparse(page_url).netloc.lower().lstrip('www.')
        email_domain = email.split('@')[1].lower() if '@' in email else ''
        if not email_domain or not site_domain:
            return False
        return (email_domain == site_domain or
                email_domain.endswith('.' + site_domain) or
                site_domain.endswith('.' + email_domain))
    except Exception:
        return False


def _scrape_for_creator_email(url: str) -> list[str]:
    """Scrape a URL for emails, filtering out site-owned emails."""
    result = _tool_scrape_url(url)
    emails = result.get('emails', [])
    return [e for e in emails if not _is_site_own_email(e, url)]


def _fetch_video_descriptions(channel_url: str, n: int = 3) -> list[str]:
    """Fetch descriptions of last N videos — creators often put email there."""
    if not channel_url:
        return []
    try:
        import yt_dlp
        opts = {
            'skip_download': True, 'quiet': True, 'no_warnings': True,
            'ignoreerrors': True, 'playlistend': n, 'extract_flat': False,
        }
        target = channel_url.rstrip('/') + '/videos'
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            return []
        entries = info.get('entries') or []
        descs = []
        for e in entries:
            if isinstance(e, dict):
                d = e.get('description', '') or ''
                if d and d not in descs:
                    descs.append(d)
        return descs[:n]
    except Exception:
        return []


def _llm_verify_emails(channel_data: dict, emails: list[str],
                       sources: dict[str, str]) -> list[dict]:
    """
    Haiku verifies multiple email candidates.
    Deduplicates identical emails, validates each against channel context.
    Returns list of verified emails with confidence.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return [{'email': e, 'confidence': 'medium', 'reasoning': 'AI verification unavailable'}
                for e in emails]

    # Deduplicate
    unique = list(dict.fromkeys(e.lower().strip() for e in emails))
    if not unique:
        return []

    # If only one unique email, no need for AI
    if len(unique) == 1:
        return [{'email': unique[0], 'confidence': 'high',
                 'reasoning': sources.get(unique[0], 'Found via free web search')}]

    try:
        import anthropic

        name = channel_data.get('name', '')
        handle = channel_data.get('handle', '')

        email_list = '\n'.join(
            f'- {e} (source: {sources.get(e, "unknown")})'
            for e in unique
        )

        prompt = f"""You are verifying email addresses found for a YouTube creator.

Channel: {name} (handle: {handle})

Candidate emails:
{email_list}

For EACH email, decide if it likely belongs to this creator:
- Check if email username relates to creator name/handle
- Reject emails from unrelated companies or platforms
- Gmail/Yahoo/Outlook are valid if username matches creator

Respond ONLY with JSON array:
[{{"email": "x@y.com", "valid": true, "confidence": "high|medium|low", "reasoning": "brief reason"}}]

Include ALL emails in your response. Mark invalid ones as valid: false."""

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            verified = []
            for item in data:
                if item.get('valid') and item.get('email') and _is_valid_email(item['email']):
                    verified.append({
                        'email': item['email'].lower().strip(),
                        'confidence': item.get('confidence', 'medium'),
                        'reasoning': item.get('reasoning', ''),
                    })
            if verified:
                return verified
    except Exception:
        pass

    # Fallback: return all unique emails with medium confidence
    return [{'email': e, 'confidence': 'medium',
             'reasoning': sources.get(e, 'Found via web search')}
            for e in unique]


def _llm_synthesize_email(channel_data: dict, evidence: list[tuple[str, str]],
                          candidate_emails: list[str]) -> dict | None:
    """Claude Haiku last-resort: analyze ALL collected evidence to find/infer email."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = ['=== YouTube Channel ===']
        for field, label in [('name', 'Name'), ('handle', 'Handle'),
                             ('description', 'Description'), ('location', 'Location')]:
            if channel_data.get(field):
                parts.append(f'{label}: {channel_data[field]}')
        for k in ('instagram', 'twitter', 'tiktok', 'facebook', 'linkedin'):
            if channel_data.get(k):
                parts.append(f'{k.capitalize()}: {channel_data[k]}')
        if channel_data.get('all_links'):
            parts.append('Links: ' + ', '.join(channel_data['all_links'][:10]))

        if evidence:
            parts.append('\n=== Evidence Collected ===')
            for label, content in evidence[:12]:
                if content:
                    parts.append(f'[{label}]\n{content[:500]}')

        if candidate_emails:
            parts.append('\n=== Candidate Emails ===')
            parts.append(', '.join(candidate_emails[:10]))

        context = '\n'.join(parts)[:6000]

        prompt = f"""You are finding a YouTube creator's contact email.

{context}

CRITICAL: You must find the email that belongs to THIS SPECIFIC creator, not emails from
unrelated companies, other creators, or the websites themselves.

Steps:
1. Check if any candidate email username matches the creator's name/handle (e.g. "eceronay@gmail.com" for "Ece Ronay")
2. Check if any email was found on the creator's OWN website or social media
3. Look for obfuscated emails in evidence: "name at domain dot com"
4. If a personal domain was found in their links, guess: contact@domain, hello@domain
5. Cross-reference channel name/handle with email usernames

REJECT these even if found:
- Emails from news/media/TV sites (e.g. iletisim@aksutv.com.tr)
- Emails from other YouTube channels or creators
- Emails from influencer database sites
- Emails where the username has no relation to the creator

ACCEPT: Gmail/Yahoo/Outlook ARE valid if the username relates to the creator.

Respond ONLY with JSON:
{{"found": true, "email": "x@domain.com", "confidence": "high|medium|low", "reasoning": "one sentence"}}
or {{"found": false}}"""

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        if data.get('found') and data.get('email'):
            email = data['email'].lower().strip()
            if _is_valid_email(email):
                return {
                    'found': True,
                    'email': email,
                    'source': 'ai_analysis',
                    'confidence': data.get('confidence', 'low'),
                    'reasoning': data.get('reasoning', ''),
                }
    except Exception:
        pass
    return None


def _free_web_pipeline(channel_data: dict, steps: list[str], deadline: float) -> dict | None:
    """
    Parallel free email investigation — 10+ agents run simultaneously.
    Each agent independently searches for emails using different methods.
    All results collected, deduped, and verified by Haiku.
    """
    name = channel_data.get('name', '')
    handle = channel_data.get('handle', '').lstrip('@')
    description = channel_data.get('description', '')
    all_links = channel_data.get('all_links', [])
    channel_url = channel_data.get('channel_url', '')

    # ── Quick check: Obfuscated emails in description (instant, no network) ──
    if description:
        for m in _RE_OBFUSCATED.finditer(description):
            local, domain_part, tld = m.group(1), m.group(2), m.group(3)
            e = f'{local}@{domain_part}.{tld}'.lower()
            if _is_valid_email(e):
                steps.append(f'Obfuscated email in description: {e}')
                return {'found': True, 'email': e, 'source': 'description',
                        'confidence': 'high', 'steps': steps,
                        'reasoning': 'Obfuscated email decoded from channel description.'}

    # ── Classify links ──
    aggregator_links = []
    company_links = []
    for lnk in all_links:
        lo = lnk.lower()
        if any(d in lo for d in _LINK_AGGREGATORS):
            aggregator_links.append(lnk)
        elif not any(d in lo for d in (*_SKIP_DOMAINS, *_SOCIAL_DOMAINS)):
            company_links.append(lnk)

    # Short name for search queries
    short_name = name
    if name:
        for suffix in (' Official', ' Music', ' VEVO', ' TV', ' Channel', ' Resmi'):
            if name.endswith(suffix):
                short_name = name[:-len(suffix)].strip()
                break

    # ─────────────────────────────────────────
    # AGENT DEFINITIONS — each returns list of (email, source_label)
    # ─────────────────────────────────────────

    def agent_external_links() -> list[tuple[str, str]]:
        """Agent 1: Scrape external links from channel (personal websites)."""
        found = []
        for link in company_links[:3]:
            result = _tool_scrape_deep(link)
            for e in result.get('emails', []):
                if _is_valid_email(e) and not _is_site_own_email(e, link):
                    found.append((e, f'External link: {link}'))
        return found

    def agent_linktree() -> list[tuple[str, str]]:
        """Agent 2: Extract emails from link aggregators (Linktree, bio.link)."""
        found = []
        for agg in aggregator_links[:2]:
            lt = _tool_extract_linktree(agg)
            for e in lt.get('emails', []):
                if _is_valid_email(e):
                    found.append((e, f'Link aggregator: {agg}'))
            for link in lt.get('links', [])[:3]:
                for e in _scrape_for_creator_email(link):
                    found.append((e, f'Linktree link: {link}'))
        return found

    def _agent_social(platform: str) -> list[tuple[str, str]]:
        """Generic social media bio scraper."""
        url = channel_data.get(platform, '')
        if not url:
            return []
        html = _fetch_html(url)
        if not html and platform == 'twitter':
            alt = url.replace('x.com', 'twitter.com') if 'x.com' in url else url.replace('twitter.com', 'x.com')
            html = _fetch_html(alt)
        if not html:
            return []
        found = []
        for e in _extract_emails_from_text(html):
            if _is_valid_email(e):
                found.append((e, f'{platform.capitalize()} profile'))
        bio = _og_desc(html)
        if bio:
            for m in _RE_OBFUSCATED.finditer(bio):
                local, dp, tld = m.group(1), m.group(2), m.group(3)
                e = f'{local}@{dp}.{tld}'.lower()
                if _is_valid_email(e):
                    found.append((e, f'{platform.capitalize()} bio (obfuscated)'))
            for m in RE_EMAIL.finditer(bio):
                e = m.group(1).lower().strip().rstrip('.')
                if _is_valid_email(e):
                    found.append((e, f'{platform.capitalize()} bio'))
        return found

    def agent_instagram() -> list[tuple[str, str]]:
        """Agent 3: Instagram profile."""
        return _agent_social('instagram')

    def agent_twitter() -> list[tuple[str, str]]:
        """Agent 4: Twitter/X profile."""
        return _agent_social('twitter')

    def agent_tiktok() -> list[tuple[str, str]]:
        """Agent 5: TikTok profile."""
        return _agent_social('tiktok')

    def agent_facebook() -> list[tuple[str, str]]:
        """Agent 6: Facebook profile."""
        return _agent_social('facebook')

    def agent_video_descriptions() -> list[tuple[str, str]]:
        """Agent 7: Scan recent video descriptions for emails."""
        if not channel_url:
            return []
        found = []
        descs = _fetch_video_descriptions(channel_url, n=3)
        for i, desc in enumerate(descs):
            if not desc:
                continue
            for m in RE_EMAIL.finditer(desc):
                e = m.group(1).lower().strip().rstrip('.')
                if _is_valid_email(e):
                    found.append((e, f'Video #{i+1} description'))
        return found

    def _search_and_extract(search_fn, engine_name: str, query: str) -> list[tuple[str, str]]:
        """Run a search engine, extract emails from snippets + scrape top results."""
        found = []
        try:
            results = search_fn(query)
        except Exception:
            return found
        # Emails in snippets
        for item in results:
            for text in (item.get('snippet', ''), item.get('title', '')):
                for e in _extract_emails_from_text(text):
                    if not _is_site_own_email(e, item.get('url', '')):
                        found.append((e, f'{engine_name} snippet: {query}'))
        # Scrape top results
        for item in results[:3]:
            url = item.get('url', '')
            if not url or any(d in url.lower() for d in (*_SKIP_DOMAINS, *_SOCIAL_DOMAINS)):
                continue
            result = _tool_scrape_url(url)
            page_text = result.get('text', '').lower()
            name_lower = name.lower() if name else ''
            handle_lower = handle.lower() if handle else ''
            mentions = (name_lower and name_lower in page_text) or (handle_lower and handle_lower in page_text)
            for e in result.get('emails', []):
                if _is_valid_email(e) and not _is_site_own_email(e, url):
                    tag = 'relevant' if mentions else 'unrelated'
                    found.append((e, f'{engine_name} → {url} ({tag})'))
        return found

    def agent_ddg_search() -> list[tuple[str, str]]:
        """Agent 8: DuckDuckGo search."""
        q = f'"{name}" email contact' if name else f'"{handle}" email'
        return _search_and_extract(_search_ddg, 'DuckDuckGo', q)

    def agent_bing_search() -> list[tuple[str, str]]:
        """Agent 9: Bing search."""
        q = f'"{short_name}" email iletisim' if short_name else f'"{handle}" email'
        return _search_and_extract(_search_bing, 'Bing', q)

    def agent_serper_search() -> list[tuple[str, str]]:
        """Agent 10: Serper.dev Google search (if API key available)."""
        if not os.environ.get('SERPER_API_KEY', ''):
            return []
        q = f'"{name}" email contact' if name else f'"{handle}" email'
        return _search_and_extract(_search_serper, 'Serper/Google', q)

    def agent_yahoo_search() -> list[tuple[str, str]]:
        """Agent 11: Yahoo search."""
        q = f'"{short_name or handle}" youtube email contact'
        return _search_and_extract(_search_yahoo, 'Yahoo', q)

    def agent_ecosia_search() -> list[tuple[str, str]]:
        """Agent 12: Ecosia search."""
        q = f'"{name}" email business contact' if name else f'"{handle}" email'
        return _search_and_extract(_search_ecosia, 'Ecosia', q)

    def agent_startpage_search() -> list[tuple[str, str]]:
        """Agent 13: Startpage search (Google proxy)."""
        q = f'{short_name or handle} youtube creator email business'
        return _search_and_extract(_search_startpage, 'Startpage', q)

    def agent_handle_search() -> list[tuple[str, str]]:
        """Agent 14: Handle-focused search across engines."""
        if not handle:
            return []
        found = []
        for fn, eng in [(_search_ddg, 'DDG'), (_search_bing, 'Bing')]:
            try:
                results = fn(f'@{handle} email')
                for item in results:
                    for text in (item.get('snippet', ''), item.get('title', '')):
                        for e in _extract_emails_from_text(text):
                            if not _is_site_own_email(e, item.get('url', '')):
                                found.append((e, f'{eng} handle search'))
            except Exception:
                pass
        return found

    def agent_domain_guess() -> list[tuple[str, str]]:
        """Agent 15: Guess emails from personal domains found in links."""
        found = []
        from urllib.parse import urlparse
        for link in company_links[:3]:
            try:
                domain = urlparse(link).netloc.lstrip('www.')
                if domain:
                    for prefix in ('contact', 'hello', 'info', 'business'):
                        found.append((f'{prefix}@{domain}', f'Domain guess: {domain}'))
            except Exception:
                pass
        return found

    # ─────────────────────────────────────────
    # RUN ALL AGENTS IN PARALLEL
    # ────────��────────────────────────────────

    agents = {
        'External Links': agent_external_links,
        'Linktree': agent_linktree,
        'Instagram': agent_instagram,
        'Twitter': agent_twitter,
        'TikTok': agent_tiktok,
        'Facebook': agent_facebook,
        'Video Descriptions': agent_video_descriptions,
        'DuckDuckGo': agent_ddg_search,
        'Bing': agent_bing_search,
        'Serper/Google': agent_serper_search,
        'Yahoo': agent_yahoo_search,
        'Ecosia': agent_ecosia_search,
        'Startpage': agent_startpage_search,
        'Handle Search': agent_handle_search,
        'Domain Guess': agent_domain_guess,
    }

    steps.append(f'Launching {len(agents)} parallel email agents...')
    all_found: list[tuple[str, str]] = []  # (email, source)
    agent_results: dict[str, int] = {}  # agent_name -> email count

    with ThreadPoolExecutor(max_workers=12) as executor:
        future_map = {
            executor.submit(fn): agent_name
            for agent_name, fn in agents.items()
        }
        for future in as_completed(future_map):
            agent_name = future_map[future]
            try:
                results = future.result(timeout=max(0, deadline - time.time()))
                agent_results[agent_name] = len(results)
                all_found.extend(results)
                if results:
                    steps.append(f'  {agent_name}: found {len(results)} email(s)')
            except Exception:
                agent_results[agent_name] = 0

    active = sum(1 for v in agent_results.values() if v > 0)
    steps.append(f'{active}/{len(agents)} agents found emails, {len(all_found)} total results')

    # ─────────────────────────────────────────
    # COLLECT & DEDUPLICATE
    # ──────���────────────���─────────────────────

    candidate_emails: list[str] = []
    email_sources: dict[str, str] = {}
    for email, source in all_found:
        e = email.lower().strip()
        if e not in candidate_emails:
            candidate_emails.append(e)
            email_sources[e] = source
        else:
            # Append additional source info
            email_sources[e] += f' + {source}'

    unique_candidates = [e for e in candidate_emails if _is_valid_email(e)]

    # ─────────────────────────────────────────
    # HAIKU VERIFICATION
    # ─────���─────────────────────────────────��─

    if unique_candidates:
        steps.append(f'{len(unique_candidates)} unique candidate(s), running AI verification...')
        verified = _llm_verify_emails(channel_data, unique_candidates, email_sources)
        if verified:
            steps.append(f'AI verified {len(verified)} email(s): {", ".join(v["email"] for v in verified)}')
            if len(verified) == 1:
                return {'found': True, 'email': verified[0]['email'], 'source': 'web_search',
                        'confidence': verified[0]['confidence'], 'steps': steps,
                        'reasoning': verified[0]['reasoning']}
            else:
                return {'found': True, 'email': verified[0]['email'],
                        'all_emails': [v['email'] for v in verified],
                        'email_details': verified,
                        'source': 'web_search', 'confidence': verified[0]['confidence'],
                        'steps': steps,
                        'reasoning': f'Found {len(verified)} verified emails via parallel agents.'}

    # No candidates — try AI synthesis on evidence
    steps.append('No candidates from agents, trying AI synthesis...')
    evidence = [(src, e) for e, src in email_sources.items()] if email_sources else []
    result = _llm_synthesize_email(channel_data, evidence, [])
    if result:
        result['steps'] = steps
        return result

    return None


# ─────────────────────────────────────────────
# BUILD SYSTEM PROMPT
# ─────────────────────────────────────────────

def _build_system_prompt() -> str:
    return """You are an elite digital detective finding YouTube creators' contact emails.

CRITICAL RULE: Call exactly ONE tool per round. Never call multiple tools at once.
Think step by step. After each tool result, analyze it carefully before deciding the next step.

## Investigation Order (follow this exactly)

STEP 1: Check the channel's links. If there's a link aggregator (Linktree, bio.link, beacons.ai), call extract_linktree on it.
STEP 2: If external/personal website links exist, call scrape_deep on the most promising one.
STEP 3: If social media profiles exist (Instagram, Twitter, TikTok), call scrape_url on each one at a time.
STEP 4: Search the web: "{creator_name} email contact youtube"
STEP 5: Search differently: "{handle} business email" or "{name} management agency contact"
STEP 6: If you found any interesting URL in previous results, scrape_url or scrape_deep it.
STEP 7: Try one more creative search based on clues found so far.
STEP 8: If still nothing, try "{name} interview" or "{name} about" to find press/interview pages.

## When you find an email
- Call report_email IMMEDIATELY. Do not continue investigating.
- Gmail, Yahoo, Hotmail, Outlook are ALL VALID — many creators use personal email.

## When NOT to report
- noreply@, support@platform.com, info@youtube.com — these are platform emails
- Emails clearly belonging to unrelated third-party companies
- Emails from the scraped site itself (e.g. contact@socialblade.com found on socialblade.com)

## Key principle
Each round: ONE tool call. Analyze result. Decide next step. Be methodical."""


def _build_user_message(channel_data: dict, pre_evidence: str = '') -> str:
    """Build the initial investigation brief for the AI."""
    parts = ['## YouTube Channel Under Investigation\n']

    for field, label in [
        ('name', 'Channel Name'), ('handle', 'Handle'), ('channel_url', 'Channel URL'),
        ('description', 'Description'), ('location', 'Location'),
        ('subscribers', 'Subscribers'), ('email', 'Email on page (if any)'),
    ]:
        val = channel_data.get(field, '')
        if val:
            parts.append(f'**{label}:** {val}')

    # Social links
    socials = []
    for k in ('instagram', 'twitter', 'tiktok', 'facebook', 'linkedin'):
        if channel_data.get(k):
            socials.append(f'- {k.capitalize()}: {channel_data[k]}')
    if socials:
        parts.append('\n**Social Media:**')
        parts.extend(socials)

    # All links
    all_links = channel_data.get('all_links', [])
    if all_links:
        parts.append('\n**Links found on channel:**')
        for link in all_links[:15]:
            parts.append(f'- {link}')

    if pre_evidence:
        parts.append(f'\n## Pre-collected Evidence\n{pre_evidence}')

    parts.append('\n## Your Mission')
    parts.append('Find this creator\'s business/contact email. Investigate every lead.')
    parts.append('Start with the most promising sources and work outward.')

    return '\n'.join(parts)


# ─────────────────────────────────────────────
# MAIN AGENT LOOP
# ─────────────────────────────────────────────

def find_email_v2(channel_data: dict) -> dict:
    """
    AI Detective email finder — iterative tool-use agent.
    Returns: {'found': True, 'email': str, 'source': str, 'confidence': str,
              'reasoning': str, 'steps': list[str]}
    Or:      {'found': False, 'steps': list[str]}
    """
    deadline = time.time() + 90  # 90 second hard cap

    steps: list[str] = []  # Human-readable investigation log

    # ── Pre-check: YouTube InnerTube hidden email ──
    channel_id = channel_data.get('channel_id', '')
    channel_url = channel_data.get('channel_url', '')
    if not channel_id and channel_url:
        m = re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', channel_url)
        if m:
            channel_id = m.group(1)

    if channel_id:
        steps.append('Checking YouTube InnerTube API for hidden email...')
        it_email, has_hidden = _fetch_email_innertube(channel_id)
        if it_email and _is_valid_email(it_email):
            steps.append(f'Found hidden email via InnerTube: {it_email}')
            return {'found': True, 'email': it_email, 'source': 'youtube_hidden',
                    'confidence': 'high', 'steps': steps,
                    'reasoning': 'Found via YouTube InnerTube API (hidden behind "View email address" button).'}

    if channel_url:
        steps.append('Trying yt-dlp about page extraction...')
        ydl_email = _fetch_email_ydl_about(channel_url)
        if ydl_email and _is_valid_email(ydl_email):
            steps.append(f'Found email via yt-dlp: {ydl_email}')
            return {'found': True, 'email': ydl_email, 'source': 'youtube_about',
                    'confidence': 'high', 'steps': steps,
                    'reasoning': 'Found via yt-dlp full about page extraction.'}

    # Already have email on channel
    existing = channel_data.get('email', '')
    if existing and _is_valid_email(existing):
        steps.append(f'Email already on channel page: {existing}')
        return {'found': True, 'email': existing, 'source': 'channel',
                'confidence': 'high', 'steps': steps,
                'reasoning': 'Listed on the channel about page.'}

    # ── FREE WEB PIPELINE — exhaustive free investigation ──
    steps.append('Starting free web investigation pipeline...')
    free_result = _free_web_pipeline(channel_data, steps, deadline)
    if free_result:
        return free_result
    steps.append('Free pipeline exhausted — trying paid services...')

    # ── PAID FALLBACK 1: ChannelCrawler API ──
    cc_key = os.environ.get('CC_API_KEY', '')
    if cc_key and channel_id:
        steps.append('Trying ChannelCrawler API...')
        cc_result = _channelcrawler_lookup(channel_id, cc_key)
        if cc_result:
            steps.append(f'ChannelCrawler found: {cc_result}')
            return {
                'found': True,
                'email': cc_result,
                'source': 'channelcrawler',
                'confidence': 'high',
                'reasoning': 'Found via ChannelCrawler database.',
                'steps': steps,
            }
        else:
            steps.append('ChannelCrawler: no email in database.')

    # ── PAID FALLBACK 2: Apify exporter24 ($0.03/result) ──
    apify_token = os.environ.get('APIFY_API_TOKEN', '')
    if apify_token and (channel_url or channel_id):
        steps.append('Trying Apify exporter24 email scraper...')
        apify_result, apify_debug = _apify_exporter24(channel_url, channel_id, apify_token)
        steps.append(f'exporter24: {apify_debug[:300]}')
        if apify_result:
            steps.append(f'exporter24 found: {apify_result}')
            return {
                'found': True,
                'email': apify_result,
                'source': 'apify_exporter24',
                'confidence': 'high',
                'reasoning': 'Found via Apify exporter24 (YouTube hidden business email).',
                'steps': steps,
            }

    # ── PAID FALLBACK 3: Apify endspec instant ($0.075/result, handle only) ──
    handle = channel_data.get('handle', '')
    if apify_token and handle:
        steps.append(f'Trying Apify endspec instant for {handle}...')
        endspec_result, endspec_debug = _apify_endspec_instant(handle, apify_token)
        steps.append(f'endspec: {endspec_debug[:300]}')
        if endspec_result:
            steps.append(f'endspec found: {endspec_result}')
            return {
                'found': True,
                'email': endspec_result,
                'source': 'apify_endspec',
                'confidence': 'high',
                'reasoning': 'Found via Apify endspec instant (YouTube hidden business email).',
                'steps': steps,
            }

    steps.append('Investigation complete — no email found.')
    return {'found': False, 'steps': steps}
