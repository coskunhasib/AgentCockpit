# Claude Cross-Platform Smoke Test

Bu belge Claude entegrasyonunun Windows, macOS ve Linux'ta hizli dogrulamasi icin kullanilir.

## 1. Otomatik Kontrol

Proje kokunden su komutu calistir:

### Windows
```powershell
& .\venv\Scripts\python.exe .\utils\smoke_claude_transport.py
```

### macOS / Linux
```bash
python3 ./utils/smoke_claude_transport.py
```

Beklenen ana alanlar:

- `transport_mode`
  - Windows: genelde `desktop`
  - macOS: genelde `desktop`
  - Linux: genelde `cli`
- `claude_exe_exists`: `true` olmali
- `session_count_check.ok`: `true` olmali
- `profile_summary`: aktif profil bilgisini gostermeli
- `capabilities`: aktif transporta gore uygulanmis destek matrisi gorunmeli
- `config_path`: aktif config kaynagi gorunmeli
- `config_warnings`: varsa override/validation uyarilari listelenmeli

## 2. Derleme Kontrolu

### Windows
```powershell
& .\venv\Scripts\python.exe -m py_compile .\core\data_manager.py .\core\platform_utils.py .\core\claude_bridge.py .\core\bot_engine.py
```

### macOS / Linux
```bash
python3 -m py_compile ./core/data_manager.py ./core/platform_utils.py ./core/claude_bridge.py ./core/bot_engine.py
```

Beklenen sonuc:

- Komut sessiz tamamlanmali
- Hata veya traceback olmamali

## 3. Unit Test Paketi

### Windows
```powershell
& .\venv\Scripts\python.exe -m unittest discover -s .\tests -v
```

### macOS / Linux
```bash
python3 -m unittest discover -s ./tests -v
```

Beklenen sonuc:

- `OK` ile bitmeli
- `claude_ui_config`, `claude_state`, `data_manager`, `claude_chat_ui_parser`, `claude_capabilities` testleri gecmeli

## 4. Telegram Uzerinden Canli Test

Sirayla su adimlari uygula:

1. Botu ac
2. `Claude Code` moduna gec
3. `Durum` butonuna bas
4. `Sekme` sec ve `Chat`, sonra `Cowork`, sonra `Code` dene
5. `Model` sec ve baska bir modele gec
6. `Effort` sec ve `Low` ile `Max` arasinda gecis dene
7. `Izin Modu` sec ve mod degisikligini dene
8. `Session Sec` ile mevcut bir session ac
9. Kisa bir prompt gonder

Beklenen sonuc:

- `Durum` ekraninda `Transport` bilgisi gorunmeli
- Secilen tab/model/effort/izin modu durum ekranina yansimali
- Session acildiktan sonra prompt gonderilebilmeli
- Yanit Telegram'a geri dusmeli

## 5. Platform Bazli Beklenti

### Windows

- Beklenen transport: `desktop`
- Sidebar, tab, model, effort, permission mode, runtime allow/deny calismali
- En yuksek parity burada beklenir

### macOS

- Beklenen transport: tercihen `desktop`
- AppleScript izinleri verilmis olmali
- Claude Desktop acikken tab/model/effort/permission secimleri denenmeli
- Chat session listesi ve gorunur chat history best-effort calisir; sahada teyit edilmelidir
- Eger Desktop algilanmazsa ve CLI varsa `cli`'ye dusebilir

### Linux

- Beklenen transport: `cli`
- Claude Desktop UI parity beklenmez; resmi strateji CLI fallback'tir
- Prompt gonderme ve cevap alma Claude CLI uzerinden calismali
- `Durum` ekraninda `Transport: Claude CLI` gorulmesi normaldir

## 6. Runtime Permission Testi

Bu test sadece Desktop transport icin anlamlidir.

1. Claude'da izin isteyen bir komut calistir
2. Telegram'da gelen izin butonlarini kontrol et
3. `Allow` veya `Deny` sec

Beklenen sonuc:

- Telegram butonu tiklaninca Desktop tarafinda ilgili izin butonu basilmali
- Gerekirse yeni izin ekranlari tekrar Telegram'a donmeli

## 7. Config Override Notu

- Varsayilan tek config kaynagi repo kokundeki `claude_ui_config.json` dosyasidir
- Ortama ozel override lazimsa `CLAUDE_UI_CONFIG_PATH` ile ayri bir JSON dosyasi verilebilir
- Ornek override icin `claude_ui_config.override.example.json` kullanilabilir
- Override dosyasindaki gecersiz key veya tipler warning olarak raporlanir ve yok sayilir

## 8. Zorunlu Ortam Notlari

- `CLAUDE_TRANSPORT=desktop` ile Desktop zorlama yapilabilir
- `CLAUDE_TRANSPORT=cli` ile CLI zorlama yapilabilir
- Bu degisken set edilmezse kod uygun transportu otomatik secer

## 9. Basarisizlik Yorumlama

- `transport_mode = none`
  - Claude Desktop bulunamadi ve CLI da yok
- `session_count_check.ok = false`
  - Session metadata veya log klasoru okunamiyor
- `config_warnings` dolu
  - Override dosyasinda gecersiz alan ya da eksik tip olabilir
- Prompt gidiyor ama cevap donmuyor
  - Desktop UI degismis olabilir
  - Linux'ta CLI auth/oturum sorunu olabilir
  - macOS'ta Accessibility izni eksik olabilir
