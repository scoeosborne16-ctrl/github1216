#!/usr/bin/env python3
"""
PrizePicks $100/Day Income Strategy
=====================================
Builds on pp_finder.py to suggest optimal PrizePicks entries
aimed at a $100/day profit target.

Usage:
    python income_strategy.py                          # NBA, $100 target, $100 bankroll
    python income_strategy.py --target 100 --bankroll 500 --league NBA
    python income_strategy.py --picks 4                # use 4-pick entries (10x)
    python income_strategy.py --log                    # show performance log
    python income_strategy.py --record 0 win           # log entry #0 as a win
    python income_strategy.py --record 0 loss          # log entry #0 as a loss

Requirements:
    pip install requests rich
"""

import argparse
import json
import os
from datetime import date

from pp_finder import analyze, fetch_prizepicks

# ---------------------------------------------------------------------------
# PrizePicks power-play payout multipliers (all picks must hit)
# ---------------------------------------------------------------------------
PAYOUT_MULTIPLIERS = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0}

LOG_FILE = "strategy_log.json"


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------

def build_entries(
    results: list[dict],
    target_profit: float,
    bankroll: float,
    picks_per_entry: int = 3,
    max_entries: int = 4,
) -> list[dict]:
    """
    Select the highest-edge props and slice them into entry slates.

    Stake sizing:
      stake = target_profit / (multiplier - 1)
      capped at 20 % of bankroll per entry (simple risk-of-ruin guard).
    """
    multiplier = PAYOUT_MULTIPLIERS.get(picks_per_entry, 5.0)
    stake_per_entry = min(
        target_profit / (multiplier - 1),
        bankroll * 0.20,
    )

    # Sort best overs (highest positive edge) and best unders (most negative edge)
    overs = sorted(
        [r for r in results if r["edge_pct"] > 0],
        key=lambda x: x["edge_pct"],
        reverse=True,
    )
    unders = sorted(
        [r for r in results if r["edge_pct"] < 0],
        key=lambda x: x["edge_pct"],
    )

    # Interleave overs/unders for diversity, label direction
    pool: list[dict] = []
    needed = picks_per_entry * max_entries
    while len(pool) < needed and (overs or unders):
        if len(pool) % 2 == 0 and overs:
            pick = overs.pop(0)
            pick = dict(pick, direction="OVER")
        elif unders:
            pick = unders.pop(0)
            pick = dict(pick, direction="UNDER")
        elif overs:
            pick = overs.pop(0)
            pick = dict(pick, direction="OVER")
        else:
            break
        pool.append(pick)

    # Slice pool into entries
    entries = []
    for i in range(0, len(pool) - picks_per_entry + 1, picks_per_entry):
        chunk = pool[i : i + picks_per_entry]
        if len(chunk) == picks_per_entry:
            entries.append(
                {
                    "picks": chunk,
                    "stake": round(stake_per_entry, 2),
                    "potential_profit": round(stake_per_entry * (multiplier - 1), 2),
                    "multiplier": multiplier,
                }
            )

    return entries


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_strategy(
    entries: list[dict],
    target: float,
    bankroll: float,
    picks_per_entry: int,
) -> None:
    multiplier = PAYOUT_MULTIPLIERS.get(picks_per_entry, 5.0)
    total_stake = sum(e["stake"] for e in entries)
    break_even_pct = (1 / multiplier) * 100

    print(f"\n{'\u2550'*72}")
    print(f"  $100/DAY STRATEGY  |  Target: ${target:.0f}  |  Bankroll: ${bankroll:.0f}")
    print(f"  Entry type: {picks_per_entry}-pick Power Play ({multiplier:.0f}x payout)")
    print(f"{'\u2550'*72}\n")

    for i, entry in enumerate(entries):
        print(
            f"  Entry #{i}  \u2014  Stake: ${entry['stake']:.2f}  "
            f"\u2192  Net profit on win: ${entry['potential_profit']:.2f}"
        )
        print(f"  {'\u2500'*62}")
        for p in entry["picks"]:
            arrow = "\u2191" if p["direction"] == "OVER" else "\u2193"
            print(
                f"    {arrow} {p['player']:<26} {p['stat_type']:<16} "
                f"Line: {p['line']:>5.1f}  Avg L10: {p['avg']:>5.2f}  "
                f"Edge: {p['edge_pct']:>+5.1f}%"
            )
        print()

    print(f"  Total at risk today : ${total_stake:.2f}")
    print(f"  Break-even win rate : {break_even_pct:.1f}% of entries")
    print(f"  To log a result run : python income_strategy.py --record <entry#> win|loss")
    print(
        "\n  NOTE: PrizePicks is a skill-based contest. Past averages do not"
        "\n  guarantee future results. Never risk money you cannot afford to lose.\n"
    )


# ---------------------------------------------------------------------------
# P&L logger
# ---------------------------------------------------------------------------

def record_result(entries: list[dict], entry_index: int, won: bool) -> None:
    entry = entries[entry_index]
    today = str(date.today())
    pnl = entry["potential_profit"] if won else -entry["stake"]

    record = {
        "date": today,
        "stake": entry["stake"],
        "result": "WIN" if won else "LOSS",
        "pnl": round(pnl, 2),
        "picks": [
            f"{p['direction']} {p['player']} {p['stat_type']} {p['line']}"
            for p in entry["picks"]
        ],
    }

    log: list[dict] = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            log = json.load(f)

    log.append(record)
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

    sign = "+" if pnl >= 0 else ""
    print(f"Logged {record['result']}: {sign}${pnl:.2f} on {today}")


def show_log() -> None:
    if not os.path.exists(LOG_FILE):
        print("No log yet. Record some results with --record.")
        return

    with open(LOG_FILE) as f:
        log: list[dict] = json.load(f)

    if not log:
        print("Log is empty.")
        return

    wins = sum(1 for r in log if r["result"] == "WIN")
    total = len(log)
    total_pnl = sum(r["pnl"] for r in log)

    print(f"\n{'\u2550'*64}")
    print(f"  PERFORMANCE LOG  ({total} entries)")
    print(f"{'\u2550'*64}")
    print(f"  {'Date':<12} {'Result':<6} {'P&L':>9}  Picks")
    print(f"  {'\u2500'*60}")
    for r in log[-20:]:
        sign = "+" if r["pnl"] >= 0 else ""
        pnl_str = f"{sign}${r['pnl']:.2f}"
        picks_preview = " | ".join(r["picks"][:2])
        if len(r["picks"]) > 2:
            picks_preview += " ..."
        print(f"  {r['date']:<12} {r['result']:<6} {pnl_str:>9}  {picks_preview[:36]}")

    print(f"  {'\u2500'*60}")
    sign = "+" if total_pnl >= 0 else ""
    print(f"  Win rate : {wins}/{total} ({wins/total*100:.1f}%)")
    print(f"  Total P&L: {sign}${total_pnl:.2f}")
    print(f"  Avg/entry: {sign}${total_pnl/total:.2f}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PrizePicks $100/Day Income Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target",   type=float, default=100.0, help="Daily profit target in $ (default: 100)")
    parser.add_argument("--bankroll", type=float, default=100.0, help="Available bankroll in $ (default: 100)")
    parser.add_argument("--league",   type=str,   default="NBA",  help="League: NBA/NHL/MLB (default: NBA)")
    parser.add_argument("--picks",    type=int,   default=3,      choices=[2, 3, 4, 5], help="Picks per entry (default: 3)")
    parser.add_argument("--log",      action="store_true",        help="Show the P&L performance log")
    parser.add_argument(
        "--record", nargs=2, metavar=("ENTRY_NUM", "win|loss"),
        help="Record the result of an entry, e.g. --record 0 win",
    )
    args = parser.parse_args()

    if args.log:
        show_log()
        return

    print(f"\nPrizePicks $100/Day Strategy \u2014 {args.league.upper()}")
    print("Fetching and analyzing today's props...\n")

    try:
        projections = fetch_prizepicks(args.league)
    except Exception as exc:
        print(f"ERROR fetching PrizePicks: {exc}")
        return

    if not projections:
        print("No projections found for today.")
        return

    results = analyze(projections)
    if not results:
        print("No analyzable props found.")
        return

    entries = build_entries(results, args.target, args.bankroll, args.picks)
    if not entries:
        print("Not enough high-edge props today to build entries.")
        return

    print_strategy(entries, args.target, args.bankroll, args.picks)

    if args.record:
        entry_num, outcome = int(args.record[0]), args.record[1].lower()
        if outcome not in ("win", "loss"):
            print("Outcome must be 'win' or 'loss'.")
            return
        if entry_num < 0 or entry_num >= len(entries):
            print(f"Entry number must be 0-{len(entries)-1}.")
            return
        record_result(entries, entry_num, won=(outcome == "win"))


if __name__ == "__main__":
    main()
