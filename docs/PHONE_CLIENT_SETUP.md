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
- `PHONE_PUBLIC_TUNNEL_WAIT_SEC=8`
- `PHONE_PUBLIC_TUNNEL_MAX_RESTARTS=5`
- `PHONE_PUBLIC_TUNNEL_RESTART_DELAY_SEC=3`
- `PHONE_PUBLIC_TUNNEL_RESTART_MAX_DELAY_SEC=60`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_CACHE_SEC=8`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_GRACE_SEC=120`
- `PHONE_PUBLIC_TUNNEL_VALIDATE_FAILURES_BEFORE_RESTART=3`
- `PHONE_PUBLIC_TUNNEL_LIMIT_COOLOFF_SEC=300`
- `PHONE_PUBLIC_TUNNEL_FALLBACK=off`
- `PHONE_PUBLIC_TUNNEL_FALLBACK_DELAY_SEC=20`
- `PHONE_BORE_SERVER=159.223.110.159`
- `PHONE_BORE_PUBLIC_HOST=159.223.110.159`
- `PHONE_BORE_REMOTE_PORT=`
  Opsiyonel Bore fallback icindir. Varsayilan kapali kalir; acilirsa bos port degerinde uzak WAN portu otomatik secilir.
- `PHONE_BORE_RESTART_DELAY_SEC=3`
- `PHONE_BORE_RESTART_MAX_DELAY_SEC=60`
- `PHONE_KEEP_AWAKE=1`
- `PHONE_KEEP_AWAKE_FLAGS=-dims`
- `PHONE_CAPTURE_LOCK_TIMEOUT_SEC=3.0`
- `PHONE_DRAG_STEP_PIXELS=16`
- `PHONE_DRAG_STEP_DELAY_MS=4`
- `PHONE_STREAM_MAX_CONNECTIONS=2`
- `PHONE_STREAM_MAX_SECONDS=600`
- `PHONE_STREAM_GC_EVERY_FRAMES=120`
- `CLOUDFLARED_FORCE_GO_DNS=auto`
- `PHONE_NOTIFY_TUNNEL_CHANGES=1`
- `PHONE_NOTIFY_TUNNEL_INTERVAL_SEC=20`

Tarayici istemcisinde `Normal`, sigdirilan goruntunun fiziksel ekran pikseli genisligini kullanir. Arac cubugu, klavye veya yardim panelleri goruntu alanini degistirince `ResizeObserver` yayinin hedef cozunurlugunu da yeniler; yalnizca CSS boyutunu degistirmek JPEG'in tekrar olceklenmesine ve bulanikliga yol aciyordu. Konum ve boyutlar cihaz piksellerine yuvarlanir, kaynak ekran orani kullanilir ve `translate3d` GPU olceklemesi uygulanmaz. Chromium DPR=1 testinde once 1476x954 kare 1352x874'e indirgenirken, duzeltmeyle 1352x873 kare 1352x873 olarak cizildi; DPR 1.25, 1.5 ve 2 de kontrol edildi. Retina kaynak hedef boyuta indirilirken arayuz yazilari icin kenar koruyan metin filtresi kullanilir. `Normal`, JPEG `q85` ve 4:4:4 renk orneklemesi kullanir. `HD`, sigdirilmis gorunumde ayni piksel eslemesini JPEG `q90` ile korur ve kullanici yakinlastirdikca kaynak cozunurlugunu 4096 piksel sinirina kadar otomatik yukselterek detay saglar. `Hizli`, bant genisligini azaltmak icin hedef genisligin yuzde 75'ini kullanir. Tum modlar ekrani kirpmadan sigdirir.

## Ekran ve Isaretci Notu

Yazilar bulaniksa baglanti kartindaki `Sorun Giderme > Kareyi Incele` ile ayni JPEG'i yeniden sikistirmadan dondurup inceleyin. Dugme ilk goruntu geldiginde etkinlesir; acilan pencerede `1:1` ve `Sigdir` bulunur. `1:1`, goruntu piksellerini ekran piksellerine esler; `Sigdir`, ayni kareyi pencereye kucultur. 1:1 net, sigdir bulaniksa olcekleme/ekran yogunlugu etkisini arastirin. Ikisi de bulaniksa kaynak yakalama ve JPEG sikistirmasini inceleyin. Panel, alinan JPEG boyutunu, canli gorunumun ekran piksel boyutunu ve tarayici DPR degerini gosterir. Bu karsilastirma tek basina Windows JPEG cozumleyicisini dogrulamaz.

Akis, hareket sirasinda JPEG kalitesini dusurebilir ama kare genisligini degistirmez. Tarayici yeni kareyi cozumleyene kadar son gecerli goruntuyu korur. Akis kesilirse son karenin yasi goruntunun ustunde belirtilir; saglikli ama hareketsiz ekran bu uyariyi tetiklemez.

- macOS Retina ekranlarda screenshot boyutu ile masaustu logical koordinatlari farkli olabilir.
- Kirmizi fare noktasi bu fark dikkate alinerek cizilir; isaretci screenshot ustunde gercek konuma olabildigince yakin gosterilir.
- Surukleme hedefleri tarayicida her 24 uzak ekran pikselinde uretilir. Bridge iki hedef arasini `PHONE_DRAG_STEP_PIXELS` araligiyla doldurur ve bekleyen son hareketi mouse birakilmadan once uygular.
- `/health` icindeki `capture_available`, `capture_error`, `capture_last_error_at`, `active_streams`, `max_streams` ve `keep_awake_active` alanlari goruntu aktarimi sorununu teshis etmek icindir.
- `screen=unavailable` veya `capture_error=screen metrics unavailable` gorulurse bridge calisiyor olsa bile macOS ekran oturumu yakalanabilir durumda degildir. Ekrani uyandirip kilidi acmak, Screen Recording iznini kontrol etmek ve uygulamayi LaunchAgent/GUI oturumundan baslatmak gerekir.
- `PHONE_KEEP_AWAKE=1` macOS'ta bridge baslarken `caffeinate` calistirir. Bu basarisiz olursa hata `/health` icindeki `keep_awake_error` alaninda gorunur.
- `PHONE_STREAM_MAX_CONNECTIONS` ve capture lock ayarlari, ayni anda birden fazla WAN sekmesi acildiginda ekran yakalamanin bellek tuketimini sinirlar.
- `CLOUDFLARED_FORCE_GO_DNS=auto`, cloudflared `no such host` ve macOS TLS `OSStatus -26276` hatalari arasinda otomatik DNS stratejisi degistirir. `1` Go DNS'i zorlar, `0` sistem DNS'inden cikmaz.
- Cloudflare DNS/TLS hatasi devam ederse hizli sonsuz restart yapilmaz. Varsayilan
  `PHONE_PUBLIC_TUNNEL_MAX_RESTARTS=5` denemeden sonra `PHONE_PUBLIC_TUNNEL_LIMIT_COOLOFF_SEC=300`
  saniye cooloff uygular; `/health` icindeki `public_tunnel_error` macOS DNS/root certificate/Keychain
  sorununu acikca yazar.
- Varsayilan WAN yolu Cloudflare Quick Tunnel'dir. IP tabanli Bore fallback varsayilan kapali tutulur; sadece `PHONE_PUBLIC_TUNNEL_FALLBACK=auto` veya `bore` olarak bilerek acilirsa kullanilir. Uzaktan link uretilmeden telefon/PWA akisi tamamlanmis sayilmaz.
- Uzaktan input tarafinda `Win+L`, macOS `Control+Command+Q`, `Shift+Command+Q`, `sleep`, `power` ve benzeri kilit/uyku kombinasyonlari bilerek engellenir. Bu uygulama kilitli ekrani kontrol edemedigi icin remote-control akisini bozan sistem kisa yollarina fail-closed davranir.
- `/api/action` komutlari `logs/diagnostics/events_<pid>.jsonl` icine audit olarak yazilir. Metin icerigi kaydedilmez; sadece action tipi, hotkey, text uzunlugu, sensitive bayragi ve basari/hata sonucu tutulur.
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

- Klavye hedefi varsayilan olarak otomatik secilir. Manuel Mac veya Parsec secimi yalnizca baglanti kartinin ayrintilarindaki **Sorun Giderme > Klavye hedefi** menusundedir.

- `Hedef: Parsec` seciliyken macOS metin, tek tus ve kisayollari gercek sanal HID klavyeden gonderir. Pano veya sag tik menusu kullanilmaz. Bir defaya mahsus [vhid](https://github.com/promptctl/vhid) ve paketindeki Karabiner DriverKit surucusu kurulup Sistem Ayarlari > Genel > Giris Ogeleri ve Uzantilar > Surucu Uzantilari altindan onaylanmalidir. `vhid doctor` sonucu `ready` olmalidir. Surucu eklenirken Parsec aciksa Parsec'i yeniden baslatin. AgentCockpit root calistirilmaz; imzali yerel yardimci servis surucuye erisir. Bu servis kalicidir ve yerel hesaplarin klavye girdisi uretebilmesini saglar; kurulumdan once [guvenlik etkilerini](https://github.com/promptctl/vhid/blob/master/docs/security.md) inceleyin.
- Hedef Windows klavye duzeni icin `AGENTCOCKPIT_PARSEC_LAYOUT=tr-q` veya `us` secilebilir. Ayar yoksa Mac Turkce Q-PC duzeni `tr-q`, US/ABC duzeni `us` olarak eslenir; diger duzenlerde acik secim gerekir. Windows'taki etkin duzen secimle eslesmeli, Caps Lock kapali olmalidir. Turkce harfler dogrudan fiziksel tus konumlariyla, semboller gerektiginde sag Alt/AltGr ile gonderilir. macOS'un Option ile uretebildigi alternatif harfler kullanilmaz: bunlar Windows'ta metin yerine menuleri tetikleyebilir. Emoji ve desteklenmeyen karakterler ilgili istek baslamadan reddedilir; otomatik pano geri donusu yoktur.
- HID metni/raporlari sadece yerel stdin uzerinden iletilir; komut satirina veya loglara yazilmaz, OTEL aktarimi alt surecte devre disidir. Parsec odagi kaybolursa islem durdurulur ve tuslar birakilir. PWA uzun metinleri sirali 64 karakterlik WAN isteklerine ayirir; sonraki parcalarda yeniden tiklamaz. Bir hata, onceki parcalarin veya mevcut parcanin bir kisminin yazilmis olabilecegi anlamina gelir; otomatik yeniden gonderim yapilmaz. Sonraki parcalardaki desteklenmeyen karakterler de onceki parcalari geri almaz. Servisin raporu kabul etmesi hedef alanda metnin gorundugunun kaniti degildir; canli dogrulama gerekir.
- Modifier raporu harften 60 ms once, birakma raporu harften 40 ms sonra gonderilir. Normal tuslar 120 ms basili tutulur, aralarinda en az 80 ms bosluk birakilir. Tek raporda Shift+harf veya cok kisa basma sureleri Parsec'te buyuk/kucuk harf hatasi ve karakter kaybina yol acabildigi icin kullanilmaz. macOS 27 -> Parsec -> Windows Not Defteri canli testinde Turkce harfler, buyuk harfler, noktalama ve Ctrl+A dogrulandi; uc ayni test satiri toplam 182 karakterle eksiksiz goruldu. Odak, NSWorkspace'in olay dongusune bagli onbellegi yerine canli surec kimligiyle okunur; macOS'un eski Carbon odak API'leri kullanilamazsa Parsec girdisi guvenli bicimde reddedilir.
- `Ekran Sol` ve `Ekran Sag` canli WindowServer Space sirasini okur; hedef Space'i gosterir, oncekini gizler ve aktif Space'i degistirir. Gecis sonrasi hedef kimlik dogrulanamazsa onceki Space'e geri doner ve hata raporlar. Mission Control veya Parsec'in yakalayabilecegi klavye kisayollari kullanilmaz. Bu yol macOS'un ozel SkyLight API'lerine baglidir; isletim sistemi guncellemelerinde tekrar dogrulanmalidir. Space sinirinda islem yapilmaz; farkli ekranlarin Space'leri gizlenmez.
- Uzak adres degisimlerini kullaniciya daha proaktif bildirme
- eslesmis cihazlari arayuzden listeleyip sifirlama
- akisi websocket veya delta-update mantigina yaklastirma
