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
Eski cekirdek botu test etmek gerekirse:

```powershell
python main.py --legacy
```

Ortam tani raporu almak icin:

```powershell
python main.py --doctor
```

## Telefon ve PWA

Telefon/PWA kurulum notlari:

- `docs/PHONE_CLIENT_SETUP.md`
- `docs/PHONE_INTEGRATION_NOTES.md`

Kisa notlar:

- Pairing dashboard: `http://127.0.0.1:8765/pair`
- QR, uzak tunnel saglikliysa WAN linkini; degilse otomatik LAN linkini kullanir.
- macOS Retina ekranlarda screenshot ustundeki kirmizi fare isareti logical/display scale farkina gore normalize edilir.

## Dokumanlar

Detayli inceleme raporlari, smoke test notlari ve eski destek matrisleri `docs/` altinda tutulur.

## Kisa Kimlik

- Urun adi: `AgentCockpit`
- Repo adi hedefi: `agent-cockpit`
- Kisa aciklama: `Unified cockpit for Claude, Codex, and desktop automation.`
