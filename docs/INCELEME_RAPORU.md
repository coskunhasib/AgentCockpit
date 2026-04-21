# AgentCockpit Inceleme Raporu

Tarih: 2026-04-13
Inceleme tipi: Taze gozuyle ikinci tur teknik inceleme
Kapsam: Kod tabani, yardimci scriptler, config dosyalari, mevcut loglar ve crash kayitlari
Not: Kaynak kod degistirilmedi. Bu turda sadece rapor dosyasi yenilendi.

## Genel Durum

Proje hala calisabilir bir noktada, ama guvenlik, yeniden baslatma dayanıkliligi ve durum yonetimi tarafinda ciddi kirilganliklar tasiyor. Ilk turdan sonra bazi faydali iyilestirmeler yapilmis:

- Screenshot dosya adlari artik mikro saniye iceriyor.
- Telegram dosya yukleme akisi artik dogrudan keyfi path yazmiyor; `updates/` altina indiriyor.
- `pyautogui.FAILSAFE` varsayilan olarak acik kalmis.
- macOS session title kacislama mantigi iyilestirilmis.
- `requirements.txt` sadeleşmis.

Buna ragmen, ana riskler halen su alanlarda toplanmis:

1. Calisma dizinine bagimli path kullanimi
2. Ilk kullaniciyi otomatik sahip yapma tasarimi
3. PID tabanli zayif lock ve surec oldurme mantigi
4. Event loop kapanma senaryosunda toparlanamama
5. Claude entegrasyonunda global state ve sessiz dedup

## Dogrulanan Teknik Durum

- `py_compile` kontrolu gecti; belirgin syntax hatasi yok.
- Mevcut crash loglari `Event loop is closed` probleminin gercekten yasanmis oldugunu gosteriyor.
- Loglar, bazi komutlarin mod secilmeden de calistigini gosteriyor.
- Kodda onceki bazi hatalar kapatilmis olsa da mimari kirilganliklar duruyor.

## Bulgular

### P1 - CWD bagimliligi hala ana kirilma noktasi

Ilgili dosyalar:

- `main.py`
- `autostart.py`
- `core/data_manager.py`
- `core/logger.py`
- `core/system_tools.py`

Sorun:

- `main.py` icinde `venv` ve `requirements.txt` icin `os.getcwd()` kullaniliyor.
- `core/data_manager.py` `hotkeys.json` dosyasini relatif okuyor.
- `core/logger.py` log dizinlerini relatif olusturuyor.
- `core/system_tools.py` screenshot klasorunu relatif olusturuyor.
- Windows autostart kaydi task icin net bir working directory guvencesi koymuyor.

Etkisi:

- Bot farkli bir dizinden acilinca yeni `venv` yanlis yerde olusabilir.
- Loglar, hotkey verisi ve screenshot klasoru baska yerde cikabilir.
- Sorunlar makineden makineye rastgele gorunebilir.

Sonuc:

- Bu, projenin en buyuk operasyonel riski olmaya devam ediyor.

### P1 - Ilk yazan kullaniciyi otomatik owner yapmak guvenlik acigi

Ilgili dosya:

- `core/bot_engine.py`

Sorun:

- `ALLOWED_USER_ID` bos ise bota ilk yazan kisi otomatik owner olarak `.env` dosyasina kaydediliyor.

Etkisi:

- Kurulum asamasinda bot yanlis kisiye acik kalirsa sahiplik ele gecirilebilir.
- Token sizmasi ya da bota erken ulasim durumunda kontrol tamamen kaybedilebilir.

Sonuc:

- Bu davranis kullanisli ama guvenlik olarak zayif. Kurulum kolayligi icin guvenlikten odun verilmis.

### P1 - Lock mekanizmasi sadece PID ile calisiyor ve oldurme basarisini dogrulamiyor

Ilgili dosyalar:

- `core/bot_engine.py`
- `core/platform_utils.py`
- `bot.lock`

Sorun:

- Lock dosyasinda sadece PID tutuluyor.
- Yeni surec, locktaki PID'nin gercekten bu projeye ait olup olmadigini dogrulamiyor.
- Windows tarafinda `taskkill` cagrisi hata dondurse bile `kill_process()` basarili gibi `True` donuyor.
- `_kill_old_instances()` da sonuca bakmadan "Eski bot process kapatildi" logu basiyor.

Etkisi:

- PID reuse durumunda alakasiz proses hedef alinabilir.
- Loglar sahte bir basari hissi verebilir.
- Singleton davranisi gercekte garanti degil.

Sonuc:

- Surec yonetimi su an hem riskli hem de gozlemlenebilirlik acisindan guvenilmez.

### P1 - Event loop kapanma senaryosu halen cozulmemis gorunuyor

Ilgili dosyalar:

- `core/bot_engine.py`
- `logs/crashes/crash_20260413_215753.log`
- `logs/crashes/crash_20260413_215759.log`
- `logs/crashes/crash_20260413_215804.log`

Sorun:

- `run_polling()` hataya dusunce ayni surecte yeniden deneme yapiliyor.
- Crash bildirimi de `asyncio.get_event_loop()` uzerinden gonderilmeye calisiliyor.
- Crash loglari, kapanmis loop ile tekrar tekrar ayni failure'a girildigini gosteriyor.

Etkisi:

- Bot kendi kendine saglikli toparlanamiyor.
- Bildirim mekanizmasi bile ayni sebeple basarisiz oluyor.

Sonuc:

- Bu alan gercek saha hatasi urettigi icin teorik degil, dogrudan kanitli problem.

### P2 - Claude dedup mantigi gecerli mesaji sessizce yutabilir

Ilgili dosya:

- `core/claude_bridge.py`

Sorun:

- Son 5 saniyede gelen ayni prompt global olarak tekrar sayiliyor.
- Kontrol chat bazli degil, session bazli degil, kullanici bazli degil.
- Ikinci istek sessizce `None` ile atlanıyor.

Etkisi:

- Kullanici ayni promptu bilerek tekrar gonderirse cevap alamaz.
- Farkli session veya farkli kullanici ayni metni gonderse de etkilenebilir.

Sonuc:

- Bu davranis spam engelleme gibi dursa da gercek kullanimi bozabilir.

### P2 - Claude CWD state'i tutuluyor ama davranisa donusmuyor

Ilgili dosyalar:

- `core/bot_engine.py`
- `core/claude_bridge.py`

Sorun:

- `/cwd` komutu state'i degistiriyor.
- `claude_cwd` tutuluyor.
- Ama `run_claude()` bu bilgiyi kullanmiyor; `cwd` parametresi de fiilen bos.

Etkisi:

- Kullanici CWD degistirdigini saniyor ama gercek entegrasyon davranisi degismiyor.
- Ozellik yarim uygulanmis hissi veriyor.

Sonuc:

- UI ile arka plan davranisi arasinda uyumsuzluk var.

### P2 - Claude session state ve callback cache global

Ilgili dosyalar:

- `core/claude_bridge.py`
- `core/bot_engine.py`

Sorun:

- Session ID, title, cwd ve dedup bilgisi proses geneline ait global degiskenlerde tutuluyor.
- Inline callback cache de global.
- Callback data icinde session ID sadece ilk 20 karaktere kisaltiliyor.

Etkisi:

- Cok kullanicili veya stale inline keyboard senaryolarinda state kolayca karisabilir.
- Session collision ihtimali dusuk ama sifir degil.

Sonuc:

- Mevcut tasarim tek kullanici/tek aktif akis varsayimina asiri bagli.

### P2 - Ana menu gercekten bir guvenlik veya mod kapisi degil

Ilgili dosya:

- `core/bot_engine.py`

Sorun:

- Kod akisi, mod secilmeden de `Ekran Al` ve benzeri komutlari calistirabiliyor.
- Loglarda `[menu] Gelen: Ekran Al` sonrasinda screenshot alindigi acikca goruluyor.

Etkisi:

- UI kullaniciya "once mod sec" diyormus gibi gorunurken mantik bunu zorlamiyor.
- Davranis beklenenden farkli oldugu icin operator hatasi riskini arttiriyor.

Sonuc:

- Bu daha cok mantik/UX uyumsuzlugu ama uzaktan kontrol aracinda onemli.

### P2 - Hotkey verisi daginik ve bozuk config kendini onarmiyor

Ilgili dosyalar:

- `core/data_manager.py`
- `hotkeys.json`

Sorun:

- `hotkeys.json` hem root seviyesinde hotkey'ler hem `hotkeys` altinda ayri hotkey'ler tasiyor.
- Kod fiilen `data["hotkeys"]` uzerinden calisiyor; root seviyedeki cogu veri olu hale geliyor.
- JSON bozulursa `load_data()` bos dict donuyor.
- Sonraki yazma akislarinda self-heal yerine `KeyError` benzeri ikincil sorunlar cikabilir.

Etkisi:

- Kullanici verisi tutarsizlasabilir.
- Konfigürasyon bozuldugunda uygulama graceless sekilde davranabilir.

Sonuc:

- Veri modeli sade degil ve dayaniksiz.

### P3 - Telegram update yukleme akisi artik daha guvenli ama hala filtre yok

Ilgili dosya:

- `core/bot_engine.py`

Durum:

- Eski path traversal riski buyuk oranda kapatilmis.
- Dosya adi `basename` ile temizlenip `updates/` altina yaziliyor.

Kalan eksik:

- Dosya tipi, boyut, uzanti ve overwrite politikasi kontrol edilmiyor.
- Yuklenen dosya gercekten ne icin kullanilacak belli degil; su an sadece bir staging klasorune iniyor.

Sonuc:

- Eskisine gore daha iyi, ama "guvenli update sistemi" demek icin yeterli degil.

### P3 - Kucuk ama gercek davranis kusurlari

Ilgili dosyalar:

- `core/bot_engine.py`
- `core/system_tools.py`

Gozlemler:

- Antigravity modunda screenshot alma basarisiz olursa status mesaji silinmeden kalabilir.
- `remove_hotkey_command()` silinecek kayit bulunamazsa komut argumanli kullanimda geri bildirim vermiyor.
- Bircok yerde hala genis `except` bloklari var; bu da hatalari sessizlestiriyor.

## Pozitif Notlar

Bu turda onceki duruma gore gercekten iyiye giden noktalar var:

- Screenshot name collision problemi kod tarafinda cozulmus gorunuyor.
- Uzaktan dosya guncelleme akisindaki en tehlikeli path sorunu azaltılmis.
- FAILSAFE tamamen kapali olmaktan cikarilmis.
- macOS session title kacislama problemi ele alinmis.
- Gereksiz gorunen bazi bagimliliklar temizlenmis.

## Fazlaliklar ve Hijyen Konulari

- `main_backup.py` kokten kaldirildi; legacy calistirma icin `python main.py --legacy` kullaniliyor.
- `nul` isimli artefact Windows araclariyla sorun cikartabiliyor.
- Proje kokunde `venv`, `logs`, `temp_screens` birikimi var.
- Mevcut rapor ve operasyon dosyalari repo hijyenini zamanla bozabilir.

## Oncelikli Aksiyon Sirasi

1. Tum path yonetimini proje kokune bagli absolute path modeline cekmek
2. Owner atama akisini otomatik ilk kullanici modelinden cikarmak
3. Lock mekanizmasini PID disi dogrulamalarla guclendirmek
4. Event loop crash recovery akisini temiz yeniden baslatma mantigina cevirmek
5. Claude state'ini chat veya user bazli hale getirmek
6. Dedup mantigini sessiz drop yerine daha kontrollu hale getirmek
7. Hotkeys/config semasini tek bir net yapida toplamak
8. Update staging klasorune dosya filtreleme ve politika eklemek

## Sonuc

Kod tabani ilk bakisa gore daha toplu hale gelmis, ama sistem hala "tek makine, tek operator, kontrollu ortam" varsayimiyla yasiyor. Bu varsayim bozuldugunda en cok zarar gorecek alanlar yetkilendirme, surec yonetimi ve state tutarliligi.

Kisa ozetle:

- Bazi kritik hatalar kapatilmis.
- En buyuk mimari riskler hala duruyor.
- Raporun yeni versiyonu, artik gecerli olmayan eski maddeleri ayiklayip sadece bugunku koda gore guncellenmistir.
