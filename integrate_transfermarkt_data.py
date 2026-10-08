import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache" / "transfermarkt"
DEFAULT_INPUT = ROOT / "player_performance_data_statbunker.json"
DEFAULT_OUTPUT = ROOT / "player_performance_data_statbunker.json"
DEFAULT_REVIEW = ROOT / "player_performance_data_transfermarkt_review.json"
DEFAULT_PERFORMANCES = CACHE_DIR / "player_performances.csv"
DEFAULT_OVERRIDES = ROOT / "player_identity_overrides.json"
DEFAULT_ALIASES = ROOT / "player_name_aliases.json"


COUNTRY_ALIAS = {
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde",
    "Curacao": "Curacao",
    "Czech Republic": "Czech Republic",
    "DR Congo": "DR Congo",
    "England": "England",
    "Iran": "Iran",
    "Ivory Coast": "Cote d'Ivoire",
    "South Korea": "Korea, South",
    "Turkey": "Türkiye",
    "United States": "United States",
}


CLUB_ALIASES = {
    "1 fsv mainz 05": "mainz",
    "ac milan": "milan",
    "afc bournemouth": "bournemouth",
    "al ahli fc": "al ahli",
    "al hilal sc": "al hilal",
    "al nassr fc": "al nassr",
    "arsenal fc": "arsenal",
    "aston villa fc": "aston villa",
    "bayern munchen": "bayern munich",
    "borussia monchengladbach": "borussia monchengladbach",
    "brighton hove albion fc": "brighton hove albion",
    "chelsea fc": "chelsea",
    "cr flamengo": "flamengo",
    "fc internazionale milano": "inter milan",
    "fc porto": "porto",
    "fc red bull salzburg": "red bull salzburg",
    "fenerbahce sk": "fenerbahce",
    "inter": "inter milan",
    "juventus fc": "juventus",
    "lille osc": "lille",
    "liverpool fc": "liverpool",
    "manchester city fc": "manchester city",
    "manchester united fc": "manchester united",
    "newcastle united fc": "newcastle united",
    "nottingham forest fc": "nottingham forest",
    "olympique lyonnais": "lyon",
    "olympique marseille": "marseille",
    "paris saint germain": "psg",
    "paris saint germain fc": "psg",
    "psv eindhoven": "psv",
    "rb leipzig": "rasenballsport leipzig",
    "real betis balompie": "real betis",
    "real madrid cf": "real madrid",
    "ssc napoli": "napoli",
    "ss lazio": "lazio",
    "tottenham hotspur fc": "tottenham hotspur",
    "west ham united fc": "west ham united",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def clean_profile_name(name):
    return re.sub(r"\s*\(\d+\)\s*$", "", str(name or "")).strip()


def name_variants(name):
    base = norm(name)
    variants = {base}
    variants.add(re.sub(r"\b(jr|jr\.|junior|sr|sr\.)\b", "", base).strip())
    variants.add(base.replace("ue", "u").replace("oe", "o").replace("ae", "a"))
    variants.add(base.replace("ngolo", "n golo"))
    variants.add(base.replace("n golo", "ngolo"))
    return {variant for variant in variants if variant}


def korean_name_variants(name):
    parts = str(name or "").split()
    if len(parts) != 2:
        return set()
    given, family = parts
    variants = {f"{family} {given}"}
    for split_at in range(2, len(given) - 1):
        variants.add(f"{family} {given[:split_at]}-{given[split_at:]}")
    return variants


def load_name_aliases(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("players", data if isinstance(data, list) else [])
    aliases = defaultdict(list)
    for row in rows:
        values = [alias for alias in row.get("aliases", []) if alias]
        keys = [row.get("player_key")]
        if row.get("country") and row.get("name"):
            keys.append(f"{row['country']}::{row['name']}")
        for key in keys:
            if key:
                aliases[key].extend(values)
    return aliases


def player_search_names(player, aliases=None):
    names = {player.get("name") or ""}
    key = player.get("player_key") or f"{player.get('country')}::{player.get('name')}"
    for alias in (aliases or {}).get(key, []):
        names.add(alias)
    if player.get("country") == "South Korea":
        names.update(korean_name_variants(player.get("name")))
    return {name for name in names if name}


def club_without_country(club):
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", str(club or "")).strip()


def canonical_club(club):
    cleaned = norm(club_without_country(club))
    return CLUB_ALIASES.get(cleaned, cleaned)


def tokens(text):
    return set(norm(text).split())


def single_name_score(left, right):
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return max(0.88, len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens)))
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def name_score(left, right):
    best = 0.0
    for left_variant in name_variants(left):
        for right_variant in name_variants(right):
            best = max(best, single_name_score(left_variant, right_variant))
    return best


def club_score(left, right):
    left_tokens = tokens(canonical_club(left))
    right_tokens = tokens(canonical_club(right))
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def country_matches(player_country, profile):
    wanted = norm(COUNTRY_ALIAS.get(player_country, player_country))
    country_fields = [
        profile.get("citizenship"),
        profile.get("country_of_birth"),
    ]
    for value in country_fields:
        if wanted and wanted in norm(value).split():
            return True
        if wanted and norm(value) == wanted:
            return True
    citizenship = norm(profile.get("citizenship"))
    return bool(wanted and (wanted in citizenship or citizenship in wanted))


def parse_int(value):
    text = str(value or "").replace(",", "").replace("'", "").strip()
    if not text or text in {"-", "nan"}:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def safe_div(numerator, denominator):
    return round(float(numerator) / denominator, 4) if denominator else None


def load_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def load_market_values():
    values = {}
    path = CACHE_DIR / "player_latest_market_value.csv"
    if not path.exists():
        return values
    for row in load_csv(path):
        values[row["player_id"]] = {
            "date": row.get("date_unix"),
            "value_eur": parse_int(row.get("value")),
        }
    return values


def load_team_details():
    teams = {}
    path = CACHE_DIR / "team_details.csv"
    if not path.exists():
        return teams
    for row in load_csv(path):
        club_id = row.get("club_id")
        if club_id and club_id not in teams:
            teams[club_id] = {
                "team_id": club_id,
                "team_name": clean_profile_name(row.get("club_name")),
                "country_name": row.get("country_name"),
                "competition_name": row.get("competition_name"),
            }
    return teams


def load_national_performances(team_details):
    by_player = defaultdict(list)
    path = CACHE_DIR / "player_national_performances.csv"
    if not path.exists():
        return by_player
    for row in load_csv(path):
        team = team_details.get(row.get("team_id"), {})
        by_player[row["player_id"]].append(
            {
                "team_id": row.get("team_id"),
                "team_name": team.get("team_name"),
                "country_name": team.get("country_name"),
                "matches": parse_int(row.get("matches")),
                "goals": parse_int(row.get("goals")),
                "shirt_number": parse_int(row.get("shirt_number")),
                "career_state": row.get("career_state"),
            }
        )
    return by_player


def load_profiles():
    profiles = []
    by_name = defaultdict(list)
    path = CACHE_DIR / "player_profiles.csv"
    for row in load_csv(path):
        row["clean_player_name"] = clean_profile_name(row.get("player_name"))
        row["clean_home_name"] = clean_profile_name(row.get("name_in_home_country"))
        profiles.append(row)
        for name in [row["clean_player_name"], row["clean_home_name"], row.get("player_slug", "").replace("-", " ")]:
            for key in name_variants(name):
                by_name[key].append(row)
    return profiles, by_name


def load_overrides(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("players", data if isinstance(data, list) else [])
    overrides = {}
    for row in rows:
        player_id = str(row.get("transfermarkt_player_id") or row.get("player_id") or "").strip()
        if not player_id:
            continue
        keys = [row.get("player_key")]
        if row.get("country") and row.get("name"):
            keys.append(f"{row['country']}::{row['name']}")
        for key in keys:
            if key:
                overrides[key] = {"player_id": player_id, "row": row}
    return overrides


def season_sort_key(season):
    match = re.match(r"^(\d{2})/(\d{2})$", str(season or ""))
    if match:
        return 2000 + int(match.group(1))
    try:
        return int(season)
    except (TypeError, ValueError):
        return -1


def performance_row(row):
    return {
        "season_name": row.get("season_name"),
        "competition_id": row.get("competition_id"),
        "competition_name": row.get("competition_name"),
        "team_id": row.get("team_id"),
        "team_name": clean_profile_name(row.get("team_name")),
        "squad_appearances": parse_int(row.get("nb_in_group")),
        "appearances": parse_int(row.get("nb_on_pitch")),
        "goals": parse_int(row.get("goals")),
        "assists": parse_int(row.get("assists")),
        "own_goals": parse_int(row.get("own_goals")),
        "subbed_in": parse_int(row.get("subed_in")),
        "subbed_out": parse_int(row.get("subed_out")),
        "yellow_cards": parse_int(row.get("yellow_cards")),
        "second_yellow_cards": parse_int(row.get("second_yellow_cards")),
        "red_cards": parse_int(row.get("direct_red_cards")),
        "penalty_goals": parse_int(row.get("penalty_goals")),
        "minutes_played": parse_int(row.get("minutes_played")),
        "goals_conceded": parse_int(row.get("goals_conceded")),
        "clean_sheets": parse_int(row.get("clean_sheets")),
    }


def load_performances(path, player_ids):
    by_player = defaultdict(list)
    path = Path(path)
    if not path.exists() or not player_ids:
        return by_player
    wanted = set(player_ids)
    for row in load_csv(path):
        player_id = row.get("player_id")
        if player_id in wanted:
            by_player[player_id].append(performance_row(row))
    for rows in by_player.values():
        rows.sort(key=lambda row: (season_sort_key(row.get("season_name")), row.get("competition_name") or ""), reverse=True)
    return by_player


def aggregate_performance_rows(rows):
    rows = list(rows)
    minutes = sum(row["minutes_played"] for row in rows)
    appearances = sum(row["appearances"] for row in rows)
    goals = sum(row["goals"] for row in rows)
    assists = sum(row["assists"] for row in rows)
    yellow_cards = sum(row["yellow_cards"] for row in rows)
    red_cards = sum(row["red_cards"] + row["second_yellow_cards"] for row in rows)
    return {
        "row_count": len(rows),
        "seasons": sorted({row["season_name"] for row in rows if row.get("season_name")}, key=season_sort_key, reverse=True),
        "teams": sorted({row["team_name"] for row in rows if row.get("team_name")}),
        "competitions": sorted({row["competition_name"] for row in rows if row.get("competition_name")}),
        "squad_appearances": sum(row["squad_appearances"] for row in rows),
        "appearances": appearances,
        "minutes_played": minutes,
        "goals": goals,
        "assists": assists,
        "goal_contributions": goals + assists,
        "own_goals": sum(row["own_goals"] for row in rows),
        "subbed_in": sum(row["subbed_in"] for row in rows),
        "subbed_out": sum(row["subbed_out"] for row in rows),
        "yellow_cards": yellow_cards,
        "red_cards": red_cards,
        "penalty_goals": sum(row["penalty_goals"] for row in rows),
        "goals_conceded": sum(row["goals_conceded"] for row in rows),
        "clean_sheets": sum(row["clean_sheets"] for row in rows),
        "per_90": {
            "goals": safe_div(goals * 90, minutes),
            "assists": safe_div(assists * 90, minutes),
            "goal_contributions": safe_div((goals + assists) * 90, minutes),
            "cards": safe_div((yellow_cards + red_cards) * 90, minutes),
        },
        "per_appearance": {
            "goals": safe_div(goals, appearances),
            "assists": safe_div(assists, appearances),
            "goal_contributions": safe_div(goals + assists, appearances),
        },
    }


def performance_summary(player_id, performances, recent_seasons):
    rows = performances.get(player_id, [])
    recent = [row for row in rows if row.get("season_name") in recent_seasons]
    return {
        "recent_seasons": list(recent_seasons),
        "recent": aggregate_performance_rows(recent),
        "career": aggregate_performance_rows(rows),
        "recent_rows": recent[:40],
    }


def source_match_score(player, profile, name_counts, aliases=None):
    ns = max(
        max(name_score(name, profile.get("clean_player_name")), name_score(name, profile.get("clean_home_name")))
        for name in player_search_names(player, aliases)
    )
    cs = club_score(player.get("club"), profile.get("current_club_name"))
    country_ok = country_matches(player.get("country"), profile)
    score = ns * 0.72 + cs * 0.2 + (0.08 if country_ok else 0.0)
    if ns >= 0.99 and country_ok:
        score = max(score, 0.92)
    if ns >= 0.99 and name_counts.get(norm(profile.get("clean_player_name")), 0) == 1:
        score = max(score, 0.9)
    if ns >= 0.78 and cs >= 0.75 and country_ok:
        score = max(score, 0.86)
    return round(min(score, 1.0), 4), round(ns, 4), round(cs, 4), country_ok


def candidate_pool(player, by_name, profiles, aliases=None):
    keys = set()
    for name in player_search_names(player, aliases):
        keys.update(name_variants(name))
        name_parts = norm(name).split()
        if len(name_parts) >= 2:
            keys.update(name_variants(" ".join(name_parts)))
    pool = []
    seen = set()
    for key in keys:
        for row in by_name.get(key, []):
            if row["player_id"] not in seen:
                seen.add(row["player_id"])
                pool.append(row)
    if pool:
        return pool
    wanted_token_sets = [tokens(name) for name in player_search_names(player, aliases) if len(tokens(name)) >= 2]
    if not wanted_token_sets:
        return []
    for row in profiles:
        row_tokens = tokens(row.get("clean_player_name")) | tokens(row.get("clean_home_name"))
        if any(wanted_tokens <= row_tokens or row_tokens <= wanted_tokens for wanted_tokens in wanted_token_sets):
            if row["player_id"] not in seen:
                seen.add(row["player_id"])
                pool.append(row)
    return pool


def build_transfermarkt_source(profile, score_info, market_values, national_rows, player_country):
    score, ns, cs, country_ok = score_info
    national = [
        row
        for row in national_rows.get(profile["player_id"], [])
        if norm(row.get("country_name")) == norm(COUNTRY_ALIAS.get(player_country, player_country))
        or norm(row.get("team_name")) == norm(COUNTRY_ALIAS.get(player_country, player_country))
    ]
    if not national:
        national = national_rows.get(profile["player_id"], [])[:5]
    national_summary = {
        "rows": national,
        "matches": sum(row.get("matches") or 0 for row in national),
        "goals": sum(row.get("goals") or 0 for row in national),
    }
    return {
        "player_id": profile.get("player_id"),
        "player_slug": profile.get("player_slug"),
        "player_name": profile.get("clean_player_name"),
        "name_in_home_country": profile.get("clean_home_name"),
        "date_of_birth": profile.get("date_of_birth"),
        "citizenship": profile.get("citizenship"),
        "country_of_birth": profile.get("country_of_birth"),
        "position": profile.get("position"),
        "main_position": profile.get("main_position"),
        "foot": profile.get("foot"),
        "current_club_id": profile.get("current_club_id"),
        "current_club_name": clean_profile_name(profile.get("current_club_name")),
        "joined": profile.get("joined"),
        "contract_expires": profile.get("contract_expires"),
        "on_loan_from_club_name": clean_profile_name(profile.get("on_loan_from_club_name")),
        "latest_market_value": market_values.get(profile.get("player_id")),
        "national_team_summary": national_summary,
        "source_match_score": score,
        "source_name_score": ns,
        "source_club_score": cs,
        "source_country_match": country_ok,
    }


def merge(args):
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    market_values = load_market_values()
    team_details = load_team_details()
    national_rows = load_national_performances(team_details)
    profiles, by_name = load_profiles()
    profiles_by_id = {row["player_id"]: row for row in profiles}
    overrides = load_overrides(args.overrides)
    aliases = load_name_aliases(args.aliases)
    name_counts = {key: len(rows) for key, rows in by_name.items()}
    review = []
    matched = 0
    filled_unmatched = 0
    override_matches = 0
    assignments = []
    recent_seasons = [season.strip() for season in args.recent_seasons.split(",") if season.strip()]

    for player in data.get("players", []):
        original_status = player.get("collection_status")
        override = overrides.get(player.get("player_key")) or overrides.get(f"{player.get('country')}::{player.get('name')}")
        if override and override["player_id"] in profiles_by_id:
            best_profile = profiles_by_id[override["player_id"]]
            best_score = source_match_score(player, best_profile, name_counts, aliases)
            best_score = (max(best_score[0], 0.99), best_score[1], best_score[2], best_score[3])
            override_matches += 1
            source = build_transfermarkt_source(best_profile, best_score, market_values, national_rows, player.get("country"))
            source["identity_override"] = {
                "applied": True,
                "note": override["row"].get("note"),
            }
            player.setdefault("sources", {})["transfermarkt"] = source
            player["transfermarkt_summary"] = {
                "profile_collected": True,
                "national_team_matches": source["national_team_summary"]["matches"],
                "national_team_goals": source["national_team_summary"]["goals"],
                "latest_market_value_eur": (source.get("latest_market_value") or {}).get("value_eur"),
                "main_position": source.get("main_position"),
                "current_club_name": source.get("current_club_name"),
                "free_data_confidence": source["source_match_score"],
                "limitations": [
                    "Transfermarkt rows are season-and-competition aggregates, not event data or match ratings.",
                ],
            }
            matched += 1
            assignments.append((player, source["player_id"], original_status))
            if original_status != "stats_collected":
                player["collection_status"] = "transfermarkt_profile_collected"
                player["reason"] = "Transfermarkt profile matched by identity override; StatBunker stats unavailable."
                filled_unmatched += 1
            continue

        scored = []
        for profile in candidate_pool(player, by_name, profiles, aliases):
            score_info = source_match_score(player, profile, name_counts, aliases)
            if score_info[0] >= args.review_threshold:
                scored.append((score_info, profile))
        scored.sort(key=lambda item: item[0][0], reverse=True)
        if not scored:
            continue

        best_score, best_profile = scored[0]
        near = [item for item in scored if best_score[0] - item[0][0] <= args.ambiguity_margin]
        if best_score[0] < args.identity_threshold or (len(near) > 1 and best_score[0] < args.high_confidence_threshold):
            review.append(
                {
                    "player_key": player.get("player_key"),
                    "country": player.get("country"),
                    "name": player.get("name"),
                    "club": player.get("club"),
                    "candidates": [
                        {
                            "score": info[0],
                            "name_score": info[1],
                            "club_score": info[2],
                            "country_match": info[3],
                            "player_id": profile.get("player_id"),
                            "player_name": profile.get("clean_player_name"),
                            "current_club_name": clean_profile_name(profile.get("current_club_name")),
                            "citizenship": profile.get("citizenship"),
                        }
                        for info, profile in scored[: args.max_review_candidates]
                    ],
                }
            )
            continue

        source = build_transfermarkt_source(best_profile, best_score, market_values, national_rows, player.get("country"))
        player.setdefault("sources", {})["transfermarkt"] = source
        player["transfermarkt_summary"] = {
            "profile_collected": True,
            "national_team_matches": source["national_team_summary"]["matches"],
            "national_team_goals": source["national_team_summary"]["goals"],
            "latest_market_value_eur": (source.get("latest_market_value") or {}).get("value_eur"),
            "main_position": source.get("main_position"),
            "current_club_name": source.get("current_club_name"),
            "free_data_confidence": source["source_match_score"],
            "limitations": [
                "Transfermarkt rows are season-and-competition aggregates, not event data or match ratings.",
            ],
        }
        matched += 1
        assignments.append((player, source["player_id"], original_status))
        if original_status != "stats_collected":
            player["collection_status"] = "transfermarkt_profile_collected"
            player["reason"] = "Transfermarkt profile matched; StatBunker stats unavailable."
            filled_unmatched += 1

    performance_path = Path(args.performances)
    performances = load_performances(performance_path, [player_id for _player, player_id, _status in assignments])
    performance_matches = 0
    previously_unmatched_stats = 0
    for player, player_id, original_status in assignments:
        summary = performance_summary(player_id, performances, recent_seasons)
        player["sources"]["transfermarkt"]["club_performance_summary"] = summary
        player["transfermarkt_summary"]["club_performance_recent"] = summary["recent"]
        player["transfermarkt_summary"]["club_performance_career"] = summary["career"]
        has_performance_rows = bool(summary["career"]["row_count"])
        player["transfermarkt_summary"]["club_performance_collected"] = has_performance_rows
        if has_performance_rows:
            performance_matches += 1
            if original_status != "stats_collected":
                player["collection_status"] = "transfermarkt_stats_collected"
                player["reason"] = "Transfermarkt profile and club-season aggregate stats matched; StatBunker stats unavailable."
                previously_unmatched_stats += 1

    metadata = data.setdefault("metadata", {})
    metadata["transfermarkt_enrichment"] = {
        "created_at": now_iso(),
        "source": "salimt/football-datasets Transfermarkt CSVs",
        "source_url": "https://github.com/salimt/football-datasets",
        "profile_matches": matched,
        "identity_override_matches": override_matches,
        "previously_unmatched_profile_matches": filled_unmatched,
        "club_performance_matches": performance_matches,
        "previously_unmatched_club_performance_matches": previously_unmatched_stats,
        "review_count": len(review),
        "files_used": [
            "player_profiles.csv",
            str(performance_path),
            "player_national_performances.csv",
            "player_latest_market_value.csv",
            "team_details.csv",
        ],
        "recent_seasons": recent_seasons,
    }
    counts = defaultdict(int)
    for player in data.get("players", []):
        counts[player.get("collection_status")] += 1
    metadata["collection_status_counts"] = dict(sorted(counts.items()))

    Path(args.output).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.review_output).write_text(
        json.dumps({"metadata": {"created_at": now_iso(), "review_count": len(review)}, "players": review}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata["transfermarkt_enrichment"], indent=2))
    print("collection_status_counts", dict(sorted(counts.items())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--review-output", default=str(DEFAULT_REVIEW))
    parser.add_argument("--performances", default=str(DEFAULT_PERFORMANCES))
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument("--recent-seasons", default="25/26,24/25,23/24")
    parser.add_argument("--identity-threshold", type=float, default=0.86)
    parser.add_argument("--review-threshold", type=float, default=0.72)
    parser.add_argument("--ambiguity-margin", type=float, default=0.03)
    parser.add_argument("--high-confidence-threshold", type=float, default=0.95)
    parser.add_argument("--max-review-candidates", type=int, default=8)
    args = parser.parse_args()
    merge(args)


if __name__ == "__main__":
    main()
