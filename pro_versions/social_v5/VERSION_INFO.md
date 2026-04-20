# Social v5 — 2026-04-20

## Neler Var

- **İki-katmanlı sensitivity classifier** — `_layer3_sensitivity_batch`
  - Pass A: P0 (active crisis) binary detector üzerinde tüm batch
  - Pass B: P1 (concern signal) binary detector non-P0 üzerinde
  - Kalan her şey → P2 (medium)
  - Eski tek geniş prompt her şeyi "low" / "neutral"a yığıyordu; yeni dar binary prompt'lar P0 ve P1'i gerçekten ayırıyor
- **Ayrı meta katmanı** — `_layer3_meta_batch`: sentiment + source_type kendi dar promptunda
- **Sharpened sentiment prompt** — "olay Bilibili için iyi mi kötü mü, yazar tonu değil" kuralı + pozitif/negatif örnek listesi
- **EN / 中文 UI toggle** — sağ üst fixed, `navigator.language` ile auto-detect, `localStorage` override
- **Simplified Chinese UI lokalizasyonu** — tüm UI string'leri (başlık, filtre başlıkları, ay/gün isimleri, empty/loading, details butonu) `I18N` sözlüğünden; dil isimleri (English → 英语) TL() ile çevrilir
- **Per-mention Chinese translation** — L2 extract artık `content_chinese` da üretir; zh UI'de kart özetleri Çince, content_original her zaman kaynak dilinde
- **Hashtag chip'leri kaldırıldı** — `keywords` backend'de saklanmaya devam ediyor, sadece UI'dan çıkarıldı
- **Noto Sans SC font** — `html[lang^="zh"]` seçiciyle otomatik CJK font

## Dosyalar

- `social.html` — canlı (inline CSS+JS), duflat.com/social
- `social_test.html` — test (`static/social_*.css/js` linkli), duflat.com/social_test
- `social_app.js` + `social_style.css` — static/ altındaki ayrık yapı

## DB Migration (bir kerelik, v5 ile birlikte çalıştırıldı)

```sql
ALTER TABLE social_mentions ADD COLUMN content_chinese TEXT;
```

## Yeni Endpoint

- `POST /social/translate-missing` — `content_chinese` boş olan mentionlar için Haiku ile toplu çeviri backfill (batch 10, max_tokens 4096)

## Backend Pipeline (v5 itibarıyla)

```
process_urls (fetch + 2026 date check)
  → L1 TRIAGE     (Haiku yes/no: Bilibili mention + scope + social angle)
  → L2 EXTRACT    (Haiku: content_english + content_chinese + content_original + meta)
  → L3 SENSITIVITY (Haiku x2: P0 binary, sonra non-P0 için P1 binary)
  → L3 META       (Haiku: sentiment + source_type)
  → _validate_and_repair
  → save_mentions (Mainland + Simplified Chinese scope filter) → DB
```
