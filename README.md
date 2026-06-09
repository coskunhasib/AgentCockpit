# AgentCockpit

Claude, Codex ve masaustu otomasyon akislari icin birlesik kontrol paneli.

## Ne Yapiyor

- Telegram uzerinden ana kontrol merkezi sunar
- Claude Code ve Codex session'larini listeler, acar ve yonetir
- Masaustu otomasyon komutlarini merkezi bot akisina baglar
- Cok kullanicili state, capability-aware UI ve platform adapter katmanlariyla calisir

## Ana Bilesenler

- `main.py`: ana bootstrap ve birlesik stack giris noktasi
- `launcher.py`: telefon bridge + Telegram UX + ilk kurulum tarayici akisini baslatir
- `telegram_ux.py`: mevcut bot motorunu AgentCockpit UX ve telefon akislariyla genisletir
- `phone_bridge_server.py`: telefon/PWA icin yerel kontrol koprusu
- `phone_client/`: mobil PWA arayuzu
- `core/bot_engine.py`: legacy Telegram kontrol cekirdegi
- `core/claude_bridge.py`: Claude entegrasyonu
- `core/codex_bridge.py`: Codex entegrasyonu
- `core/platform_utils.py`: platformlar arasi desktop yardimcilari

## Calistirma

Ana giris:

```powershell
python main.py
```

Windows:

```powershell
.\runner.bat
```

Linux/macOS:

```bash
./runner.sh
```

Bu giris artik telefon bridge'i, PWA/pairing sayfasini ve tek Telegram botunu birlikte acar.
`TELEGRAM_TOKEN` bos veya placeholder ise ilk acilista tarayicida local kurulum sayfasi acilir; BotFather token'i burada dogrulanip `.env` dosyasina kaydedilir.
Startup asamasinda platform uyumluluk kontrolu de yapilir; tarayici, masaustu otomasyonu veya quick tunnel bu PC'de tam desteklenmiyorsa sistem kisitli modda yine acilmaya calisir.
Port, localhost hostu, runtime root ve benzeri varsayilanlar artik tek merkezden env ile override edilebilir; daginik hardcoded degerlere bagli degildir.
Eski cekirdek botu test etmek gerekirse:

```powershell
python main.py --legacy
```

Ortam tani raporu almak icin:

```powershell
python main.py --doctor
```

## Sistem Baslangicinda Acma

AgentCockpit'i kullanici oturumu acilinca otomatik baslatmak icin:

```bash
python autostart.py register
```

Bu komut macOS'ta LaunchAgent, Windows'ta Task Scheduler, Linux'ta systemd user
service kaydi olusturur. macOS LaunchAgent dogrudan venv Python'u calistirir;
`screen` veya aktif terminal oturumu gerekmez. Uygulama zaten aciksa ve sadece
sonraki oturum icin kaydetmek istiyorsan:

```bash
python autostart.py register --no-start
```

macOS'ta LaunchAgent, `Desktop`, `Documents` veya `Downloads` altindaki venv
dosyalarini izin/TCC nedeniyle okuyamayabilir. Repo bu klasorlerdeyse uygulama
kopyasini korumali olmayan bir dizine koyup kaydi o dizinden verin:

```bash
python autostart.py register --bot-dir "$HOME/AgentCockpit" --no-start
```

Durumu kontrol etmek veya kaydi kaldirmak icin:

```bash
python autostart.py status
python autostart.py unregister
```

macOS'ta ekran aktarimi icin Sistem Ayarlari > Gizlilik ve Guvenlik > Ekran ve
Sistem Sesi Kaydi altinda AgentCockpit'i baslatan uygulamaya izin verilmis
olmasi gerekir. Elle baslatmada bu uygulama genelde terminal/Codex, otomatik
baslatmada ise Python olabilir.

Telefon bridge'i baslatilirken macOS'ta `caffeinate` keep-awake islemi de
devreye girer. `/health` ciktisinda `keep_awake_active`, `capture_available` ve
`capture_error` alanlarini kontrol ederek link ayakta oldugu halde goruntu
gelmeyen durumlari ayirt edebilirsin. `screen=0x0` veya `capture_error` varsa
macOS ekran oturumu kilitli/uykuda olabilir ya da Screen Recording izni eksik
olabilir.

Runtime diagnostikleri `logs/diagnostics/` altina yazilir:

- `state_<process>_<pid>.json`: son heartbeat ve process/runtime snapshot'i.
- `events_<pid>.jsonl`: bridge, launcher, bot restart, DNS bekleme ve crash olaylari.
- `fault_<pid>.log`: native crash veya `SIGUSR1` thread dump ciktilari.
- `logs/crashes/crash_*.log`: traceback, runtime snapshot, thread dump ve son log tail'i.

Varsayilan heartbeat araligi 30 saniyedir. `AGENTCOCKPIT_DIAGNOSTICS_INTERVAL=0`
ile kapatilabilir. Token ve session query degerleri loglarda otomatik redakte edilir.

## Telefon ve PWA

Telefon/PWA kurulum notlari:

- `docs/PHONE_CLIENT_SETUP.md`
- `docs/PHONE_INTEGRATION_NOTES.md`

Kisa notlar:

- Pairing dashboard: `http://127.0.0.1:8765/pair`
- QR, uzak tunnel saglikliysa WAN linkini; degilse otomatik LAN linkini kullanir.
- WAN icin varsayilan yol Cloudflare Quick Tunnel'dir. IP tabanli Bore fallback
  istenirse bilincli olarak `PHONE_PUBLIC_TUNNEL_FALLBACK=bore` ayarlanabilir.
- macOS Retina ekranlarda screenshot ustundeki kirmizi fare isareti logical/display scale farkina gore normalize edilir.
- WAN tunnelini terminal/Codex gibi eksik GUI/DNS baglamindan yeniden baslatmak
  Cloudflare quick tunnel olusturmayi bozabilir; kalici calisma icin auto-start
  LaunchAgent kaydi tercih edilir.

## Dokumanlar

Detayli inceleme raporlari, smoke test notlari ve eski destek matrisleri `docs/` altinda tutulur.

## Kisa Kimlik

- Urun adi: `AgentCockpit`
- Repo adi hedefi: `agent-cockpit`
- Kisa aciklama: `Unified cockpit for Claude, Codex, and desktop automation.`
