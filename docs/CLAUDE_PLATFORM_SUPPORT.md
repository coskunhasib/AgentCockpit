# Claude Platform Support Matrix

Bu belge mevcut entegrasyonda hangi ozelligin hangi platform ve transport ile beklendigini tek yerde toplar.

## 1. Transport Stratejisi

- Windows: varsayilan hedef `desktop`
- macOS: varsayilan hedef `desktop`
- Linux: varsayilan hedef `cli`
- `CLAUDE_TRANSPORT=desktop` veya `CLAUDE_TRANSPORT=cli` ile elle zorlama yapilabilir

## 2. Ozellik Matrisi

### Windows + Desktop

- Sekme secimi: var
- Model secimi: var
- Code effort: var
- Permission mode: var
- Extended thinking: var
- Chat session listing: var
- Chat history read: var
- Runtime permission buttons: var

### Windows + CLI

- Sekme secimi: var
- Model secimi: var
- Code effort: var
- Permission mode: var
- Extended thinking: yok
- Chat session listing: var
- Chat history read: var
- Runtime permission buttons: yok

### macOS + Desktop

- Sekme secimi: var
- Model secimi: var
- Code effort: var
- Permission mode: var
- Extended thinking: var
- Chat session listing: best-effort
- Chat history read: best-effort
- Runtime permission buttons: var

### macOS + CLI

- Sekme secimi: var
- Model secimi: var
- Code effort: var
- Permission mode: var
- Extended thinking: yok
- Chat session listing: best-effort local veri varsa
- Chat history read: best-effort local veri varsa
- Runtime permission buttons: yok

### Linux + Desktop

- Sekme secimi: yok
- Model secimi: yok
- Code effort: yok
- Permission mode: yok
- Extended thinking: yok
- Chat session listing: yok
- Chat history read: yok
- Runtime permission buttons: yok

### Linux + CLI

- Sekme secimi: var
- Model secimi: var
- Code effort: var
- Permission mode: var
- Extended thinking: yok
- Chat session listing: yok
- Chat history read: yok
- Runtime permission buttons: yok

## 3. Uygulama Karari

- Windows: tam desktop deneyimi ana yol
- macOS: desktop ana yol, chat tarafi best-effort ve sahada dogrulanmali
- Linux: resmi hedef CLI fallback; desktop parity hedeflenmiyor

## 4. Paylasim Notu

Bir makinede destek matrisi farkli gorunuyorsa once `utils/smoke_claude_transport.py` calistirilip `transport_mode` ve `capabilities` alanlari kontrol edilmeli.
