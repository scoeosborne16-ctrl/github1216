#!/usr/bin/env python3
"""
PrizePicks Trades Database
==========================
Stores analyzed picks in a local SQLite database and surfaces
the highest-edge entries to place today.

Usage:
    python trades_db.py --refresh          # fetch today's picks and save to DB
    python trades_db.py --refresh --league NHL
    python trades_db.py --best             # show today's top picks from DB
    python trades_db.py --best --min-edge 10  # only edge >= 10%
    python trades_db.py --history          # all-time pick history
    python trades_db.py --result ID win    # mark pick ID as won
    python trades_db.py --result ID loss   # mark pick ID as lost

Requirements:
    pip install requests rich
"""

import argparse
import sqlite3
from datetime import date
from pathlib import Path

from pp_finder import analyze, fetch_prizepicks

DB_PATH = Path("trades.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS picks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_on  TEXT    NOT NULL,          -- YYYY-MM-DD
    league      TEXT    NOT NULL,
    player      TEXT    NOT NULL,
    stat_type   TEXT    NOT NULL,
    direction   TEXT    NOT NULL,          -- OVER / UNDER
    line        REAL    NOT NULL,
    avg_l10     REAL    NOT NULL,
    diff        REAL    NOT NULL,
    edge_pct    REAL    NOT NULL,
    games       INTEGER NOT NULL,
    matchup     TEXT,
    result      TEXT    DEFAULT NULL,      -- WIN / LOSS / NULL
    pnl         REAL    DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_fetched ON picks (fetched_on);
CREATE INDEX IF NOT EXISTS idx_edge    ON picks (edge_pct);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


# ---------------------------------------------------------------------------
# Refresh: fetch + analyze + insert
# ---------------------------------------------------------------------------

def refresh(league: str) -> None:
    today = str(date.today())
    print(f"\nFetching {league} props for {today}...")

    try:
        projections = fetch_prizepicks(league)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return

    if not projections:
        print("No projections found.")
        return

    results = analyze(projections)
    if not results:
        print("No analyzable props.")
        return

    conn = get_conn()

    # Remove today's existing rows for this league so we can re-insert fresh data
    conn.execute(
        "DELETE FROM picks WHERE fetched_on = ? AND league = ?",
        (today, league.upper()),
    )

    rows = []
    for r in results:
        direction = "OVER" if r["edge_pct"] > 0 else "UNDER"
        rows.append(
            (
                today,
                league.upper(),
                r["player"],
                r["stat_type"],
                direction,
                r["line"],
                r["avg"],
                r["diff"],
                r["edge_pct"],
                r["games"],
                r.get("matchup", ""),
            )
        )

    conn.executemany(
        """
        INSERT INTO picks
            (fetched_on, league, player, stat_type, direction,
             line, avg_l10, diff, edge_pct, games, matchup)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    print(f"Saved {len(rows)} picks to {DB_PATH}.")
    print(f"Run:  python trades_db.py --best   to see the top trades.")


# ---------------------------------------------------------------------------
# Best picks query
# ---------------------------------------------------------------------------

def show_best(min_edge: float, league: str | None, top_n: int) -> None:
    today = str(date.today())
    conn = get_conn()

    query = """
        SELECT id, player, stat_type, direction, line, avg_l10, diff,
               edge_pct, games, matchup, league
        FROM picks
        WHERE fetched_on = ?
          AND ABS(edge_pct) >= ?
    """
    params: list = [today, min_edge]

    if league:
        query += " AND league = ?"
        params.append(league.upper())

    query += " ORDER BY ABS(edge_pct) DESC LIMIT ?"
    params.append(top_n)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print(
            f"No picks found for {today} with edge >= {min_edge}%.\n"
            "Run:  python trades_db.py --refresh"
        )
        return

    sep = "\u2550" * 78
    div = "\u2500" * 78
    header = (
        f"  {'ID':>4}  {'Player':<24} {'Stat':<16} {'Dir':<6} "
        f"{'Line':>6} {'Avg L10':>8} {'Diff':>7} {'Edge':>7}  Matchup"
    )

    print(f"\n{sep}")
    print(f"  BEST TRADES TODAY ({today})  \u2014  min edge {min_edge:.0f}%")
    print(sep)
    print(header)
    print(div)

    for r in rows:
        arrow = "\u2191" if r["direction"] == "OVER" else "\u2193"
        matchup = (r["matchup"] or "")[:12]
        print(
            f"  {r['id']:>4}  {r['player']:<24} {r['stat_type']:<16} "
            f"{arrow} {r['direction']:<4} {r['line']:>6.1f} {r['avg_l10']:>8.2f} "
            f"{r['diff']:>+7.2f} {r['edge_pct']:>+6.1f}%  {matchup}"
        )

    print(div)
    print(f"  {len(rows)} picks shown.  Use --result <ID> win|loss to log outcomes.\n")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def show_history(league: str | None) -> None:
    conn = get_conn()

    query = """
        SELECT fetched_on, COUNT(*) AS total,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
               ROUND(SUM(COALESCE(pnl, 0)), 2) AS day_pnl
        FROM picks
    """
    params: list = []
    if league:
        query += " WHERE league = ?"
        params.append(league.upper())
    query += " GROUP BY fetched_on ORDER BY fetched_on DESC LIMIT 30"

    days = conn.execute(query, params).fetchall()

    # Overall stats
    overall = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN result='WIN'  THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(COALESCE(pnl, 0)), 2)               AS total_pnl
        FROM picks
        WHERE result IS NOT NULL
        """
    ).fetchone()
    conn.close()

    sep = "\u2550" * 52
    div = "\u2500" * 52
    print(f"\n{sep}")
    print(f"  PICK HISTORY (last 30 days)")
    print(sep)
    print(f"  {'Date':<12} {'Total':>6} {'W':>5} {'L':>5} {'Day P&L':>10}")
    print(div)
    for d in days:
        sign = "+" if (d["day_pnl"] or 0) >= 0 else ""
        pnl_str = f"{sign}${d['day_pnl']:.2f}" if d["day_pnl"] is not None else "  —"
        print(
            f"  {d['fetched_on']:<12} {d['total']:>6} "
            f"{d['wins'] or 0:>5} {d['losses'] or 0:>5} {pnl_str:>10}"
        )
    print(div)
    if overall and overall["total"]:
        sign = "+" if (overall["total_pnl"] or 0) >= 0 else ""
        print(
            f"  Graded picks : {overall['total']}  "
            f"Wins: {overall['wins'] or 0}  "
            f"({(overall['wins'] or 0) / overall['total'] * 100:.1f}%)  "
            f"Total P&L: {sign}${overall['total_pnl']:.2f}"
        )
    print()


# ---------------------------------------------------------------------------
# Record result
# ---------------------------------------------------------------------------

def record_result(pick_id: int, won: bool) -> None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM picks WHERE id = ?", (pick_id,)).fetchone()
    if not row:
        print(f"No pick with ID {pick_id}.")
        conn.close()
        return

    # Simple flat pnl: +1 unit win (net), -1 unit loss
    pnl = round(abs(row["edge_pct"]) / 100, 4) if won else -1.0  # symbolic unit
    result = "WIN" if won else "LOSS"

    conn.execute(
        "UPDATE picks SET result = ?, pnl = ? WHERE id = ?",
        (result, pnl, pick_id),
    )
    conn.commit()
    conn.close()

    sign = "+" if pnl >= 0 else ""
    print(f"Pick #{pick_id} ({row['player']} {row['stat_type']}) marked {result}  P&L: {sign}{pnl:.4f}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PrizePicks Trades Database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--refresh",  action="store_true", help="Fetch today's props and save to DB")
    parser.add_argument("--best",     action="store_true", help="Show today's best picks from DB")
    parser.add_argument("--history",  action="store_true", help="Show day-by-day pick history")
    parser.add_argument("--league",   type=str, default=None, help="Filter by league (NBA/NHL/MLB)")
    parser.add_argument("--min-edge", type=float, default=5.0, help="Minimum edge %% to show (default: 5)")
    parser.add_argument("--top",      type=int,   default=20,  help="Max picks to display (default: 20)")
    parser.add_argument(
        "--result", nargs=2, metavar=("ID", "win|loss"),
        help="Grade a pick, e.g. --result 42 win",
    )
    args = parser.parse_args()

    if args.refresh:
        league = (args.league or "NBA").upper()
        refresh(league)

    if args.best:
        show_best(args.min_edge, args.league, args.top)

    if args.history:
        show_history(args.league)

    if args.result:
        pick_id  = int(args.result[0])
        outcome  = args.result[1].lower()
        if outcome not in ("win", "loss"):
            print("Outcome must be 'win' or 'loss'.")
            return
        record_result(pick_id, won=(outcome == "win"))

    if not any([args.refresh, args.best, args.history, args.result]):
        parser.print_help()


if __name__ == "__main__":
    main()
