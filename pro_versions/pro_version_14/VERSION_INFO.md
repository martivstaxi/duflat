# pro_version_14

**Tarih:** 2026-04-05
**Durum:** Stabil

## Degisiklikler

- Hero text: "Find creator's contact" + "Paste any YouTube URL. We'll find the email and details."
- Placeholder: "Video URL..."
- "Creator's External Links" label
- Search butonu: icon-only (SVG buyutec), lowercase mono font, kompakt
- YouTube kanal autocomplete (v13'ten devam): avatar + abone sayisi + Data API v3

## Dosyalar

- `index.html` — canli frontend
- `test.html` — test frontend
- `app.py` — Flask routes (/suggest dahil)
- `modules/` — scraper, email_finder, email_detective, summarizer_v2, email_generator
- `requirements.txt` — Python bagimliliklari
