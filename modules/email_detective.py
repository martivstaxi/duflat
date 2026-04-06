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
    tld_match = re.search(r'\.([a-z]{2,12})$', domain)
    if not tld_match:
        return False
    tld = tld_match.group(1)
    if tld in _FAKE_TLDS:
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


def _search_brave(query: str, count: int = 10) -> list[dict]:
    """Web search via Brave Search API ($5 free credits/month)."""
    api_key = os.environ.get('BRAVE_API_KEY', '')
    if not api_key:
        return []
    try:
        r = requests.get(
            'https://api.search.brave.com/res/v1/web/search',
            headers={'X-Subscription-Token': api_key, 'Accept': 'application/json'},
            params={'q': query, 'count': count},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for item in data.get('web', {}).get('results', []):
            results.append({
                'url': item.get('url', ''),
                'title': item.get('title', ''),
                'snippet': item.get('description', ''),
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


def _tool_web_search(query: str) -> dict:
    """
    Multi-engine web search. Priority order:
    1. Serper.dev (Google results, best quality) — if SERPER_API_KEY set
    2. Brave Search API — if BRAVE_API_KEY set
    3. DuckDuckGo HTML scraping (free, no key)
    4. Bing HTML scraping (free, no key)
    Merges results from all available engines, deduplicates by URL.
    """
    results = []
    seen_urls: set[str] = set()

    def _merge(items: list[dict]):
        for item in items:
            url = item.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(item)

    # Tier 1: API-based search (best quality)
    serper_results = _search_serper(query)
    if serper_results:
        _merge(serper_results)

    brave_results = _search_brave(query)
    if brave_results:
        _merge(brave_results)

    # Tier 2: HTML scraping (free fallback)
    if len(results) < 5:
        _merge(_search_ddg(query))

    if len(results) < 5:
        _merge(_search_bing(query))

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
    Deterministic free web investigation pipeline.
    Returns result dict if email found, None otherwise.
    Uses only free resources: DDG, Bing, direct scraping, Haiku synthesis.
    """
    name = channel_data.get('name', '')
    handle = channel_data.get('handle', '').lstrip('@')
    description = channel_data.get('description', '')
    all_links = channel_data.get('all_links', [])
    channel_url = channel_data.get('channel_url', '')
    location = channel_data.get('location', '')

    evidence: list[tuple[str, str]] = []
    candidate_emails: list[str] = []
    found_domains: list[str] = []

    # ── Step 1: Obfuscated emails in description ──
    if description:
        for m in _RE_OBFUSCATED.finditer(description):
            local, domain_part, tld = m.group(1), m.group(2), m.group(3)
            e = f'{local}@{domain_part}.{tld}'.lower()
            if _is_valid_email(e):
                steps.append(f'Obfuscated email in description: {e}')
                return {'found': True, 'email': e, 'source': 'description',
                        'confidence': 'high', 'steps': steps,
                        'reasoning': 'Obfuscated email decoded from channel description.'}
        evidence.append(('description', description[:500]))

    # ── Step 2: External links (personal websites) ──
    aggregator_links = []
    company_links = []
    for lnk in all_links:
        lo = lnk.lower()
        if any(d in lo for d in _LINK_AGGREGATORS):
            aggregator_links.append(lnk)
        elif not any(d in lo for d in (*_SKIP_DOMAINS, *_SOCIAL_DOMAINS)):
            company_links.append(lnk)

    steps.append(f'Checking {len(company_links)} external links + {len(aggregator_links)} link aggregators...')
    for link in company_links[:4]:
        if time.time() > deadline:
            break
        result = _tool_scrape_deep(link)
        emails = [e for e in result.get('emails', []) if not _is_site_own_email(e, link)]
        if result.get('text'):
            evidence.append((f'link:{link}', result['text'][:400]))
        try:
            from urllib.parse import urlparse
            domain = urlparse(link).netloc.lstrip('www.')
            if domain and domain not in found_domains:
                found_domains.append(domain)
        except Exception:
            pass
        if emails:
            steps.append(f'Found email via external link {link}: {emails[0]}')
            return {'found': True, 'email': emails[0], 'source': 'external_link',
                    'confidence': 'high', 'steps': steps,
                    'reasoning': f'Found on external website: {link}'}

    # ── Step 3: Link aggregators (Linktree etc.) ──
    for agg in aggregator_links[:2]:
        if time.time() > deadline:
            break
        lt_result = _tool_extract_linktree(agg)
        if lt_result.get('emails'):
            e = lt_result['emails'][0]
            if _is_valid_email(e):
                steps.append(f'Found email in linktree {agg}: {e}')
                return {'found': True, 'email': e, 'source': 'linktree',
                        'confidence': 'high', 'steps': steps,
                        'reasoning': f'Found on link aggregator: {agg}'}
        for link in lt_result.get('links', [])[:4]:
            if time.time() > deadline:
                break
            emails = _scrape_for_creator_email(link)
            if emails:
                steps.append(f'Found email via linktree link {link}: {emails[0]}')
                return {'found': True, 'email': emails[0], 'source': 'linktree',
                        'confidence': 'high', 'steps': steps,
                        'reasoning': f'Found via link aggregator → {link}'}

    # ── Step 4: Social media bios ──
    for platform in ('instagram', 'twitter', 'tiktok', 'facebook'):
        if time.time() > deadline:
            break
        url = channel_data.get(platform, '')
        if not url:
            continue
        steps.append(f'Checking {platform} profile...')
        html = _fetch_html(url)
        if not html:
            # For Twitter/X try alternate domain
            if platform == 'twitter':
                alt = url.replace('x.com', 'twitter.com') if 'x.com' in url else url.replace('twitter.com', 'x.com')
                html = _fetch_html(alt)
            if not html:
                continue
        # Check full HTML for emails
        emails = _extract_emails_from_text(html)
        valid = [e for e in emails if _is_valid_email(e)]
        if valid:
            steps.append(f'Found email on {platform}: {valid[0]}')
            return {'found': True, 'email': valid[0], 'source': platform,
                    'confidence': 'high', 'steps': steps,
                    'reasoning': f'Found in {platform.capitalize()} profile page.'}
        # Check OG description for obfuscated emails
        bio = _og_desc(html)
        if bio:
            for m in _RE_OBFUSCATED.finditer(bio):
                local, domain_part, tld = m.group(1), m.group(2), m.group(3)
                e = f'{local}@{domain_part}.{tld}'.lower()
                if _is_valid_email(e):
                    steps.append(f'Obfuscated email in {platform} bio: {e}')
                    return {'found': True, 'email': e, 'source': platform,
                            'confidence': 'high', 'steps': steps,
                            'reasoning': f'Obfuscated email decoded from {platform.capitalize()} bio.'}
            for m in RE_EMAIL.finditer(bio):
                e = m.group(1).lower().strip().rstrip('.')
                if _is_valid_email(e):
                    steps.append(f'Email in {platform} bio: {e}')
                    return {'found': True, 'email': e, 'source': platform,
                            'confidence': 'high', 'steps': steps,
                            'reasoning': f'Found in {platform.capitalize()} bio.'}
            evidence.append((f'{platform}_bio', bio[:300]))

    # ── Step 5: Video descriptions ──
    if channel_url and time.time() < deadline:
        steps.append('Checking recent video descriptions...')
        video_descs = _fetch_video_descriptions(channel_url, n=3)
        for i, vid_desc in enumerate(video_descs):
            if not vid_desc:
                continue
            for m in _RE_OBFUSCATED.finditer(vid_desc):
                local, domain_part, tld = m.group(1), m.group(2), m.group(3)
                e = f'{local}@{domain_part}.{tld}'.lower()
                if _is_valid_email(e):
                    steps.append(f'Obfuscated email in video #{i+1}: {e}')
                    return {'found': True, 'email': e, 'source': 'video_description',
                            'confidence': 'high', 'steps': steps,
                            'reasoning': f'Obfuscated email in video #{i+1} description.'}
            for m in RE_EMAIL.finditer(vid_desc):
                e = m.group(1).lower().strip().rstrip('.')
                if _is_valid_email(e):
                    steps.append(f'Email in video #{i+1}: {e}')
                    return {'found': True, 'email': e, 'source': 'video_description',
                            'confidence': 'high', 'steps': steps,
                            'reasoning': f'Found in video #{i+1} description.'}
            if i == 0:
                evidence.append(('video_desc', vid_desc[:500]))

    # ── Step 6: Web search (multi-engine) ──
    # Build diverse queries: English + creator's language, name + handle variants
    queries = []
    if name:
        queries.append(f'"{name}" email contact')
        queries.append(f'"{name}" iletisim email')  # Turkish (common for TR creators)
    if handle:
        queries.append(f'"{handle}" email')
    # Name without quotes — broader search
    if name:
        queries.append(f'{name} youtube creator email business inquiry')
    if found_domains:
        queries.append(f'site:{found_domains[0]} contact email')

    seen_urls: set[str] = set()
    steps.append(f'Running {min(len(queries), 4)} web searches...')

    for query in queries[:4]:
        if time.time() > deadline:
            break
        search_result = _tool_web_search(query)

        # Collect snippet emails as evidence (don't trust blindly — too many false positives)
        for e in search_result.get('emails_in_snippets', []):
            if _is_valid_email(e) and e not in candidate_emails:
                candidate_emails.append(e)
                evidence.append((f'snippet_email', f'{e} (found in search snippet for: {query})'))

        # Scrape top results — prefer pages that mention the creator
        for item in search_result.get('results', [])[:4]:
            url = item.get('url', '')
            if not url or url in seen_urls:
                continue
            if any(d in url.lower() for d in (*_SKIP_DOMAINS, *_SOCIAL_DOMAINS)):
                continue
            seen_urls.add(url)
            if time.time() > deadline:
                break

            snippet = item.get('snippet', '')
            evidence.append((f'search:{url}', snippet[:300]))

            result = _tool_scrape_url(url)
            page_text = result.get('text', '').lower()
            page_emails = [e for e in result.get('emails', []) if not _is_site_own_email(e, url)]

            # Only consider emails from pages that mention the creator
            name_lower = name.lower() if name else ''
            handle_lower = handle.lower() if handle else ''
            page_mentions_creator = (
                (name_lower and name_lower in page_text) or
                (handle_lower and handle_lower in page_text)
            )

            for e in page_emails:
                if e not in candidate_emails:
                    candidate_emails.append(e)
                    relevance = 'relevant' if page_mentions_creator else 'unrelated page'
                    evidence.append((f'scraped_email:{url}',
                                     f'{e} (on {relevance} page: {url})'))
                    steps.append(f'Candidate email from {url}: {e} ({relevance})')

    # ── Step 7: Domain email guessing ──
    for domain in found_domains[:3]:
        guesses = [f'{prefix}@{domain}' for prefix in _CONTACT_PREFIXES]
        candidate_emails.extend(guesses)
        evidence.append((f'domain:{domain}',
                         f'Corporate domain. Possible: {", ".join(guesses[:5])}'))

    # ── Step 8: Claude Haiku synthesis ──
    if evidence or candidate_emails:
        steps.append('Running AI analysis on collected evidence...')
        result = _llm_synthesize_email(channel_data, evidence, candidate_emails)
        if result:
            result['steps'] = steps
            steps.append(f'AI found: {result["email"]} ({result["confidence"]})')
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
