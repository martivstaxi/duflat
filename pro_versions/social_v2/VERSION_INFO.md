# Social Listening v2

**Tarih:** 2026-04-10
**Proje:** Bilibili Social Listening (duflat.com/social)

## Degisiklikler (v1 → v2)

### Backend (social_listening.py)
- DDG arama iyilestirmeleri: timelimit='y', coklu region, ek sorgular
- Domain TLD → dil ipucu (Haiku'ya gonderiliyor)
- Haiku dil tespiti guclendi (orijinal metin dili, domain hint)
- Zaman butcesi: DDG 50s + URL indirme 55s (timeout onleme)
- Gelecek tarihli mention'lari kaydetme engeli (save_mentions)

### Frontend (social.html / social_test.html)
- Google-style sayfalamali tarih navigasyonu (prev/next ok butonlari)
- Viewport anchoring: tarih/ok degisiminde ekran kaymasi yok
- "All" butonu her zaman gorunur
- Takvim tarih filtresi: 2026 → Month → Calendar grid
- Kart duzeni: sol ust kaynak link, sag ust dil butonu, alt hashtag'ler
- Mention/tarih siralama: bugun/yakin gecmis once, gelecek tarihler filtrelendi
- Toplam sayi "All" butonunda, bos filtre mesaji

### Altyapi
- Gunluk otomatik discover: Claude Code schedule (06:00 Istanbul)
- Trigger ID: trig_01E3sjXFzWZoo1QeLNoVchjp

## Mevcut Durum
- 51 mention (23 EN, 19 ZH, 9 JP, 1 TR) — gelecek tarihli 1 mention silindi
- ~900+ URL incelenmis
- 8 dil destegi, coklu region DDG aramalari

## Dosyalar
- social.html — Canli sayfa
- social_test.html — Test sayfasi (TEST BUILD badge'li)
- social_listening.py — Backend modul
