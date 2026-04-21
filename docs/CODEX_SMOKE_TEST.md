# Codex Smoke Test

Bu belge Codex entegrasyonunu hizlica dogrulamak icin kullanilir.

## Hazirlik

- Codex Desktop acik olsun.
- Telegram botta ana menude `Codex` butonu gorunsun.
- Windows icin bu proje dizininde `venv` hazir olsun.

## Teknik Smoke Check

Asagidaki komut proje dizininde calistirilir:

```powershell
venv\Scripts\python utils\smoke_codex_transport.py
```

Beklenenler:

- `transport_mode` = `desktop`
- `window_detected` = `true`
- `session_count` `0` veya daha buyuk
- `profile_summary` icinde `Transport: Desktop UI`

## Telegram Smoke Check

1. Botta `Codex` sec.
2. `Durum` butonuna bas.
Beklenen:
- CWD, aktif klasor ve transport bilgisi gelir.

3. `Session Sec` butonuna bas.
Beklenen:
- Codex rollout loglarindan gelen mevcut session listesi gorunur.

4. Bir session sec.
Beklenen:
- Session botta aktif olur.
- Son mesajlar `SEN` ve `CODEX` olarak ayrismis gelir.

5. `Yeni Session` butonuna bas.
Beklenen:
- Codex Desktop'ta yeni thread acilmaya calisilir.

## Dikkat

- Bu entegrasyon masaustu penceresi ve `.codex` rollout loglari ile calisir.
- Canli prompt gonderimi mevcut session'i etkiler; bu yuzden smoke testte otomatik prompt yollamak bilerek zorunlu tutulmadi.
