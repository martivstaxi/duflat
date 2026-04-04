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
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'was',
    'one', 'our', 'out', 'day', 'get', 'has', 'how', 'new', 'now', 'old',
    'see', 'two', 'way', 'who', 'did', 'its', 'let', 'put', 'say', 'too',
    'use', 'from', 'have', 'this', 'will', 'your', 'that', 'with', 'they',
    'been', 'more', 'when', 'come', 'here', 'just', 'know', 'like', 'look',
    'make', 'most', 'over', 'than', 'them', 'well', 'were',
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


def _tool_web_search(query: str) -> dict:
    """Execute web search via DDG + Bing, return results."""
    results = []

    # DuckDuckGo
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

    # Bing
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
                    url = a['href']
                    if not any(r['url'] == url for r in results):
                        results.append({
                            'url': url,
                            'title': a.get_text(strip=True),
                            'snippet': snippet.get_text(strip=True) if snippet else '',
                        })
    except Exception:
        pass

    # Also extract emails directly from search snippets
    snippet_emails = []
    for r_item in results:
        snippet_emails += _extract_emails_from_text(r_item.get('snippet', ''))
        snippet_emails += _extract_emails_from_text(r_item.get('title', ''))

    return {
        'results': results[:10],
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
# APIFY DATAOVERCOFFEE — YouTube hidden email
# ─────────────────────────────────────────────

def _apify_email_lookup(channel_url: str, channel_id: str, api_token: str) -> tuple[str | None, str]:
    """
    Use Apify DataOverCoffee actor to extract YouTube hidden business email.
    Returns: (email_or_none, debug_info_string)
    """
    try:
        from apify_client import ApifyClient

        # Use channel ID URL for precision (avoids handle resolution issues)
        target_url = f'https://www.youtube.com/channel/{channel_id}' if channel_id else channel_url

        client = ApifyClient(token=api_token)
        run = client.actor('dataovercoffee/youtube-channel-business-email-scraper').call(
            run_input={
                'channelUrls': [target_url],
                'forceFreshEmailScrape': False,
            },
            timeout_secs=120,
        )

        items = client.dataset(run['defaultDatasetId']).list_items().items
        if not items:
            return None, 'Apify returned 0 items'

        item = items[0]
        debug = json.dumps(item, ensure_ascii=False, default=str)[:500]

        # Try common field names
        email = (item.get('email') or item.get('business_email')
                 or item.get('businessEmail') or item.get('contact_email') or '')
        if email and '@' in email and _is_valid_email(email):
            return email.lower().strip(), debug

        # Search all string values for email pattern
        for val in item.values():
            if isinstance(val, str) and '@' in val and _is_valid_email(val):
                return val.lower().strip(), debug

        return None, debug

    except Exception as e:
        return None, f'Apify error: {e}'


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
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return {'found': False, 'error': 'ANTHROPIC_API_KEY not set', 'steps': []}

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

    # ── Start AI Agent Loop ──
    steps.append('Starting AI detective investigation...')

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        return {'found': False, 'error': f'Anthropic client error: {e}', 'steps': steps}

    messages = [
        {'role': 'user', 'content': _build_user_message(channel_data)}
    ]

    for round_num in range(1, MAX_ROUNDS + 1):
        if time.time() > deadline:
            steps.append(f'[Round {round_num}] Time limit reached.')
            break

        steps.append(f'[Round {round_num}] AI is thinking...')

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=_build_system_prompt(),
                tools=_TOOLS,
                messages=messages,
            )
        except Exception as e:
            steps.append(f'[Round {round_num}] API error: {e}')
            break

        # Process response
        assistant_content = response.content
        messages.append({'role': 'assistant', 'content': assistant_content})

        # Check if AI wants to use tools
        tool_uses = [b for b in assistant_content if b.type == 'tool_use']

        if not tool_uses:
            # AI finished without finding — extract any text response
            for b in assistant_content:
                if hasattr(b, 'text') and b.text:
                    steps.append(f'[Round {round_num}] AI conclusion: {b.text[:200]}')
            break

        # Execute tools and collect results
        tool_results = []
        for tu in tool_uses:
            tool_name = tu.name
            tool_input = tu.input

            # Log what the AI is doing
            if tool_name == 'web_search':
                steps.append(f'[Round {round_num}] Searching: "{tool_input.get("query", "")}"')
            elif tool_name == 'scrape_url':
                steps.append(f'[Round {round_num}] Scraping: {tool_input.get("url", "")}')
            elif tool_name == 'scrape_deep':
                steps.append(f'[Round {round_num}] Deep-scraping: {tool_input.get("url", "")}')
            elif tool_name == 'extract_linktree':
                steps.append(f'[Round {round_num}] Extracting links from: {tool_input.get("url", "")}')
            elif tool_name == 'report_email':
                email = tool_input.get('email', '').lower().strip()
                confidence = tool_input.get('confidence', 'medium')
                reasoning = tool_input.get('reasoning', '')
                steps.append(f'[Round {round_num}] EMAIL FOUND: {email} (confidence: {confidence})')

                if _is_valid_email(email):
                    return {
                        'found': True,
                        'email': email,
                        'source': 'ai_detective',
                        'confidence': confidence,
                        'reasoning': reasoning,
                        'steps': steps,
                    }
                else:
                    steps.append(f'[Round {round_num}] Reported email failed validation, continuing...')

            # Execute tool
            if time.time() > deadline:
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.id,
                    'content': json.dumps({'error': 'Time limit reached'}),
                })
                continue

            result_str = _execute_tool(tool_name, tool_input)

            # Log findings
            try:
                result_data = json.loads(result_str)
                emails_found = result_data.get('emails', []) or result_data.get('emails_in_snippets', [])
                if emails_found:
                    steps.append(f'  → Found emails: {", ".join(emails_found[:3])}')
                links_found = result_data.get('links', [])
                if links_found and tool_name == 'extract_linktree':
                    steps.append(f'  → Found {len(links_found)} links')
            except Exception:
                pass

            tool_results.append({
                'type': 'tool_result',
                'tool_use_id': tu.id,
                'content': result_str,
            })

        messages.append({'role': 'user', 'content': tool_results})

        # If stop_reason is end_turn (no more tool calls expected), break
        if response.stop_reason == 'end_turn':
            break

    # ── FALLBACK 1: ChannelCrawler API ──
    cc_key = os.environ.get('CC_API_KEY', '')
    if cc_key and channel_id:
        steps.append('AI Detective could not find email. Trying ChannelCrawler API...')
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

    # ── FALLBACK 2: Apify DataOverCoffee (YouTube hidden email) ──
    apify_token = os.environ.get('APIFY_API_TOKEN', '')
    if apify_token and (channel_url or channel_id):
        target = f'https://www.youtube.com/channel/{channel_id}' if channel_id else channel_url
        steps.append(f'Trying Apify DataOverCoffee for {target}...')
        apify_result, apify_debug = _apify_email_lookup(channel_url, channel_id, apify_token)
        steps.append(f'Apify raw response: {apify_debug[:300]}')
        if apify_result:
            steps.append(f'Apify found: {apify_result}')
            return {
                'found': True,
                'email': apify_result,
                'source': 'apify',
                'confidence': 'high',
                'reasoning': 'Found via Apify DataOverCoffee (YouTube hidden business email).',
                'steps': steps,
            }
        else:
            steps.append('Apify: no email found.')

    steps.append('Investigation complete — no email found.')
    return {'found': False, 'steps': steps}
