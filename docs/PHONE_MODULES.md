# AgentCockpit Telefon Modulleri

Telefon/PWA modulleri proje kokundedir. Ana calistirma kokteki `main.py` uzerinden yapilir; bu dokuman telefon hattinin ana projeye nasil yerlestigini kayit altinda tutar.

## Su An Burada Olanlar

- `telegram_ux.py`
  Mevcut tek Telegram botunu AgentCockpit UX ve telefon akislariyla genisleten katman
- `phone_bridge_server.py`
  Telefon istemcisi icin hafif HTTP koprusu
- `phone_client/`
  Mobil PWA arayuzu

## Telefon UX Durumu

- varsayilan olarak sinirsiz telefon linki
- local QR pairing dashboard
- admin token ile yeni link uretebilme
- uyarlanabilir polling (`Live / Normal / Eco`)
- dokunma, scroll ve klavye odakli mobil kontrol
- Telegram hattindan `Telefon` dugmesiyle yeni link mint etme
- service worker destekli app shell
- ana ekrana eklenebilir PWA akisi
- tek PWA icinde yerel/uzak baglanti rozeti
- Cloudflare Quick Tunnel ile opsiyonel uzak PWA erisimi
- Telegram uzerinden WAN snapshot modu yedegi

## Calistirma

Ana giris noktasi proje kokundeki `main.py`:

```powershell
.\venv\Scripts\python.exe .\main.py
```

`main.py` acildiginda local pairing sayfasi tarayicida otomatik acilir.
Ilk kurulumda `TELEGRAM_TOKEN` yoksa once sadece bu PC'de calisan local kurulum sayfasi acilir.
BotFather token'ini bu sayfaya yapistirinca token dogrulanir, `.env` dosyasina kaydedilir ve bot kullanici adi otomatik bulunur.
Yeni startup katmani tarayici, GUI oturumu ve public tunnel destegini de onceden kontrol eder; eksik olan kisimlar icin kisitli mod fallback'i uygular.

Telefon istemcisi:

```powershell
.\venv\Scripts\python.exe .\phone_bridge_server.py
```

Bridge acildiginda bu bilgisayarda pairing dashboard da hazir olur:

```text
http://127.0.0.1:8765/pair
```

Bu sayfada QR goruruz. Telefonda kamerayla okutunca LAN linki acilir ve PWA kurulumu daha temiz baslar.
Uzak baglanti hazirsa QR ve `Baglantiyi Ac` dugmesi uzak linki kullanir; degilse yerel linkle devam eder.
Quick Tunnel adresi stale/olu ise QR artik onu kullanmaz; saglikli WAN dogrulanamazsa otomatik LAN fallback uygulanir.
Link suresi varsayilan olarak sinirsizdir; istersen bu PC'de acilan pairing sayfasindan degistirebiliriz.
Ilk pairing tamamlandiktan sonra cihaz guvenilir olarak hatirlanir; bot/bridge yeniden baslasa da ayni origin uzerinden tekrar QR gerekmez.
Hesapsiz uzak tunnel adresi degisirse bot yeni `Uzak Ac` linkini Telegram'a otomatik bildirir.

Ek not:

- macOS Retina ekranlarda screenshot ustundeki kirmizi fare isareti logical/display scale farkina gore normalize edilir.
- Ortam tanisi icin `python main.py --doctor` komutu kullanilabilir.
