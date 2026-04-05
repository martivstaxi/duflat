# pro_version_13

**Tarih:** 2026-04-05
**Durum:** Stabil

## Degisiklikler

- Hero text guncellendi: "Find creator's contact" + kisa alt yazi
- Arama cubugu placeholder guncellendi: "Search any channel or video URL..."
- YouTube kanal autocomplete: isim yazinca gercek kanallar onerilir (avatar + abone sayisi)
- YouTube Data API v3 ile kanal arama (/suggest endpoint)
- Abone sayisina gore siralama (en populer ust sirada)
- Backend isim arama destegi: bosluklu isimler ytsearch1 ile kanala donusturuluyor
- Oneri tiklaninca otomatik investigate basliyor

## Dosyalar

- `index.html` — canli frontend
- `test.html` — test frontend
- `app.py` — Flask routes (/suggest eklendi)
- `modules/` — scraper (normalize_url ytsearch destegi), email_finder, email_detective, summarizer_v2, email_generator
- `requirements.txt` — Python bagimliliklari
