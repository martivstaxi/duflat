# pro_version_10

**Tarih:** 2026-04-04
**Açıklama:** Personalized Email Generator — Bilibili davet emaili, Sonnet ile

## Değişiklikler

- **Yeni modül:** `modules/email_generator.py` — Claude Sonnet ile kişisel email
- **Yeni endpoint:** `POST /generate-email`
- **✨ Personalized Email butonu:** AI Report hazır olunca Report Ready yanında belirir
- Email kanalın dilinde yazılır (content_language)
- Em dash (`—`) kullanımı yasaklandı (prompt + post-processing)
- Subject ve Body için ayrı Copy butonları
- Dots animasyonu ile email yazılma loading gösterimi
- Email preview kartı external links altında, agency butonundan önce
- Smooth scroll ile email hazır olunca otomatik kayma
- UI polish: Apple-style butonlar, spacing düzeltmeleri

## Dosyalar

- `index.html` — Canlı frontend
- `test.html` — Test frontend
- `app.py` — Flask routes (+generate-email)
- `email_generator.py` — Yeni modül
- `*.py` — Tüm modüller
