# Claude Shareable Setup

Bu belge projeyi baska bir makineye tasirken hangi parcalarin ozellestirilebilir oldugunu ozetler.

## 1. Config Kaynagi

- Varsayilan UI config dosyasi: `claude_ui_config.json`
- Bu dosya artik tek canonical default kaynaktir
- Ortama ozel degisiklik gerekiyorsa `CLAUDE_UI_CONFIG_PATH` ile ayri bir override dosyasi tanimlanabilir
- Ornek override: `claude_ui_config.override.example.json`

## 2. Validation Davranisi

- Override dosyasindaki bilinmeyen anahtarlar yok sayilir
- Tipi yanlis alanlar warning olarak raporlanir
- Gecerli alanlar default config ustune merge edilir

## 3. Platform Capability Ozeti

- Ayrintili matris: `CLAUDE_PLATFORM_SUPPORT.md`
- Windows: ana yol `desktop`
- macOS: ana yol `desktop`, chat listing/history best-effort
- Linux: resmi yol `cli`, desktop parity hedeflenmiyor

## 4. Test Komutlari

### Unit test
```powershell
& .\venv\Scripts\python.exe -m unittest discover -s .\tests -v
```

### Smoke test
```powershell
& .\venv\Scripts\python.exe .\utils\smoke_claude_transport.py
```

## 5. Paylasim Oncesi Checklist

1. `.env` icindeki gizli anahtarlari ayikla
2. `CLAUDE_SMOKE_TEST.md` adimlarini bir tur calistir
3. `config_warnings` alaninin bos oldugunu dogrula
4. Kullanilan platformun capability limitlerini okuyana not et

## 6. Gelecekte Yeni Provider Ekleme

- Ortak sozlesme: `core/provider_contract.py`
- Hazir Claude adapter'i: `core/claude_provider.py`
- Yeni bir saglayici eklenirse ayni `SessionRecord`/provider yuzeyi hedeflenmeli
