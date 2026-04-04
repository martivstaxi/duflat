# pro_versions — Sürüm Arşivi

Bu klasör, projenin önemli milestone'larında alınan tam kod yedeklerini içerir.

## Nasıl Kullanılır

- **Normal geliştirmede bu klasöre bakılmaz.**
- Yalnızca şu durumlarda açılır:
  1. Proje bozulur ve geri dönük versiyon gerekir
  2. Önceki bir versiyonun nasıl yapıldığı öğrenilmek istenir
  3. Karşılaştırma / diff yapmak gerekir

Her sürüm kendi alt klasöründe `VERSION_INFO.md` içerir — ne içerdiği, hangi tarihe ait olduğu ve bilinen durumu.

## Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|---|---|---|
| [pro_version_1](./pro_version_1/VERSION_INFO.md) | 2026-04-04 | İlk stabil versiyon — scraping, email, ajans, AI özet hepsi çalışıyor |
| [pro_version_2](./pro_version_2/VERSION_INFO.md) | 2026-04-04 | Bug fixes + AI Summary yeniden yazıldı: manuel buton, tablo rapor, algoritmik dil tespiti |
| [pro_version_3](./pro_version_3/VERSION_INFO.md) | 2026-04-04 | UI yeniden yapılandırıldı + kanal avatar + description fix (video desc bug) + email finder timeout |
| [pro_version_4](./pro_version_4/VERSION_INFO.md) | 2026-04-04 | Apple-inspired UI redesign — header kaldırıldı, shadow kartlar, refined spacing, profesyonel görünüm |
