"""
Social Listening Module — Bilibili mention tracking

Flow (optimized — single endpoint):
  1. AI finds ~100 links mentioning "bilibili"
  2. POST /social/scan        → Python dedup + download + Haiku analysis + save (ALL IN ONE)
  3. GET  /social/mentions    → Frontend reads mentions by date

Legacy endpoints still available:
  - POST /social/check-urls, /social/process, /social/save
"""

import hashlib
import json
import os
import re
import requests
from datetime import datetime, date, timedelta
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from modules.constants import BROWSER_HEADERS

# ─────────────────────────────────────────────
# SUPABASE CLIENT
# ─────────────────────────────────────────────

_supabase = None

def init_supabase(url, key):
    global _supabase
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase

def _db():
    if not _supabase:
        raise RuntimeError('Supabase not initialized')
    return _supabase


# ─────────────────────────────────────────────
# URL HASHING
# ─────────────────────────────────────────────

def hash_url(url):
    """Deterministic 16-char hash of a normalized URL."""
    normalized = url.strip().lower().rstrip('/')
    # Remove common tracking params
    normalized = re.sub(r'[?&](utm_\w+|ref|fbclid|gclid)=[^&]*', '', normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def hash_content(text):
    """Hash content text for dedup."""
    cleaned = re.sub(r'\s+', ' ', text.strip().lower())
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────
# STEP 1: CHECK URLS (dedup against DB)
# ─────────────────────────────────────────────

def check_urls(urls):
    """
    Receive list of URLs → hash → check DB → return only new unique ones.
    Zero AI cost, zero network cost (just DB queries).
    """
    # Local dedup first
    seen = {}
    for url in urls:
        url = url.strip()
        if not url:
            continue
        h = hash_url(url)
        if h not in seen:
            seen[h] = url

    if not seen:
        return []

    # Check DB in batches
    hashes = list(seen.keys())
    existing = set()

    for i in range(0, len(hashes), 50):
        batch = hashes[i:i+50]
        result = _db().table('social_sources').select('url_hash').in_('url_hash', batch).execute()
        for row in result.data:
            existing.add(row['url_hash'])

    # Return only new
    new_urls = []
    for h, url in seen.items():
        if h not in existing:
            new_urls.append({'url': url, 'url_hash': h})

    return new_urls


# ─────────────────────────────────────────────
# STEP 2: PROCESS URLS (download + date filter)
# ─────────────────────────────────────────────

# Date patterns that capture 2026 — multilingual
_DATE_PATTERNS = [
    # 2026-01-15, 2026/01/15, 2026.01.15
    re.compile(r'(2026[-/.]\d{1,2}[-/.]\d{1,2})'),
    # 15-01-2026, 01/15/2026, 15.01.2026
    re.compile(r'(\d{1,2}[-/.]\d{1,2}[-/.]2026)'),
    # English months: January 15, 2026 / Jan 15 2026
    re.compile(r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+2026)', re.I),
    # 15 January 2026
    re.compile(r'(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+2026)', re.I),
    # Chinese/Japanese: 2026年
    re.compile(r'(2026年\d{1,2}月)'),
    re.compile(r'(2026年)'),
    # Arabic months with 2026
    re.compile(r'((?:يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s+2026)'),
    # Spanish months
    re.compile(r'((?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?2026)', re.I),
    # Portuguese months
    re.compile(r'((?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+(?:de\s+)?2026)', re.I),
    # Russian months
    re.compile(r'((?:январ[яь]|феврал[яь]|март[а]?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|август[а]?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])\s+2026)', re.I),
    # Turkish months
    re.compile(r'((?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+2026)', re.I),
    # Loose: "date/posted/published/updated" near 2026
    re.compile(r'(?:date|posted|published|updated|reviewed?)[\s:]*[^0-9]*?(2026)', re.I),
    # URL contains 2026 (many news sites embed date in URL)
    re.compile(r'/2026/\d{1,2}/'),
]


def _extract_dates_2026(text):
    """Find all 2026 date references in text."""
    found = []
    for pat in _DATE_PATTERNS:
        found.extend(pat.findall(text))
    return found


def _parse_date_string(s):
    """Try to parse a date string into YYYY-MM-DD format."""
    s = s.strip().replace('/', '-').replace(',', '')
    formats = [
        '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
        '%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    # Fallback: if just "2026" found
    if '2026' in s:
        return '2026-01-01'
    return None


def process_urls(url_items, time_budget=55):
    """
    Download each URL, extract text, check for 2026 dates.
    Returns only content that has 2026 dates — ready for AI analysis.
    Zero AI cost. Stops after time_budget seconds.
    """
    import time
    results = []
    processed = 0
    start = time.time()

    for item in url_items:
        if time.time() - start > time_budget:
            break
        url = item['url']
        url_hash = item['url_hash']
        processed += 1

        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
            resp.raise_for_status()

            # Use resp.content (bytes) so BS4 detects encoding from HTML meta tags
            # resp.text can corrupt CJK characters when headers don't declare charset
            soup = BeautifulSoup(resp.content, 'html.parser')

            # Remove noise
            for tag in soup(['script', 'style', 'nav', 'footer', 'iframe', 'noscript']):
                tag.decompose()

            text = soup.get_text(separator='\n', strip=True)

            # Cap at 15K chars for processing
            text_trimmed = text[:15000]

            # Check for 2026 dates — in page text AND URL itself
            dates = _extract_dates_2026(text_trimmed + '\n' + url)

            # Detect platform from URL
            domain = urlparse(url).netloc.replace('www.', '')

            # Save source record
            _db().table('social_sources').upsert({
                'url_hash': url_hash,
                'url': url,
                'domain': domain,
                'has_2026_content': len(dates) > 0,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()

            if dates:
                # Parse the first date found
                parsed_date = _parse_date_string(dates[0])

                results.append({
                    'url': url,
                    'url_hash': url_hash,
                    'platform': domain,
                    'text': text_trimmed[:5000],  # Limit text sent to AI
                    'dates_found': dates[:5],
                    'content_date': parsed_date,
                })

        except Exception as e:
            # Record failed attempt
            try:
                _db().table('social_sources').upsert({
                    'url_hash': url_hash,
                    'url': url,
                    'domain': urlparse(url).netloc.replace('www.', ''),
                    'has_2026_content': False,
                    'checked_at': datetime.utcnow().isoformat(),
                }, on_conflict='url_hash').execute()
            except:
                pass

    return {
        'processed': processed,
        'with_2026_content': len(results),
        'items': results,
    }


# ─────────────────────────────────────────────
# STEP 3: SAVE MENTIONS (AI-analyzed results)
# ─────────────────────────────────────────────

def _detect_lang_from_text(text):
    """
    Heuristic language detection by counting character types.
    Returns detected language string or None if ambiguous.
    """
    if not text or len(text) < 10:
        return None
    total = len([c for c in text if not c.isspace()])
    if total == 0:
        return None

    arabic  = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    kana    = sum(1 for c in text if '\u3040' <= c <= '\u30FF')  # hiragana + katakana
    cjk     = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
    cyril   = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin   = sum(1 for c in text if c.isascii() and c.isalpha())

    if arabic / total > 0.15:
        return 'Arabic'
    if kana / total > 0.05:
        return 'Japanese'
    if cjk / total > 0.15:
        # Distinguish Simplified vs Traditional by key character pairs
        simp = sum(1 for c in text if c in '国来对说时间会这们问东车头马书开关无')
        trad = sum(1 for c in text if c in '國來對說時間會這們問東車頭馬書開關無')
        return 'Simplified Chinese' if simp >= trad else 'Traditional Chinese'
    if cyril / total > 0.15:
        return 'Russian'
    if latin / total > 0.25:
        return 'Latin'   # English/Spanish/Portuguese/Turkish — trust Haiku for exact lang
    return None


# Terms that confirm a mention is about Bilibili
_BILIBILI_TERMS = [
    'bilibili', 'b站', 'ビリビリ', 'blg', '哔哩哔哩', '嗶哩嗶哩',
    '9626', 'anisora', 'bili bili', 'bilibil', '哔哩', '嗶哩',
    'bilibili gaming', 'first stand', 'anisora',
]


def _validate_and_repair(mention):
    """
    Validate a Haiku-analyzed mention before saving to DB.
    Returns (is_valid, mention, issues[]).
    Repairs what it can (language label); rejects what it cannot.

    Checks:
      1. Language match  — detect from text, auto-repair if wrong
      2. content_original ≠ content_english
      3. Bilibili relevance — reject if Bilibili not mentioned at all
      4. Date sanity — reject future dates, warn on very old dates
      5. Minimum content length
    """
    issues = []
    original = mention.get('content_original', '').strip()
    english  = mention.get('content_english', '').strip()
    lang     = mention.get('language', '')
    content_date = mention.get('content_date') or ''
    today    = date.today().isoformat()

    # ── 1. LANGUAGE CHECK ──────────────────────────────────────────
    detected = _detect_lang_from_text(original)
    if detected == 'Latin' and lang in (
        'Traditional Chinese', 'Simplified Chinese', 'Japanese', 'Arabic', 'Russian'
    ):
        # Text is clearly Latin/English but Haiku labeled it as non-Latin → fix
        issues.append(f'lang_repair:{lang}→English')
        mention['language'] = 'English'
    elif detected and detected != 'Latin' and detected != lang:
        # Confident non-Latin detection disagrees with Haiku
        issues.append(f'lang_repair:{lang}→{detected}')
        mention['language'] = detected

    # ── 2. ORIGINAL ≠ ENGLISH CHECK ───────────────────────────────
    if original and english and original == english:
        issues.append('reject:original_same_as_english')
        return False, mention, issues

    # ── 3. BILIBILI RELEVANCE CHECK ───────────────────────────────
    combined = (original + ' ' + english).lower()
    if not any(term in combined for term in _BILIBILI_TERMS):
        issues.append('reject:bilibili_not_mentioned')
        return False, mention, issues

    # ── 4. DATE SANITY ─────────────────────────────────────────────
    if content_date:
        if content_date > today:
            issues.append(f'reject:future_date:{content_date}')
            return False, mention, issues
        if content_date < '2024-01-01':
            issues.append(f'warn:very_old_date:{content_date}')  # allow but flag

    # ── 5. MINIMUM LENGTH ──────────────────────────────────────────
    if len(original) < 15:
        issues.append(f'reject:content_too_short:{len(original)}chars')
        return False, mention, issues

    return True, mention, issues


def _ai_validate_and_repair(mentions):
    """
    Second AI pass: Haiku reviews Haiku's own output.
    For each mention, checks:
      1. Is Bilibili actually mentioned? (reject if not)
      2. Is the language label correct? (fix if wrong, still save)
      3. Is content_original genuinely different from content_english? (reject if same)

    Returns list of mentions — repaired ones included, rejected ones removed.
    This runs AFTER _validate_and_repair() heuristics, as a final quality gate.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not mentions:
        return mentions

    try:
        import anthropic
    except ImportError:
        return mentions

    entries = []
    for i, m in enumerate(mentions):
        entries.append({
            'idx': i,
            'url': m.get('url', ''),
            'platform': m.get('platform', ''),
            'language_label': m.get('language', ''),
            'content_original': m.get('content_original', '')[:800],
            'content_english': m.get('content_english', '')[:400],
        })

    prompt = f"""You are a quality control agent reviewing social listening data about Bilibili.

For EACH entry below, answer three questions and return fixes:

1. BILIBILI_RELEVANT: Does content_original actually mention Bilibili, Bilibili Gaming (BLG), B站, ビリビリ, 哔哩哔哩, 嗶哩嗶哩, AniSora, or any directly related topic? Answer true/false.

2. LANGUAGE_CORRECT: Is the language_label correct for the actual text in content_original?
   - If wrong, provide the correct language ("English", "Japanese", "Arabic", "Traditional Chinese", "Simplified Chinese", "Turkish", "Russian", "Spanish", "Portuguese")
   - If correct, return null

3. CONTENT_DISTINCT: Is content_original meaningfully different from content_english (different language OR different wording)?

Rules:
- If BILIBILI_RELEVANT=false → mark action:"reject"
- If LANGUAGE_CORRECT has a correction → mark action:"repair_language", corrected_language:"..."
- If CONTENT_DISTINCT=false → mark action:"reject"
- Otherwise → mark action:"keep"
- If both repair and keep → action:"repair_language" (repair + keep, do NOT reject)

Return ONLY a JSON array, one object per entry:
[{{"idx":0,"bilibili_relevant":true,"language_correct":null,"content_distinct":true,"action":"keep"}}, ...]

Entries:
{json.dumps(entries, ensure_ascii=False)}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = resp.content[0].text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        verdicts = json.loads(text)
    except Exception:
        return mentions  # if AI validator fails, pass through (don't block saves)

    # Apply verdicts
    result = []
    for v in verdicts:
        idx = v.get('idx')
        if idx is None or idx >= len(mentions):
            continue
        action = v.get('action', 'keep')
        m = mentions[idx]

        if action == 'reject':
            continue  # drop silently

        if action == 'repair_language':
            corrected = v.get('corrected_language')
            if corrected:
                m['language'] = corrected
            result.append(m)
        else:
            result.append(m)  # keep as-is

    # Safety: if validator returned fewer items than expected (parse issue), pass all through
    if len(result) == 0 and len(mentions) > 0:
        return mentions

    return result


def save_mentions(mentions):
    """
    Save AI-analyzed mentions to Supabase.
    Each mention passes _validate_and_repair() before saving:
      - Language label auto-corrected if wrong
      - Irrelevant, duplicate-content, future-dated, too-short mentions rejected
    """
    saved = 0
    skipped = 0
    repaired = 0

    for m in mentions:
        original = m.get('content_original', '').strip()
        if not original:
            skipped += 1
            continue

        # Run validation + auto-repair
        is_valid, m, issues = _validate_and_repair(m)
        if not is_valid:
            skipped += 1
            continue
        if any(i.startswith('lang_repair') for i in issues):
            repaired += 1

        original = m.get('content_original', '').strip()
        c_hash = hash_content(original)

        row = {
            'content_hash': c_hash,
            'url': m.get('url', ''),
            'url_hash': m.get('url_hash', hash_url(m.get('url', ''))),
            'platform': m.get('platform', ''),
            'author': m.get('author', ''),
            'country': m.get('country', ''),
            'language': m.get('language', ''),
            'sentiment': m.get('sentiment', 'neutral'),
            'content_original': original,
            'content_english': m.get('content_english', ''),
            'keywords': m.get('keywords', []),
            'content_date': m.get('content_date'),
        }

        try:
            _db().table('social_mentions').upsert(
                row, on_conflict='content_hash'
            ).execute()
            saved += 1
        except Exception:
            skipped += 1

    return {'saved': saved, 'skipped': skipped, 'repaired': repaired}


# ─────────────────────────────────────────────
# STEP 4: GET MENTIONS (for frontend)
# ─────────────────────────────────────────────

def get_mentions(days=None, specific_date=None, limit=100):
    """
    Fetch mentions for social.html display.
    - days=3  → last 3 days
    - specific_date='2026-01-01' → that exact date
    """
    query = _db().table('social_mentions').select('*')

    if specific_date:
        query = query.eq('content_date', specific_date)
    elif days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query = query.gte('content_date', cutoff)

    result = query.order('content_date', desc=True).limit(limit).execute()
    return result.data


# ─────────────────────────────────────────────
# HAIKU ANALYSIS (replaces manual AI analysis)
# ─────────────────────────────────────────────

def _analyze_with_haiku(items):
    """
    Use Claude Haiku to analyze 2026-dated content in ONE batch call.
    Returns list of mention dicts ready for save_mentions().
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not items:
        return []

    try:
        import anthropic
    except ImportError:
        return []

    # Domain TLD → language hint mapping
    _TLD_LANG_HINTS = {
        '.ru': 'Russian', '.jp': 'Japanese', '.cn': 'Simplified Chinese',
        '.tw': 'Traditional Chinese', '.hk': 'Traditional Chinese',
        '.tr': 'Turkish', '.es': 'Spanish', '.mx': 'Spanish',
        '.ar': 'Spanish', '.br': 'Portuguese', '.pt': 'Portuguese',
        '.sa': 'Arabic', '.ae': 'Arabic', '.eg': 'Arabic',
    }

    # Build compact summaries for Haiku
    entries = []
    for item in items:
        # Detect language hint from domain TLD
        domain = item['platform']
        lang_hint = ''
        for tld, lang in _TLD_LANG_HINTS.items():
            if domain.endswith(tld):
                lang_hint = lang
                break
        entry = {
            'url': item['url'],
            'url_hash': item['url_hash'],
            'platform': item['platform'],
            'date': item.get('content_date', ''),
            'text': item['text'][:2000],  # cap per item
        }
        if lang_hint:
            entry['lang_hint'] = lang_hint
        entries.append(entry)

    prompt = f"""You are a social listening analyst. Your job is to capture what PEOPLE and COMMUNITIES are saying about Bilibili — public opinion, user reactions, community sentiment, social commentary.

For EACH article, write a plain-English summary that sounds like a social media insight, NOT a news headline. Use simple, everyday language. Avoid jargon, financial terms, or corporate-speak.

Good examples:
- "Users are excited about Bilibili's new anime lineup for winter 2026, especially Frieren Season 2."
- "Fans are celebrating BLG's first international esports title after beating G2 in Brazil."
- "Some investors worry the new algorithm change might push users away."

Bad examples (too formal/news-like):
- "Bilibili Inc. reported Q4 revenue of RMB 8.32 billion, an increase of 8% YoY."
- "The company achieved its first full year of GAAP profitability."

For EACH article, extract:
- content_english: 1-2 sentence plain-English social insight (what people think/feel about this). Smooth, easy to read, like butter.
- content_original: copy the most relevant 1-3 sentences VERBATIM from the original article text. Do NOT rewrite — keep the exact original wording. This is shown behind a "Details" button.
- sentiment: "positive", "negative", or "neutral"
- keywords: array of 2-4 single-word topic tags
- author: author name if found, otherwise the platform name
- country: country of origin if detectable, otherwise "International"
- language: detect the language by reading the ACTUAL WORDS in content_original. Do NOT guess from the platform name or domain. Use: "English", "Japanese", "Arabic", "Traditional Chinese", "Simplified Chinese", "Turkish", "Russian", "Spanish", "Portuguese". Rules: if content_original contains Latin alphabet words in English → "English". Chinese scripts: 简体字 (simplified strokes) → "Simplified Chinese", 繁體字 (complex strokes, traditional) → "Traditional Chinese". If a lang_hint field is provided, use it as a strong tie-breaker only when the text is ambiguous. Example: aastocks.com/en/ page with English text → "English" (not Traditional Chinese just because it's a HK site).

Return ONLY a JSON array. Each element must have: url, url_hash, platform, content_date, content_original, content_english, sentiment, keywords, author, country, language.

Skip articles that do NOT mention Bilibili at all (complete false positives with no connection to Bilibili).
Skip pages that are ONLY raw stock price tickers with no text (just numbers/charts, no sentences).
DO include: financial news, earnings, analyst opinions, esports match reports mentioning BLG/Bilibili Gaming, anime streaming news, AI tools from Bilibili, anything where Bilibili is mentioned even if not the main focus.
When in doubt, INCLUDE the article — it's better to save a borderline mention than to miss it.

Articles:
{json.dumps(entries, ensure_ascii=False)}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=8192,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = resp.content[0].text.strip()
        # Extract JSON from response
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        # Try full parse first, fallback to partial recovery
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to recover truncated JSON array
            last_brace = text.rfind('},')
            if last_brace > 0:
                try:
                    return json.loads(text[:last_brace + 1] + ']')
                except Exception:
                    pass
            return []
    except Exception:
        return []


# ─────────────────────────────────────────────
# SCAN — ALL-IN-ONE ENDPOINT
# ─────────────────────────────────────────────

def scan_urls(urls):
    """
    Full pipeline in one call:
      1. Dedup URLs against DB
      2. Download & check for 2026 dates
      3. Analyze with Haiku
      4. Save to Supabase
    Returns summary dict.
    """
    # Step 1: dedup
    new_urls = check_urls(urls)
    if not new_urls:
        return {'received': len(urls), 'new': 0, 'with_2026': 0, 'saved': 0, 'skipped': 0}

    # Step 2: download + date filter
    processed = process_urls(new_urls, time_budget=40)
    items_2026 = processed.get('items', [])

    if not items_2026:
        return {
            'received': len(urls),
            'new': len(new_urls),
            'with_2026': 0,
            'saved': 0,
            'skipped': 0,
        }

    # Step 3: Haiku analysis
    mentions = _analyze_with_haiku(items_2026)

    # Step 3b: AI validation + repair (second Haiku pass)
    if mentions:
        mentions = _ai_validate_and_repair(mentions)

    # Step 4: save (heuristic validation also runs inside save_mentions)
    if mentions:
        result = save_mentions(mentions)
    else:
        result = {'saved': 0, 'skipped': 0, 'repaired': 0}

    return {
        'received': len(urls),
        'new': len(new_urls),
        'with_2026': len(items_2026),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
    }


# ─────────────────────────────────────────────
# AUTO-DISCOVER — DDG search across 8 languages
# ─────────────────────────────────────────────

# Search queries per language — short, no year (pipeline filters for 2026 content)
_DISCOVER_QUERIES = {
    'English': [
        'Bilibili news',
        'Bilibili BILI stock earnings',
        'Bilibili anime platform users',
        'Bilibili gaming esports BLG',
        'Bilibili China video platform',
        'Bilibili AniSora AI anime',
        'Bilibili revenue profit',
        'Bilibili Spring Festival',
    ],
    'Japanese': [
        'ビリビリ ニュース',
        'ビリビリ 動画プラットフォーム',
        'ビリビリ アニメ',
        'ビリビリ 決算 株',
        'ビリビリ eスポーツ BLG',
        'ビリビリ AniSora AI',
        'ビリビリ 中国 Z世代',
        '哔哩哔哩 日本',
    ],
    'Arabic': [
        'بيليبيلي أخبار',
        'بيليبيلي منصة فيديو صينية',
        'بيليبيلي أنمي صيني',
        'Bilibili Arabic',
        'بيليبيلي أسهم',
        'بيليبيلي ذكاء اصطناعي',
        'موقع بيليبيلي الصيني',
        'Bilibili China platform review',
    ],
    'Traditional Chinese': [
        '嗶哩嗶哩 新聞',
        '嗶哩嗶哩 股票',
        'B站 動漫 用戶',
        '嗶哩嗶哩 電競 BLG',
        'B站 廣告收入',
        'B站 AniSora AI',
        '嗶哩嗶哩 春節',
        'B站 創作者',
    ],
    'Turkish': [
        'Bilibili nedir',
        'Bilibili Çin video platformu',
        'Bilibili anime',
        'Bilibili hisse',
        'Bilibili espor',
        'Bilibili AniSora yapay zeka',
        'Bilibili platform inceleme',
        'Bilibili YouTube Çin',
    ],
    'Russian': [
        'Bilibili новости',
        'Bilibili платформа видео Китай',
        'Bilibili аниме',
        'Bilibili акции',
        'Bilibili киберспорт',
        'Bilibili AniSora ИИ',
        'Bilibili обзор платформа',
        'Bilibili китайский YouTube',
    ],
    'Spanish': [
        'Bilibili noticias',
        'Bilibili plataforma china',
        'Bilibili anime',
        'Bilibili acciones',
        'Bilibili esports',
        'Bilibili AniSora inteligencia artificial',
        'Bilibili qué es plataforma',
        'Bilibili China streaming',
    ],
    'Portuguese': [
        'Bilibili notícias',
        'Bilibili plataforma chinesa',
        'Bilibili anime',
        'Bilibili ações',
        'Bilibili esports',
        'Bilibili AniSora inteligência artificial',
        'Bilibili o que é',
        'Bilibili China streaming',
    ],
    'Simplified Chinese': [
        '哔哩哔哩 新闻',
        'B站 股票 财报',
        'B站 动漫 用户',
        '哔哩哔哩 电竞 BLG',
        'B站 广告收入',
        'B站 AniSora AI',
        '哔哩哔哩 春节晚会',
        'B站 创作者 UP主',
        'B站 2026',
        '哔哩哔哩 可转债',
    ],
}

# Google News RSS params per language — reliable multilingual news source
_GNEWS_PARAMS = {
    'English':            {'hl': 'en',    'gl': 'US', 'ceid': 'US:en'},
    'Japanese':           {'hl': 'ja',    'gl': 'JP', 'ceid': 'JP:ja'},
    'Arabic':             {'hl': 'ar',    'gl': 'SA', 'ceid': 'SA:ar'},
    'Traditional Chinese':{'hl': 'zh-TW', 'gl': 'TW', 'ceid': 'TW:zh-Hant'},
    'Turkish':            {'hl': 'tr',    'gl': 'TR', 'ceid': 'TR:tr'},
    'Russian':            {'hl': 'ru',    'gl': 'RU', 'ceid': 'RU:ru'},
    'Spanish':            {'hl': 'es',    'gl': 'ES', 'ceid': 'ES:es'},
    'Portuguese':         {'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'},
    'Simplified Chinese': {'hl': 'zh-CN', 'gl': 'CN', 'ceid': 'CN:zh-Hans'},
}

# Domains to skip (not content pages)
_SKIP_DOMAINS = {
    'youtube.com', 'reddit.com', 'play.google.com', 'apps.apple.com',
    'wikipedia.org', 'bilibili.com', 'bilibili.tv', 'github.com',
}


def _google_news_rss(query, hl, gl, ceid, max_results=20):
    """Fetch article URLs from Google News RSS. Returns list of URLs."""
    import xml.etree.ElementTree as ET
    import urllib.parse
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        urls = []
        for item in root.iter('item'):
            # Try <link> tag first, then <guid>
            link_el = item.find('link')
            guid_el = item.find('guid')
            url = None
            if link_el is not None and link_el.text and link_el.text.startswith('http'):
                url = link_el.text.strip()
            elif guid_el is not None and guid_el.text and guid_el.text.startswith('http'):
                url = guid_el.text.strip()
            if url:
                domain = urlparse(url).netloc.lower().replace('www.', '')
                if not any(skip in domain for skip in _SKIP_DOMAINS):
                    urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


def _bing_news_rss(query, mkt='en-US', max_results=20):
    """Fetch article URLs from Bing News RSS. Returns list of URLs."""
    import xml.etree.ElementTree as ET
    import urllib.parse
    rss_url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=RSS&mkt={mkt}"
    try:
        resp = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        urls = []
        for item in root.iter('item'):
            link_el = item.find('link')
            url = None
            if link_el is not None and link_el.text and link_el.text.startswith('http'):
                url = link_el.text.strip()
            if url:
                domain = urlparse(url).netloc.lower().replace('www.', '')
                if not any(skip in domain for skip in _SKIP_DOMAINS):
                    urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


# Bing News market codes per language
_BING_MARKETS = {
    'English':            'en-US',
    'Japanese':           'ja-JP',
    'Arabic':             'ar-SA',
    'Traditional Chinese':'zh-TW',
    'Simplified Chinese': 'zh-CN',
    'Turkish':            'tr-TR',
    'Russian':            'ru-RU',
    'Spanish':            'es-ES',
    'Portuguese':         'pt-BR',
}


def _ddg_search(query, max_results=20, region='wt-wt', timelimit=None):
    """DuckDuckGo search via duckduckgo-search library — returns list of URLs.
    timelimit: 'd'=day, 'w'=week, 'm'=month, 'y'=year, None=all time
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=region, timelimit=timelimit, max_results=max_results))
        urls = []
        for r in results:
            url = r.get('href', '')
            if not url:
                continue
            domain = urlparse(url).netloc.lower().replace('www.', '')
            if any(skip in domain for skip in _SKIP_DOMAINS):
                continue
            if url not in urls:
                urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


# DDG region codes per language — multiple regions for better coverage
_LANG_REGIONS = {
    'English': ['us-en', 'uk-en', 'wt-wt'],
    'Japanese': ['jp-jp', 'wt-wt'],
    'Arabic': ['xa-ar', 'wt-wt'],
    'Traditional Chinese': ['hk-tzh', 'tw-tzh', 'wt-wt'],
    'Turkish': ['tr-tr', 'wt-wt'],
    'Russian': ['ru-ru', 'wt-wt'],
    'Spanish': ['es-es', 'ar-es', 'mx-es', 'wt-wt'],
    'Portuguese': ['br-pt', 'pt-pt', 'wt-wt'],
    'Simplified Chinese': ['cn-zh', 'wt-wt'],
}


# Known domains with Bilibili content — crawl their listing pages for fresh articles
_DIRECT_CRAWL_SOURCES = [
    # English
    'https://www.ainvest.com/news/?q=bilibili',
    'https://www.invenglobal.com/lol/teams/bilibili-gaming',
    'https://www.vlr.gg/team/12010/bilibili-gaming',
    'https://longbridge.com/en/news?keyword=bilibili',
    # Traditional Chinese (Hong Kong/Taiwan)
    'http://www.aastocks.com/tc/usq/quote/stock-news.aspx?symbol=BILI',
    'https://hk.finance.yahoo.com/quote/9626.HK/news/',
    'https://www.etnet.com.hk/www/tc/stocks/realtime/quote_news_detail.php?code=09626',
    # Japanese
    'https://fistbump-news.jp/?s=bilibili',
    'https://media.rakuten-sec.net/search/?q=%E3%83%93%E3%83%AA%E3%83%93%E3%83%AA',
    # Simplified Chinese
    'https://www.huxiu.com/search.html?q=B站',
    'https://www.aibase.com/zh/search?q=bilibili',
]


def crawl_direct_sources(max_urls=50):
    """
    Crawl known good domains' listing/search pages to extract fresh article links.
    Returns list of URLs found on these pages.
    """
    all_urls = []
    seen = set()
    for listing_url in _DIRECT_CRAWL_SOURCES:
        try:
            resp = requests.get(listing_url, headers=BROWSER_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            base_domain = urlparse(listing_url).netloc
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if href.startswith('/'):
                    href = f"https://{base_domain}{href}"
                elif not href.startswith('http'):
                    continue
                link_domain = urlparse(href).netloc.replace('www.', '')
                if any(skip in link_domain for skip in _SKIP_DOMAINS):
                    continue
                if href not in seen and len(href) > 30:
                    seen.add(href)
                    all_urls.append(href)
        except Exception:
            continue
    return all_urls[:max_urls]


def auto_discover(languages=None):
    """
    Auto-discover Bilibili mentions in specified language(s) using DDG.
    Pass one language at a time to stay within gunicorn timeout.
    Uses multiple regions per language for better coverage.
    Time budget: 50s for DDG search, rest for scan pipeline.
    Returns per-language summary.
    """
    import time

    if languages is None:
        languages = list(_DISCOVER_QUERIES.keys())

    results = {}
    for lang in languages:
        queries = _DISCOVER_QUERIES.get(lang, [])
        if not queries:
            continue

        regions = _LANG_REGIONS.get(lang, ['wt-wt'])

        # Collect URLs from all queries × all regions for this language
        # Time budget: 50s for DDG searches (leaves ~60s for download+analyze+save)
        all_urls = []
        seen = set()
        search_start = time.time()

        # Bilibili-specific Google News queries (broader for Simplified Chinese)
        gnews_queries = ['bilibili', 'bilibili platform', 'bilibili anime']
        if lang == 'Simplified Chinese':
            gnews_queries = ['哔哩哔哩', 'B站', 'bilibili 哔哩哔哩', '哔哩哔哩 2026', 'B站 股票']
        elif lang == 'Traditional Chinese':
            gnews_queries = ['嗶哩嗶哩', 'B站', 'bilibili', '嗶哩嗶哩 2026']
        elif lang == 'Japanese':
            gnews_queries = ['ビリビリ', 'bilibili', 'ビリビリ 2026', 'BLG esports']
        elif lang == 'Arabic':
            gnews_queries = ['بيليبيلي', 'bilibili', 'bilibili 2026']

        # 1. Google News RSS — fast, multilingual
        gnews = _GNEWS_PARAMS.get(lang)
        if gnews:
            for q in gnews_queries:
                if time.time() - search_start > 15:
                    break
                urls = _google_news_rss(q, gnews['hl'], gnews['gl'], gnews['ceid'], max_results=20)
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)

        # 2. Bing News RSS — separate index from Google (max 5s, 1-2 queries)
        bing_mkt = _BING_MARKETS.get(lang, 'en-US')
        for q in gnews_queries[:2]:
            if time.time() - search_start > 20:
                break
            urls = _bing_news_rss(q, mkt=bing_mkt, max_results=20)
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    all_urls.append(u)

        # 3. DDG — broader search, main workhorse (budget: 20s–65s = 45s)
        for q in queries:
            if time.time() - search_start > 65:
                break
            for region in regions:
                if time.time() - search_start > 65:
                    break
                urls = _ddg_search(q, max_results=20, region=region, timelimit='y')
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)
                # If first region already found enough URLs for this query, skip extras
                if len(urls) >= 10:
                    break

        # Run through scan pipeline
        if all_urls:
            scan_result = scan_urls(all_urls)
        else:
            scan_result = {'received': 0, 'new': 0, 'with_2026': 0, 'saved': 0, 'skipped': 0}

        scan_result['language'] = lang
        scan_result['queries'] = len(queries)
        scan_result['urls_found'] = len(all_urls)
        results[lang] = scan_result

    # Bonus: direct domain crawl (outside language loop, runs once per discover call)
    try:
        direct_urls = crawl_direct_sources(max_urls=60)
        if direct_urls:
            direct_result = scan_urls(direct_urls)
            direct_result['language'] = 'direct_crawl'
            results['direct_crawl'] = direct_result
    except Exception:
        pass

    return results


def delete_mentions(ids):
    """Delete mentions by ID list."""
    deleted = 0
    for mid in ids:
        try:
            _db().table('social_mentions').delete().eq('id', mid).execute()
            deleted += 1
        except Exception:
            pass
    return deleted


def update_mention(mid, content_english=None, content_original=None, language=None):
    """Update a mention's fields. Only updates provided fields."""
    updates = {}
    if content_english is not None:
        updates['content_english'] = content_english
    if content_original is not None:
        updates['content_original'] = content_original
    if content_english or content_original:
        updates['content_hash'] = hash_content(content_original or content_english)
    if language is not None:
        updates['language'] = language
    if not updates:
        return False
    try:
        _db().table('social_mentions').update(updates).eq('id', mid).execute()
        return True
    except Exception:
        return False


def compute_stats_and_dates(mentions):
    """Compute stats and available dates from already-fetched mentions (zero extra DB calls)."""
    pos = sum(1 for m in mentions if m.get('sentiment') == 'positive')
    neg = sum(1 for m in mentions if m.get('sentiment') == 'negative')
    neu = sum(1 for m in mentions if m.get('sentiment') == 'neutral')
    dates = sorted(set(m['content_date'] for m in mentions if m.get('content_date')), reverse=True)
    stats = {'total': len(mentions), 'positive': pos, 'negative': neg, 'neutral': neu}
    return stats, dates
