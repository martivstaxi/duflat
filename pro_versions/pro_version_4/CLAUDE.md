# Duflat — Technical Reference

## What This Project Does

**Duflat.com** is a YouTube channel investigation platform. Users paste any YouTube URL (video, channel, handle, @username) and the system:

1. **Identifies the channel** — extracts all metadata
2. **Scrapes the about page** — email, location, socials, join date, view count
3. **Investigates the agency/management company** behind the channel using a multi-source pipeline + AI

Target users: influencer marketing teams, brand partnership researchers, talent scouts.

---

## Stack

| Layer | Technology | Where |
|---|---|---|
| Frontend | Vanilla HTML/CSS/JS | `index.html` → GitHub Pages (duflat.com) |
| Backend | Python Flask | `app.py` → Railway (duflat-production.up.railway.app) |
| YouTube data | yt-dlp | `modules/scraper.py` |
| Website scraping | requests + BeautifulSoup4 | `modules/agency.py` |
| Web search | DuckDuckGo HTML (no API) | `modules/agency.py` |
| AI analysis | Claude Haiku (claude-haiku-4-5-20251001) | `modules/agency.py` |
| DNS/SSL | Cloudflare Flexible | — |

---

## File Structure

```
duflat/
├── app.py                    Flask routes only (thin layer)
├── index.html                Full frontend SPA
├── requirements.txt          Python deps
├── Dockerfile                Railway deployment
├── CLAUDE.md                 This file
├── ROADMAP.md                Feature roadmap
└── modules/
    ├── __init__.py
    ├── constants.py          Shared regex, platform configs, utilities
    ├── scraper.py            YouTube channel scraping (yt-dlp + about page)
    └── agency.py             Agency/management company investigation
```

**Rule:** `app.py` only imports from `modules/`. All logic lives in modules. New features = new module file.

---

## Modules

### `modules/constants.py`
Pure constants and tiny utilities. No network calls, no side effects.

**Exports:**
- `SOCIAL_PLATFORMS` — dict of platform configs (regex, URL format, validator)
- `INVALID_USERNAMES` — sets of blacklisted usernames per platform
- `RE_EMAIL`, `EMAIL_BLACKLIST` — email extraction
- `NAV_DOMAINS`, `YT_DOMAINS` — domains to skip in link extraction
- `BROWSER_HEADERS` — realistic browser headers for requests
- `RE_EMBED`, `RE_CLEAN` — YouTube URL cleanup regex
- `is_valid_username(username, platform)` → bool
- `decode_redirect(url)` → str — resolves youtube.com/redirect?q=... URLs

**When to edit:** Adding a new social platform, updating headers, adding shared regex.

---

### `modules/scraper.py`
YouTube channel metadata extraction.

**Key technique:** `InfoExtractor._download_webpage` monkey-patch to intercept yt-dlp's internal HTTP calls and capture ytInitialData HTML before YouTube's consent redirect can block it. Protected by `threading.Lock`.

**Public API:**
```python
scrape_channel(url: str) -> dict
```
Accepts any YouTube URL. Returns flat dict:
```json
{
  "channel_url": "https://www.youtube.com/channel/UC...",
  "name": "Channel Name",
  "handle": "@handle",
  "subscribers": "1,234,567",
  "views": "99,999,999",
  "videos": "361",
  "description": "...",
  "email": "contact@example.com",
  "location": "Turkey",
  "joined": "Jan 1, 2020",
  "last_video_date": "3 days ago",
  "thumbnail": "https://...",
  "instagram": "https://www.instagram.com/...",
  "twitter": "https://x.com/...",
  "all_links": ["https://..."]
}
```
On error: `{"error": "message"}`

**Internal functions:**
- `normalize_url(url)` — handles handles, short URLs, embed URLs
- `fetch_about_page(channel_url)` → 8-tuple: socials, links, email, location, joined, views, video_count, last_video_date
- `_extract_about_via_ytdlp(channel_url)` → (html, parsed_dict) — the monkey-patch magic
- `extract_socials_from_text(text)` → (socials_dict, links, email)
- `_oembed_channel_url(video_url)` → (channel_url, channel_name) — oEmbed fallback

---

### `modules/agency.py`
Multi-source agency investigation pipeline.

**Investigation pipeline** (stops at first success, then enriches):
```
1. email domain      → _investigate_url(domain)
                     → _search_and_investigate(domain) if scraping fails
                     → return domain as minimal lead if all fails
2. external links    → _investigate_url(link) for each non-social link
3. linktree links    → _try_linktree(url) → extract links → _investigate_url()
4. description regex → find "Management: X" patterns → _search_and_investigate(hint)
5. DDG search        → "{channel_name} management agency booking contact"
6. Claude Haiku      → _llm_find_agency(channel_data) — last resort
```

After finding: `enrich_agency()` runs:
- `_deep_scrape_agency_site()` — scrapes /, /about, /contact, /team, /roster (max 5 pages)
- `_llm_enrich_agency()` — Haiku analyzes all scraped text → structured profile

**Public API:**
```python
find_agency(channel_data: dict) -> dict
```
Returns:
```json
{
  "found": true,
  "source": "email_domain",
  "name": "Agency Name",
  "website": "https://agency.com",
  "description": "...",
  "summary": "...",
  "services": ["talent management", "content production"],
  "contact_email": "hello@agency.com",
  "contact_phone": "+1 555 ...",
  "address": "Istanbul, Turkey",
  "founded": "2018",
  "socials": {"linkedin": "https://...", "instagram": "https://..."},
  "notable_clients": ["Channel A", "Artist B"],
  "reasoning": "Found via email domain iamxlive.com"
}
```
Or: `{"found": false}`

**source values:** `email_domain`, `external_link`, `linktree`, `description_regex`, `web_search`, `ai_analysis`

---

## API Endpoints

### `POST /scrape`
Request: `{"url": "https://youtube.com/watch?v=..."}`
Response: channel data dict (see scraper module) or `{"error": "..."}` with 500

### `POST /agency`
Request (option A — preferred, avoids re-scraping):
```json
{"channel_data": { ...full scrape result... }}
```
Request (option B):
```json
{"url": "https://youtube.com/..."}
```
Response: agency result dict or `{"error": "..."}`

### Debug endpoints (GET)
- `/debug?url=` — raw yt-dlp scalar fields
- `/debug-about?url=` — about page extraction results
- `/debug-rawpage?url=` — ytInitialData HTML snippets
- `/debug-deep?url=` — full yt-dlp info dict (2-level truncated)

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `PORT` | No (default 5000) | Flask/gunicorn port (Railway sets this automatically) |
| `ANTHROPIC_API_KEY` | Yes for AI features | Claude Haiku calls in agency.py |

---

## Frontend Flow

```
User pastes URL
  → POST /scrape (shows loader: "Fetching channel info...")
  → renderResult(data) — channel card appears
  → investigateAgency(channelData) starts immediately (parallel)
      → showAgencyLoading() — agency card shows spinner with cycling step text
      → POST /agency with channel_data
      → renderAgency(data) — agency card fills in or shows "not found"
```

---

## Adding a New Feature

Example: adding a "Generate Email" feature.

**Step 1 — New module** `modules/email_generator.py`:
```python
def generate_outreach_email(channel_data: dict, agency_data: dict) -> dict:
    """Generate personalized outreach email using channel + agency data."""
    # fetch last N video transcripts
    # analyze with Claude
    # return {"subject": "...", "body": "..."}
```

**Step 2 — New route** in `app.py`:
```python
from modules.email_generator import generate_outreach_email

@app.route('/generate-email', methods=['POST'])
def generate_email():
    body = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    agency_data  = body.get('agency_data', {})
    result = generate_outreach_email(channel_data, agency_data)
    return jsonify(result)
```

**Step 3 — Frontend** in `index.html`:
- Add button to existing result card
- Add `generateEmail(channelData, agencyData)` async function
- Add email modal/card render function

**That's it.** No other files need touching.

---

## Deployment

- **Push to main** → Railway auto-deploys backend (takes ~2 min)
- **Push to main** → GitHub Pages auto-serves `index.html`
- Railway git user: `martivstaxi` / `martivstaxi@users.noreply.github.com`
- gunicorn: 1 worker, 120s timeout (enough for agency investigation)

---

## Known Technical Decisions

**Why monkey-patch `_download_webpage`?**
Railway datacenter IPs get redirected to `consent.youtube.com`. yt-dlp handles consent internally via its `_download_webpage`. By patching this method, we intercept the already-consent-handled HTML without having to manage cookies ourselves.

**Why Claude Haiku and not a bigger model?**
Speed + cost. Haiku is fast enough for real-time investigation and costs ~$0.001/call. The structured JSON prompt works reliably.

**Why DuckDuckGo HTML scraping?**
No API key, no rate limit registration, free. DDG HTML endpoint returns clean results.

**Why single gunicorn worker?**
The monkey-patch on `InfoExtractor._download_webpage` is not safe for concurrent use. `threading.Lock` protects it but with 1 worker there's no cross-worker conflict. If scaling to multiple workers is needed, the monkey-patch must be replaced with a per-request yt-dlp config or subprocess approach.
