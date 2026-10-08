import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "player_performance_data_statbunker.json"
DEFAULT_OUTPUT = ROOT / "player_performance_data_statbunker.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_get(mapping, key, default=0):
    value = (mapping or {}).get(key, default)
    return default if value is None else value


def blank_stats():
    return {
        "source": "none",
        "data_status": "no_external_player_stats_found",
        "confidence": 0.0,
        "recent": {
            "appearances": None,
            "minutes_played": None,
            "goals": None,
            "assists": None,
            "goal_contributions": None,
            "yellow_cards": None,
            "red_cards": None,
            "clean_sheets": None,
            "goals_conceded": None,
            "per_90": {},
            "per_appearance": {},
        },
        "career": {},
        "notes": [
            "No confident StatBunker or Transfermarkt identity match was available.",
            "Do not treat null values as zero production.",
        ],
    }


def from_statbunker(player):
    summary = player.get("statbunker_summary") or {}
    derived = player.get("derived_scores") or {}
    return {
        "source": "statbunker",
        "data_status": "stats_collected",
        "confidence": safe_get(derived, "free_data_confidence", 0.0),
        "recent": {
            "appearances": safe_get(summary, "appearances"),
            "minutes_played": None,
            "goals": safe_get(summary, "goals"),
            "assists": safe_get(summary, "assists"),
            "goal_contributions": safe_get(summary, "goal_contributions"),
            "yellow_cards": safe_get(summary, "yellow_cards"),
            "red_cards": safe_get(summary, "red_cards"),
            "clean_sheets": safe_get(summary, "clean_sheets"),
            "goals_conceded": None,
            "per_90": {},
            "per_appearance": summary.get("per_appearance") or {},
        },
        "career": {},
        "competitions": summary.get("competitions") or [],
        "notes": [
            "StatBunker public tables do not expose minutes or advanced event metrics for this collector.",
        ],
    }


def from_transfermarkt(player):
    transfermarkt = player.get("transfermarkt_summary") or {}
    recent = transfermarkt.get("club_performance_recent") or {}
    career = transfermarkt.get("club_performance_career") or {}
    return {
        "source": "transfermarkt",
        "data_status": "stats_collected",
        "confidence": safe_get(transfermarkt, "free_data_confidence", 0.0),
        "recent": {
            "appearances": safe_get(recent, "appearances"),
            "minutes_played": safe_get(recent, "minutes_played"),
            "goals": safe_get(recent, "goals"),
            "assists": safe_get(recent, "assists"),
            "goal_contributions": safe_get(recent, "goal_contributions"),
            "yellow_cards": safe_get(recent, "yellow_cards"),
            "red_cards": safe_get(recent, "red_cards"),
            "clean_sheets": safe_get(recent, "clean_sheets"),
            "goals_conceded": safe_get(recent, "goals_conceded"),
            "per_90": recent.get("per_90") or {},
            "per_appearance": recent.get("per_appearance") or {},
        },
        "career": career,
        "competitions": recent.get("competitions") or [],
        "teams": recent.get("teams") or [],
        "notes": [
            "Transfermarkt rows are season-and-competition aggregates, not match ratings or event-level data.",
        ],
    }


def from_wikipedia(player):
    wikipedia = player.get("sources", {}).get("wikipedia") or {}
    summary = wikipedia.get("summary") or {}
    return {
        "source": "wikipedia",
        "data_status": "basic_infobox_stats_collected",
        "confidence": safe_get(wikipedia, "source_match_score", 0.0),
        "recent": {
            "appearances": None,
            "minutes_played": None,
            "goals": None,
            "assists": None,
            "goal_contributions": None,
            "yellow_cards": None,
            "red_cards": None,
            "clean_sheets": None,
            "goals_conceded": None,
            "per_90": {},
            "per_appearance": {},
        },
        "career": {
            "senior_appearances": safe_get(summary, "senior_appearances"),
            "senior_goals": safe_get(summary, "senior_goals"),
            "national_caps": safe_get(summary, "national_caps"),
            "national_goals": safe_get(summary, "national_goals"),
        },
        "competitions": [],
        "teams": [row.get("team") for row in wikipedia.get("club_career", []) if row.get("team")],
        "notes": [
            "Wikipedia infobox stats are basic career aggregates and may lag the article update date.",
            "No recent-season breakdown or minutes are available from this fallback.",
        ],
    }


def statistics_for_player(player):
    if player.get("collection_status") == "stats_collected" and player.get("statbunker_summary"):
        return from_statbunker(player)
    if player.get("sources", {}).get("transfermarkt") and player.get("transfermarkt_summary", {}).get("club_performance_collected"):
        return from_transfermarkt(player)
    if player.get("sources", {}).get("wikipedia"):
        return from_wikipedia(player)
    return blank_stats()


def apply(args):
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    counts = {}
    for player in data.get("players", []):
        stats = statistics_for_player(player)
        player["player_statistics"] = stats
        counts[stats["source"]] = counts.get(stats["source"], 0) + 1

    metadata = data.setdefault("metadata", {})
    metadata["player_statistics_summary"] = {
        "created_at": now_iso(),
        "player_count": len(data.get("players", [])),
        "source_counts": dict(sorted(counts.items())),
        "complete": all("player_statistics" in player for player in data.get("players", [])),
        "notes": [
            "Every player has a player_statistics block.",
            "Players with source=none have explicit null statistics because no confident external identity match was found.",
        ],
    }
    Path(args.output).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(metadata["player_statistics_summary"], indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    apply(args)


if __name__ == "__main__":
    main()
