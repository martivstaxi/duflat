"""
Email Finder
-----------
Finds a business contact email for a YouTube channel when not present in channel data.

Investigation pipeline (runs in order, collects hints for AI along the way):
    1. External links  → scrape each page for mailto: / email regex
    2. Instagram bio   → OG description tag (server-side rendered)
    3. DDG search      → "{channel} contact email" → scrape top results
    4. Claude Haiku    → synthesize all collected content, find best email

Public API:
    find_email(channel_data: dict) -> dict
        {'found': True, 'email': 'x@y.com', 'source': str, 'confidence': str, 'reasoning': str}
     or {'found': False}

source values: 'channel', 'external_link', 'instagram_bio', 'web_search', 'ai_analysis'
"""

import re
import os
import json
import requests

from .constants import BROWSER_HEADERS, RE_EMAIL, EMAIL_BLACKLIST

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

_SKIP_DOMAINS = (
    'youtube.com', 'youtu.be', 'instagram.com', 'twitter.com', 'x.com',
    'facebook.com', 'tiktok.com', 'discord.gg', 'discord.com', 'twitch.tv',
    'reddit.com', 'wikipedia.org', 'linktr.ee', 'bio.link', 'beacons.ai',
    'myanimelist.net', 'linkedin.com', 'linkin.bio',
)

_PERSONAL_EMAIL_DOMAINS = (
    'gmail.', 'yahoo.', 'hotmail.', 'outlook.', 'icloud.',
    'protonmail.', 'live.', 'msn.', 'aol.', 'mail.',
)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _is_business_email(email: str) -> bool:
    """Return True if email looks like a real business contact (not personal/noreply)."""
    e = email.lower()
    if any(x in e for x in EMAIL_BLACKLIST):
        return False
    domain = e.split('@')[1] if '@' in e else ''
    if any(domain.startswith(p) for p in _PERSONAL_EMAIL_DOMAINS):
        return False
    return bool(domain)


def _extract_emails_from_html(html: str) -> list[str]:
    """Extract business emails from HTML — prefers mailto: links over regex matches."""
    from bs4 import BeautifulSoup
    emails: list[str] = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('mailto:'):
                e = href[7:].split('?')[0].strip().lower()
                if e and _is_business_email(e) and e not in emails:
                    emails.append(e)
    except Exception:
        pass
    # Regex fallback
    for m in RE_EMAIL.finditer(html):
        e = m.group(1).lower()
        if _is_business_email(e) and e not in emails:
            emails.append(e)
    return emails[:5]


def _fetch(url: str, timeout: int = 10) -> str | None:
    """GET a URL, return text or None."""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''):
            return r.text
    except Exception:
        pass
    return None


def _ddg_search(query: str, max_results: int = 6) -> list[str]:
    """DuckDuckGo HTML search — no API key needed."""
    try:
        r = requests.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query, 'b': '', 'kl': 'en-us'},
            headers={**BROWSER_HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        urls = []
        for el in soup.select('.result__url'):
            url_text = el.get_text(strip=True)
            if not url_text:
                continue
            if not url_text.startswith('http'):
                url_text = 'https://' + url_text
            if url_text not in urls:
                urls.append(url_text)
        return urls[:max_results]
    except Exception:
        return []


def _page_text(html: str) -> str:
    """Strip scripts/styles, return cleaned visible text (max 600 chars)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        return ' '.join(soup.get_text(' ', strip=True).split())[:600]
    except Exception:
        return ''


# ─────────────────────────────────────────────
# AI HELPER
# ─────────────────────────────────────────────

def _llm_find_email(channel_data: dict, hints: list[tuple[str, str]]) -> dict | None:
    """
    Use Claude Haiku to deduce the contact email from all collected evidence.
    hints: list of (source_label, content) tuples gathered during earlier steps.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = ['=== YouTube Channel ===']
        for field, label in [('name', 'Channel'), ('handle', 'Handle'),
                              ('description', 'Description'), ('location', 'Location')]:
            if channel_data.get(field):
                parts.append(f'{label}: {channel_data[field]}')
        for k in ('instagram', 'twitter', 'tiktok', 'facebook', 'linkedin'):
            if channel_data.get(k):
                parts.append(f'{k.capitalize()}: {channel_data[k]}')
        if channel_data.get('all_links'):
            parts.append('External links: ' + ', '.join(channel_data['all_links'][:12]))

        if hints:
            parts.append('\n=== Investigated Sources ===')
            for label, content in hints[:10]:
                if content:
                    parts.append(f'[{label}]\n{content[:500]}')

        context = '\n'.join(parts)[:5500]

        prompt = f"""You are a private investigator specializing in finding business contact emails for YouTube creators.

{context}

Your task: identify the best business contact email for this channel.

Rules:
- Prefer emails found in the investigated sources over guesses
- Business emails (not gmail/yahoo/personal) are preferred
- If you see a domain that belongs to this creator (e.g. from external links), an email at that domain is likely correct
- Do NOT invent emails — only report emails that appear in the data or are strongly implied

Respond ONLY with valid JSON:
If confident: {{"found": true, "email": "contact@example.com", "confidence": "high", "reasoning": "found in external link xyz.com"}}
If a likely email: {{"found": true, "email": "info@example.com", "confidence": "low", "reasoning": "domain matches channel branding"}}
If nothing found: {{"found": false}}"""

        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=150,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group())
        if data.get('found') and data.get('email'):
            email = data['email'].lower().strip()
            if _is_business_email(email):
                return {
                    'found':      True,
                    'email':      email,
                    'source':     'ai_analysis',
                    'confidence': data.get('confidence', 'low'),
                    'reasoning':  data.get('reasoning', ''),
                }
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def find_email(channel_data: dict) -> dict:
    """
    Investigate and return the best business contact email for a YouTube channel.

    Args:
        channel_data: dict from scraper.scrape_channel()

    Returns:
        {'found': True,  'email': str, 'source': str, 'confidence': str, 'reasoning': str}
     or {'found': False}
    """
    # Already have a business email — done
    existing = channel_data.get('email', '')
    if existing and _is_business_email(existing):
        return {'found': True, 'email': existing, 'source': 'channel', 'confidence': 'high', 'reasoning': 'Listed on channel about page.'}

    channel_name = channel_data.get('name', '')
    handle       = channel_data.get('handle', '').lstrip('@')
    all_links    = channel_data.get('all_links', [])
    hints: list[tuple[str, str]] = []

    # ── Step 1: Scrape external links ──────────────────
    for link in all_links[:8]:
        if any(d in link.lower() for d in _SKIP_DOMAINS):
            continue
        html = _fetch(link)
        if html:
            emails = _extract_emails_from_html(html)
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'external_link',
                        'confidence': 'high', 'reasoning': f'Found in external link: {link}'}
            hints.append((f'external_link:{link}', _page_text(html)))

    # ── Step 2: Instagram bio (OG description is server-rendered) ──
    if channel_data.get('instagram'):
        html = _fetch(channel_data['instagram'])
        if html:
            # Check mailto / regex in full page
            emails = _extract_emails_from_html(html)
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'instagram_bio',
                        'confidence': 'high', 'reasoning': 'Found in Instagram profile page.'}
            # OG description = bio text
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                og = soup.find('meta', property='og:description')
                bio = og['content'] if og and og.get('content') else ''
                if bio:
                    for m in RE_EMAIL.finditer(bio):
                        e = m.group(1).lower()
                        if _is_business_email(e):
                            return {'found': True, 'email': e, 'source': 'instagram_bio',
                                    'confidence': 'high', 'reasoning': 'Found in Instagram bio.'}
                    hints.append(('instagram_bio', bio))
            except Exception:
                pass

    # ── Step 3: DuckDuckGo search ──────────────────────
    queries = []
    if channel_name:
        queries.append(f'"{channel_name}" contact email business inquiry')
    if handle:
        queries.append(f'"{handle}" youtube business contact email')

    for query in queries[:2]:
        for url in _ddg_search(query, max_results=5):
            if any(d in url.lower() for d in _SKIP_DOMAINS):
                continue
            html = _fetch(url, timeout=8)
            if html:
                emails = _extract_emails_from_html(html)
                if emails:
                    return {'found': True, 'email': emails[0], 'source': 'web_search',
                            'confidence': 'medium', 'reasoning': f'Found via web search: {url}'}
                hints.append((f'search_result:{url}', _page_text(html)))

    # ── Step 4: Claude Haiku — private detective mode ──
    result = _llm_find_email(channel_data, hints)
    if result:
        return result

    return {'found': False}
