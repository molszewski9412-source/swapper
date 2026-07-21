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
4. Jeśli gain% > threshold → wykonujemy swap
5. Po swapie aktualizujemy top_eq dla WSZYSTKICH tokenów

## 🔧 Struktura projektu

```
/workspace/project/swapper/matrix_swap/
├── config.py          # Konfiguracja (FEE=0.04%, INITIAL_USDT=1000, POLL=1s)
├── matrix.py         # Główna logika Matrix
├── api.py            # Klient Mexc API + tick logging
├── app.py            # Flask web app (port 5000)
├── backtest.py       # Backtesting engine
├── requirements.txt
├── templates/
│   └── index.html    # Frontend web
├── backtest_results.json
└── threshold_optimization.json
```

## 📊 BACKTEST - PEŁNA OPTYMALIZACJA

### Dane: market.csv (241k records, 20 tokenów)

Testowano threshold od 0.05% do 10% (co 0.05%):

| Threshold | Swapy | Gain % |
|-----------|-------|--------|
| **7.0%** | 61 | **+278%** |
| 7.5% | 51 | +248% |
| 7.2% | 45 | +193% |
| 6.8% | 44 | +170% |
| 0.1% | 248 | +16% |

### Dynamic thresholds - NIE pomogły:
- Volatility-adjusted: ~+278% (bez poprawy)
- Momentum-based: max +175%
- Adaptive market: max +141%
- Min hold time: POGARSZA wyniki

### Wniosek: Threshold 7.0% jest optymalny!

### Live test z threshold 0.1%:
- 7 swapów w 30 minut
- Wszystkie przy ~0.1% gain
- System działa prawidłowo!

## ✅ Weryfikacja obliczeń

```
Sell BTC: 0.0151 × 66290.2 × 0.9996 = 999.20 USDT
Buy VET:  999.20 / (0.004865 × 1.0004) = 205303.69 VET
Gain vs TOP_EQ: -0.08% ✅
```

## 🚀 Uruchomienie

```bash
cd /workspace/project/swapper/matrix_swap
python app.py
# Otwórz http://localhost:5000
```

## 📁 Pliki z danymi

- `backtest_results.json` - wyniki backtestu
- `threshold_optimization.json` - optymalizacja threshold
- `advanced_results.json` - dynamic thresholds
- `fine_tune_results.json` - fine-tuning around 7%

## 🎓 Lekcje

1. **Threshold 7% optymalny** - mało swapów, duży zysk
2. **Dynamic thresholds nie pomagają** - statyczny 7% najlepszy
3. **Min hold time pogarsza** wyniki
4. **System działa poprawnie** - zweryfikowano ręcznie

## 📝 Stan na 2026-07-21 (noc)

### Aktualny status:
- **Threshold**: 7.0%
- **Holding**: BTCUSDT (restart z czystą historią)
- **System**: Uruchomiony na localhost:5000
- **Swaps**: 0 (brak okazji >7% przez kilka godzin)
- **Git**: Branch v2-matrix-swap

### Test 0.1% (poprzednia sesja):
- 7 swapów w 30 minut przy threshold 0.1%
- Live test zweryfikowany - system działa poprawnie!
- Backtest potwierdza: 0.1% = +16%, 7% = +278%

### Wnioski:
1. Rynek spokojny - brak ruchów >7%
2. System działa stabilnie
3. Threshold 7% optymalny dla tego datasetu
