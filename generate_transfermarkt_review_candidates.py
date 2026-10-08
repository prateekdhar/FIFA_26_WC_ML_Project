import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from integrate_transfermarkt_data import (
    CACHE_DIR,
    DEFAULT_ALIASES,
    DEFAULT_INPUT,
    DEFAULT_OVERRIDES,
    candidate_pool,
    clean_profile_name,
    load_name_aliases,
    load_market_values,
    load_overrides,
    load_profiles,
    name_score,
    source_match_score,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "remaining_transfermarkt_candidates.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def candidate_rows(player, profiles, by_name, name_counts, market_values, aliases, limit):
    scored = []
    for profile in candidate_pool(player, by_name, profiles, aliases):
        score, ns, cs, country_ok = source_match_score(player, profile, name_counts, aliases)
        loose_name = max(name_score(player.get("name"), profile.get("clean_player_name")), name_score(player.get("name"), profile.get("clean_home_name")))
        if score >= 0.55 or loose_name >= 0.78:
            scored.append((score, ns, cs, country_ok, profile))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    rows = []
    for score, ns, cs, country_ok, profile in scored[:limit]:
        rows.append(
            {
                "score": score,
                "name_score": ns,
                "club_score": cs,
                "country_match": country_ok,
                "transfermarkt_player_id": profile.get("player_id"),
                "player_name": profile.get("clean_player_name"),
                "name_in_home_country": profile.get("clean_home_name"),
                "citizenship": profile.get("citizenship"),
                "country_of_birth": profile.get("country_of_birth"),
                "date_of_birth": profile.get("date_of_birth"),
                "position": profile.get("position"),
                "main_position": profile.get("main_position"),
                "current_club_name": clean_profile_name(profile.get("current_club_name")),
                "latest_market_value": market_values.get(profile.get("player_id")),
            }
        )
    return rows


def generate(args):
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    profiles, by_name = load_profiles()
    market_values = load_market_values()
    overrides = load_overrides(args.overrides)
    aliases = load_name_aliases(args.aliases)
    name_counts = {key: len(rows) for key, rows in by_name.items()}
    rows = []
    for player in data.get("players", []):
        if player.get("collection_status") != "identity_not_matched":
            continue
        key = player.get("player_key") or f"{player.get('country')}::{player.get('name')}"
        candidates = candidate_rows(player, profiles, by_name, name_counts, market_values, aliases, args.limit)
        rows.append(
            {
                "player_key": key,
                "country": player.get("country"),
                "name": player.get("name"),
                "club": player.get("club"),
                "position": player.get("position"),
                "override_exists": key in overrides,
                "suggested_override": candidates[0] if candidates else None,
                "candidates": candidates,
            }
        )
    rows.sort(key=lambda row: (0 if row["candidates"] else 1, row["country"] or "", row["name"] or ""))
    payload = {
        "metadata": {
            "created_at": now_iso(),
            "source_input": Path(args.input).name,
            "candidate_player_count": len(rows),
            "with_candidates": sum(1 for row in rows if row["candidates"]),
            "without_candidates": sum(1 for row in rows if not row["candidates"]),
            "instructions": [
                "To approve a match, copy player_key and transfermarkt_player_id into player_identity_overrides.json.",
                "Prefer candidates with matching country/citizenship and club; use manual web verification for duplicate/common names.",
            ],
        },
        "players": rows,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["metadata"], indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    generate(args)


if __name__ == "__main__":
    main()
