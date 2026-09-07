# Swing scanner

Runs itself on GitHub's servers each weekday after the US close, screens a
watchlist for pullback setups, and emails a ranked shortlist. Nothing to
install locally.

**Start here: [SETUP.md](SETUP.md)**

## What it does

1. Pulls daily bars for every ticker in `watchlist.txt` (free Yahoo data)
2. Applies hard filters: above the 200- and 50-day, below the 20-day, RSI 35-55,
   over $10, over 500K average volume, within 20% of the 52-week high
3. Scores the survivors on three factors and ranks them:
   - **Pullback depth** — how far below the 50-day (40%)
   - **Coil** — 5-day ATR over 20-day ATR, lower is tighter (30%)
   - **Relative strength** — 60-day return versus SPY (30%)
4. Emails the top 10 with suggested stop and target levels

## Files

| File | What it is |
|---|---|
| `swing_scanner.py` | The screen and the ranking |
| `report.py` | HTML email formatting and sending |
| `watchlist.txt` | Your tickers, one per line — edit this |
| `.github/workflows/scan.yml` | The schedule |
| `results/` | A dated CSV per run, committed automatically |

## Tuning

Weights are at the top of `swing_scanner.py` in the `WEIGHTS` dict, and must
sum to 1.0. Hard filters are in `passes_filters()`. Edit either directly in
GitHub's web editor — the next run picks up the change.

Don't tune based on a hunch about a single day's output. Tune based on the
Summary tab of your trade log after 30+ closed trades.

## Caveats

Free Yahoo data has bad ticks and occasional gaps. The scoring weights and the
1.5x/3x ATR stop and target multiples are untested starting assumptions. This
produces a list to look at, not signals to act on. Not investment advice.
