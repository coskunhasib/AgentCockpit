# Phone Integration Notes

`docs/assets/phone-client-source.zip` icindeki telefon denemesinden projeye alinabilecek net parcalar bunlar.

## Alinabilir Parcalar

- `index.html` icindeki mobil uzaktan kontrol arayuzu
  Bu dosya iyi bir ilk prototip. Dokunma hareketleri, scroll modu, keyboard paneli ve reconnect akisi yeniden kullanilabilir.
- screenshot yenileme ve dokunma koordinatini normalize etme mantigi
  Mevcut masaustu kontrol katmanina uyarlanabilir.
- mobil HUD ve landscape odakli tasarim
  AgentCockpit icin ayri bir `phone-client` modulu acilacaksa iyi bir baslangic verir.

## Dogrudan Alinmamasi Gerekenler

- `agent.py` icindeki ayri Telegram polling mantigi
  Mevcut bot mimarisiyle cakisir. Telegram komutlari tek merkezden AgentCockpit tarafinda kalmali.
- URL query icine token gomup Telegram'a acik token yazma yaklasimi
  Guvenlik acisindan zayif.
- README'deki `pc-agent / phone-app` klasor yapisi
  Zipin gercek dosya yapisiyla uyusmuyor.

## Onerilen Entegrasyon Yonu

1. Telefon arayuzu ayri bir `phone-client` veya `web/phone` klasorune alinmali.
2. WebSocket veya HTTP kontrol katmani mevcut AgentCockpit state ve auth modeline baglanmali.
3. Telegram fallback komutlari ayri bir agent yerine mevcut `core/bot_engine.py` icinde kalmali.
4. Token modeli tek kullanici, sureli ve rotate edilebilir hale getirilmeli.

## Karar

Bu zipten en degerli parca `mobil istemci arayuzu`.
En riskli parca ise `ayri agent + ayri Telegram polling + URL token` tasarimi.
