#!/usr/bin/env python3
"""
PrizePicks Value Finder
=======================
Fetches today's PrizePicks lines and compares them against each player's
recent game averages (last 10 games) to surface the highest-edge picks.

Usage:
    python pp_finder.py          # defaults to NBA
    python pp_finder.py NBA
    python pp_finder.py NHL
    python pp_finder.py MLB

Requirements:
    pip install requests rich
"""

import sys
import time
from collections import defaultdict

import requests

# ── Config ────────────────────────────────────────────────────────────────────

PP_URL = "https://api.prizepicks.com/projections"
BDL_URL = "https://www.balldontlie.io/api/v1"

# PrizePicks league IDs
LEAGUE_IDS = {
    "NBA": 7,
    "MLB": 2,
    "NHL": 8,
    "WNBA": 3,
    "NFL": 9,
}

# Map PrizePicks stat labels → balldontlie field(s)
STAT_MAP = {
    "Points":          ["pts"],
    "Rebounds":        ["reb"],
    "Assists":         ["ast"],
    "3-PT Made":       ["fg3m"],
    "Blocks":          ["blk"],
    "Steals":          ["stl"],
    "Turnovers":       ["turnover"],
    "FG Made":         ["fgm"],
    "Free Throws Made":["ftm"],
    # Composite
    "Pts+Reb+Ast":     ["pts", "reb", "ast"],
    "Pts+Ast":         ["pts", "ast"],
    "Pts+Reb":         ["pts", "reb"],
    "Reb+Ast":         ["reb", "ast"],
    "Blks+Stls":       ["blk", "stl"],
}

RECENT_GAMES = 10   # games to average over
API_DELAY    = 0.2  # seconds between balldontlie calls (rate-limit courtesy)
CURRENT_SEASON = 2024  # balldontlie season key (year season started)

# ── PrizePicks ─────────────────────────────────────────────────────────────────

def fetch_prizepicks(league: str) -> list[dict]:
    """Return list of {player, stat_type, line, description} dicts."""
    league_id = LEAGUE_IDS.get(league.upper())
    if not league_id:
        raise ValueError(f"Unsupported league '{league}'. Choose from: {list(LEAGUE_IDS)}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://app.prizepicks.com/",
    }
    params = {"per_page": 250, "league_id": league_id, "single_stat": "true"}

    resp = requests.get(PP_URL, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    # Build player-id → name map from the "included" sidecar data
    players: dict[str, str] = {}
    for item in payload.get("included", []):
        if item["type"] == "new_player":
            players[item["id"]] = item["attributes"]["name"]

    projections = []
    for proj in payload.get("data", []):
        attrs = proj.get("attributes", {})
        player_rel = (
            proj.get("relationships", {})
                .get("new_player", {})
                .get("data", {})
        )
        player_name = players.get(player_rel.get("id"), "Unknown")
        stat_type   = attrs.get("stat_type")
        line        = attrs.get("line_score")

        if player_name == "Unknown" or stat_type not in STAT_MAP or line is None:
            continue

        projections.append({
            "player":      player_name,
            "stat_type":   stat_type,
            "line":        float(line),
            "description": attrs.get("description", ""),
        })

    return projections


# ── balldontlie stats ──────────────────────────────────────────────────────────

_id_cache: dict[str, int | None] = {}


def find_player_id(name: str) -> int | None:
    if name in _id_cache:
        return _id_cache[name]

    try:
        resp = requests.get(
            f"{BDL_URL}/players",
            params={"search": name, "per_page": 5},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception:
        _id_cache[name] = None
        return None

    results = resp.json().get("data", [])
    if not results:
        _id_cache[name] = None
        return None

    # Prefer exact full-name match, fall back to first result
    name_lower = name.lower()
    for p in results:
        if f"{p['first_name']} {p['last_name']}".lower() == name_lower:
            _id_cache[name] = p["id"]
            return p["id"]

    _id_cache[name] = results[0]["id"]
    return results[0]["id"]


def fetch_recent_stats(player_id: int, n: int = RECENT_GAMES) -> list[dict]:
    try:
        resp = requests.get(
            f"{BDL_URL}/stats",
            params={
                "player_ids[]": player_id,
                "per_page": n,
                "seasons[]": CURRENT_SEASON,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except Exception:
        return []

    games = resp.json().get("data", [])
    # Drop DNPs (no minutes played)
    return [g for g in games if g.get("min") and g["min"] not in ("", "0:00", "00:00")]


def avg_for_fields(games: list[dict], fields: list[str]) -> float | None:
    if not games:
        return None
    total = sum(
        sum(g.get(f) or 0 for f in fields)
        for g in games
    )
    return round(total / len(games), 2)


# ── Core analysis ──────────────────────────────────────────────────────────────

def analyze(projections: list[dict]) -> list[dict]:
    results = []
    seen: set[tuple] = set()
    total = len(projections)

    for i, proj in enumerate(projections, 1):
        key = (proj["player"], proj["stat_type"])
        if key in seen:
            continue
        seen.add(key)

        fields = STAT_MAP.get(proj["stat_type"])
        if not fields:
            continue

        print(f"  [{i:>3}/{total}] {proj['player']:<26} {proj['stat_type']}", end="\r", flush=True)

        pid = find_player_id(proj["player"])
        if pid is None:
            continue

        time.sleep(API_DELAY)
        games = fetch_recent_stats(pid)
        avg   = avg_for_fields(games, fields)
        if avg is None:
            continue

        diff = avg - proj["line"]
        pct  = round((diff / proj["line"]) * 100, 1) if proj["line"] else 0.0

        results.append({
            "player":       proj["player"],
            "stat_type":    proj["stat_type"],
            "line":         proj["line"],
            "avg":          avg,
            "diff":         round(diff, 2),
            "edge_pct":     pct,
            "games":        len(games),
            "matchup":      proj["description"],
        })

    print(" " * 70, end="\r")  # clear progress line
    return results


# ── Display ────────────────────────────────────────────────────────────────────

def _banner(text: str) -> None:
    print(f"\n{'═'*72}")
    print(f"  {text}")
    print(f"{'═'*72}")


def print_results(results: list[dict], top_n: int = 15) -> None:
    overs  = sorted([r for r in results if r["edge_pct"] > 0],
                    key=lambda x: x["edge_pct"], reverse=True)[:top_n]
    unders = sorted([r for r in results if r["edge_pct"] < 0],
                    key=lambda x: x["edge_pct"])[:top_n]

    header = f"{'Player':<26} {'Stat':<16} {'PP Line':>8} {'Avg L10':>8} {'Diff':>7} {'Edge':>7}  Matchup"
    divider = "─" * 72

    _banner(f"↑  BEST OVERS  (avg > line, last {RECENT_GAMES} games)")
    print(header)
    print(divider)
    if overs:
        for r in overs:
            matchup = (r["matchup"] or "")[:12]
            print(
                f"{r['player']:<26} {r['stat_type']:<16} {r['line']:>8.1f}"
                f" {r['avg']:>8.2f} {r['diff']:>+7.2f} {r['edge_pct']:>+6.1f}%  {matchup}"
            )
    else:
        print("  No over value found.")

    _banner(f"↓  BEST UNDERS  (avg < line, last {RECENT_GAMES} games)")
    print(header)
    print(divider)
    if unders:
        for r in unders:
            matchup = (r["matchup"] or "")[:12]
            print(
                f"{r['player']:<26} {r['stat_type']:<16} {r['line']:>8.1f}"
                f" {r['avg']:>8.2f} {r['diff']:>+7.2f} {r['edge_pct']:>+6.1f}%  {matchup}"
            )
    else:
        print("  No under value found.")

    _banner(f"Analyzed {len(results)} props | Source: PrizePicks + balldontlie (last {RECENT_GAMES} games)")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    league = (sys.argv[1] if len(sys.argv) > 1 else "NBA").upper()

    print(f"\nPrizePicks Value Finder — {league}")
    print("Fetching today's projections from PrizePicks...")

    try:
        projections = fetch_prizepicks(league)
    except Exception as exc:
        print(f"ERROR fetching PrizePicks data: {exc}")
        sys.exit(1)

    if not projections:
        print("No projections found for today.")
        sys.exit(0)

    unique_players = len({p["player"] for p in projections})
    print(f"Found {len(projections)} props across {unique_players} players.")
    print(f"Fetching last-{RECENT_GAMES}-game stats (may take ~{unique_players // 3}s)...\n")

    results = analyze(projections)
    print_results(results)


if __name__ == "__main__":
    main()
