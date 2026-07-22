# Matrix Swap v2 - Session State

## Date: 2026-07-22 (Alert System Added!)

## 🚨 NEW: Alert System

Stworzono system alertów z powiadomieniami Telegram!

### Jak skonfigurować Telegram (ZA DARMO!):

1. Otwórz Telegram i wyszukaj **@BotFather**
2. Wyślij `/newbot`
3. Podaj nazwę bota (np. "Matrix Swap Alerts")
4. Podaj username bota (np. "matrix_swap_alerts_bot")
5. BotFather da Ci **BOT_TOKEN** - skopiuj go
6. Wyszukaj swojego bota i kliknij **Start**
7. Wyślij dowolną wiadomość do bota
8. Wejdź na: `https://api.telegram.org/bot<TWOJ_TOKEN>/getUpdates`
9. Znajdź **chat.id** w odpowiedzi JSON

### Konfiguracja w aplikacji:

```bash
curl -X POST http://localhost:5000/api/alerts/configure \
  -H "Content-Type: application/json" \
  -d '{"telegram_token": "123456:ABC-DEF...", "telegram_chat_id": "123456789"}'
```

### Alerty wysyłane automatycznie:

- 🟢 **ZAKUP** - gdy kupimy token
- 🔄 **SWAP** - gdy wykonamy wymianę
- 🚨 **THRESHOLD 7%** - gdy osiągniemy 7% gain
- 📊 **PODSUMOWANIE** - raport dzienny

## Current Status

- **Server**: localhost:5000 ✅
- **Threshold**: 7.0% ✅
- **Alert System**: ✅ Active
- **Holding**: BTCUSDT
- **Purchase**: 0.01516 BTC @ $65926.86
- **Best candidate**: APTUSDT +0.02%
- **Tokens**: 49

## API Endpoints (Alert System)

| Endpoint | Opis |
|----------|------|
| `GET /api/alerts/status` | Status alertów |
| `GET /api/alerts/purchases` | Historia zakupów |
| `GET /api/alerts/history` | Historia alertów |
| `POST /api/alerts/configure` | Konfiguracja Telegram |
| `POST /api/alerts/test` | Test alertu |

## Backtest Results

| Threshold | Swaps | Gain % |
|-----------|-------|--------|
| **7.0%** | 61 | **+278%** |

## Files

- `alerts.py` - System alertów (NOWE!)
- `app.py` - Zintegrowany alert system
- `config.py` - Threshold 7.0%
- `matrix.py` - Core logic
