# pro_version_1 — Snapshot: 2026-04-04

## Bu versiyon ne?

Projenin ilk stabil, çalışan versiyonunun tam yedeği.

## Tarih
2026-04-04

## Commit referansı
`0129340` — "Show hidden email indicator when YouTube requires login"

## Bu versiyonda çalışan özellikler

### Kanal Scraping
- Video URL → Channel URL dönüşümü (oEmbed fallback dahil)
- Subscriber, video sayısı, görüntülenme, description, thumbnail
- Location, join date, last video date
- _download_webpage monkey-patch (Railway consent bypass)

### Email Extraction
- About page regex + yt-dlp full extraction
- İki aşamalı InnerTube (Phase 1: continuation token, Phase 2: aboutChannelViewModel)
- `has_hidden_email` flag: YouTube login gerektiren emailler için badge
- 7-adımlı Find Email pipeline (Step -1 InnerTube → obfuscated → external links → socials → video desc → DDG/Bing → AI)

### Sosyal Medya
- Instagram, TikTok, Twitter/X, Facebook, Discord, Twitch, LinkedIn, MyAnimeList
- Redirect URL decode, about page link cards

### Ajans Araştırma
- 6-adımlı pipeline: email domain → link scraping → linktree → description regex → DDG → AI
- Deep enrichment: multi-page site scraping + Claude Haiku analizi
- Agency card: name, website, services, clients, contact, socials

### AI Özet
- Son 8 video başlıklarından İngilizce creator özeti
- Topic tag üretimi (Claude Haiku)

### Frontend
- Dark theme, vanilla JS SPA
- Paralel scrape + agency kartları
- "Find Email" butonu
- Hidden email badge

## Bilinen açık bug (henüz fix edilmedi)

`_try_decode_b64_email()` bazen garbled output üretiyor (errors='ignore' + `@` kontrolü yeterli değil).
Etkilenen fonksiyon: `modules/scraper.py:51-59`

## Stack
- Backend: Python Flask (Railway)
- Frontend: index.html (GitHub Pages / duflat.com)
- AI: Claude Haiku (claude-haiku-4-5-20251001)
- YouTube: yt-dlp + InnerTube API
