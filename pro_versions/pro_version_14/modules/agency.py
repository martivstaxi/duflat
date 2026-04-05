"""
Agency / Management Company Finder
------------------------------------
Investigates who manages a YouTube channel.

Investigation pipeline (stops at first success):
    1. Email domain  → scrape corporate website
    2. External links (non-social) → scrape
    3. Linktree / link aggregators → extract links → scrape
    4. Description regex ("Management: X") → DuckDuckGo search
    5. Channel name + "agency management" → DuckDuckGo search
    6. Claude Haiku fallback (requires ANTHROPIC_API_KEY env var)

After finding basic info, enrich_agency() runs:
    - Deep-scrapes agency website (/, /about, /contact, /team, /roster)
    - Passes all content to Claude Haiku for structured profile extraction

Public API:
    find_agency(channel_data) → dict
        {'found': True, 'source': str, 'name': str, 'website': str,
         'contact_email': str, 'contact_phone': str, 'address': str,
         'founded': str, 'description': str, 'summary': str,
         'services': list, 'notable_clients': list,
         'socials': dict, 'reasoning': str}
      or {'found': False}
"""

import re
import os
import json
import requests
from urllib.parse import urlparse

from .constants import (
    SOCIAL_PLATFORMS, RE_EMAIL, EMAIL_BLACKLIST,
    BROWSER_HEADERS, is_valid_username,
)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

_AGENCY_SKIP_DOMAINS = (
    'youtube.com', 'youtu.be', 'instagram.com', 'twitter.com', 'x.com',
    'facebook.com', 'tiktok.com', 'discord.gg', 'discord.com', 'twitch.tv',
    'reddit.com', 'wikipedia.org', 'linktr.ee', 'bio.link', 'linkin.bio',
    'beacons.ai', 'allmylinks.com', 'myanimelist.net',
)
_PERSONAL_EMAIL_DOMAINS = (
    'gmail.', 'yahoo.', 'hotmail.', 'outlook.', 'icloud.',
    'protonmail.', 'live.', 'msn.', 'aol.', 'mail.',
)
_AGENCY_DESC_RE = [
    re.compile(r'(?:management|managed by|booking|talent agency|mcn|multi.?channel network|production company|produced by|partner(?:ship)?s?)\s*[:\-]?\s*([A-Za-z0-9&\s\.]{3,60})', re.I),
    re.compile(r'(?:for business(?: inquiries)?|business contact|business email|work with us)\s*[:\-]?\s*[\w\s]{0,20}?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.I),
    re.compile(r'(?:network|agency|label|studio|entertainment)\s*[:\-]?\s*([A-Za-z0-9&\s\.]{3,50})', re.I),
]

# ─────────────────────────────────────────────
# WEB SCRAPING HELPERS
# ─────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 5) -> list[str]:
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


def _extract_company_info(html: str, page_url: str) -> dict | None:
    """Extract company name, email, phone, description, socials from HTML."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return None

    result = {'website': page_url}

    # Company name: OG title > title tag
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        raw = og_title['content'].strip()
        result['name'] = re.sub(r'\s*[-|–|·]\s*(home|official|welcome|website).*$', '', raw, flags=re.I).strip()
    elif soup.title and soup.title.string:
        raw = soup.title.string.strip()
        result['name'] = re.sub(r'\s*[-|–|·]\s*(home|official|welcome|website).*$', '', raw, flags=re.I).strip()

    # Description
    for attr in [{'property': 'og:description'}, {'name': 'description'}]:
        tag = soup.find('meta', attrs=attr)
        if tag and tag.get('content'):
            result['description'] = tag['content'].strip()[:300]
            break

    # Email — prefer mailto: links, then regex
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('mailto:'):
            e = href[7:].split('?')[0].strip()
            if e and not any(x in e.lower() for x in EMAIL_BLACKLIST):
                result['email'] = e
                break
    if not result.get('email'):
        for m in RE_EMAIL.finditer(html):
            e = m.group(1)
            if not any(x in e.lower() for x in EMAIL_BLACKLIST):
                result['email'] = e
                break

    # Phone
    phone_m = re.search(r'(?:tel|phone|call)[\s:]*(\+?[\d\s\-().]{7,20})', html, re.I)
    if phone_m:
        result['phone'] = phone_m.group(1).strip()

    # Social media
    socials = {}
    for key, info in SOCIAL_PLATFORMS.items():
        for m in info['regex'].finditer(html):
            uname = m.group(1)
            v = info.get('validator')
            if (v is None or is_valid_username(uname, v)) and len(uname) > 1:
                socials[key] = info['url_fmt'].format(uname)
                break
    if socials:
        result['socials'] = socials

    return result


def _investigate_url(url: str) -> dict | None:
    """
    Scrape a URL for company info.
    Also tries /contact and /about sub-pages to fill missing email/description.
    Returns None if not enough info found.
    """
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None
        result = _extract_company_info(r.text, r.url)
        if not result:
            return None

        base = r.url.rstrip('/')
        for sub in ('/contact', '/about'):
            if result.get('email') and result.get('name'):
                break
            try:
                r2 = requests.get(base + sub, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
                if r2.status_code == 200:
                    sub_info = _extract_company_info(r2.text, r2.url)
                    if sub_info:
                        if not result.get('email') and sub_info.get('email'):
                            result['email'] = sub_info['email']
                        if not result.get('description') and sub_info.get('description'):
                            result['description'] = sub_info['description']
                        for k, v in sub_info.get('socials', {}).items():
                            result.setdefault('socials', {})[k] = v
            except Exception:
                pass

        return result if (result.get('name') or result.get('email')) else None
    except Exception:
        return None


def _search_and_investigate(query: str) -> dict | None:
    """DDG search → investigate first non-social result."""
    urls = _ddg_search(query, max_results=6)
    for url in urls:
        if any(d in url.lower() for d in _AGENCY_SKIP_DOMAINS):
            continue
        result = _investigate_url(url)
        if result:
            return result
    return None


def _try_linktree(url: str) -> list[str]:
    """Extract company links from a Linktree / link-aggregator page."""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and not any(d in href.lower() for d in _AGENCY_SKIP_DOMAINS):
                if href not in links:
                    links.append(href)
        return links[:5]
    except Exception:
        return []

# ─────────────────────────────────────────────
# AI HELPERS (Claude Haiku)
# ─────────────────────────────────────────────

def _llm_find_agency(channel_data: dict) -> dict | None:
    """
    Use Claude Haiku to identify the agency from channel data alone.
    Last-resort fallback when all scraping/search methods fail.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = []
        for f, l in [('name','Channel name'), ('handle','Handle'), ('description','Description'),
                     ('email','Email'), ('location','Location'), ('joined','Joined')]:
            if channel_data.get(f):
                parts.append(f'{l}: {channel_data[f]}')
        socials = [f"{k}: {channel_data[k]}" for k in ['instagram','twitter','tiktok','facebook','linkedin'] if channel_data.get(k)]
        if socials:
            parts.append('Social media: ' + ', '.join(socials))
        if channel_data.get('all_links'):
            parts.append('External links: ' + ', '.join(channel_data['all_links'][:10]))

        prompt = f"""Analyze this YouTube channel data and identify the management company, talent agency, MCN, or production company behind it.

{chr(10).join(parts)}

Respond ONLY with a JSON object. Use null for unknown fields.
If an agency/company can be identified:
{{"found": true, "name": "company name", "website": "URL or domain", "email": "contact email or null", "reasoning": "one sentence"}}
If no agency can be identified:
{{"found": false}}"""

        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        if not data.get('found'):
            return None
        result = {k: v for k, v in data.items() if k != 'found' and v and v != 'null'}
        return result if (result.get('name') or result.get('website')) else None
    except Exception:
        return None


def _deep_scrape_agency_site(website: str) -> dict[str, str]:
    """
    Scrape up to 5 pages of an agency website (/, /about, /contact, /team, /roster…).
    Returns {path: cleaned_text} mapping.
    """
    from bs4 import BeautifulSoup
    parsed = urlparse(website.rstrip('/'))
    base   = f"{parsed.scheme}://{parsed.netloc}"
    pages  = {}
    for path in ['', '/about', '/about-us', '/contact', '/contact-us', '/team', '/roster', '/talent', '/services']:
        if len(pages) >= 5:
            break
        try:
            r = requests.get(base + path, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''):
                soup = BeautifulSoup(r.text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                    tag.decompose()
                text = ' '.join(soup.get_text(' ', strip=True).split())
                if len(text) > 100:
                    pages[path or '/'] = text[:1800]
        except Exception:
            pass
    return pages


def _llm_enrich_agency(channel_data: dict, basic_info: dict, scraped_content: dict) -> dict | None:
    """
    Use Claude Haiku to produce a comprehensive agency profile from:
    - Channel data
    - Basic agency info (name, website)
    - Scraped website content

    Returns a structured dict or None.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = ['=== YouTube Channel ===']
        for f, l in [('name','Channel'), ('handle','Handle'), ('email','Email'),
                     ('description','Description'), ('location','Location')]:
            if channel_data.get(f):
                parts.append(f'{l}: {channel_data[f]}')
        soc = [f"{k}: {channel_data[k]}" for k in ['instagram','twitter','tiktok','facebook','linkedin'] if channel_data.get(k)]
        if soc:
            parts.append('Social: ' + ', '.join(soc))
        if channel_data.get('all_links'):
            parts.append('Links: ' + ', '.join(channel_data['all_links'][:8]))

        parts.append('\n=== Agency (found so far) ===')
        for f, l in [('name','Name'), ('website','Website'), ('email','Email')]:
            if basic_info.get(f):
                parts.append(f'{l}: {basic_info[f]}')

        if scraped_content:
            parts.append('\n=== Agency Website Content ===')
            for path, text in list(scraped_content.items())[:5]:
                parts.append(f'[{path or "/"}]\n{text}')

        context = '\n'.join(parts)[:6000]

        prompt = f"""Analyze this data and extract a detailed profile of the management company / talent agency.

{context}

Return ONLY a valid JSON object. Use null for unknown fields. Only include what is supported by the data:
{{
  "name": "official company name",
  "website": "main website URL",
  "description": "2-3 sentences describing what this company does",
  "summary": "one paragraph executive summary about this agency",
  "services": ["talent management", "content production", ...],
  "contact_email": "primary business contact email",
  "contact_phone": "phone number or null",
  "address": "city/country or full address or null",
  "founded": "founding year or null",
  "socials": {{
    "instagram": "URL or null",
    "twitter": "URL or null",
    "linkedin": "URL or null",
    "facebook": "URL or null"
  }},
  "notable_clients": ["channel or artist names managed by this agency"],
  "reasoning": "one sentence explaining how you identified this as the agency"
}}"""

        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            return {k: v for k, v in data.items() if v and v != 'null'}
    except Exception:
        pass
    return None


def enrich_agency(channel_data: dict, basic_info: dict) -> dict:
    """
    Deep-enrich an already-found agency result:
    1. Scrape agency website (multiple pages)
    2. Run Claude Haiku analysis on all collected content
    Returns merged dict (basic_info + enriched fields).
    """
    website  = basic_info.get('website', '')
    scraped  = _deep_scrape_agency_site(website) if website else {}
    enriched = _llm_enrich_agency(channel_data, basic_info, scraped)
    if enriched:
        merged = {**basic_info}
        for k, v in enriched.items():
            if v:
                merged[k] = v
        return merged
    return basic_info

# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def find_agency(channel_data: dict) -> dict:
    """
    Full agency investigation for a YouTube channel.

    Tries each source in order, stops at first success, then enriches.

    Args:
        channel_data: dict returned by scraper.scrape_channel()

    Returns:
        {'found': True, 'source': str, ...agency fields...}
        {'found': False}
    """
    channel_name = channel_data.get('name', '')
    email        = channel_data.get('email', '')
    description  = channel_data.get('description', '')
    all_links    = channel_data.get('all_links', [])

    # ── Collect hints ──────────────────────────

    # Email domain (skip personal providers)
    email_domain = None
    if email and '@' in email:
        domain = email.split('@')[1].lower()
        if not any(domain.startswith(g) for g in _PERSONAL_EMAIL_DOMAINS):
            email_domain = domain

    # Description regex hints
    desc_hints = []
    for pat in _AGENCY_DESC_RE:
        m = pat.search(description)
        if m:
            val = m.group(1).strip().rstrip('.').strip()
            if len(val) > 3 and val not in desc_hints:
                desc_hints.append(val)

    # External links: split into company links vs. link-aggregators
    company_links  = []
    linktree_links = []
    for lnk in all_links:
        u_lower = lnk.lower()
        if any(x in u_lower for x in ('linktr.ee', 'linkin.bio', 'beacons.ai')):
            linktree_links.append(lnk)
        elif not any(d in u_lower for d in _AGENCY_SKIP_DOMAINS):
            company_links.append(lnk)

    # ── Pipeline ───────────────────────────────

    def _finish(info: dict, source: str) -> dict:
        enriched = enrich_agency(channel_data, info)
        return {'found': True, 'source': source, **enriched}

    # 1. Email domain → corporate site
    if email_domain:
        r = _investigate_url(f'https://{email_domain}')
        if not r:
            r = _investigate_url(f'https://www.{email_domain}')
        if r:
            return _finish(r, 'email_domain')

        # Scraping failed — try DDG for the domain
        r = _search_and_investigate(f'site:{email_domain} OR "{email_domain}"')
        if r:
            return _finish(r, 'email_domain')

        # Fallback: return domain as minimal lead
        brand = re.sub(r'[-_]', ' ', email_domain.rsplit('.', 1)[0]).title()
        return _finish({'website': f'https://{email_domain}', 'name': brand,
                        'note': 'Website could not be scraped — identified from email domain.'}, 'email_domain')

    # 2. External company links
    for lnk in company_links[:3]:
        r = _investigate_url(lnk)
        if r:
            return _finish(r, 'external_link')

    # 3. Linktree / link aggregators
    for lt in linktree_links[:2]:
        for lnk in _try_linktree(lt):
            r = _investigate_url(lnk)
            if r:
                return _finish(r, 'linktree')

    # 4. Description regex → DDG
    for hint in desc_hints[:2]:
        r = _search_and_investigate(f'"{hint}" official site')
        if r:
            return _finish(r, 'description_regex')

    # 5. Channel name + agency keywords → DDG
    if channel_name:
        r = _search_and_investigate(f'{channel_name} management agency booking contact')
        if r:
            return _finish(r, 'web_search')

    # 6. Claude Haiku fallback
    r = _llm_find_agency(channel_data)
    if r:
        return _finish(r, 'ai_analysis')

    return {'found': False}
