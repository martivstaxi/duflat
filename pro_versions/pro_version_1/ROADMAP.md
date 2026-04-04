# Duflat — Feature Roadmap

## ✅ Completed

### Phase 1 — Infrastructure
- Flask backend on Railway (Docker)
- GitHub Pages + Cloudflare DNS/SSL
- yt-dlp channel scraping

### Phase 2 — Channel Data
- Video → channel URL extraction
- Subscriber count, video count, views, description, thumbnail
- oEmbed fallback for bot-detection bypass

### Phase 3 — About Page Extraction
- `_download_webpage` monkey-patch (bypasses consent.youtube.com block)
- Email, location, join date, total views, video count
- Last video date from /videos tab

### Phase 4 — Social Media Extraction
- Instagram, TikTok, Twitter/X, Facebook, Discord, Twitch, LinkedIn, MyAnimeList
- From: description text, about page link cards, redirect URL decoding

### Phase 5 — UI Polish
- English UI, dark theme
- "X time ago" relative date formatting
- Duplicate link deduplication
- YouTube links filtered from external links list

### Phase 6 — Agency Finder (Current)
- 6-step investigation pipeline (email domain → scraping → DDG → AI)
- Claude Haiku as last-resort fallback
- Deep website enrichment (multi-page scraping + AI analysis)
- Agency card: name, website, description, summary, services, clients, socials, contact

---

## 🔜 Next Up

### P0 — Personalized Outreach Email Generator
**What:** Button on result page → "Generate Email" → AI writes personalized cold outreach email to the agency/channel on behalf of the user.

**How it works:**
1. Fetch last 10 video titles + descriptions (yt-dlp playlist)
2. Optionally: fetch transcripts via YouTube's subtitle API (yt-dlp `writesubtitles`)
3. Pass channel profile + agency profile + content summary to Claude
4. Claude generates subject line + email body tailored to that creator's content

**New files:**
- `modules/email_generator.py` — transcript fetching + email generation
- New endpoint: `POST /generate-email` with `{channel_data, agency_data, sender_info}`

**UI:** "Generate Email" button appears after agency card loads. Opens email modal with copy button.

---

### P1 — Multi-Channel Agency Map
**What:** Given an agency, find ALL YouTube channels they manage.

**How it works:**
1. Take agency name / domain from agency result
2. DDG search: `site:youtube.com "{agency name}"` + LinkedIn company page scrape
3. Also search: `"managed by {agency}" OR "{agency} talent"`
4. Return list of channel URLs → batch scrape basics for each

**New files:**
- `modules/agency_roster.py`
- New endpoint: `POST /agency-roster` with `{agency_data}`

---

### P2 — Contact Score / Reach Score
**What:** Score how "reachable" a channel is (1–10).

**Factors:**
- Has public email? (+3)
- Has agency with contact info? (+3)
- Active social media? (+2)
- Last video < 30 days? (+2)

Simple calculation, no AI needed.

**Where:** Additional stat in channel card.

---

### P3 — Batch Lookup
**What:** Paste multiple YouTube URLs (one per line) → investigate all → export CSV.

**How it works:**
- Frontend: textarea instead of single input
- Backend: `POST /batch-scrape` with `{urls: []}` — runs scrape_channel() for each
- Agency investigation optional (slower) — checkbox
- Frontend renders table, "Export CSV" button

**New files:**
- Frontend: batch mode toggle
- Backend: `/batch-scrape` and `/batch-agency` endpoints with simple for-loop

---

### P4 — Saved Investigations
**What:** Save investigation results to browser localStorage. "History" panel.

**How it works:** Pure frontend — no backend changes needed.
- On each successful investigation, `localStorage.setItem(channelUrl, JSON.stringify(result))`
- History panel: list of past searches, click to reload result instantly
- "Clear history" button

---

### P5 — Chrome Extension
**What:** Duflat button that appears on YouTube channel/video pages.

**How it works:**
- Chrome extension injects a "Investigate" button on youtube.com pages
- Click → opens duflat.com with the current page URL pre-filled

**New files:** Separate `chrome-extension/` directory with manifest.json + content script.

---

### P6 — Similar Channel Finder
**What:** Given a channel, find similar channels (same niche, same agency, same audience size).

**How it works:**
1. Extract channel category/niche from description + video titles (AI)
2. DDG/YouTube search for similar creators
3. Batch-scrape top results
4. Return ranked list with similarity score

---

## Technical Debt / Improvements

- [ ] Replace monkey-patch with proper yt-dlp plugin or subprocess isolation (enables multi-worker gunicorn)
- [ ] Add response caching (Redis or simple in-memory) for repeated lookups of same channel
- [ ] Rate limiting on Railway endpoints (Flask-Limiter)
- [ ] Proper error logging (Sentry or Railway logs structured output)
- [ ] LinkedIn agency scraping (currently blocked by JS — would need Playwright)
- [ ] Instagram bio scraping (same issue — JS-heavy)
