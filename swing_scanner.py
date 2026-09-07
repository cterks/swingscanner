"""
Swing scanner - ranks a watchlist of tickers by pullback quality.

Reads tickers from watchlist.txt (one per line), pulls daily bars,
computes three factors, and writes a ranked CSV.

Setup (one time):
    pip install yfinance pandas numpy

Run:
    python swing_scanner.py

Output:
    ranked_YYYY-MM-DD.csv
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

BENCHMARK = "SPY"
LOOKBACK_DAYS = 400
RS_WINDOW = 60
ATR_SHORT = 5
ATR_LONG = 20
TOP_N = 10

# Factor weights. Must sum to 1.0. Tune these once you have a trade log.
WEIGHTS = {
    "pullback": 0.40,
    "coil": 0.30,
    "rel_strength": 0.30,
}


# ---------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------

def true_range(df):
    """Wilder's true range: the largest of three candidate ranges."""
    prev_close = df["Close"].shift(1)
    a = df["High"] - df["Low"]
    b = (df["High"] - prev_close).abs()
    c = (df["Low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df, window):
    return true_range(df).rolling(window).mean()


def sma(series, window):
    return series.rolling(window).mean()


def rsi(series, window=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # No down days at all -> RSI is 100 by definition, not undefined.
    return out.mask(avg_loss.eq(0) & avg_gain.gt(0), 100.0)


# ---------------------------------------------------------------------
# Factors
# ---------------------------------------------------------------------

def compute_metrics(df, bench_return_60d):
    """Return a dict of raw metrics for one ticker, or None if unusable."""
    if df is None or len(df) < 210:
        return None

    close = df["Close"]
    last = float(close.iloc[-1])

    sma20 = float(sma(close, 20).iloc[-1])
    sma50 = float(sma(close, 50).iloc[-1])
    sma200 = float(sma(close, 200).iloc[-1])

    if any(np.isnan(x) for x in (sma20, sma50, sma200)):
        return None

    atr_s = float(atr(df, ATR_SHORT).iloc[-1])
    atr_l = float(atr(df, ATR_LONG).iloc[-1])
    if np.isnan(atr_s) or np.isnan(atr_l) or atr_l == 0:
        return None

    ret_60 = last / float(close.iloc[-(RS_WINDOW + 1)]) - 1.0

    return {
        "price": last,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": float(rsi(close).iloc[-1]),
        "avg_vol_50d": float(df["Volume"].rolling(50).mean().iloc[-1]),
        "pct_from_52w_high": last / float(close.tail(252).max()) - 1.0,
        # Distance below the 50-day, as a fraction. Positive = below the MA.
        "pullback_depth": (sma50 - last) / sma50,
        # Volatility contraction. Below 1.0 means recent ranges are tightening.
        "coil_ratio": atr_s / atr_l,
        "rel_strength": ret_60 - bench_return_60d,
    }


def passes_filters(m):
    """Hard gates. A name must clear all of these to be ranked at all."""
    return (
        m["price"] > 10
        and m["avg_vol_50d"] > 500_000
        and m["price"] > m["sma200"]
        and m["price"] > m["sma50"]
        and m["price"] < m["sma20"]
        and 35 <= m["rsi14"] <= 55
        and m["pct_from_52w_high"] > -0.20
    )


def normalize(values):
    """Min-max to 0-1. Returns 0.5 for everything if there's no spread."""
    arr = np.asarray(values, dtype=float)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-12:
        return np.full_like(arr, 0.5)
    return (arr - lo) / (hi - lo)


def score(rows):
    """Rank candidates. Higher score = better setup."""
    if not rows:
        return []

    # Deeper pullback scores higher, but only within reason - the hard
    # filters already excluded anything that broke its 50-day badly.
    pullback = normalize([r["pullback_depth"] for r in rows])
    # Tighter coil scores higher, so invert.
    coil = 1.0 - normalize([r["coil_ratio"] for r in rows])
    rel = normalize([r["rel_strength"] for r in rows])

    for i, r in enumerate(rows):
        r["s_pullback"] = pullback[i]
        r["s_coil"] = coil[i]
        r["s_rel_strength"] = rel[i]
        r["score"] = (
            WEIGHTS["pullback"] * pullback[i]
            + WEIGHTS["coil"] * coil[i]
            + WEIGHTS["rel_strength"] * rel[i]
        )

    return sorted(rows, key=lambda r: r["score"], reverse=True)


# ---------------------------------------------------------------------
# Trade levels
# ---------------------------------------------------------------------

def levels(df, price):
    """Suggested stop and target based on recent volatility. Not advice."""
    a = float(atr(df, 14).iloc[-1])
    stop = price - 1.5 * a
    return {
        "atr14": round(a, 2),
        "suggested_stop": round(stop, 2),
        "suggested_target": round(price + 3.0 * a, 2),
        "risk_pct": round((price - stop) / price * 100, 2),
    }


# ---------------------------------------------------------------------
# Data + main
# ---------------------------------------------------------------------

def fetch(tickers):
    """Pull daily bars. Returns {ticker: DataFrame}."""
    import yfinance as yf

    data = yf.download(
        tickers,
        period=f"{LOOKBACK_DAYS}d",
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )

    out = {}
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            df = df.dropna()
            if len(df) > 0:
                out[t] = df
        except (KeyError, TypeError):
            continue
    return out


def read_watchlist(path="watchlist.txt"):
    try:
        with open(path) as f:
            return [
                line.strip().upper()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        sys.exit(
            f"No {path} found. Create it with one ticker per line, "
            "e.g. export your Finviz screen to CSV and paste the symbols in."
        )


def main():
    tickers = read_watchlist()
    print(f"Fetching {len(tickers)} tickers plus benchmark...")

    bars = fetch(tickers + [BENCHMARK])

    if BENCHMARK not in bars:
        sys.exit(f"Could not fetch {BENCHMARK}. Check your connection.")

    bench = bars[BENCHMARK]["Close"]
    bench_ret = float(bench.iloc[-1]) / float(bench.iloc[-(RS_WINDOW + 1)]) - 1.0
    print(f"{BENCHMARK} {RS_WINDOW}d return: {bench_ret:+.1%}")

    rows = []
    for t in tickers:
        m = compute_metrics(bars.get(t), bench_ret)
        if m is None:
            continue
        if not passes_filters(m):
            continue
        m["ticker"] = t
        m.update(levels(bars[t], m["price"]))
        rows.append(m)

    ranked = score(rows)
    print(f"{len(ranked)} of {len(tickers)} passed filters.\n")

    if not ranked:
        print("No candidates today. That is a normal and useful result.")
        emit_report(None, date.today().isoformat(), len(tickers), bench_ret)
        return

    cols = [
        "ticker", "score", "price", "rsi14",
        "pullback_depth", "coil_ratio", "rel_strength",
        "atr14", "suggested_stop", "suggested_target", "risk_pct",
    ]
    out = pd.DataFrame(ranked)[cols]
    out["score"] = out["score"].round(3)
    out["pullback_depth"] = (out["pullback_depth"] * 100).round(2)
    out["rel_strength"] = (out["rel_strength"] * 100).round(2)
    out["coil_ratio"] = out["coil_ratio"].round(3)
    out["rsi14"] = out["rsi14"].round(1)
    out = out.rename(columns={
        "pullback_depth": "pullback_pct_below_sma50",
        "rel_strength": "rel_strength_pct_vs_spy",
    })

    run_date = date.today().isoformat()
    os.makedirs("results", exist_ok=True)
    fname = os.path.join("results", f"ranked_{run_date}.csv")
    out.to_csv(fname, index=False)

    print(out.head(TOP_N).to_string(index=False))
    print(f"\nWrote {fname}")

    emit_report(out, run_date, len(tickers), bench_ret)


def emit_report(out, run_date, scanned, bench_ret):
    import report
    html = report.build_html(out, run_date, scanned, bench_ret, TOP_N)
    n = 0 if out is None else len(out)
    subject = f"Swing scan {run_date} - {n} candidate{'' if n == 1 else 's'}"
    report.send(html, subject)


if __name__ == "__main__":
    main()
