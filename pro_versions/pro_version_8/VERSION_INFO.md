# pro_version_8

**Tarih:** 2026-04-04
**Aciklama:** AI Report v2 — video transkript analizi + avatar fix

## Degisiklikler

### Yeni: AI Report v2 (summarizer_v2.py)
- Son 5 + en populer 5 videonun transkriptleri yt-dlp ile indirilir
- Haiku ile icerik analizi yapilir (niche, themes, audience, style, brand fit, key insight)
- key_insight: bullet point format, plain English, data-driven
- Endpoint: POST /summarize-v2

### Avatar Fix
- scraper.py: break indentation bug duzeltildi (ikinci thumbnail loop)
- Video URL'lerinde about page avatar bulunamayinca channel_url'den fallback

### Diger
- youtube-transcript-api kaldirildi, yt-dlp subtitle (ydl.urlopen) kullaniliyor
- debug-subs endpoint eklendi

## Dosyalar
- index.html — canli frontend (v2 rapor dahil)
- app.py — /summarize-v2 + /debug-subs route'lari
- summarizer_v2.py — video transkript analiz modulu
- scraper.py — avatar fix
- requirements.txt — youtube-transcript-api kaldirildi
