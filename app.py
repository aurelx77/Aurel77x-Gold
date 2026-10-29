from contextlib import asynccontextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "signals.db"
SYMBOL = "XAUUSD=X"  # Yahoo Finance gold spot symbol; availability/delay may vary.
INTERVAL = "5m"
PERIOD = "5d"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            outcome TEXT,
            closed_at TEXT
        )
        """)
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Gold Signal Bot", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


def fetch_candles():
    try:
        df = yf.download(
            SYMBOL, period=PERIOD, interval=INTERVAL,
            auto_adjust=False, progress=False, threads=False
        )
        if df is None or df.empty:
            raise ValueError("No candle data returned.")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.title)
        required = {"Open", "High", "Low", "Close"}
        if not required.issubset(df.columns):
            raise ValueError(f"Missing columns. Received: {list(df.columns)}")
        df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
        if len(df) < 60:
            raise ValueError("Not enough candles to calculate indicators.")
        return df
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not load XAU/USD candles: {exc}. Data provider availability may vary."
        )


def indicators(df):
    close = df["Close"]
    df["ema20"] = close.ewm(span=20, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi14"] = 100 - (100 / (1 + rs))
    prev_close = close.shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    return df


def latest_signal(df):
    df = indicators(df).dropna()
    if len(df) < 3:
        return None
    prev, last = df.iloc[-2], df.iloc[-1]
    # Conservative illustrative rule: EMA cross + RSI filter.
    buy = prev["ema20"] <= prev["ema50"] and last["ema20"] > last["ema50"] and 50 <= last["rsi14"] <= 70
    sell = prev["ema20"] >= prev["ema50"] and last["ema20"] < last["ema50"] and 30 <= last["rsi14"] <= 50
    if not (buy or sell):
        return None
    entry = float(last["Close"])
    atr = float(last["atr14"])
    if not pd.notna(atr) or atr <= 0:
        return None
    side = "BUY" if buy else "SELL"
    risk_distance = 1.5 * atr
    reward_distance = 2.0 * risk_distance  # planned reward:risk = 2:1
    sl = entry - risk_distance if side == "BUY" else entry + risk_distance
    tp = entry + reward_distance if side == "BUY" else entry - reward_distance
    candle_time = last.name
    if hasattr(candle_time, "to_pydatetime"):
        candle_time = candle_time.to_pydatetime()
    if candle_time.tzinfo is None:
        candle_time = candle_time.replace(tzinfo=timezone.utc)
    return {
        "side": side, "entry": round(entry, 3), "stop_loss": round(sl, 3),
        "take_profit": round(tp, 3), "candle_time": candle_time.isoformat(),
        "rsi": round(float(last["rsi14"]), 2), "ema20": round(float(last["ema20"]), 3),
        "ema50": round(float(last["ema50"]), 3), "atr": round(atr, 3)
    }


def evaluate_open_signals(df):
    """Evaluate OPEN signals against candles after their creation time.
    If SL and TP are touched in the same candle, conservatively count SL first.
    """
    with db() as conn:
        rows = conn.execute("SELECT * FROM signals WHERE status='OPEN'").fetchall()
        for row in rows:
            later = df[df.index > pd.Timestamp(row["created_at"])]
            outcome = None
            for _, candle in later.iterrows():
                if row["side"] == "BUY":
                    sl_hit = float(candle["Low"]) <= row["stop_loss"]
                    tp_hit = float(candle["High"]) >= row["take_profit"]
                else:
                    sl_hit = float(candle["High"]) >= row["stop_loss"]
                    tp_hit = float(candle["Low"]) <= row["take_profit"]
                if sl_hit:
                    outcome = "LOSS"
                    break
                if tp_hit:
                    outcome = "WIN"
                    break
            if outcome:
                conn.execute(
                    "UPDATE signals SET status='CLOSED', outcome=?, closed_at=? WHERE id=?",
                    (outcome, datetime.now(timezone.utc).isoformat(), row["id"])
                )
        conn.commit()


@app.get("/api/overview")
def overview():
    df = fetch_candles()
    df = indicators(df)
    evaluate_open_signals(df)
    last = df.iloc[-1]
    signal = latest_signal(df)
    # Avoid creating duplicate signals from the same candle.
    if signal:
        with db() as conn:
            existing = conn.execute(
                "SELECT id FROM signals WHERE created_at=? AND side=?",
                (signal["candle_time"], signal["side"])
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO signals(created_at,side,entry,stop_loss,take_profit)
                    VALUES(?,?,?,?,?)""",
                    (signal["candle_time"], signal["side"], signal["entry"],
                     signal["stop_loss"], signal["take_profit"])
                )
                conn.commit()

    with db() as conn:
        rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 25").fetchall()
        stats = conn.execute("""
            SELECT
              SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) wins,
              SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) losses,
              SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open_count
            FROM signals
        """).fetchone()
    wins = int(stats["wins"] or 0)
    losses = int(stats["losses"] or 0)
    closed = wins + losses
    return {
        "symbol": SYMBOL, "interval": INTERVAL,
        "price": round(float(last["Close"]), 3),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "latest_setup": signal,
        "stats": {
            "wins": wins, "losses": losses, "open": int(stats["open_count"] or 0),
            "closed": closed, "win_rate": round(100 * wins / closed, 1) if closed else None
        },
        "signals": [dict(row) for row in rows]
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "symbol": SYMBOL, "interval": INTERVAL}
