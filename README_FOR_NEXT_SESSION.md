# README dla kontynuacji projektu Matrix Swap v2

## 📋 Streszczenie projektu

Stworzyliśmy system **Matrix Swap v2** - token accumulator który maksymalizuje ilość tokenów (nie USDT) poprzez inteligentne swapowanie między kryptowalutami na giełdzie Mexc.

## 🎯 Główna koncepcja

### Kluczowe metryki:
- **BASELINE** - ile tokenów mielibyśmy gdybyśmy kupili za 1000 USDT na początku
- **ACTUAL_EQ** - ile tokenów moglibyśmy mieć gdybyśmy teraz wymienili nasz portfel
- **TOP_EQ** - rekord (najwyższy actual_eq) - aktualizowany tylko przy swapie!
- **GAIN %** - (actual_eq - top_eq) / top_eq - zysk/strata vs rekord

### Logika swapu:
1. Co 1 sekundę pobieramy ceny z Mexc
2. Obliczamy actual_eq dla WSZYSTKICH tokenów
3. Szukamy tokena z najwyższym gain%
4. Jeśli gain% > threshold (domyślnie 2%) → wykonujemy swap
5. Po swapie aktualizujemy top_eq dla WSZYSTKICH tokenów

## 🔧 Struktura projektu

```
/workspace/project/swapper/matrix_swap/
├── config.py          # Konfiguracja (FEE=0.04%, INITIAL_USDT=1000, POLL=1s)
├── matrix.py         # Główna logika Matrix (POPRAWIONA!)
├── api.py            # Klient Mexc API + tick logging
├── app.py            # Flask web app (port 5000)
├── requirements.txt
├── templates/
│   └── index.html    # Frontend web
├── DOCUMENTATION.md  # Pełna dokumentacja techniczna
├── SESSION_STATE.md  # Stan sesji testowej
└── tick_log*.json   # Dane z testów
```

## 🐛 Naprawione bugs

### Bug 1: Obliczanie top_eq
- **Problem**: `new_value_usdt = new_qty * ask_price` (używało ASK bez fee)
- **Poprawka**: `new_value_usdt = new_qty * bid_price * (1 - fee)` (prawidłowa wartość USDT)

### Bug 2: top_eq po swapie
- **Problem**: top_eq nie równało się ilości po swapie
- **Poprawka**: `target_token.top_eq = new_qty` - bezpośrednie przypisanie

## ✅ Weryfikacja obliczeń

Test swap BTC → ALGO:
```
Sell: 0.015349399 BTC at bid 65119.22
USDT after sell: 999.14 USDT (po fee 0.04%)
Buy ALGO at ask 0.0828
Expected ALGO: 12062.096597
Actual ALGO: 12062.096597 ✅
```

## 📊 Wyniki testów

### Backtest - pełna optymalizacja (market.csv, 241k records, 20 tokenów)

Testowano threshold od 0.05% do 10% (co 0.05%):

| Threshold | Swapy | Gain % |
|-----------|-------|--------|
| **7.0%** | 61 | **+278%** |
| 7.5% | 51 | +248% |
| 7.2% | 45 | +193% |
| 6.8% | 44 | +170% |

#### Dynamic thresholds - NIE pomogły:
- Volatility-adjusted: ~+278% (bez poprawy)
- Momentum-based: max +175%
- Adaptive market: max +141%
- Min hold time: POGARSZA wyniki

### Wniosek: Threshold 7.0% jest optymalny!

### Live test:
- Threshold: 7%
- Holding: BTCUSDT
- Swaps: 0 (brak okazji >7% w spadkowym rynku)
- Best candidate: ZECUSDT +0.47%

## 🚀 Uruchomienie

```bash
cd /workspace/project/swapper/matrix_swap
python app.py
# Otwórz http://localhost:5000
```

## 🔄 Co dalej?

1. **Zmienić threshold** - obniżyć do 0.5% lub 1%
2. **Testować w różnych warunkach** - hossa vs bessa
3. **Eksperymentować ze strategiami** - worst momentum vs median vs top
4. **Dodać więcej tokenów** - obecnie 50

## 📝 Dla następnego chatu - co powiedzieć:

```
Kontynuuj projekt Matrix Swap v2:
- Jest na branchu v2-matrix-swap
- Zawiera poprawki bugów w matrix.py
- Serwer działa na porcie 5000
- Następne kroki: zmienić threshold, przetestować strategie
```

## 📁 Pliki z danymi

- `tick_log.json` - 311 ticków z pierwszej sesji
- `tick_log_v2.json` - 338 ticków z drugiej sesji
- `output/strategy_comparison.json` - porównanie strategii (ale może być nieaktualne)

## 🎓 Lekcje

1. ZAWSZE weryfikuj obliczenia na realnych danych
2. Loguj wszystkie ticki żeby móc debugować
3. Testuj na żywych danych przez kilka minut
4. Sprawdzaj czy top_eq = qty po swapie
