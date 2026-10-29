# Gold Signal Bot (prototip)

Panel web për sinjale XAU/USD me FastAPI, Yahoo Finance/yfinance dhe SQLite.

## Çfarë përfshin
- Panel web me çmimin e fundit të marrë nga burimi, setup-in e fundit dhe historikun.
- Strategji ilustruese EMA 20/EMA 50 + RSI 14.
- Entry, SL bazuar në ATR dhe TP me raport të planifikuar risk/shpërblim 1:2.
- Vlerësim të sinjaleve të hapura kundrejt qirinjve pasues; nëse SL dhe TP preken në të njëjtin qiri, numërohet SL i pari.
- Statistika win/loss për sinjalet e mbyllura nga ky prototip.

## Nisja lokale
Kërkohet Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --reload
```

Hap http://127.0.0.1:8000

## Shënime të rëndësishme
- Simboli i përdorur është `XAUUSD=X` dhe intervali `5m`; mbulimi, vonesa dhe disponueshmëria e Yahoo Finance mund të ndryshojnë.
- Ky nuk është burim i garantuar për ekzekutim tregtar. Për përdorim serioz, zëvendëso `fetch_candles()` me API të licencuar nga brokeri ose furnizues tregu; ruaje çelësin API në variabla mjedisi, jo në frontend.
- Rregulli është shembull teknik, jo strategji e provuar. Bëj backtest me spread, komisione, slippage dhe të dhëna jashtë kampionit.
- Win rate nuk llogaritet derisa të mbyllet të paktën një sinjal. Sinjalet nuk garantojnë fitime.
- Për një shërbim publik duhet shtuar autentikimi, kufizimi i kërkesave, monitorimi, testet, menaxhimi i gabimeve dhe hostimi.
- Prototipi jep sinjale informative; nuk vendos urdhra tregtimi te brokeri.
