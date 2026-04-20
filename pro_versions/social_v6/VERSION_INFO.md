# Social v6 — 2026-04-20

## Neler Var (UI Redesign — Apple Inspired)

**Backend ve veri pipeline'i degismedi (v5 ile ayni: 2-katmanli P0/P1 classifier, content_chinese, EN/中文 UI). Bu surum yalniz UI/UX yenilemesi.**

### Apple-inspired tasarim sistemi
- **Tipografi** — SF Pro / system font stack (`-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", Inter`). Headline -0.025em letter-spacing. Merriweather kaldirildi.
- **Sicak/uyumlu palet** — `#f6f3ec` warm cream canvas, `#2b2620` warm graphite text, `#d8d2c3` warm border. Stark black yerine **terrakotta `#b85d3a`** tek aktif renk olarak kullaniliyor (All butonu, takvim, arsiv, dil toggle, filter option, details aciksin).
- **Sentiment renkleri muted** — sage `#3d8a5e`, brick `#b54a35`, ochre `#b08322`.

### Bilesenler
- **Lang toggle** — frosted glass (backdrop-filter blur 20px + saturate 180%), pill, ust sag fixed.
- **Sentiment buttons** — segmented control benzeri pill-leri, hover translateY(-1px) lift + shadow.
- **Filter dropdown** — animasyonlu (cubic-bezier ease-out giris), 16px radius. Aktif option `accent-tint` bg + accent text.
- **Cards** — beyaz, 18px radius (16 mobile), hover translateY(-2px) lift + softer shadow. Border `border-subtle` warm.
- **Priority marker** — 22px **dairesel avatar**, kart disinda solda (left:-32px, top:22px), source link seviyesinde. P0 negative bg, P1 ochre `#d18a2c` bg, P2 outlined transparent. Hover scale(1.08).
- **Date divider** — uppercase tracking, hairline line.
- **Archive** — kart-style date butonlari, hover lift.

### Easing / Tabular numerals
- Tum interaktif elemanlarda `cubic-bezier(.4,0,.2,1)`
- Sayilar `font-variant-numeric: tabular-nums`

## Dosyalar

- `social.html` — canlı (inline CSS+JS), duflat.com/social
- `social_test.html` — test (`static/social_*.css/js` linkli), duflat.com/social_test
- `social_app.js` + `social_style.css` — static/ altındaki ayrık yapı

## Backend Durumu

v5 ile ayni — pipeline / DB schema / endpoint'ler degismedi.
- `process_urls` → L1 TRIAGE → L2 EXTRACT (en + zh + original) → L3 SENSITIVITY (P0 binary + P1 binary) → L3 META → save
- `social_mentions` tablosu `content_chinese` kolonuyla (v5'te eklendi)
- Endpoint'ler: `/social/discover`, `/social/scan`, `/social/reclassify`, `/social/translate-missing`, `/social/cleanup`, `/social/mentions`, `/ping`
