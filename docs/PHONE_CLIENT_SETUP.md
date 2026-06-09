# AgentCockpit Phone Client

Bu hat, AgentCockpit'in telefon/PWA moduludur. Ayrı bir Telegram botu baslatmaz; ana bot kokteki `main.py` ile acilir.

## Ne Var

- `phone_bridge_server.py`
  Mevcut masaustu araclarini kullanarak telefon istemcisine screenshot ve kontrol endpoint'leri sunar.
- `phone_client/index.html`
  Dokunma, scroll ve keyboard odakli mobil arayuz.
- `phone_client/manifest.webmanifest`
  Ana ekrana eklemeye uygun hafif PWA manifesti.

## Neyi Bilerek Yapmiyor

- Telegram polling yapmaz
- ngrok acmaz
- mevcut botun mesaj akisina karismaz

## Calistirma

En kolay yol:

```powershell
.\venv\Scripts\python.exe .\main.py
```

Bu tek giris hem `phone_bridge_server.py` hem de tek Telegram botunu birlikte kaldirir.
Ek olarak local pairing sayfasini tarayicida otomatik acar.
`TELEGRAM_TOKEN` placeholder ise bundan once local ilk kurulum sayfasi acilir; BotFather token'i burada dogrulanip `.env` dosyasina yazilir.
Tarayici veya masaustu otomasyonu bu makinede hazir degilse AgentCockpit bunu startup sirasinda raporlar ve mumkun olan kisimlari kisitli modda calistirir.

Bridge acildiginda pairing dashboard da hazir olur:

```text
http://127.0.0.1:8765/pair
```

PC uyumlulugunu hizli kontrol etmek istersen:

```powershell
python main.py --doctor
```

En temiz ilk kurulum akisi:

1. PC'de bu pairing sayfasini ac
2. Telefonda kamerayla QR'i okut
3. AgentCockpit PWA'yi ac
4. `Yukle` veya `Ana Ekrana Ekle` ile uygulama gibi sabitle

Ayri ayri acmak istersen:

```powershell
.\venv\Scripts\python.exe .\phone_bridge_server.py
```

Alternatif:

```powershell
.\launch_phone_client.bat
```

Sunucu acildiginda konsolda yerel URL'leri ve hazirsa uzak URL'yi yazar:

- `LAN URL`
- `WAN URL`
- `Local URL`

Telefonda ayni Wi-Fi uzerindeysen `LAN URL` ile ac. Disaridan baglanacaksan `WAN URL` veya pairing sayfasindaki `Baglantiyi Ac` dugmesi ayni PWA'yi acabilir.
Bu link artik varsayilan olarak sinirsizdir.
Ilk acilista istemci seni uygulama gibi kurmaya da yonlendirir.
QR pairing dashboard sadece bu PC'den acilir; boylece link mint etme sayfasi LAN'a acik kalmaz. Link suresi ayari da sadece bu local sayfadan degistirilebilir.
Ilk pairing sonrasi telefon guvenilir cihaz olarak kaydolur; bot/bridge yeniden baslasa da ayni origin uzerinden PWA tekrar QR istemeden acilabilir.
Not: Hesapsiz Quick Tunnel uzak adresi yeniden baslatmalarda degisebilir. Bu eslesmeyi silmez.
Bot aciksa adres degisimini izler ve yeni `Uzak Ac` linkini Telegram'a otomatik yollar; bu yeni linke dokunmak tekrar QR okutma yerine gecer.
QR artik sadece saglik kontrolunden gecen bir WAN adresini kullanir; tunnel hazir gorunse bile ulasilamiyorsa pairing otomatik olarak LAN linkine duser. Eski/olu bir Quick Tunnel adresi 530 verirse pairing sayfasini yenileyip yeni QR uretmek yeterlidir.

## Opsiyonel Ayarlar

Istersen root `.env` dosyana bunlari ekleyebilirsin. Ornek ayarlar root `.env.example` icinde:

- `PHONE_BIND=0.0.0.0`
- `PHONE_PORT=8765`
- `PHONE_ADMIN_TOKEN=`
  Opsiyonel. Bos birakilirsa AgentCockpit kurulum/cihaz bazli guclu bir token'i otomatik uretir.
- `PHONE_SESSION_MINUTES=0`
- `PHONE_POLL_MS=1400`
- `TELEGRAM_BOT_USERNAME=bot_kullanici_adi`
- `PHONE_TELEGRAM_URL=https://t.me/bot_kullanici_adi`
- `PHONE_SCREENSHOT_QUALITY=55`
- `PHONE_SCREENSHOT_MAX_WIDTH=1600`
- `PHONE_PUBLIC_TUNNEL=auto`
- `PHONE_PUBLIC_TUNNEL_DOWNLOAD=1`
- `PHONE_PUBLIC_TUNNEL_MAX_RESTARTS=0`
- `PHONE_PUBLIC_TUNNEL_RESTART_DELAY_SEC=3`
- `PHONE_PUBLIC_TUNNEL_RESTART_MAX_DELAY_SEC=60`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_CACHE_SEC=8`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_GRACE_SEC=120`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_FAILURES_BEFORE_RESTART=3`
- `PHONE_KEEP_AWAKE=1`
- `PHONE_KEEP_AWAKE_FLAGS=-dims`
- `PHONE_CAPTURE_LOCK_TIMEOUT_SEC=3.0`
- `PHONE_STREAM_MAX_CONNECTIONS=2`
- `PHONE_STREAM_MAX_SECONDS=600`
- `PHONE_STREAM_GC_EVERY_FRAMES=120`
- `CLOUDFLARED_FORCE_GO_DNS=auto`
- `PHONE_NOTIFY_TUNNEL_CHANGES=1`
- `PHONE_NOTIFY_TUNNEL_INTERVAL_SEC=20`

## Ekran ve Isaretci Notu

- macOS Retina ekranlarda screenshot boyutu ile masaustu logical koordinatlari farkli olabilir.
- Kirmizi fare noktasi bu fark dikkate alinerek cizilir; isaretci screenshot ustunde gercek konuma olabildigince yakin gosterilir.
- `/health` icindeki `capture_available`, `capture_error`, `capture_last_error_at`, `active_streams`, `max_streams` ve `keep_awake_active` alanlari goruntu aktarimi sorununu teshis etmek icindir.
- `screen=unavailable` veya `capture_error=screen metrics unavailable` gorulurse bridge calisiyor olsa bile macOS ekran oturumu yakalanabilir durumda degildir. Ekrani uyandirip kilidi acmak, Screen Recording iznini kontrol etmek ve uygulamayi LaunchAgent/GUI oturumundan baslatmak gerekir.
- `PHONE_KEEP_AWAKE=1` macOS'ta bridge baslarken `caffeinate` calistirir. Bu basarisiz olursa hata `/health` icindeki `keep_awake_error` alaninda gorunur.
- `PHONE_STREAM_MAX_CONNECTIONS` ve capture lock ayarlari, ayni anda birden fazla WAN sekmesi acildiginda ekran yakalamanin bellek tuketimini sinirlar.
- `CLOUDFLARED_FORCE_GO_DNS=auto`, cloudflared `no such host` ve macOS TLS `OSStatus -26276` hatalari arasinda otomatik DNS stratejisi degistirir. `1` Go DNS'i zorlar, `0` sistem DNS'inden cikmaz.
- `logs/diagnostics/state_<process>_<pid>.json` son heartbeat snapshot'ini, `events_<pid>.jsonl` runtime olaylarini, `fault_<pid>.log` native/thread dump ciktilarini tutar.
- `logs/crashes/crash_*.log` artik traceback'e ek olarak runtime snapshot, thread dump ve son log tail'i icerir. Token/session query degerleri otomatik redakte edilir.

## Guvenlik Notu

- Telefona verilen erisim linki varsayilan olarak sinirsizdir.
- Konsolda gorunen `Admin token`, yeni telefon linkleri uretmek icin ayridir.
- `PHONE_ADMIN_TOKEN` bos birakilirsa kurulum/cihaz bazli bir default token otomatik uretilir.
- Bu bilgiler repo icinde degil, kullanicinin local runtime klasorunde saklanir.
- Yani farkli insanlar ayni projeyi kullansa bile varsayilan tokenlar birbiriyle cakismaz.
- Bu yuzden linki sadece guvendigin cihazlarda kullanmak ve pairing ekranini acikta birakmamak daha dogru olur.

## Yeni Link Uretme

Sunucu acikken yeni bir sinirsiz link almak istersen ayni makinede su istegi calistirabilirsin:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/session-links" `
  -Headers @{ "X-AgentCockpit-Admin" = "ADMIN_TOKEN_BURAYA" } `
  -Body '{"minutes":0,"label":"iphone"}'
```

## Backend Entegrasyonu

Ana botta `Telefon` dugmesi gorunur. Bridge aciksa bot yeni bir sinirsiz telefon linki uretip sana dogrudan yollar.
Ana kullanim pairing sayfasindaki tek PWA akisi olmali; Telegram snapshot modu sadece uzak PWA linki yoksa yedek olarak dusunulmeli.

## PWA Kullanimi

- Android/Chrome tarafinda `Yukle` dugmesi gorunurse dogrudan kullan.
- iPhone/iPad tarafinda Safari icinden `Ana Ekrana Ekle` yolunu izle.
- Kurulumdan sonra istemci tarayici sayfasi gibi degil, uygulama gibi daha temiz acilir.
- Baglanti kopsa bile app shell acik kalir; masaustu koprusu geri geldiginde ayni kisayoldan devam edebilirsin.
- PWA tek kalir; ust rozette `Yerel` veya `Uzak` gorunur.
- `TELEGRAM_BOT_USERNAME` veya `PHONE_TELEGRAM_URL` tanimliysa, uzak PWA hazir degilken Telegram yedegi gorunebilir.

## Sonraki Mantikli Adim

- Uzak adres degisimlerini kullaniciya daha proaktif bildirme
- eslesmis cihazlari arayuzden listeleyip sifirlama
- akisi websocket veya delta-update mantigina yaklastirma
