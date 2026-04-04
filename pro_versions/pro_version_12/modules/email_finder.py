"""
Email Finder — Detective Mode
------------------------------
Exhaustive multi-source investigation to find a YouTube creator's business
contact email. Tries every angle before giving up.

Investigation pipeline:
    0. Obfuscated email decode  — description / about text ("contact [at] x [dot] com")
    1. External links           — scrape each + /contact /about subpages
    2. Link aggregators         — Linktree / beacons.ai / bio.link → extract links → scrape
    3. Social media profiles    — Instagram, Twitter/X, TikTok, Facebook OG tags + bio
    4. Latest video description — yt-dlp fetch of most recent video description
    5. DuckDuckGo searches      — 5 different targeted queries
    6. Domain pattern guessing  — known contact prefixes on any found domain
    7. Claude Haiku             — detective synthesis of ALL collected evidence

Public API:
    find_email(channel_data: dict) -> dict
        {'found': True, 'email': str, 'source': str, 'confidence': str, 'reasoning': str}
     or {'found': False}
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
    'youtube.com', 'youtu.be', 'instagram.com', 'twitter.com', 'x.com',
    'facebook.com', 'tiktok.com', 'discord.gg', 'discord.com', 'twitch.tv',
    'reddit.com', 'wikipedia.org', 'google.com', 'gstatic.com',
    'googleapis.com', 'apple.com', 'microsoft.com', 'amazon.com',
    'myanimelist.net', 'myanimelist.com', 'anilist.co',
    'twitch.tv', 'kick.com', 'spotify.com', 'soundcloud.com',
    'patreon.com', 'onlyfans.com', 'ko-fi.com', 'buymeacoffee.com',
    'snapchat.com', 'pinterest.com', 'tumblr.com', 'threads.net',
)

# Short/common English words that look like TLDs but aren't real email TLDs
_FAKE_TLDS = frozenset({
    'on', 'at', 'in', 'or', 'to', 'be', 'we', 'my', 'me', 'by', 'do',
    'go', 'up', 'us', 'it', 'if', 'as', 'so', 'no', 'an', 'of', 'is',
    'he', 'she', 'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
    'can', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him',
    'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two', 'way', 'who',
    'boy', 'did', 'its', 'let', 'put', 'say', 'she', 'too', 'use', 'from',
    'have', 'this', 'will', 'your', 'that', 'with', 'they', 'been', 'more',
    'when', 'come', 'here', 'just', 'know', 'like', 'look', 'make', 'most',
    'over', 'than', 'them', 'well', 'were',
})

_LINK_AGGREGATORS = ('linktr.ee', 'bio.link', 'beacons.ai', 'allmylinks.com',
                     'linkin.bio', 'lnk.bio', 'msha.ke', 'campsite.bio')

_CONTACT_PREFIXES = (
    'contact', 'info', 'hello', 'business', 'collab', 'collaboration',
    'booking', 'management', 'press', 'media', 'pr', 'partnerships',
    'brand', 'sponsor', 'work', 'agency',
)

# Obfuscated email patterns
_RE_OBFUSCATED = re.compile(
    r'([a-zA-Z0-9._%+\-]+)'      # local part
    r'\s*(?:\[at\]|\(at\)|@| at )\s*'
    r'([a-zA-Z0-9.\-]+)'          # domain
    r'\s*(?:\[dot\]|\(dot\)|\. | dot |\.)?\s*'
    r'([a-zA-Z]{2,})',             # TLD
    re.I
)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _is_business_email(email: str) -> bool:
    e = email.lower().strip()
    if len(e) < 10 or '@' not in e:
        return False
    if any(x in e for x in EMAIL_BLACKLIST):
        return False
    parts = e.split('@')
    if len(parts) != 2:
        return False
    local, domain = parts[0], parts[1]
    # Local part must be at least 3 chars
    if len(local) < 3:
        return False
    # TLD must exist, be 2-12 chars, only letters, and not a common English word
    tld_match = re.search(r'\.([a-z]{2,12})$', domain)
    if not tld_match:
        return False
    tld = tld_match.group(1)
    if tld in _FAKE_TLDS:
        return False
    # Domain name before TLD must be at least 2 chars (e.g. reject "x.com" → "x")
    domain_body = domain[:domain.rfind('.')]
    if len(domain_body.lstrip('www.')) < 2:
        return False
    # Reject if domain is a known platform
    if any(skip in domain for skip in _SKIP_DOMAINS):
        return False
    return True


def _clean_emails(emails: list[str]) -> list[str]:
    seen, out = set(), []
    for e in emails:
        e = e.lower().strip().rstrip('.')
        if _is_business_email(e) and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _decode_obfuscated(text: str) -> list[str]:
    """Find emails written as 'name [at] domain [dot] com'."""
    found = []
    for m in _RE_OBFUSCATED.finditer(text):
        local, domain_part, tld = m.group(1), m.group(2), m.group(3)
        email = f'{local}@{domain_part}.{tld}'.lower()
        if _is_business_email(email) and email not in found:
            found.append(email)
    return found


def _extract_emails_html(html: str) -> list[str]:
    """Extract emails from HTML — mailto: links first, then regex."""
    from bs4 import BeautifulSoup
    results = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            if a['href'].startswith('mailto:'):
                e = a['href'][7:].split('?')[0].strip().lower()
                if e not in results:
                    results.append(e)
    except Exception:
        pass
    for m in RE_EMAIL.finditer(html):
        e = m.group(1).lower()
        if e not in results:
            results.append(e)
    results += _decode_obfuscated(html)
    return _clean_emails(results)


def _fetch(url: str, timeout: int = 10) -> str | None:
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''):
            return r.text
    except Exception:
        pass
    return None


def _page_text(html: str, max_chars: int = 800) -> str:
    """Strip scripts/styles, return visible text."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'iframe']):
            tag.decompose()
        return ' '.join(soup.get_text(' ', strip=True).split())[:max_chars]
    except Exception:
        return ''


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


def _ddg_search(query: str, max_results: int = 6) -> list[str]:
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


def _is_site_own_email(email: str, page_url: str) -> bool:
    """
    Return True if the email belongs to the scraped site itself
    (e.g. contact@myanimelist.net found on myanimelist.net).
    We want to skip these — they're not the creator's email.
    """
    try:
        from urllib.parse import urlparse
        site_domain = urlparse(page_url).netloc.lower().lstrip('www.')
        email_domain = email.split('@')[1].lower() if '@' in email else ''
        if not email_domain or not site_domain:
            return False
        # Same domain or subdomain
        return (email_domain == site_domain or
                email_domain.endswith('.' + site_domain) or
                site_domain.endswith('.' + email_domain))
    except Exception:
        return False


def _scrape_url_shallow(url: str) -> tuple[list[str], str]:
    """Scrape only the main URL — no subpages. Used for web search results."""
    html = _fetch(url)
    if not html:
        return [], ''
    emails = [e for e in _extract_emails_html(html) if not _is_site_own_email(e, url)]
    return _clean_emails(emails), _page_text(html, 400)


def _scrape_url_deep(url: str) -> tuple[list[str], str]:
    """
    Scrape a URL and its /contact + /about subpages.
    Returns (emails_found, combined_text_hint).
    """
    emails: list[str] = []
    texts: list[str] = []

    html = _fetch(url)
    if html:
        raw = _extract_emails_html(html)
        emails += [e for e in raw if not _is_site_own_email(e, url)]
        texts.append(_page_text(html, 600))
        base = url.rstrip('/')
        for sub in ('/contact', '/about', '/about-us', '/contact-us'):
            if emails:
                break
            sub_html = _fetch(base + sub, timeout=8)
            if sub_html:
                raw = _extract_emails_html(sub_html)
                emails += [e for e in raw if not _is_site_own_email(e, url)]
                texts.append(_page_text(sub_html, 400))

    return _clean_emails(emails), ' '.join(t for t in texts if t)[:800]


def _extract_linktree_links(url: str) -> list[str]:
    """Pull all external links from a link-aggregator page."""
    html = _fetch(url)
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('http') and not any(d in href.lower() for d in _SKIP_DOMAINS):
                if href not in links:
                    links.append(href)
        return links[:8]
    except Exception:
        return []


def _fetch_video_descriptions(channel_url: str, n: int = 5) -> list[str]:
    """
    Fetch descriptions of the last N videos.
    Many creators put business email in every video description.
    """
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
        pass
    return []


def _bing_search(query: str, max_results: int = 5) -> list[str]:
    """Bing HTML search — no API key needed."""
    try:
        r = requests.get(
            'https://www.bing.com/search',
            params={'q': query, 'count': 10},
            headers={**BROWSER_HEADERS, 'Accept-Language': 'en-US,en;q=0.9'},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        urls = []
        for a in soup.select('h2 a[href]'):
            href = a.get('href', '')
            if href.startswith('http') and 'bing.com' not in href and 'microsoft.com' not in href:
                if href not in urls:
                    urls.append(href)
        return urls[:max_results]
    except Exception:
        return []


# ─────────────────────────────────────────────
# STEP 6 — DOMAIN EMAIL GUESSING
# ─────────────────────────────────────────────

def _guess_domain_emails(domain: str) -> list[str]:
    """Generate plausible contact emails for a domain using common prefixes."""
    return [f'{prefix}@{domain}' for prefix in _CONTACT_PREFIXES]


# ─────────────────────────────────────────────
# STEP 7 — CLAUDE HAIKU DETECTIVE
# ─────────────────────────────────────────────

def _llm_find_email(channel_data: dict, evidence: list[tuple[str, str]],
                    candidate_emails: list[str]) -> dict | None:
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return None
    try:
        import anthropic

        parts = ['=== YouTube Channel ===']
        for field, label in [('name','Name'), ('handle','Handle'),
                              ('description','Description (raw)'), ('location','Location'),
                              ('email','Email on page (if any)')]:
            if channel_data.get(field):
                parts.append(f'{label}: {channel_data[field]}')
        for k in ('instagram','twitter','tiktok','facebook','linkedin'):
            if channel_data.get(k):
                parts.append(f'{k.capitalize()}: {channel_data[k]}')
        if channel_data.get('all_links'):
            parts.append('All links: ' + ', '.join(channel_data['all_links'][:15]))

        if evidence:
            parts.append('\n=== Evidence Collected ===')
            for label, content in evidence[:15]:
                if content:
                    parts.append(f'[{label}]\n{content[:600]}')

        if candidate_emails:
            parts.append('\n=== Candidate Emails (domain-guessed, unverified) ===')
            parts.append(', '.join(candidate_emails[:12]))

        context = '\n'.join(parts)[:7000]

        prompt = f"""You are an elite digital private investigator specializing in finding YouTube creators' contact emails.

{context}

Your task: identify the BEST contact email for this creator to receive business/collab inquiries.

Investigation steps:
1. Scan all evidence text for any email address (including @gmail.com, @yahoo.com — creators often use these)
2. Look for obfuscated emails: "name at domain dot com", "name[at]domain[dot]com"
3. If a personal website/domain was found in the links, generate the most likely email: contact@domain, info@domain, collab@domain, hello@domain, [creator_name]@domain
4. Cross-reference the channel name/handle with any found domain to guess the email format
5. If the creator's first name is identifiable, try firstname@domain.com or firstnamelastname@gmail.com patterns

REJECT only emails that are clearly:
- Auto-generated site emails (noreply@, donotreply@, support@platform.com)
- Incorrectly parsed from natural language (e.g. "follow@somesite.on" where ".on" is a preposition)
- Contact emails of unrelated third-party companies (not the creator's own)

Gmail, Yahoo, Hotmail, Outlook ARE valid — many creators use them.

Be bold: if you can reasonably infer an email from the evidence, report it with "low" confidence.
Only return found:false if there is truly zero signal.

Respond ONLY with valid JSON:
{{"found": true, "email": "x@domain.com", "confidence": "high|medium|low", "reasoning": "one sentence"}}
or
{{"found": false}}"""

        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text  = message.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        data  = json.loads(match.group())
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
    Exhaustive email investigation for a YouTube creator.
    Tries every available method before giving up.
    """

    deadline = time.time() + 45  # hard cap: 45 seconds total

    # Already have a clean business email
    existing = channel_data.get('email', '')
    if existing and _is_business_email(existing):
        return {'found': True, 'email': existing, 'source': 'channel',
                'confidence': 'high', 'reasoning': 'Listed on the channel about page.'}

    name       = channel_data.get('name', '')
    handle     = channel_data.get('handle', '').lstrip('@')
    description= channel_data.get('description', '')
    all_links  = channel_data.get('all_links', [])
    channel_url= channel_data.get('channel_url', '')

    evidence:          list[tuple[str, str]] = []   # (label, text) for Haiku
    candidate_emails:  list[str]             = []   # domain-guessed
    found_domains:     list[str]             = []   # corporate domains found

    # ── STEP -1: InnerTube API deep extraction ─────────────────
    # Two-phase InnerTube: browse → continuation token → aboutChannelViewModel
    # This catches emails hidden behind YouTube's "View email address" button
    channel_id = channel_data.get('channel_id', '')
    if not channel_id and channel_url:
        m = re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', channel_url)
        if m:
            channel_id = m.group(1)
    if channel_id:
        it_email, has_hidden = _fetch_email_innertube(channel_id)
        if it_email and _is_business_email(it_email):
            return {'found': True, 'email': it_email, 'source': 'youtube_hidden',
                    'confidence': 'high',
                    'reasoning': 'Found via YouTube InnerTube API (hidden behind "View email address" button).'}

    # Also try yt-dlp full about extraction
    if channel_url:
        ydl_email = _fetch_email_ydl_about(channel_url)
        if ydl_email and _is_business_email(ydl_email):
            return {'found': True, 'email': ydl_email, 'source': 'youtube_about',
                    'confidence': 'high',
                    'reasoning': 'Found via yt-dlp full about page extraction.'}

    # ── STEP 0: Obfuscated emails in description ───────────────
    if description:
        obf = _decode_obfuscated(description)
        if obf:
            return {'found': True, 'email': obf[0], 'source': 'description',
                    'confidence': 'high', 'reasoning': 'Obfuscated email decoded from channel description.'}
        evidence.append(('channel_description', description[:600]))

    # ── STEP 1: External links — scrape deep ──────────────────
    company_links  = []
    aggregator_links = []
    for lnk in all_links:
        lo = lnk.lower()
        if any(d in lo for d in _LINK_AGGREGATORS):
            aggregator_links.append(lnk)
        elif not any(d in lo for d in _SKIP_DOMAINS):
            company_links.append(lnk)

    for link in company_links[:6]:
        emails, hint = _scrape_url_deep(link)
        if hint:
            evidence.append((f'external_link:{link}', hint))
        # Track domain for guessing later
        try:
            from urllib.parse import urlparse
            domain = urlparse(link).netloc.lstrip('www.')
            if domain and domain not in found_domains:
                found_domains.append(domain)
        except Exception:
            pass
        if emails:
            return {'found': True, 'email': emails[0], 'source': 'external_link',
                    'confidence': 'high', 'reasoning': f'Found in external link: {link}'}

    # ── STEP 2: Link aggregators (Linktree etc.) ──────────────
    for agg in aggregator_links[:2]:
        for link in _extract_linktree_links(agg):
            emails, hint = _scrape_url_deep(link)
            if hint:
                evidence.append((f'linktree_link:{link}', hint))
            try:
                from urllib.parse import urlparse
                domain = urlparse(link).netloc.lstrip('www.')
                if domain and domain not in found_domains:
                    found_domains.append(domain)
            except Exception:
                pass
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'linktree',
                        'confidence': 'high', 'reasoning': f'Found via link aggregator → {link}'}

    # ── STEP 3: Social media profiles ────────────────────────

    # Instagram — full page + OG description
    if channel_data.get('instagram'):
        ig_html = _fetch(channel_data['instagram'])
        if ig_html:
            emails = _extract_emails_html(ig_html)
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'instagram',
                        'confidence': 'high', 'reasoning': 'Found in Instagram profile page.'}
            bio = _og_desc(ig_html)
            if bio:
                obf = _decode_obfuscated(bio)
                if obf:
                    return {'found': True, 'email': obf[0], 'source': 'instagram',
                            'confidence': 'high', 'reasoning': 'Obfuscated email decoded from Instagram bio.'}
                for m in RE_EMAIL.finditer(bio):
                    e = m.group(1).lower()
                    if _is_business_email(e):
                        return {'found': True, 'email': e, 'source': 'instagram',
                                'confidence': 'high', 'reasoning': 'Found in Instagram bio.'}
                evidence.append(('instagram_bio', bio))

    # Twitter/X — try OG description from profile page
    if channel_data.get('twitter'):
        for tw_url in [channel_data['twitter'],
                       channel_data['twitter'].replace('x.com', 'twitter.com')]:
            tw_html = _fetch(tw_url)
            if tw_html:
                emails = _extract_emails_html(tw_html)
                if emails:
                    return {'found': True, 'email': emails[0], 'source': 'twitter',
                            'confidence': 'high', 'reasoning': 'Found in Twitter/X profile page.'}
                bio = _og_desc(tw_html)
                if bio:
                    obf = _decode_obfuscated(bio)
                    if obf:
                        return {'found': True, 'email': obf[0], 'source': 'twitter',
                                'confidence': 'high', 'reasoning': 'Obfuscated email from Twitter/X bio.'}
                    evidence.append(('twitter_bio', bio))
                break

    # TikTok profile
    if channel_data.get('tiktok'):
        tt_html = _fetch(channel_data['tiktok'])
        if tt_html:
            emails = _extract_emails_html(tt_html)
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'tiktok',
                        'confidence': 'high', 'reasoning': 'Found in TikTok profile page.'}
            bio = _og_desc(tt_html)
            if bio:
                obf = _decode_obfuscated(bio)
                if obf:
                    return {'found': True, 'email': obf[0], 'source': 'tiktok',
                            'confidence': 'high', 'reasoning': 'Obfuscated email from TikTok bio.'}
                evidence.append(('tiktok_bio', bio))

    # Facebook page
    if channel_data.get('facebook'):
        fb_html = _fetch(channel_data['facebook'])
        if fb_html:
            emails = _extract_emails_html(fb_html)
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'facebook',
                        'confidence': 'high', 'reasoning': 'Found in Facebook page.'}
            bio = _og_desc(fb_html)
            if bio:
                evidence.append(('facebook_bio', bio))

    # ── STEP 4: Last 3 video descriptions ────────────────────
    if channel_url and time.time() < deadline:
        video_descs = _fetch_video_descriptions(channel_url, n=3)
        for i, vid_desc in enumerate(video_descs):
            if not vid_desc:
                continue
            obf = _decode_obfuscated(vid_desc)
            if obf:
                return {'found': True, 'email': obf[0], 'source': 'video_description',
                        'confidence': 'high', 'reasoning': f'Obfuscated email in video #{i+1} description.'}
            for m in RE_EMAIL.finditer(vid_desc):
                e = m.group(1).lower()
                if _is_business_email(e):
                    return {'found': True, 'email': e, 'source': 'video_description',
                            'confidence': 'high', 'reasoning': f'Found in video #{i+1} description.'}
            if i == 0:
                evidence.append(('video_description_1', vid_desc[:600]))

    # ── STEP 5: Multi-engine search ───────────────────────────
    # Build targeted queries using every piece of data we have
    location = channel_data.get('location', '')
    first_name = name.split()[0] if name and ' ' in name else name

    ddg_queries = []
    if name:
        ddg_queries += [
            f'"{name}" youtube contact email',
            f'"{name}" business email inquiry',
            f'"{name}" youtuber email collab',
        ]
    if handle:
        ddg_queries += [
            f'"{handle}" email contact',
            f'"{handle}" youtube business email',
        ]
    if first_name and first_name != name:
        ddg_queries.append(f'"{first_name}" youtube {location} contact email'.strip())
    if found_domains:
        ddg_queries.append(f'site:{found_domains[0]} contact email')
    if location and name:
        ddg_queries.append(f'"{name}" {location} youtube email')

    seen_urls: set[str] = set()

    for query in ddg_queries[:4]:
        if time.time() > deadline or len(seen_urls) >= 10:
            break
        for url in _ddg_search(query, max_results=3):
            if url in seen_urls or any(d in url.lower() for d in _SKIP_DOMAINS):
                continue
            seen_urls.add(url)
            emails, hint = _scrape_url_shallow(url)
            if hint:
                evidence.append((f'ddg:{url}', hint))
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'web_search',
                        'confidence': 'medium', 'reasoning': f'Found via web search: {url}'}

    # Bing search — different index, may find different results
    bing_queries = []
    if name:
        bing_queries.append(f'{name} youtube email contact business')
    if handle:
        bing_queries.append(f'{handle} youtube email')

    for query in bing_queries[:2]:
        if time.time() > deadline or len(seen_urls) >= 15:
            break
        for url in _bing_search(query, max_results=3):
            if url in seen_urls or any(d in url.lower() for d in _SKIP_DOMAINS):
                continue
            seen_urls.add(url)
            emails, hint = _scrape_url_shallow(url)
            if hint:
                evidence.append((f'bing:{url}', hint))
            if emails:
                return {'found': True, 'email': emails[0], 'source': 'web_search',
                        'confidence': 'medium', 'reasoning': f'Found via Bing: {url}'}

    # ── STEP 6: Domain email pattern guessing ─────────────────
    for domain in found_domains[:3]:
        guesses = _guess_domain_emails(domain)
        candidate_emails.extend(guesses)
        evidence.append((f'domain_found:{domain}',
                         f'Corporate domain identified. Possible contacts: {", ".join(guesses[:5])}'))

    # ── STEP 7: Claude Haiku — full detective synthesis ───────
    result = _llm_find_email(channel_data, evidence, candidate_emails)
    if result:
        return result

    return {'found': False}
