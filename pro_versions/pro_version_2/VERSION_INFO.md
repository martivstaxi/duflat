# pro_version_2 — Snapshot: 2026-04-04

## Bu versiyon ne?

pro_version_1 üzerine yapılan tüm düzeltmeler ve AI Summary yeniden yazımı tamamlandıktan sonra alınan yedek.

## Tarih
2026-04-04

## Commit referansı
`f168cce` — "Language detection: algorithmic, zero AI tokens"

## pro_version_1'den bu versiyona yapılan değişiklikler

### Bug Fixes
- **Email decode fix** (`scraper.py`): `_try_decode_b64_email()` artık doğru base64 padding kullanıyor ve strict UTF-8 decode yapıyor — garbled email output sorunu çözüldü
- **Subscribers fix** (`scraper.py`): yt-dlp video URL'lerinde `channel_follower_count: null` döndürüyor; `fetch_about_page` artık ytInitialData HTML'inden `subscriberCountText` regex ile çıkarıp fallback olarak kullanıyor
- **AI Summary button scope fix** (`index.html`): `window._currentChannelData` undefined hatası düzeltildi, `summarizeChannel()` closure üzerinden `_currentChannelData`'ya erişiyor

### Yeni Özellik: Manuel AI Summary
- AI özet artık otomatik çalışmıyor — her kanal araştırmasında token harcamıyor
- "✨ AI Summary" butonu eklendi (About label'ın yanında)
- Tıklanınca analiz başlıyor, tamamlanınca "✅ Report Ready" oluyor

### AI Summary Tamamen Yeniden Yazıldı
- **7 field → structured report** (niche, audience, upload_frequency, content_style, brand_fit, key_insight + content_language)
- **Tablo görünümü**: düz paragraf yerine 2 sütunlu HTML table
- **Dil tespiti algoritmik** (`_detect_language()`): Unicode karakter sayımıyla (ğşı = Turkish, Kiril = Russian vb.) sıfır AI token ile 15+ dil tespiti
- Dil AI'a FACT olarak geçiliyor, AI değiştiremiyor → "Mixed/Bilingual" hatası ortadan kalktı
- 15 video başlığı çekiyor (eskiden 8)
- Zaten ekranda görünen bilgileri (subs/views/join date) tekrar etmiyor

## Bilinen açık sorunlar
- Yok — tüm bilinen buglar düzeltildi

## Stack
- Backend: Python Flask (Railway)
- Frontend: index.html (GitHub Pages / duflat.com)
- AI: Claude Haiku (claude-haiku-4-5-20251001)
- YouTube: yt-dlp + InnerTube API
