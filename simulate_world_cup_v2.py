import argparse
import json
import math
import os
import random
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is available in the Codex runtime.
    pd = None

try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:  # pragma: no cover - optional user/runtime dependency.
    RandomForestClassifier = None


ROOT = Path(__file__).resolve().parent
SQUAD_FILE = ROOT / "guardian_world_cup_2026_player_guide.json"
PERFORMANCE_FILE = ROOT / "player_performance_data_statbunker.json"
STRUCTURE_FILE = ROOT / "world_cup_2026_simulation_structure.json"
DEFAULT_ELO_FILE = ROOT / "national_team_elo_ratings.json"
VENUE_CONTEXT_FILE = ROOT / "world_cup_2026_venue_context.json"
TOURNAMENT_START_DATE = date(2026, 6, 11)
HOST_COUNTRIES = {"Canada", "Mexico", "United States"}
MEXICO_ALTITUDE_GROUPS = {"A"}
VENUE_CONTEXT_CACHE = None

GROUP_MATCH_DATES = {
    (1, "A", 0): date(2026, 6, 11),
    (1, "A", 1): date(2026, 6, 11),
    (1, "B", 0): date(2026, 6, 12),
    (1, "B", 1): date(2026, 6, 13),
    (1, "C", 0): date(2026, 6, 13),
    (1, "C", 1): date(2026, 6, 13),
    (1, "D", 0): date(2026, 6, 12),
    (1, "D", 1): date(2026, 6, 13),
    (1, "E", 0): date(2026, 6, 14),
    (1, "E", 1): date(2026, 6, 14),
    (1, "F", 0): date(2026, 6, 14),
    (1, "F", 1): date(2026, 6, 14),
    (1, "G", 0): date(2026, 6, 15),
    (1, "G", 1): date(2026, 6, 15),
    (1, "H", 0): date(2026, 6, 15),
    (1, "H", 1): date(2026, 6, 15),
    (1, "I", 0): date(2026, 6, 16),
    (1, "I", 1): date(2026, 6, 16),
    (1, "J", 0): date(2026, 6, 16),
    (1, "J", 1): date(2026, 6, 16),
    (1, "K", 0): date(2026, 6, 17),
    (1, "K", 1): date(2026, 6, 17),
    (1, "L", 0): date(2026, 6, 17),
    (1, "L", 1): date(2026, 6, 17),
}

GROUP_MATCHDAY_DATES = {
    2: {
        "A": date(2026, 6, 18),
        "B": date(2026, 6, 18),
        "C": date(2026, 6, 19),
        "D": date(2026, 6, 19),
        "E": date(2026, 6, 20),
        "F": date(2026, 6, 20),
        "G": date(2026, 6, 21),
        "H": date(2026, 6, 21),
        "I": date(2026, 6, 22),
        "J": date(2026, 6, 22),
        "K": date(2026, 6, 23),
        "L": date(2026, 6, 23),
    },
    3: {
        "A": date(2026, 6, 24),
        "B": date(2026, 6, 24),
        "C": date(2026, 6, 24),
        "D": date(2026, 6, 25),
        "E": date(2026, 6, 25),
        "F": date(2026, 6, 25),
        "G": date(2026, 6, 26),
        "H": date(2026, 6, 26),
        "I": date(2026, 6, 26),
        "J": date(2026, 6, 27),
        "K": date(2026, 6, 27),
        "L": date(2026, 6, 27),
    },
}

KNOCKOUT_STAGE_DAYS = {
    "round_of_32": [17, 18, 19, 20, 21, 22],
    "round_of_16": [23, 24, 25, 26],
    "quarter_finals": [28, 29, 30],
    "semi_finals": [33, 34],
    "third_place_match": [37],
    "final": [38],
}

DEFENDERS = {"LB", "CB", "RB", "LWB", "RWB"}
MIDFIELDERS = {"CDM", "CM", "CAM", "LM", "RM"}
FORWARDS = {"LW", "RW", "CF", "ST"}
WIDE_POSITIONS = {"LB", "RB", "LWB", "RWB", "LM", "RM", "LW", "RW"}
CENTRAL_POSITIONS = {"CB", "CDM", "CM", "CAM", "CF", "ST"}

FORMATION_REQUIREMENTS = [
    ("GK", lambda player: player["position"] == "GK", 1),
    ("DEF", lambda player: player["position"] in DEFENDERS, 4),
    ("MID", lambda player: player["position"] in MIDFIELDERS, 3),
    ("FWD", lambda player: player["position"] in FORWARDS, 3),
]

STAGE_ORDER = [
    "round_of_32",
    "round_of_16",
    "quarter_finals",
    "semi_finals",
    "final",
]

ROUND_OF_32_SLOTS = [
    (("W", "A"), ("T", ("C", "E", "F", "H", "I"))),
    (("R", "A"), ("R", "B")),
    (("W", "B"), ("T", ("E", "F", "G", "I", "J"))),
    (("W", "C"), ("R", "F")),
    (("W", "D"), ("T", ("B", "E", "F", "I", "J"))),
    (("R", "D"), ("R", "G")),
    (("W", "E"), ("T", ("A", "B", "C", "D", "F"))),
    (("R", "E"), ("R", "I")),
    (("W", "F"), ("R", "C")),
    (("W", "G"), ("T", ("A", "E", "H", "I", "J"))),
    (("W", "H"), ("R", "J")),
    (("W", "I"), ("T", ("C", "D", "F", "G", "H"))),
    (("W", "J"), ("R", "H")),
    (("W", "K"), ("T", ("D", "E", "I", "J", "L"))),
    (("R", "K"), ("R", "L")),
    (("W", "L"), ("T", ("E", "H", "I", "J", "K"))),
]


def clamp(value, low, high):
    return max(low, min(high, value))


def safe_float(value, default=0.0):
    if value is None:
        return default
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_div(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def logistic(value):
    return 1.0 / (1.0 + math.exp(-value))


def poisson(lam, rng):
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def weighted_choice(items, weight_fn, rng):
    if not items:
        return None
    weights = [max(0.001, float(weight_fn(item))) for item in items]
    total = sum(weights)
    pick = rng.random() * total
    running = 0.0
    for item, weight in zip(items, weights):
        running += weight
        if running >= pick:
            return item
    return items[-1]


def as_list(value):
    return value if isinstance(value, list) else []


def player_role(position):
    if position == "GK":
        return "gk"
    if position in DEFENDERS:
        return "defense"
    if position in MIDFIELDERS:
        return "midfield"
    if position in FORWARDS:
        return "attack"
    return "midfield"


def role_weight(position, role):
    if role == "attack":
        return {
            "GK": 0.0,
            "LB": 0.14,
            "CB": 0.08,
            "RB": 0.14,
            "LWB": 0.24,
            "RWB": 0.24,
            "CDM": 0.18,
            "CM": 0.35,
            "CAM": 0.70,
            "LM": 0.62,
            "RM": 0.62,
            "LW": 0.88,
            "RW": 0.88,
            "CF": 1.0,
            "ST": 1.0,
        }.get(position, 0.25)
    if role == "creation":
        return {
            "GK": 0.0,
            "LB": 0.25,
            "CB": 0.07,
            "RB": 0.25,
            "LWB": 0.40,
            "RWB": 0.40,
            "CDM": 0.35,
            "CM": 0.60,
            "CAM": 1.0,
            "LM": 0.80,
            "RM": 0.80,
            "LW": 0.75,
            "RW": 0.75,
            "CF": 0.48,
            "ST": 0.32,
        }.get(position, 0.35)
    if role == "defense":
        return {
            "GK": 0.35,
            "LB": 0.78,
            "CB": 1.0,
            "RB": 0.78,
            "LWB": 0.62,
            "RWB": 0.62,
            "CDM": 0.80,
            "CM": 0.45,
            "CAM": 0.18,
            "LM": 0.30,
            "RM": 0.30,
            "LW": 0.15,
            "RW": 0.15,
            "CF": 0.12,
            "ST": 0.10,
        }.get(position, 0.35)
    return 1.0


def scoring_weight(player):
    base = role_weight(player["position"], "attack")
    form = 1.0 + player.get("goals_per_90", 0.0) * 1.4 + player.get("assists_per_90", 0.0) * 0.35
    return base * max(0.25, (player["effective_rating"] - 54) / 35) * clamp(form, 0.55, 2.2)


def assist_weight(player):
    base = role_weight(player["position"], "creation")
    form = 1.0 + player.get("assists_per_90", 0.0) * 1.8 + player.get("goals_per_90", 0.0) * 0.25
    return base * max(0.25, (player["effective_rating"] - 54) / 35) * clamp(form, 0.55, 2.2)


def card_weight(player):
    return max(0.02, player.get("card_risk", 0.05) * (1.0 + player.get("fatigue", 0.0)))


def substitution_need(player):
    return player.get("fatigue", 0.0) * 1.8 + max(0.0, 72 - player.get("effective_rating", 68)) / 50


def extract_recent_stats(player):
    stats = player.get("player_statistics") or {}
    recent = stats.get("recent") or {}
    career = stats.get("career") or {}
    source = stats.get("source") or "none"
    confidence = safe_float(stats.get("confidence"), 0.35)
    appearances = safe_float(recent.get("appearances"), safe_float(career.get("appearances"), 0.0))
    minutes = safe_float(recent.get("minutes_played"), safe_float(career.get("minutes_played"), 0.0))
    goals = safe_float(recent.get("goals"), safe_float(career.get("goals"), safe_float(career.get("senior_goals"), 0.0)))
    assists = safe_float(recent.get("assists"), safe_float(career.get("assists"), 0.0))
    yellows = safe_float(recent.get("yellow_cards"), safe_float(career.get("yellow_cards"), 0.0))
    reds = safe_float(recent.get("red_cards"), safe_float(career.get("red_cards"), 0.0))
    clean_sheets = safe_float(recent.get("clean_sheets"), safe_float(career.get("clean_sheets"), 0.0))
    goals_conceded = safe_float(recent.get("goals_conceded"), safe_float(career.get("goals_conceded"), 0.0))
    per_90 = recent.get("per_90") or {}
    per_app = recent.get("per_appearance") or {}

    if minutes:
        goals_per_90 = goals * 90 / minutes
        assists_per_90 = assists * 90 / minutes
        card_per_90 = (yellows + reds) * 90 / minutes
    else:
        goals_per_90 = safe_float(per_90.get("goals"), 0.0)
        assists_per_90 = safe_float(per_90.get("assists"), 0.0)
        if not goals_per_90 and appearances:
            goals_per_90 = safe_float(per_app.get("goals"), 0.0) * 1.25
        if not assists_per_90 and appearances:
            assists_per_90 = safe_float(per_app.get("assists"), 0.0) * 1.25
        card_per_90 = safe_float(per_90.get("cards"), 0.0)
        if not card_per_90 and appearances:
            card_per_90 = (yellows + reds) / appearances * 1.25

    return {
        "source": source,
        "confidence": clamp(confidence, 0.15, 1.0),
        "appearances": appearances,
        "minutes": minutes,
        "goals": goals,
        "assists": assists,
        "goals_per_90": clamp(goals_per_90, 0.0, 1.5),
        "assists_per_90": clamp(assists_per_90, 0.0, 1.2),
        "card_per_90": clamp(card_per_90, 0.0, 1.2),
        "yellow_cards": yellows,
        "red_cards": reds,
        "clean_sheets": clean_sheets,
        "goals_conceded": goals_conceded,
    }


def performance_adjustment(position, rating, recent):
    minutes = recent["minutes"]
    appearances = recent["appearances"]
    availability = 0.0
    if minutes >= 1800 or appearances >= 24:
        availability = 1.2
    elif minutes >= 900 or appearances >= 12:
        availability = 0.65
    elif minutes >= 300 or appearances >= 5:
        availability = 0.25
    elif appearances <= 1 and minutes <= 90:
        availability = -0.35

    attack = recent["goals_per_90"] * 3.6 + recent["assists_per_90"] * 2.7
    discipline = -recent["card_per_90"] * 1.15
    confidence = recent["confidence"]
    role = player_role(position)

    if role == "gk":
        clean_bonus = safe_div(recent["clean_sheets"], appearances) or 0.0
        conceded_penalty = safe_div(recent["goals_conceded"], appearances) or 0.0
        raw = availability + clean_bonus * 1.3 - conceded_penalty * 0.18 + discipline
    elif role == "defense":
        clean_bonus = safe_div(recent["clean_sheets"], appearances) or 0.0
        raw = availability + attack * 0.35 + clean_bonus * 1.0 + discipline
    elif role == "midfield":
        raw = availability + attack * 0.70 + discipline
    else:
        raw = availability + attack * 1.00 + discipline * 0.65

    return clamp(raw * (0.55 + confidence * 0.45), -3.5, 4.0)


def build_player_model(player):
    rating = int(player.get("eafc_rating") or player.get("rating") or 68)
    recent = extract_recent_stats(player)
    position = player.get("position") or player.get("official_position") or "CM"
    adjustment = performance_adjustment(position, rating, recent)
    effective = clamp(rating + adjustment, 48, 96)
    card_risk = clamp(0.035 + recent["card_per_90"] * 0.35, 0.025, 0.40)
    foul_rate = clamp(0.55 + card_risk * 7.0 + (0.12 if position in DEFENDERS else 0.0), 0.35, 3.0)
    stamina = clamp(0.86 + min(recent["minutes"], 2400) / 12000 + (rating - 68) / 300, 0.75, 1.08)
    penalty_skill = clamp((effective - 55) / 40 + role_weight(position, "attack") * 0.55, 0.12, 1.25)
    return {
        "name": player.get("name"),
        "country": player.get("country"),
        "position": position,
        "base_rating": rating,
        "effective_rating": round(effective, 3),
        "performance_adjustment": round(adjustment, 3),
        "source": recent["source"],
        "source_confidence": recent["confidence"],
        "appearances": recent["appearances"],
        "minutes": recent["minutes"],
        "goals_per_90": recent["goals_per_90"],
        "assists_per_90": recent["assists_per_90"],
        "card_per_90": recent["card_per_90"],
        "card_risk": round(card_risk, 4),
        "foul_rate": round(foul_rate, 4),
        "stamina": round(stamina, 4),
        "penalty_skill": round(penalty_skill, 4),
    }


def select_best_lineup(players):
    remaining = sorted(players, key=lambda row: row["effective_rating"], reverse=True)
    selected = []

    def take(predicate, count):
        picked = []
        for player in list(remaining):
            if len(picked) >= count:
                break
            if predicate(player):
                picked.append(player)
                remaining.remove(player)
        return picked

    for _label, predicate, count in FORMATION_REQUIREMENTS:
        selected.extend(take(predicate, count))
    selected.extend(remaining[: max(0, 11 - len(selected))])
    selected = selected[:11]
    bench = [player for player in players if player["name"] not in {row["name"] for row in selected}]
    bench.sort(key=lambda row: row["effective_rating"], reverse=True)
    return selected, bench


def average(values, default=68.0):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else default


def weighted_average(players, weight_fn, field="effective_rating", default=68.0):
    total_weight = 0.0
    total = 0.0
    for player in players:
        weight = max(0.0, weight_fn(player))
        total += player[field] * weight
        total_weight += weight
    return total / total_weight if total_weight else default


def rank_to_estimated_elo(rank):
    rank = max(1.0, safe_float(rank, 999.0))
    return round(2170 - 130 * math.log(rank), 1)


def split_aliases(value):
    if not value:
        return []
    if isinstance(value, list):
        aliases = value
    else:
        aliases = str(value).replace(";", "|").split("|")
    return [str(alias).strip() for alias in aliases if str(alias).strip()]


def rating_from_metadata(row):
    if not isinstance(row, dict):
        return safe_float(row, 0.0), "elo"
    source_fields = [
        ("world_football_elo", "world_football_elo"),
        ("elo", row.get("rating_type") or "elo"),
        ("rating", row.get("rating_type") or "rating"),
        ("fifa_points", "fifa_points"),
        ("points", row.get("rating_type") or "points"),
    ]
    for field, rating_type in source_fields:
        value = safe_float(row.get(field), 0.0)
        if value > 0:
            return value, rating_type
    if row.get("fifa_rank") or row.get("rank"):
        return rank_to_estimated_elo(row.get("fifa_rank") or row.get("rank")), "fifa_rank_derived_elo"
    return 0.0, "missing"


def load_elo_ratings(path):
    path = Path(path)
    if not path.exists():
        return {}, "squad_proxy", {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("teams", data if isinstance(data, list) else {})
    ratings = {}
    metadata_by_team = {}
    if isinstance(rows, dict):
        for team, row in rows.items():
            metadata = row if isinstance(row, dict) else {}
            canonical_team = normalize_team_name(team)
            value, rating_type = rating_from_metadata(row)
            if value > 0:
                ratings[canonical_team] = safe_float(value, 0.0)
            metadata_by_team[canonical_team] = {**metadata, "rating_type": metadata.get("rating_type") or rating_type}
            for alias in split_aliases(metadata.get("aliases")):
                TEAM_NAME_ALIASES[alias] = canonical_team
                if value > 0:
                    ratings[normalize_team_name(alias)] = safe_float(value, 0.0)
                    metadata_by_team[normalize_team_name(alias)] = metadata_by_team[canonical_team]
    else:
        for row in rows:
            team = row.get("team") or row.get("country") or row.get("name")
            if team:
                canonical_team = normalize_team_name(team)
                value, rating_type = rating_from_metadata(row)
                if value > 0:
                    ratings[canonical_team] = safe_float(value, 0.0)
                metadata_by_team[canonical_team] = {**row, "rating_type": row.get("rating_type") or rating_type}
                for alias in split_aliases(row.get("aliases")):
                    TEAM_NAME_ALIASES[alias] = canonical_team
                    if value > 0:
                        ratings[normalize_team_name(alias)] = safe_float(value, 0.0)
                        metadata_by_team[normalize_team_name(alias)] = metadata_by_team[canonical_team]
    ratings = {team: value for team, value in ratings.items() if value > 0}
    return ratings, data.get("metadata", {}).get("source", "national_team_elo_ratings.json"), metadata_by_team


def build_team_profiles(elo_file=DEFAULT_ELO_FILE):
    performance = json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
    elo_ratings, elo_source, team_prior_metadata = load_elo_ratings(elo_file)
    profiles = {}
    for row in performance["players"]:
        country = row["country"]
        profiles.setdefault(country, {"players": []})
        profiles[country]["players"].append(build_player_model(row))

    for country, profile in profiles.items():
        players = profile["players"]
        lineup, bench = select_best_lineup(players)
        top_18 = sorted(players, key=lambda row: row["effective_rating"], reverse=True)[:18]
        squad_avg = average([row["effective_rating"] for row in players])
        top_11_avg = average([row["effective_rating"] for row in lineup])
        top_18_avg = average([row["effective_rating"] for row in top_18])
        squad_rating = 0.62 * top_11_avg + 0.28 * top_18_avg + 0.10 * squad_avg

        gks = [row for row in lineup if row["position"] == "GK"]
        defenders = [row for row in lineup if row["position"] in DEFENDERS]
        mids = [row for row in lineup if row["position"] in MIDFIELDERS]
        forwards = [row for row in lineup if row["position"] in FORWARDS]
        attack_score = 0.52 * weighted_average(forwards, lambda p: role_weight(p["position"], "attack")) + 0.30 * weighted_average(mids, lambda p: role_weight(p["position"], "attack")) + 0.18 * top_11_avg
        midfield_score = weighted_average(mids or lineup, lambda p: 1.0)
        defense_score = 0.55 * weighted_average(defenders, lambda p: role_weight(p["position"], "defense")) + 0.25 * average([row["effective_rating"] for row in gks]) + 0.20 * top_11_avg
        gk_score = average([row["effective_rating"] for row in gks], default=top_11_avg)
        possession_score = 0.48 * midfield_score + 0.22 * weighted_average(lineup, lambda p: 1.0 if p["position"] in WIDE_POSITIONS else 0.75) + 0.30 * squad_rating
        discipline_risk = average([row["card_risk"] for row in lineup], default=0.08)
        foul_rate = sum(row["foul_rate"] for row in lineup)
        data_confidence = average([row["source_confidence"] for row in players], default=0.6)
        real_elo = elo_ratings.get(country)
        prior_metadata = team_prior_metadata.get(country, {})
        if real_elo is None:
            real_elo = clamp(1350 + (squad_rating - 66) * 35, 1125, 2160)
        profile.update(
            {
                "lineup": lineup,
                "bench": bench,
                "squad_rating": round(squad_rating, 3),
                "average_rating": round(squad_avg, 3),
                "top_11_rating": round(top_11_avg, 3),
                "top_18_rating": round(top_18_avg, 3),
                "attack_score": round(attack_score, 3),
                "midfield_score": round(midfield_score, 3),
                "defense_score": round(defense_score, 3),
                "gk_score": round(gk_score, 3),
                "possession_score": round(possession_score, 3),
                "discipline_risk": round(discipline_risk, 4),
                "foul_rate": round(foul_rate, 3),
                "data_confidence": round(data_confidence, 3),
                "nt_elo": round(real_elo, 1),
                "elo_source": elo_source if country in elo_ratings else "squad_proxy",
                "fifa_rank": prior_metadata.get("fifa_rank"),
                "confederation": prior_metadata.get("confederation"),
            }
        )
    return profiles, elo_source


def day_index_from_date(match_date):
    return (match_date - TOURNAMENT_START_DATE).days


def group_fixture_date(group_name, matchday, pair_slot):
    if matchday == 1:
        return GROUP_MATCH_DATES[(matchday, group_name, pair_slot)]
    return GROUP_MATCHDAY_DATES[matchday][group_name]


def team_host_factor(team, stage, group_name=None):
    if team not in HOST_COUNTRIES:
        return 0.0
    if stage == "group":
        if team == "Mexico" and group_name == "A":
            return 1.0
        if team == "Canada" and group_name == "B":
            return 1.0
        if team == "United States" and group_name == "D":
            return 1.0
        return 0.65
    return 0.38


def altitude_factor(team, opponent, stage, group_name=None):
    if stage != "group" or group_name not in MEXICO_ALTITUDE_GROUPS:
        return 0.0
    if team == "Mexico":
        return 1.0
    if opponent == "Mexico":
        return -0.6
    return 0.0


def load_venue_context():
    global VENUE_CONTEXT_CACHE
    if VENUE_CONTEXT_CACHE is not None:
        return VENUE_CONTEXT_CACHE
    if not VENUE_CONTEXT_FILE.exists():
        VENUE_CONTEXT_CACHE = {}
        return VENUE_CONTEXT_CACHE
    VENUE_CONTEXT_CACHE = json.loads(VENUE_CONTEXT_FILE.read_text(encoding="utf-8"))
    return VENUE_CONTEXT_CACHE


def venue_context_for_match(stage, group_name=None):
    context = load_venue_context()
    if stage == "group" and group_name:
        return context.get("groups", {}).get(group_name, {})
    return context.get("knockout_stages", {}).get(stage, context.get("knockout_stages", {}).get("round_of_32", {}))


def travel_load_for_team(team, profiles, venue):
    if team in HOST_COUNTRIES:
        return 0.10
    confederation = profiles.get(team, {}).get("confederation") or "UEFA"
    region = venue.get("region", "multi_host")
    travel_table = load_venue_context().get("confederation_travel_load", {})
    return safe_float(travel_table.get(confederation, {}).get(region), 0.58)


def team_feature_row(match_id, stage, group_name, team, opponent, profiles, allow_draw, minute_scale, round_index, match_day_index=0):
    left = profiles[team]
    right = profiles[opponent]
    elo_diff = left["nt_elo"] - right["nt_elo"]
    venue = venue_context_for_match(stage, group_name)
    return {
        "match_id": match_id,
        "stage": stage,
        "round_index": round_index,
        "group": group_name,
        "team": team,
        "opponent": opponent,
        "allow_draw": allow_draw,
        "compressed_minutes": minute_scale,
        "match_day_index": match_day_index,
        "nt_elo": left["nt_elo"],
        "opponent_nt_elo": right["nt_elo"],
        "elo_diff": elo_diff,
        "squad_rating": left["squad_rating"],
        "opponent_squad_rating": right["squad_rating"],
        "squad_rating_diff": left["squad_rating"] - right["squad_rating"],
        "top_11_rating": left["top_11_rating"],
        "top_18_rating": left["top_18_rating"],
        "attack_score": left["attack_score"],
        "opponent_defense_score": right["defense_score"],
        "attack_vs_defense": left["attack_score"] - right["defense_score"],
        "defense_score": left["defense_score"],
        "opponent_attack_score": right["attack_score"],
        "defense_vs_attack": left["defense_score"] - right["attack_score"],
        "midfield_score": left["midfield_score"],
        "gk_score": left["gk_score"],
        "possession_score": left["possession_score"],
        "possession_diff": left["possession_score"] - right["possession_score"],
        "discipline_risk": left["discipline_risk"],
        "opponent_discipline_risk": right["discipline_risk"],
        "foul_rate": left["foul_rate"],
        "data_confidence": left["data_confidence"],
        "host_factor": team_host_factor(team, stage, group_name),
        "opponent_host_factor": team_host_factor(opponent, stage, group_name),
        "altitude_factor": altitude_factor(team, opponent, stage, group_name),
        "venue_region": venue.get("region"),
        "venue_altitude_m": venue.get("altitude_m", 0),
        "venue_heat_index": venue.get("heat_index", 0),
        "venue_humidity": venue.get("humidity", 0),
        "travel_load": travel_load_for_team(team, profiles, venue),
        "opponent_travel_load": travel_load_for_team(opponent, profiles, venue),
    }


def build_group_fixtures(structure):
    fixtures = []
    match_id = 1
    pairings = structure["group_stage"]["round_robin_pairings_by_seed"]
    for group_name, teams in structure["groups"].items():
        for pair_index, (left_seed, right_seed) in enumerate(pairings):
            matchday = pair_index // 2 + 1
            pair_slot = pair_index % 2
            match_date = group_fixture_date(group_name, matchday, pair_slot)
            fixtures.append(
                {
                    "match_id": match_id,
                    "stage": "group",
                    "group": group_name,
                    "team_a": teams[left_seed - 1],
                    "team_b": teams[right_seed - 1],
                    "matchday": matchday,
                    "match_date": match_date.isoformat(),
                    "day_index": day_index_from_date(match_date),
                    "allow_draw": True,
                }
            )
            match_id += 1
    fixtures.sort(key=lambda row: (row["day_index"], row["group"], row["match_id"]))
    for index, row in enumerate(fixtures, start=1):
        row["match_id"] = index
    return fixtures


def build_feature_dataframe(structure, profiles):
    rows = []
    for fixture in build_group_fixtures(structure):
        rows.append(
            team_feature_row(
                fixture["match_id"],
                "group",
                fixture["group"],
                fixture["team_a"],
                fixture["team_b"],
                profiles,
                True,
                9,
                fixture["matchday"],
                fixture["day_index"],
            )
        )
        rows.append(
            team_feature_row(
                fixture["match_id"],
                "group",
                fixture["group"],
                fixture["team_b"],
                fixture["team_a"],
                profiles,
                True,
                9,
                fixture["matchday"],
                fixture["day_index"],
            )
        )
    if pd is None:
        return rows
    return pd.DataFrame(rows)


def decision_forest_modifiers(features):
    """Small deterministic tree ensemble until a trained sklearn forest is available."""
    seed = int(abs(features["elo_diff"]) * 13 + abs(features["attack_diff"]) * 97 + abs(features["possession_diff"]) * 53)
    rng = random.Random(20260610 + seed)
    attack_votes = []
    tempo_votes = []
    discipline_votes = []
    possession_votes = []
    for _ in range(96):
        attack_vote = 0.0
        if features["elo_diff"] > rng.uniform(-190, 190):
            attack_vote += rng.uniform(0.015, 0.055)
        else:
            attack_vote -= rng.uniform(0.010, 0.045)
        if features["attack_diff"] > rng.uniform(-4.5, 4.5):
            attack_vote += rng.uniform(0.010, 0.060)
        if features["defense_diff"] < rng.uniform(-5.0, 5.0):
            attack_vote += rng.uniform(0.005, 0.040)
        attack_votes.append(attack_vote)

        tempo = 1.0
        if abs(features["elo_diff"]) < rng.uniform(40, 180):
            tempo += rng.uniform(0.00, 0.05)
        if features["attack_sum"] > rng.uniform(140, 156):
            tempo += rng.uniform(0.00, 0.05)
        if features["defense_sum"] > rng.uniform(145, 160):
            tempo -= rng.uniform(0.00, 0.04)
        tempo_votes.append(tempo)

        discipline = 1.0
        if features["discipline_diff"] > rng.uniform(-0.03, 0.03):
            discipline += rng.uniform(0.00, 0.08)
        else:
            discipline -= rng.uniform(0.00, 0.04)
        discipline_votes.append(discipline)

        possession = 0.0
        if features["possession_diff"] > rng.uniform(-3.5, 3.5):
            possession += rng.uniform(0.005, 0.030)
        else:
            possession -= rng.uniform(0.005, 0.030)
        possession_votes.append(possession)

    return {
        "attack_shift": clamp(sum(attack_votes) / len(attack_votes), -0.11, 0.14),
        "tempo_multiplier": clamp(sum(tempo_votes) / len(tempo_votes), 0.90, 1.12),
        "discipline_multiplier": clamp(sum(discipline_votes) / len(discipline_votes), 0.88, 1.18),
        "possession_shift": clamp(sum(possession_votes) / len(possession_votes), -0.05, 0.05),
    }


ML_FEATURE_NAMES = [
    "elo_diff",
    "squad_rating_diff",
    "attack_vs_defense",
    "defense_vs_attack",
    "midfield_diff",
    "gk_diff",
    "possession_diff",
    "discipline_diff",
    "data_confidence_diff",
    "host_diff",
    "rest_diff",
    "fatigue_diff",
    "lineup_replacements_diff",
    "altitude_factor",
    "travel_diff",
    "heat_index",
    "humidity",
    "venue_altitude_km",
    "stage_is_knockout",
    "allow_draw",
    "match_day_index",
]


def match_model_features(team_a, team_b, profiles, match_context=None):
    match_context = match_context or {}
    left = profiles[team_a]
    right = profiles[team_b]
    return {
        "elo_diff": left["nt_elo"] - right["nt_elo"],
        "squad_rating_diff": left["squad_rating"] - right["squad_rating"],
        "attack_vs_defense": left["attack_score"] - right["defense_score"],
        "defense_vs_attack": left["defense_score"] - right["attack_score"],
        "midfield_diff": left["midfield_score"] - right["midfield_score"],
        "gk_diff": left["gk_score"] - right["gk_score"],
        "possession_diff": left["possession_score"] - right["possession_score"],
        "discipline_diff": left["discipline_risk"] - right["discipline_risk"],
        "data_confidence_diff": left["data_confidence"] - right["data_confidence"],
        "host_diff": match_context.get("host_factor_a", 0.0) - match_context.get("host_factor_b", 0.0),
        "rest_diff": match_context.get("rest_days_a", 5) - match_context.get("rest_days_b", 5),
        "fatigue_diff": match_context.get("carry_fatigue_a", 0.0) - match_context.get("carry_fatigue_b", 0.0),
        "lineup_replacements_diff": match_context.get("lineup_replacements_a", 0) - match_context.get("lineup_replacements_b", 0),
        "altitude_factor": match_context.get("altitude_factor_a", 0.0),
        "travel_diff": match_context.get("travel_load_a", 0.0) - match_context.get("travel_load_b", 0.0),
        "heat_index": match_context.get("heat_index", 0.0),
        "humidity": match_context.get("humidity", 0.0),
        "venue_altitude_km": match_context.get("venue_altitude_m", 0.0) / 1000,
        "stage_is_knockout": 0.0 if match_context.get("allow_draw", True) else 1.0,
        "allow_draw": 1.0 if match_context.get("allow_draw", True) else 0.0,
        "match_day_index": match_context.get("match_day_index", 0),
    }


def feature_vector(feature_dict):
    return [float(feature_dict.get(name, 0.0)) for name in ML_FEATURE_NAMES]


def synthetic_outcome_probabilities(feature_dict):
    score = (
        feature_dict["elo_diff"] / 520
        + feature_dict["squad_rating_diff"] / 11
        + feature_dict["attack_vs_defense"] / 18
        + feature_dict["defense_vs_attack"] / 24
        + feature_dict["midfield_diff"] / 18
        + feature_dict["gk_diff"] / 42
        + feature_dict["host_diff"] * 0.22
        + feature_dict["rest_diff"] * 0.035
        - feature_dict["fatigue_diff"] * 0.30
        - feature_dict["lineup_replacements_diff"] * 0.08
        + feature_dict["altitude_factor"] * 0.12
    )
    win_share = logistic(score)
    draw_base = 0.31 if feature_dict["allow_draw"] else 0.18
    draw_probability = clamp(draw_base - abs(win_share - 0.5) * 0.38, 0.08, draw_base)
    non_draw = 1.0 - draw_probability
    return {
        "A": non_draw * win_share,
        "D": draw_probability,
        "B": non_draw * (1.0 - win_share),
    }


def add_jittered_training_row(rows, labels, base_features, rng):
    row = dict(base_features)
    row["elo_diff"] += rng.uniform(-45, 45)
    row["squad_rating_diff"] += rng.uniform(-1.8, 1.8)
    row["attack_vs_defense"] += rng.uniform(-2.5, 2.5)
    row["defense_vs_attack"] += rng.uniform(-2.5, 2.5)
    row["midfield_diff"] += rng.uniform(-2.2, 2.2)
    row["gk_diff"] += rng.uniform(-2.0, 2.0)
    row["possession_diff"] += rng.uniform(-3.0, 3.0)
    row["discipline_diff"] += rng.uniform(-0.018, 0.018)
    row["rest_diff"] += rng.choice([-1, 0, 1])
    row["travel_diff"] += rng.uniform(-0.08, 0.08)
    row["heat_index"] = clamp(row["heat_index"] + rng.uniform(-0.06, 0.06), 0.0, 1.0)
    row["humidity"] = clamp(row["humidity"] + rng.uniform(-0.05, 0.05), 0.0, 1.0)
    probabilities = synthetic_outcome_probabilities(row)
    labels.append(weighted_choice(list(probabilities), lambda label: probabilities[label], rng))
    rows.append(feature_vector(row))


def build_synthetic_training_data(structure, profiles, seed):
    rng = random.Random(seed + 7703)
    rows = []
    labels = []
    teams = sorted(profiles)
    contexts = [
        {"stage": "group", "allow_draw": True, "match_day_index": 4},
        {"stage": "group", "allow_draw": True, "match_day_index": 13},
        {"stage": "final", "allow_draw": False, "match_day_index": 38},
    ]
    group_by_team = {team: group for group, group_teams in structure["groups"].items() for team in group_teams}
    for team_a in teams:
        for team_b in teams:
            if team_a == team_b:
                continue
            group_name = group_by_team.get(team_a)
            for context in contexts:
                venue = venue_context_for_match(context["stage"], group_name)
                match_context = {
                    **context,
                    "host_factor_a": team_host_factor(team_a, context["stage"], group_name),
                    "host_factor_b": team_host_factor(team_b, context["stage"], group_name),
                    "rest_days_a": rng.choice([3, 4, 5, 6, 7]),
                    "rest_days_b": rng.choice([3, 4, 5, 6, 7]),
                    "carry_fatigue_a": rng.random() * 0.12,
                    "carry_fatigue_b": rng.random() * 0.12,
                    "lineup_replacements_a": rng.choice([0, 0, 0, 1]),
                    "lineup_replacements_b": rng.choice([0, 0, 0, 1]),
                    "altitude_factor_a": altitude_factor(team_a, team_b, context["stage"], group_name),
                    "travel_load_a": travel_load_for_team(team_a, profiles, venue),
                    "travel_load_b": travel_load_for_team(team_b, profiles, venue),
                    "heat_index": venue.get("heat_index", 0.0),
                    "humidity": venue.get("humidity", 0.0),
                    "venue_altitude_m": venue.get("altitude_m", 0.0),
                }
                base_features = match_model_features(team_a, team_b, profiles, match_context)
                add_jittered_training_row(rows, labels, base_features, rng)
    return rows, labels


TEAM_NAME_ALIASES = {
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "Cape Verde Islands": "Cape Verde",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Curacao": "Curacao",
    "Curaçao": "Curacao",
    "Czechia": "Czech Republic",
    "Czech Rep": "Czech Republic",
    "Czech Republic": "Czech Republic",
    "Democratic Republic of Congo": "DR Congo",
    "DR Congo": "DR Congo",
    "Korea Republic": "South Korea",
    "Republic of Ireland": "Ireland",
    "South Korea": "South Korea",
    "Türkiye": "Turkey",
    "Turkey": "Turkey",
    "USA": "United States",
    "United States of America": "United States",
}


def normalize_team_name(value):
    name = str(value).strip()
    if not name or name.lower() in {"nan", "none"}:
        return ""
    return TEAM_NAME_ALIASES.get(name, name)


def parse_boolish(value):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "neutral"}


def historical_context_from_row(row, columns, team_a, team_b, profiles):
    tournament_col = columns.get("tournament") or columns.get("competition") or columns.get("stage")
    neutral_col = columns.get("neutral")
    date_col = columns.get("date")
    tournament = str(row[tournament_col]).lower() if tournament_col else ""
    allow_draw = "world cup" not in tournament or "qualification" in tournament or "qualifier" in tournament
    match_day_index = 0
    if date_col:
        try:
            match_date = pd.to_datetime(row[date_col], errors="coerce")
            if match_date is not pd.NaT:
                match_day_index = int((match_date.date() - TOURNAMENT_START_DATE).days)
        except Exception:
            match_day_index = 0
    neutral = parse_boolish(row[neutral_col]) if neutral_col else True
    host_factor_a = 0.0 if neutral else team_host_factor(team_a, "historical")
    host_factor_b = 0.0 if neutral else team_host_factor(team_b, "historical")
    return {
        "stage": "historical",
        "allow_draw": allow_draw,
        "match_day_index": match_day_index,
        "host_factor_a": host_factor_a,
        "host_factor_b": host_factor_b,
        "rest_days_a": 5,
        "rest_days_b": 5,
        "carry_fatigue_a": 0.0,
        "carry_fatigue_b": 0.0,
        "lineup_replacements_a": 0,
        "lineup_replacements_b": 0,
        "altitude_factor_a": 0.0,
        "travel_load_a": 0.0,
        "travel_load_b": 0.0,
        "heat_index": 0.0,
        "humidity": 0.0,
    }


def read_historical_training_data(historical_matches_file, profiles):
    if not historical_matches_file or pd is None:
        return [], [], {"source_rows": 0, "usable_matches": 0, "skipped_rows": 0}
    path = Path(historical_matches_file)
    if not path.exists():
        return [], [], {"source_rows": 0, "usable_matches": 0, "skipped_rows": 0}
    frame = pd.read_csv(path)
    columns = {column.lower(): column for column in frame.columns}
    team_a_col = columns.get("team_a") or columns.get("home_team") or columns.get("team")
    team_b_col = columns.get("team_b") or columns.get("away_team") or columns.get("opponent")
    goals_a_col = columns.get("goals_a") or columns.get("home_goals") or columns.get("goals_for")
    goals_b_col = columns.get("goals_b") or columns.get("away_goals") or columns.get("goals_against")
    if not all([team_a_col, team_b_col, goals_a_col, goals_b_col]):
        return [], [], {"source_rows": len(frame), "usable_matches": 0, "skipped_rows": len(frame), "missing_columns": True}

    rows = []
    labels = []
    usable_matches = 0
    skipped_rows = 0
    for _, row in frame.iterrows():
        team_a = normalize_team_name(row[team_a_col])
        team_b = normalize_team_name(row[team_b_col])
        if team_a not in profiles or team_b not in profiles:
            skipped_rows += 1
            continue
        goals_a = safe_float(row[goals_a_col], None)
        goals_b = safe_float(row[goals_b_col], None)
        if goals_a is None or goals_b is None:
            skipped_rows += 1
            continue
        context = historical_context_from_row(row, columns, team_a, team_b, profiles)
        label = "A" if goals_a > goals_b else "B" if goals_b > goals_a else "D"
        rows.append(feature_vector(match_model_features(team_a, team_b, profiles, context)))
        labels.append(label)
        reverse_label = "A" if label == "B" else "B" if label == "A" else "D"
        rows.append(feature_vector(match_model_features(team_b, team_a, profiles, context)))
        labels.append(reverse_label)
        usable_matches += 1
    return rows, labels, {"source_rows": len(frame), "usable_matches": usable_matches, "skipped_rows": skipped_rows}


def build_match_model_bundle(structure, profiles, seed, mode="auto", historical_matches_file=None):
    if mode == "heuristic":
        return None, {"kind": "heuristic_internal_forest", "training_rows": 0, "sklearn_available": RandomForestClassifier is not None}
    if RandomForestClassifier is None:
        return None, {"kind": "heuristic_internal_forest", "training_rows": 0, "sklearn_available": False}

    historical_rows, historical_labels, historical_status = read_historical_training_data(historical_matches_file, profiles)
    synthetic_rows, synthetic_labels = [], []
    if len(set(historical_labels)) >= 3 and len(historical_labels) >= 300:
        rows, labels = historical_rows, historical_labels
        training_source = "historical_csv"
    else:
        synthetic_rows, synthetic_labels = build_synthetic_training_data(structure, profiles, seed)
        rows, labels = historical_rows + synthetic_rows, historical_labels + synthetic_labels
        training_source = "historical_plus_synthetic_calibration" if historical_rows else "synthetic_profile_calibration"

    model = RandomForestClassifier(
        n_estimators=96,
        max_depth=8,
        min_samples_leaf=6,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=1,
    )
    model.fit(rows, labels)
    training_accuracy = round(float(model.score(rows, labels)), 4) if labels else None
    status = {
        "kind": "sklearn_random_forest",
        "training_source": training_source,
        "training_rows": len(labels),
        "training_accuracy": training_accuracy,
        "historical_rows": len(historical_labels),
        "historical_status": historical_status,
        "synthetic_rows": len(synthetic_labels),
        "features": ML_FEATURE_NAMES,
        "sklearn_available": True,
    }
    return {"model": model, "feature_names": ML_FEATURE_NAMES, "status": status}, status


def random_forest_probabilities(model_bundle, feature_dict):
    if not model_bundle:
        return None
    model = model_bundle["model"]
    probabilities = model.predict_proba([feature_vector(feature_dict)])[0]
    return {label: float(probability) for label, probability in zip(model.classes_, probabilities)}


def expected_goal_model(team_a, team_b, profiles, match_context=None, model_bundle=None):
    match_context = match_context or {}
    left = profiles[team_a]
    right = profiles[team_b]
    elo_diff = left["nt_elo"] - right["nt_elo"]
    rating_diff = left["squad_rating"] - right["squad_rating"]
    attack_diff = left["attack_score"] - right["defense_score"]
    defense_diff = left["defense_score"] - right["attack_score"]
    possession_diff = left["possession_score"] - right["possession_score"]
    features = {
        "elo_diff": elo_diff,
        "attack_diff": attack_diff,
        "defense_diff": defense_diff,
        "attack_sum": left["attack_score"] + right["attack_score"],
        "defense_sum": left["defense_score"] + right["defense_score"],
        "possession_diff": possession_diff,
        "discipline_diff": left["discipline_risk"] - right["discipline_risk"],
    }
    forest = decision_forest_modifiers(features)
    travel_diff = match_context.get("travel_load_a", 0.0) - match_context.get("travel_load_b", 0.0)
    heat_index = match_context.get("heat_index", 0.0)
    humidity = match_context.get("humidity", 0.0)
    context_shift = (
        (match_context.get("host_factor_a", 0.0) - match_context.get("host_factor_b", 0.0)) * 0.24
        + (match_context.get("rest_days_a", 5) - match_context.get("rest_days_b", 5)) * 0.035
        - (match_context.get("carry_fatigue_a", 0.0) - match_context.get("carry_fatigue_b", 0.0)) * 0.30
        - (match_context.get("lineup_replacements_a", 0) - match_context.get("lineup_replacements_b", 0)) * 0.08
        + match_context.get("altitude_factor_a", 0.0) * 0.12
        - travel_diff * 0.16
    )
    strength = elo_diff / 430 + rating_diff / 9.5 + attack_diff / 13.0 - defense_diff / 18.0 + context_shift
    base_share_a = clamp(logistic(strength + forest["attack_shift"]), 0.18, 0.82)
    climate_tempo = 1.0 - heat_index * 0.055 - humidity * 0.025
    total_goals = clamp((2.55 * forest["tempo_multiplier"] + (left["attack_score"] + right["attack_score"] - 145) * 0.015) * climate_tempo, 1.55, 3.65)
    model_features = match_model_features(team_a, team_b, profiles, match_context)
    rf_probabilities = random_forest_probabilities(model_bundle, model_features)
    if rf_probabilities:
        decisive_total = max(0.01, rf_probabilities.get("A", 0.0) + rf_probabilities.get("B", 0.0))
        rf_share_a = rf_probabilities.get("A", 0.0) / decisive_total
        share_a = clamp(base_share_a * 0.72 + rf_share_a * 0.28, 0.16, 0.84)
        draw_probability = rf_probabilities.get("D", 0.0)
        total_goals = clamp(total_goals * (1.04 - draw_probability * 0.30), 1.55, 3.80)
        forest["sklearn_random_forest"] = {
            "p_team_a_win": round(rf_probabilities.get("A", 0.0), 4),
            "p_draw": round(draw_probability, 4),
            "p_team_b_win": round(rf_probabilities.get("B", 0.0), 4),
        }
    else:
        share_a = base_share_a
    xg_a = clamp(total_goals * share_a, 0.20, 3.3)
    xg_b = clamp(total_goals * (1.0 - share_a), 0.20, 3.3)
    possession_a = clamp(0.50 + possession_diff / 60 + forest["possession_shift"], 0.35, 0.65)
    return xg_a, xg_b, possession_a, forest


def copy_player(player):
    row = dict(player)
    row["fatigue"] = 0.0
    row["match_yellows"] = 0
    row["sent_off"] = False
    return row


def rest_team_state(team_state, rest_days):
    rest_days = max(0, rest_days)
    carry = team_state.setdefault("carry_fatigue", {})
    for name in list(carry):
        carry[name] = max(0.0, carry[name] - rest_days * 0.16)
        if carry[name] <= 0.01:
            del carry[name]


def initialize_match_team(country, profile, tournament_state, current_day):
    state = tournament_state[country]
    last_day = state.get("last_day")
    rest_days = 5 if last_day is None else max(1, current_day - last_day)
    rest_team_state(state, rest_days)
    suspended = {name for name, matches in state.get("suspensions", {}).items() if matches > 0}
    lineup_names = {row["name"] for row in profile["lineup"]}
    pool = [row for row in profile["lineup"] + profile["bench"] if row["name"] not in suspended]
    active = []
    for row in profile["lineup"]:
        if row["name"] not in suspended:
            active.append(copy_player(row))
    for row in pool:
        if len(active) >= 11:
            break
        if row["name"] not in {player["name"] for player in active}:
            active.append(copy_player(row))
    if len(active) < 11:
        for row in profile["players"]:
            if len(active) >= 11:
                break
            if row["name"] not in suspended and row["name"] not in {player["name"] for player in active}:
                active.append(copy_player(row))
    bench = [copy_player(row) for row in pool if row["name"] not in {player["name"] for player in active}]
    for player in active:
        player["fatigue"] = state.get("carry_fatigue", {}).get(player["name"], 0.0)
    return {
        "country": country,
        "active": active,
        "bench": bench,
        "substitutions": 0,
        "max_substitutions": 5,
        "new_suspensions": set(),
        "yellow_counts": Counter(),
        "rest_days": rest_days,
        "lineup_replacements": len([name for name in lineup_names if name in suspended]),
    }


def active_average_fatigue(match_team):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    return average([player.get("fatigue", 0.0) for player in active], default=0.0)


def build_match_context(team_a, team_b, profiles, stage, group_name, allow_draw, current_day, state_a, state_b, rng):
    referee_strictness = clamp(rng.gauss(1.0, 0.10), 0.78, 1.28)
    venue = venue_context_for_match(stage, group_name)
    context = {
        "stage": stage,
        "group": group_name,
        "allow_draw": allow_draw,
        "match_day_index": current_day,
        "host_factor_a": team_host_factor(team_a, stage, group_name),
        "host_factor_b": team_host_factor(team_b, stage, group_name),
        "altitude_factor_a": altitude_factor(team_a, team_b, stage, group_name),
        "rest_days_a": state_a["rest_days"],
        "rest_days_b": state_b["rest_days"],
        "carry_fatigue_a": active_average_fatigue(state_a),
        "carry_fatigue_b": active_average_fatigue(state_b),
        "lineup_replacements_a": state_a["lineup_replacements"],
        "lineup_replacements_b": state_b["lineup_replacements"],
        "referee_strictness": referee_strictness,
        "venue_region": venue.get("region"),
        "venue_altitude_m": venue.get("altitude_m", 0.0),
        "heat_index": venue.get("heat_index", 0.0),
        "humidity": venue.get("humidity", 0.0),
        "travel_load_a": travel_load_for_team(team_a, profiles, venue),
        "travel_load_b": travel_load_for_team(team_b, profiles, venue),
    }
    return context


def active_strength(match_team, role=None):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    if not active:
        return 45.0
    if role == "attack":
        return weighted_average(active, lambda p: role_weight(p["position"], "attack"))
    if role == "defense":
        return weighted_average(active, lambda p: role_weight(p["position"], "defense"))
    if role == "midfield":
        mids = [player for player in active if player["position"] in MIDFIELDERS]
        return average([player["effective_rating"] for player in mids or active])
    fatigue_penalty = average([player.get("fatigue", 0.0) for player in active], 0.0) * 5.0
    red_penalty = max(0, 11 - len(active)) * 2.6
    return average([player["effective_rating"] for player in active]) - fatigue_penalty - red_penalty


def apply_fatigue(match_team, extra_time=False, climate_load=0.0):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    red_load = max(0, 11 - len(active)) * 0.012
    for player in active:
        increment = ((0.082 if not extra_time else 0.115) * (1.0 + climate_load)) / max(0.78, player.get("stamina", 0.9)) + red_load
        player["fatigue"] = clamp(player.get("fatigue", 0.0) + increment, 0.0, 1.0)


def find_bench_replacement(match_team, outgoing):
    if not match_team["bench"]:
        return None
    role = player_role(outgoing["position"])
    preferred = [player for player in match_team["bench"] if player_role(player["position"]) == role]
    if not preferred and outgoing["position"] in WIDE_POSITIONS:
        preferred = [player for player in match_team["bench"] if player["position"] in WIDE_POSITIONS]
    if not preferred and outgoing["position"] in CENTRAL_POSITIONS:
        preferred = [player for player in match_team["bench"] if player["position"] in CENTRAL_POSITIONS]
    candidates = preferred or match_team["bench"]
    replacement = max(candidates, key=lambda player: player["effective_rating"])
    match_team["bench"].remove(replacement)
    replacement = copy_player(replacement)
    replacement["fatigue"] = 0.0
    return replacement


def maybe_substitute(match_team, tick, event_stats, extra_time=False, urgency=0.0):
    if match_team["substitutions"] >= match_team["max_substitutions"]:
        return
    early_window = 5 if urgency > 0 else 6
    if tick < early_window and not extra_time:
        return
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    if not active or not match_team["bench"]:
        return
    outgoing = max(active, key=substitution_need)
    threshold = (0.74 if not extra_time else 0.64) - urgency * 0.07
    if substitution_need(outgoing) < threshold and match_team["substitutions"] >= 3:
        return
    replacement = find_bench_replacement(match_team, outgoing)
    if replacement is None:
        return
    match_team["active"].remove(outgoing)
    match_team["active"].append(replacement)
    match_team["substitutions"] += 1
    event_stats[match_team["country"]]["substitutions"] += 1
    if urgency > 0:
        event_stats[match_team["country"]]["chasing_substitutions"] += 1


def send_off(match_team, player, event_stats, second_yellow=False):
    if player.get("sent_off"):
        return
    player["sent_off"] = True
    if player in match_team["active"]:
        match_team["active"].remove(player)
    match_team["new_suspensions"].add(player["name"])
    if second_yellow:
        event_stats[match_team["country"]]["second_yellow_reds"] += 1
    else:
        event_stats[match_team["country"]]["direct_reds"] += 1
    event_stats[match_team["country"]]["red_cards"] += 1


def process_fouls(match_team, opponent, rng, event_stats, tick_scale=1.0, referee_strictness=1.0):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    if not active:
        return 0
    team_foul_lambda = sum(player["foul_rate"] for player in active) / 9.0 * tick_scale * referee_strictness
    fouls = poisson(clamp(team_foul_lambda, 0.0, 3.2), rng)
    event_stats[match_team["country"]]["fouls"] += fouls
    for _ in range(fouls):
        offender = weighted_choice(active, card_weight, rng)
        if offender is None:
            continue
        yellow_probability = clamp((0.075 + offender["card_risk"] * 0.42) * referee_strictness, 0.035, 0.34)
        direct_red_probability = clamp((0.004 + offender["card_risk"] * 0.025) * referee_strictness, 0.0015, 0.035)
        roll = rng.random()
        if roll < direct_red_probability:
            send_off(match_team, offender, event_stats, second_yellow=False)
            active = [player for player in match_team["active"] if not player.get("sent_off")]
        elif roll < direct_red_probability + yellow_probability:
            offender["match_yellows"] += 1
            match_team["yellow_counts"][offender["name"]] += 1
            event_stats[match_team["country"]]["yellow_cards"] += 1
            if offender["match_yellows"] >= 2:
                send_off(match_team, offender, event_stats, second_yellow=True)
                active = [player for player in match_team["active"] if not player.get("sent_off")]
    set_pieces = 0
    if fouls and rng.random() < 0.35:
        event_stats[opponent["country"]]["set_piece_possessions"] += 1
        set_pieces = 1
    return set_pieces


def allocate_goal(match_team, rng, player_stats, include_assist=True):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    scorer = weighted_choice(active, scoring_weight, rng)
    if scorer is None:
        return None
    key = f"{match_team['country']}::{scorer['name']}"
    player_stats[key]["team"] = match_team["country"]
    player_stats[key]["name"] = scorer["name"]
    player_stats[key]["position"] = scorer["position"]
    player_stats[key]["goals"] += 1
    if include_assist and rng.random() < 0.70 and len(active) > 1:
        assister = weighted_choice([player for player in active if player["name"] != scorer["name"]], assist_weight, rng)
        if assister is not None:
            assist_key = f"{match_team['country']}::{assister['name']}"
            player_stats[assist_key]["team"] = match_team["country"]
            player_stats[assist_key]["name"] = assister["name"]
            player_stats[assist_key]["position"] = assister["position"]
            player_stats[assist_key]["assists"] += 1
    return scorer


def score_state_multiplier(goals_for, goals_against, tick, ticks, extra_time=False):
    late = (tick + 1) / max(1, ticks)
    if goals_for < goals_against:
        return clamp(1.05 + late * (0.18 if not extra_time else 0.24), 1.05, 1.30)
    if goals_for > goals_against:
        return clamp(0.96 - late * (0.12 if not extra_time else 0.16), 0.78, 0.94)
    if extra_time and late > 0.65:
        return 0.93
    return 1.0


def record_score_state(event_stats, team_state, goals_for, goals_against):
    if goals_for < goals_against:
        event_stats[team_state["country"]]["chasing_ticks"] += 1
    elif goals_for > goals_against:
        event_stats[team_state["country"]]["protecting_ticks"] += 1


def maybe_score_set_piece(attacking_team, defending_team, rng, event_stats, player_stats):
    attack = active_strength(attacking_team, "attack")
    defense = active_strength(defending_team, "defense")
    chance = clamp(0.042 + (attack - defense) / 480 + attacking_team["substitutions"] * 0.002, 0.018, 0.095)
    if rng.random() >= chance:
        return 0
    event_stats[attacking_team["country"]]["goals"] += 1
    event_stats[attacking_team["country"]]["set_piece_goals"] += 1
    allocate_goal(attacking_team, rng, player_stats)
    return 1


def simulate_period(team_a_state, team_b_state, base_xg_a, base_xg_b, possession_a, ticks, rng, event_stats, player_stats, extra_time=False, match_context=None):
    match_context = match_context or {}
    goals_a = 0
    goals_b = 0
    possession = "A" if rng.random() < possession_a else "B"
    scale = ticks / 9.0
    referee_strictness = match_context.get("referee_strictness", 1.0)
    climate_load = match_context.get("heat_index", 0.0) * 0.10 + match_context.get("humidity", 0.0) * 0.04
    for tick in range(ticks):
        a_strength = active_strength(team_a_state)
        b_strength = active_strength(team_b_state)
        a_attack = active_strength(team_a_state, "attack")
        b_attack = active_strength(team_b_state, "attack")
        a_defense = active_strength(team_a_state, "defense")
        b_defense = active_strength(team_b_state, "defense")
        record_score_state(event_stats, team_a_state, goals_a, goals_b)
        record_score_state(event_stats, team_b_state, goals_b, goals_a)

        if possession == "A":
            event_stats[team_a_state["country"]]["possession_ticks"] += 1
            chance = base_xg_a / max(1, ticks) * clamp((a_attack - b_defense) / 32 + (a_strength - b_strength) / 55 + 1.0, 0.45, 1.75)
            chance *= score_state_multiplier(goals_a, goals_b, tick, ticks, extra_time=extra_time)
            chance = clamp(chance, 0.01, 0.48)
            if rng.random() < chance:
                goals_a += 1
                event_stats[team_a_state["country"]]["goals"] += 1
                allocate_goal(team_a_state, rng, player_stats)
                possession = "B"
            elif rng.random() < 0.52 - (possession_a - 0.5) * 0.25:
                possession = "B"
        else:
            event_stats[team_b_state["country"]]["possession_ticks"] += 1
            chance = base_xg_b / max(1, ticks) * clamp((b_attack - a_defense) / 32 + (b_strength - a_strength) / 55 + 1.0, 0.45, 1.75)
            chance *= score_state_multiplier(goals_b, goals_a, tick, ticks, extra_time=extra_time)
            chance = clamp(chance, 0.01, 0.48)
            if rng.random() < chance:
                goals_b += 1
                event_stats[team_b_state["country"]]["goals"] += 1
                allocate_goal(team_b_state, rng, player_stats)
                possession = "A"
            elif rng.random() < 0.52 + (possession_a - 0.5) * 0.25:
                possession = "A"

        # Defending teams commit most fouls, but the attacking team can foul too.
        if possession == "A":
            set_pieces = process_fouls(team_b_state, team_a_state, rng, event_stats, tick_scale=scale * 1.05, referee_strictness=referee_strictness)
            if set_pieces:
                goals_a += maybe_score_set_piece(team_a_state, team_b_state, rng, event_stats, player_stats)
            if rng.random() < 0.38:
                set_pieces = process_fouls(team_a_state, team_b_state, rng, event_stats, tick_scale=scale * 0.45, referee_strictness=referee_strictness)
                if set_pieces:
                    goals_b += maybe_score_set_piece(team_b_state, team_a_state, rng, event_stats, player_stats)
        else:
            set_pieces = process_fouls(team_a_state, team_b_state, rng, event_stats, tick_scale=scale * 1.05, referee_strictness=referee_strictness)
            if set_pieces:
                goals_b += maybe_score_set_piece(team_b_state, team_a_state, rng, event_stats, player_stats)
            if rng.random() < 0.38:
                set_pieces = process_fouls(team_b_state, team_a_state, rng, event_stats, tick_scale=scale * 0.45, referee_strictness=referee_strictness)
                if set_pieces:
                    goals_a += maybe_score_set_piece(team_a_state, team_b_state, rng, event_stats, player_stats)

        apply_fatigue(team_a_state, extra_time=extra_time, climate_load=climate_load + match_context.get("travel_load_a", 0.0) * 0.025)
        apply_fatigue(team_b_state, extra_time=extra_time, climate_load=climate_load + match_context.get("travel_load_b", 0.0) * 0.025)
        maybe_substitute(team_a_state, tick, event_stats, extra_time=extra_time, urgency=max(0, goals_b - goals_a))
        maybe_substitute(team_b_state, tick, event_stats, extra_time=extra_time, urgency=max(0, goals_a - goals_b))
    return goals_a, goals_b


def penalty_shootout(team_a_state, team_b_state, profiles, rng, player_stats):
    def shooter_pool(match_team):
        active = [player for player in match_team["active"] if not player.get("sent_off")]
        return sorted(active, key=lambda player: player["penalty_skill"] - player.get("fatigue", 0.0) * 0.25, reverse=True)[:5]

    def keeper_score(match_team, country):
        keepers = [player for player in match_team["active"] if player["position"] == "GK"]
        if keepers:
            return keepers[0]["effective_rating"]
        return profiles[country]["gk_score"]

    pool_a = shooter_pool(team_a_state)
    pool_b = shooter_pool(team_b_state)
    gk_a = keeper_score(team_a_state, team_a_state["country"])
    gk_b = keeper_score(team_b_state, team_b_state["country"])
    score_a = 0
    score_b = 0

    def take_penalty(shooter, opposing_gk, pressure):
        skill = shooter["penalty_skill"] if shooter else 0.5
        fatigue = shooter.get("fatigue", 0.0) if shooter else 0.5
        p = 0.735 + skill * 0.11 - (opposing_gk - 70) * 0.004 - fatigue * 0.055 - pressure
        return rng.random() < clamp(p, 0.54, 0.89)

    for index in range(5):
        pressure = index * 0.006
        if take_penalty(pool_a[index % len(pool_a)] if pool_a else None, gk_b, pressure):
            score_a += 1
        if take_penalty(pool_b[index % len(pool_b)] if pool_b else None, gk_a, pressure):
            score_b += 1
    sudden = 0
    while score_a == score_b and sudden < 10:
        shooter_a = pool_a[sudden % len(pool_a)] if pool_a else None
        shooter_b = pool_b[sudden % len(pool_b)] if pool_b else None
        made_a = take_penalty(shooter_a, gk_b, 0.04)
        made_b = take_penalty(shooter_b, gk_a, 0.04)
        score_a += int(made_a)
        score_b += int(made_b)
        sudden += 1
    if score_a == score_b:
        elo_a = profiles[team_a_state["country"]]["nt_elo"]
        elo_b = profiles[team_b_state["country"]]["nt_elo"]
        p_a = clamp(0.5 + (elo_a - elo_b) / 1200, 0.35, 0.65)
        winner = team_a_state["country"] if rng.random() < p_a else team_b_state["country"]
    else:
        winner = team_a_state["country"] if score_a > score_b else team_b_state["country"]
    return winner, score_a, score_b


def finalize_match_team(match_team, tournament_state):
    country = match_team["country"]
    state = tournament_state[country]
    suspensions = state.setdefault("suspensions", {})
    for name in list(suspensions):
        suspensions[name] -= 1
        if suspensions[name] <= 0:
            del suspensions[name]
    for name in match_team["new_suspensions"]:
        suspensions[name] = max(suspensions.get(name, 0), 1)

    yellow_bank = state.setdefault("yellow_bank", Counter())
    for name, count in match_team["yellow_counts"].items():
        yellow_bank[name] += count
        if yellow_bank[name] >= 2:
            suspensions[name] = max(suspensions.get(name, 0), 1)
            yellow_bank[name] = 0

    carry = state.setdefault("carry_fatigue", {})
    for player in match_team["active"]:
        carry[player["name"]] = max(carry.get(player["name"], 0.0), player.get("fatigue", 0.0) * 0.35)


def simulate_match(team_a, team_b, profiles, rng, tournament_state, allow_draw, current_day, player_stats, stage="group", group_name=None, model_bundle=None):
    state_a = initialize_match_team(team_a, profiles[team_a], tournament_state, current_day)
    state_b = initialize_match_team(team_b, profiles[team_b], tournament_state, current_day)
    match_context = build_match_context(team_a, team_b, profiles, stage, group_name, allow_draw, current_day, state_a, state_b, rng)
    xg_a, xg_b, possession_a, forest = expected_goal_model(team_a, team_b, profiles, match_context=match_context, model_bundle=model_bundle)
    event_stats = defaultdict(Counter)
    event_stats[team_a]["xg_model"] += xg_a
    event_stats[team_b]["xg_model"] += xg_b
    event_stats[team_a]["rest_days"] += match_context["rest_days_a"]
    event_stats[team_b]["rest_days"] += match_context["rest_days_b"]
    event_stats[team_a]["host_factor"] += match_context["host_factor_a"]
    event_stats[team_b]["host_factor"] += match_context["host_factor_b"]
    event_stats[team_a]["lineup_replacements"] += match_context["lineup_replacements_a"]
    event_stats[team_b]["lineup_replacements"] += match_context["lineup_replacements_b"]
    event_stats[team_a]["referee_strictness"] += match_context["referee_strictness"]
    event_stats[team_b]["referee_strictness"] += match_context["referee_strictness"]
    event_stats[team_a]["kickoffs"] += 1

    goals_a, goals_b = simulate_period(state_a, state_b, xg_a, xg_b, possession_a, 9, rng, event_stats, player_stats, match_context=match_context)
    resolution = "regular_time"
    winner = None
    penalty_score = None

    if not allow_draw and goals_a == goals_b:
        resolution = "extra_time"
        et_a, et_b = simulate_period(state_a, state_b, xg_a * 0.33, xg_b * 0.33, possession_a, 3, rng, event_stats, player_stats, extra_time=True, match_context=match_context)
        goals_a += et_a
        goals_b += et_b
        if goals_a == goals_b:
            resolution = "penalties"
            winner, pens_a, pens_b = penalty_shootout(state_a, state_b, profiles, rng, player_stats)
            penalty_score = {team_a: pens_a, team_b: pens_b}

    if winner is None and goals_a != goals_b:
        winner = team_a if goals_a > goals_b else team_b

    finalize_match_team(state_a, tournament_state)
    finalize_match_team(state_b, tournament_state)
    tournament_state[team_a]["last_day"] = current_day
    tournament_state[team_b]["last_day"] = current_day

    return {
        "team_a": team_a,
        "team_b": team_b,
        "goals_a": goals_a,
        "goals_b": goals_b,
        "winner": winner,
        "resolution": resolution,
        "penalty_score": penalty_score,
        "event_stats": {team: dict(counter) for team, counter in event_stats.items()},
        "forest": forest,
        "context": match_context,
    }


def blank_table(group):
    return {
        team: {
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
            "fair_play_points": 0,
        }
        for team in group
    }


def record_result(table, team_a, team_b, goals_a, goals_b, event_stats):
    row_a = table[team_a]
    row_b = table[team_b]
    row_a["played"] += 1
    row_b["played"] += 1
    row_a["goals_for"] += goals_a
    row_a["goals_against"] += goals_b
    row_b["goals_for"] += goals_b
    row_b["goals_against"] += goals_a
    row_a["goal_difference"] = row_a["goals_for"] - row_a["goals_against"]
    row_b["goal_difference"] = row_b["goals_for"] - row_b["goals_against"]
    if goals_a > goals_b:
        row_a["wins"] += 1
        row_b["losses"] += 1
        row_a["points"] += 3
    elif goals_b > goals_a:
        row_b["wins"] += 1
        row_a["losses"] += 1
        row_b["points"] += 3
    else:
        row_a["draws"] += 1
        row_b["draws"] += 1
        row_a["points"] += 1
        row_b["points"] += 1

    for team in (team_a, team_b):
        stats = event_stats.get(team, {})
        fair_play = -stats.get("yellow_cards", 0) - 3 * stats.get("second_yellow_reds", 0) - 4 * stats.get("direct_reds", 0)
        table[team]["fair_play_points"] += fair_play


def head_to_head_rows(teams, match_results):
    rows = {
        team: {"points": 0, "goal_difference": 0, "goals_for": 0}
        for team in teams
    }
    team_set = set(teams)
    for result in match_results or []:
        team_a = result["team_a"]
        team_b = result["team_b"]
        if team_a not in team_set or team_b not in team_set:
            continue
        goals_a = result["goals_a"]
        goals_b = result["goals_b"]
        rows[team_a]["goals_for"] += goals_a
        rows[team_b]["goals_for"] += goals_b
        rows[team_a]["goal_difference"] += goals_a - goals_b
        rows[team_b]["goal_difference"] += goals_b - goals_a
        if goals_a > goals_b:
            rows[team_a]["points"] += 3
        elif goals_b > goals_a:
            rows[team_b]["points"] += 3
        else:
            rows[team_a]["points"] += 1
            rows[team_b]["points"] += 1
    return rows


def partition_by_head_to_head(teams, match_results):
    if len(teams) <= 1:
        return [teams]
    rows = head_to_head_rows(teams, match_results)
    grouped = defaultdict(list)
    for team in teams:
        row = rows[team]
        grouped[(row["points"], row["goal_difference"], row["goals_for"])].append(team)
    if len(grouped) == 1:
        return [teams]
    partitions = []
    for _, group in sorted(grouped.items(), key=lambda item: item[0], reverse=True):
        if len(group) == 1:
            partitions.append(group)
        else:
            partitions.extend(partition_by_head_to_head(group, match_results))
    return partitions


def rank_overall_subset(teams, table, profiles, rng):
    rng.shuffle(teams)
    return sorted(
        teams,
        key=lambda team: (
            table[team]["goal_difference"],
            table[team]["goals_for"],
            table[team]["fair_play_points"],
            profiles[team]["nt_elo"],
        ),
        reverse=True,
    )


def rank_table(table, profiles, rng, match_results=None):
    teams = list(table)
    rng.shuffle(teams)
    point_groups = defaultdict(list)
    for team in teams:
        point_groups[table[team]["points"]].append(team)

    ranked = []
    for _, tied_teams in sorted(point_groups.items(), key=lambda item: item[0], reverse=True):
        if len(tied_teams) == 1:
            ranked.extend(tied_teams)
            continue
        for partition in partition_by_head_to_head(tied_teams, match_results):
            ranked.extend(rank_overall_subset(partition, table, profiles, rng))
    return ranked


def merge_counter_dict(target, source):
    for key, value in source.items():
        target[key] += value


def stage_display_name(stage_key):
    return {
        "round_of_32": "Round of 32",
        "round_of_16": "Round of 16",
        "quarter_finals": "Quarter-finals",
        "semi_finals": "Semi-finals",
        "final": "Final",
        "third_place_match": "Third-place match",
    }.get(stage_key, stage_key.replace("_", " ").title())


def event_value(result, team, key, default=0):
    return result.get("event_stats", {}).get(team, {}).get(key, default)


def append_match_trace(trace, label, result):
    team_a = result["team_a"]
    team_b = result["team_b"]
    goals_a = result["goals_a"]
    goals_b = result["goals_b"]
    resolution = result["resolution"]
    suffix = "FT"
    if resolution == "extra_time":
        suffix = "AET"
    elif resolution == "penalties":
        pens = result.get("penalty_score") or {}
        suffix = f"pens {pens.get(team_a, 0)}-{pens.get(team_b, 0)}, winner {result['winner']}"
    elif result.get("winner") is None:
        suffix = "draw"

    trace.append(f"{label}: {team_a} {goals_a}-{goals_b} {team_b} ({suffix})")
    possession_a = event_value(result, team_a, "possession_ticks")
    possession_b = event_value(result, team_b, "possession_ticks")
    possession_total = max(1, possession_a + possession_b)
    share_a = possession_a / possession_total * 100
    share_b = possession_b / possession_total * 100
    trace.append(
        "  "
        f"xG {event_value(result, team_a, 'xg_model', 0.0):.2f}-{event_value(result, team_b, 'xg_model', 0.0):.2f} | "
        f"possession ticks {possession_a}-{possession_b} ({share_a:.0f}%-{share_b:.0f}%) | "
        f"fouls {event_value(result, team_a, 'fouls')}-{event_value(result, team_b, 'fouls')} | "
        f"cards Y/R {event_value(result, team_a, 'yellow_cards')}/{event_value(result, team_a, 'red_cards')}-"
        f"{event_value(result, team_b, 'yellow_cards')}/{event_value(result, team_b, 'red_cards')} | "
        f"subs {event_value(result, team_a, 'substitutions')}-{event_value(result, team_b, 'substitutions')}"
    )
    context = result.get("context") or {}
    rf = (result.get("forest") or {}).get("sklearn_random_forest")
    model_note = ""
    if rf:
        model_note = f" | RF A/D/B {rf['p_team_a_win']:.2f}/{rf['p_draw']:.2f}/{rf['p_team_b_win']:.2f}"
    trace.append(
        "  "
        f"day +{context.get('match_day_index', 0)}, rest {context.get('rest_days_a', 0)}-{context.get('rest_days_b', 0)}, "
        f"host {context.get('host_factor_a', 0.0):.2f}-{context.get('host_factor_b', 0.0):.2f}, "
        f"travel {context.get('travel_load_a', 0.0):.2f}-{context.get('travel_load_b', 0.0):.2f}, "
        f"heat {context.get('heat_index', 0.0):.2f}, ref {context.get('referee_strictness', 1.0):.2f}{model_note}"
    )


def append_group_table(trace, group_name, ranked, table, qualified_thirds):
    trace.append(f"Group {group_name}")
    trace.append("  Pos Team                         Pts  GD  GF  GA  FP  Qual")
    for index, team in enumerate(ranked, start=1):
        row = table[team]
        if index <= 2:
            qualifier = "Q"
        elif team in qualified_thirds:
            qualifier = "3Q"
        else:
            qualifier = "-"
        trace.append(
            f"  {index:>2}  {team:<27} "
            f"{row['points']:>3} {row['goal_difference']:>3} {row['goals_for']:>3} {row['goals_against']:>3} "
            f"{row['fair_play_points']:>3}  {qualifier}"
        )


def append_tournament_summary(trace, stages, player_stats, team_event_totals):
    champion = stages["champion"]
    finalists = stages.get("final", [])
    runner_up = next((team for team in finalists if team != champion), None)

    trace.append("")
    trace.append("TOURNAMENT SUMMARY")
    trace.append(f"Champion: {champion}")
    if runner_up:
        trace.append(f"Runner-up: {runner_up}")
    trace.append(f"Third place: {stages['third_place']}")
    trace.append(f"Fourth place: {stages['fourth_place']}")

    scorers = sorted(
        [row for row in player_stats.values() if row.get("name") and row.get("goals", 0) > 0],
        key=lambda row: (row["goals"], row["assists"], row["team"], row["name"]),
        reverse=True,
    )
    if scorers:
        trace.append("")
        trace.append("Top scorers")
        for row in scorers[:10]:
            trace.append(f"  {row['goals']:>2} goals, {row['assists']:>2} assists - {row['name']} ({row['team']}, {row['position']})")

    event_rows = sorted(
        team_event_totals.items(),
        key=lambda item: (item[1].get("goals", 0), -item[1].get("red_cards", 0), item[0]),
        reverse=True,
    )
    if event_rows:
        trace.append("")
        trace.append("Team event totals")
        for team, row in event_rows[:12]:
            trace.append(
                f"  {team:<24} goals {row.get('goals', 0):>2}, fouls {row.get('fouls', 0):>3}, "
                f"Y/R {row.get('yellow_cards', 0)}/{row.get('red_cards', 0)}, "
                f"set pieces {row.get('set_piece_goals', 0)}, subs {row.get('substitutions', 0)}"
            )


def simulate_group_stage(structure, profiles, rng, tournament_state, player_stats, team_event_totals, trace=None, model_bundle=None):
    fixtures = build_group_fixtures(structure)
    tables = {group_name: blank_table(teams) for group_name, teams in structure["groups"].items()}
    group_match_results = {group_name: [] for group_name in structure["groups"]}
    group_results = {}
    if trace is not None:
        trace.append("")
        trace.append("GROUP STAGE")
    for fixture in fixtures:
        result = simulate_match(
            fixture["team_a"],
            fixture["team_b"],
            profiles,
            rng,
            tournament_state,
            allow_draw=True,
            current_day=fixture["day_index"],
            player_stats=player_stats,
            stage="group",
            group_name=fixture["group"],
            model_bundle=model_bundle,
        )
        record_result(tables[fixture["group"]], fixture["team_a"], fixture["team_b"], result["goals_a"], result["goals_b"], result["event_stats"])
        group_match_results[fixture["group"]].append(result)
        if trace is not None:
            append_match_trace(trace, f"M{fixture['match_id']:03d} Group {fixture['group']} MD{fixture['matchday']}", result)
        for team, stats in result["event_stats"].items():
            merge_counter_dict(team_event_totals[team], stats)

    qualifiers = []
    thirds = []
    performance_rows = []
    for group_name, table in tables.items():
        ranked = rank_table(table, profiles, rng, group_match_results[group_name])
        group_results[group_name] = {"ranking": ranked, "table": table}
        qualifiers.extend(ranked[:2])
        thirds.append(ranked[2])
        for team in ranked:
            performance_rows.append((team, table[team]))
    row_by_team = {team: row for team, row in performance_rows}
    thirds.sort(
        key=lambda team: (
            row_by_team[team]["points"],
            row_by_team[team]["goal_difference"],
            row_by_team[team]["goals_for"],
            row_by_team[team]["fair_play_points"],
            profiles[team]["nt_elo"],
        ),
        reverse=True,
    )
    qualified_thirds = thirds[:8]
    qualifiers.extend(qualified_thirds)
    qualifiers.sort(
        key=lambda team: (
            row_by_team[team]["points"],
            row_by_team[team]["goal_difference"],
            row_by_team[team]["goals_for"],
            row_by_team[team]["fair_play_points"],
            profiles[team]["nt_elo"],
        ),
        reverse=True,
    )
    if trace is not None:
        trace.append("")
        trace.append("GROUP TABLES")
        qualified_third_set = set(qualified_thirds)
        for group_name, result in group_results.items():
            append_group_table(trace, group_name, result["ranking"], result["table"], qualified_third_set)
        trace.append("")
        trace.append("BEST THIRD-PLACE TEAMS")
        for index, team in enumerate(thirds, start=1):
            row = row_by_team[team]
            marker = "qualified" if team in qualified_third_set else "out"
            trace.append(
                f"  {index:>2}. {team:<24} {row['points']:>2} pts, GD {row['goal_difference']:>3}, "
                f"GF {row['goals_for']:>2}, fair play {row['fair_play_points']:>3} - {marker}"
            )
    return qualifiers, group_results, qualified_thirds


def team_from_group_slot(group_results, slot):
    slot_type, group_name = slot
    ranking = group_results[group_name]["ranking"]
    if slot_type == "W":
        return ranking[0]
    if slot_type == "R":
        return ranking[1]
    if slot_type == "T":
        return ranking[2]
    raise ValueError(f"Unknown bracket slot type: {slot_type}")


def assign_third_place_slots(group_results, qualified_thirds, rng):
    third_group_by_team = {
        group_name: result["ranking"][2]
        for group_name, result in group_results.items()
        if len(group_name) == 1
    }
    qualified_groups = {
        group_name
        for group_name, team in third_group_by_team.items()
        if team in set(qualified_thirds)
    }
    third_slots = [
        (slot_index, opponent_slot[1])
        for slot_index, (_left_slot, opponent_slot) in enumerate(ROUND_OF_32_SLOTS)
        if opponent_slot[0] == "T"
    ]
    ordered_slots = sorted(third_slots, key=lambda item: len(set(item[1]) & qualified_groups))
    assignments = {}

    def backtrack(index, remaining_groups):
        if index >= len(ordered_slots):
            return True
        slot_index, allowed_groups = ordered_slots[index]
        candidates = sorted(set(allowed_groups) & remaining_groups)
        rng.shuffle(candidates)
        candidates.sort(key=lambda group_name: qualified_thirds.index(third_group_by_team[group_name]))
        for group_name in candidates:
            assignments[slot_index] = group_name
            if backtrack(index + 1, remaining_groups - {group_name}):
                return True
            del assignments[slot_index]
        return False

    if not backtrack(0, set(qualified_groups)):
        assignments.clear()
        remaining_groups = list(qualified_groups)
        for slot_index, allowed_groups in third_slots:
            candidate = next((group for group in remaining_groups if group in allowed_groups), None)
            if candidate is None and remaining_groups:
                candidate = remaining_groups[0]
            if candidate is not None:
                assignments[slot_index] = candidate
                remaining_groups.remove(candidate)
    return {slot_index: third_group_by_team[group_name] for slot_index, group_name in assignments.items()}


def build_round_of_32_bracket(group_results, qualified_thirds, rng):
    third_assignments = assign_third_place_slots(group_results, qualified_thirds, rng)
    bracket = []
    for slot_index, (left_slot, right_slot) in enumerate(ROUND_OF_32_SLOTS):
        team_a = team_from_group_slot(group_results, left_slot)
        if right_slot[0] == "T":
            team_b = third_assignments[slot_index]
        else:
            team_b = team_from_group_slot(group_results, right_slot)
        bracket.extend([team_a, team_b])
    return bracket


def simulate_knockouts(qualified, group_results, qualified_thirds, profiles, rng, tournament_state, player_stats, team_event_totals, trace=None, model_bundle=None):
    round_of_32_bracket = build_round_of_32_bracket(group_results, qualified_thirds, rng)
    stages = {
        "round_of_32": round_of_32_bracket[:],
        "round_of_16": [],
        "quarter_finals": [],
        "semi_finals": [],
        "final": [],
        "third_place_match": [],
        "third_place": None,
        "fourth_place": None,
        "champion": None,
    }
    current = round_of_32_bracket[:]
    semi_losers = []
    next_stage_names = ["round_of_16", "quarter_finals", "semi_finals", "final", "champion"]
    match_stage_names = ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final"]
    match_stage_codes = ["R32", "R16", "QF", "SF", "FIN"]
    if trace is not None:
        trace.append("")
        trace.append("KNOCKOUT STAGE")
    for stage_index, stage_name in enumerate(next_stage_names):
        winners = []
        losers = []
        if trace is not None:
            trace.append("")
            trace.append(stage_display_name(match_stage_names[stage_index]).upper())
        for i in range(len(current) // 2):
            team_a = current[i * 2]
            team_b = current[i * 2 + 1]
            match_stage = match_stage_names[stage_index]
            match_days = KNOCKOUT_STAGE_DAYS[match_stage]
            current_day = match_days[i % len(match_days)]
            result = simulate_match(
                team_a,
                team_b,
                profiles,
                rng,
                tournament_state,
                allow_draw=False,
                current_day=current_day,
                player_stats=player_stats,
                stage=match_stage,
                model_bundle=model_bundle,
            )
            winner = result["winner"]
            loser = team_b if winner == team_a else team_a
            winners.append(winner)
            losers.append(loser)
            if trace is not None:
                append_match_trace(trace, f"{match_stage_codes[stage_index]}-{i + 1:02d}", result)
            for team, stats in result["event_stats"].items():
                merge_counter_dict(team_event_totals[team], stats)
        if stage_name == "final":
            semi_losers = losers
        if stage_name == "champion":
            stages["champion"] = winners[0]
        else:
            stages[stage_name] = winners[:]
        current = winners

    stages["third_place_match"] = semi_losers
    third_result = simulate_match(
        semi_losers[0],
        semi_losers[1],
        profiles,
        rng,
        tournament_state,
        allow_draw=False,
        current_day=KNOCKOUT_STAGE_DAYS["third_place_match"][0],
        player_stats=player_stats,
        stage="third_place_match",
        model_bundle=model_bundle,
    )
    third_winner = third_result["winner"]
    if trace is not None:
        trace.append("")
        trace.append("THIRD-PLACE MATCH")
        append_match_trace(trace, "3P-01", third_result)
    stages["third_place"] = third_winner
    stages["fourth_place"] = semi_losers[1] if third_winner == semi_losers[0] else semi_losers[0]
    for team, stats in third_result["event_stats"].items():
        merge_counter_dict(team_event_totals[team], stats)
    return stages


def initial_tournament_state(profiles):
    return {
        team: {
            "suspensions": {},
            "yellow_bank": Counter(),
            "carry_fatigue": {},
            "last_day": None,
        }
        for team in profiles
    }


def simulate_one_tournament(structure, profiles, rng, trace=None, model_bundle=None):
    player_stats = defaultdict(lambda: {"team": None, "name": None, "position": None, "goals": 0, "assists": 0})
    team_event_totals = defaultdict(Counter)
    tournament_state = initial_tournament_state(profiles)
    qualified, group_results, qualified_thirds = simulate_group_stage(structure, profiles, rng, tournament_state, player_stats, team_event_totals, trace=trace, model_bundle=model_bundle)
    stages = simulate_knockouts(qualified, group_results, qualified_thirds, profiles, rng, tournament_state, player_stats, team_event_totals, trace=trace, model_bundle=model_bundle)
    return group_results, stages, player_stats, team_event_totals


def simulate_chunk(args):
    chunk_epochs, seed, structure, profiles, model_bundle = args
    rng = random.Random(seed)
    teams = sorted(profiles)
    counts = {
        team: {
            "round_of_32": 0,
            "round_of_16": 0,
            "quarter_finals": 0,
            "semi_finals": 0,
            "final": 0,
            "third_place_match": 0,
            "third_place": 0,
            "fourth_place": 0,
            "champion": 0,
        }
        for team in teams
    }
    group_points = Counter()
    group_goal_difference = Counter()
    team_events = defaultdict(Counter)
    player_totals = defaultdict(lambda: {"team": None, "name": None, "position": None, "goals": 0, "assists": 0})

    for _ in range(chunk_epochs):
        group_results, stages, player_stats, tournament_events = simulate_one_tournament(structure, profiles, rng, model_bundle=model_bundle)
        for group in group_results.values():
            for team, row in group["table"].items():
                group_points[team] += row["points"]
                group_goal_difference[team] += row["goal_difference"]
        for stage_name in ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final", "third_place_match"]:
            for team in stages[stage_name]:
                counts[team][stage_name] += 1
        counts[stages["third_place"]]["third_place"] += 1
        counts[stages["fourth_place"]]["fourth_place"] += 1
        counts[stages["champion"]]["champion"] += 1
        for team, counter in tournament_events.items():
            merge_counter_dict(team_events[team], counter)
        for key, row in player_stats.items():
            total = player_totals[key]
            total["team"] = row["team"]
            total["name"] = row["name"]
            total["position"] = row["position"]
            total["goals"] += row["goals"]
            total["assists"] += row["assists"]

    return {
        "epochs": chunk_epochs,
        "counts": counts,
        "group_points": dict(group_points),
        "group_goal_difference": dict(group_goal_difference),
        "team_events": {team: dict(counter) for team, counter in team_events.items()},
        "player_totals": dict(player_totals),
    }


def merge_chunk_results(chunks, profiles, epochs):
    teams = sorted(profiles)
    counts = {
        team: {
            "round_of_32": 0,
            "round_of_16": 0,
            "quarter_finals": 0,
            "semi_finals": 0,
            "final": 0,
            "third_place_match": 0,
            "third_place": 0,
            "fourth_place": 0,
            "champion": 0,
        }
        for team in teams
    }
    group_points = Counter()
    group_goal_difference = Counter()
    team_events = defaultdict(Counter)
    player_totals = defaultdict(lambda: {"team": None, "name": None, "position": None, "goals": 0, "assists": 0})

    for chunk in chunks:
        for team, row in chunk["counts"].items():
            for key, value in row.items():
                counts[team][key] += value
        group_points.update(chunk["group_points"])
        group_goal_difference.update(chunk["group_goal_difference"])
        for team, row in chunk["team_events"].items():
            merge_counter_dict(team_events[team], row)
        for key, row in chunk["player_totals"].items():
            total = player_totals[key]
            total["team"] = row["team"]
            total["name"] = row["name"]
            total["position"] = row["position"]
            total["goals"] += row["goals"]
            total["assists"] += row["assists"]

    team_results = []
    for team in teams:
        event_row = team_events[team]
        team_results.append(
            {
                "team": team,
                "nt_elo": profiles[team]["nt_elo"],
                "elo_source": profiles[team]["elo_source"],
                "fifa_rank": profiles[team].get("fifa_rank"),
                "confederation": profiles[team].get("confederation"),
                "squad_rating": profiles[team]["squad_rating"],
                "attack_score": profiles[team]["attack_score"],
                "defense_score": profiles[team]["defense_score"],
                "midfield_score": profiles[team]["midfield_score"],
                "gk_score": profiles[team]["gk_score"],
                "data_confidence": profiles[team]["data_confidence"],
                "average_group_points": round(group_points[team] / epochs, 3),
                "average_group_goal_difference": round(group_goal_difference[team] / epochs, 3),
                **{f"{stage}_pct": round(value / epochs * 100, 2) for stage, value in counts[team].items()},
                "fouls_per_tournament": round(event_row.get("fouls", 0) / epochs, 3),
                "yellow_cards_per_tournament": round(event_row.get("yellow_cards", 0) / epochs, 3),
                "red_cards_per_tournament": round(event_row.get("red_cards", 0) / epochs, 3),
                "substitutions_per_tournament": round(event_row.get("substitutions", 0) / epochs, 3),
                "set_piece_goals_per_tournament": round(event_row.get("set_piece_goals", 0) / epochs, 3),
                "chasing_ticks_per_tournament": round(event_row.get("chasing_ticks", 0) / epochs, 3),
                "protecting_ticks_per_tournament": round(event_row.get("protecting_ticks", 0) / epochs, 3),
                "lineup_replacements_per_tournament": round(event_row.get("lineup_replacements", 0) / epochs, 3),
                "possession_tick_share": round(
                    event_row.get("possession_ticks", 0)
                    / max(1, event_row.get("possession_ticks", 0) + sum(team_events[other].get("possession_ticks", 0) for other in teams if other != team) / max(1, len(teams) - 1)),
                    4,
                ),
            }
        )
    team_results.sort(key=lambda row: (row["champion_pct"], row["final_pct"], row["squad_rating"]), reverse=True)
    player_results = [
        {
            **row,
            "goals_per_tournament": round(row["goals"] / epochs, 4),
            "assists_per_tournament": round(row["assists"] / epochs, 4),
        }
        for row in player_totals.values()
        if row["name"]
    ]
    player_results.sort(key=lambda row: (row["goals"], row["assists"]), reverse=True)
    return team_results, player_results[:250]


def chunk_sizes(epochs, workers):
    workers = max(1, min(workers, epochs))
    base = epochs // workers
    remainder = epochs % workers
    return [base + (1 if index < remainder else 0) for index in range(workers) if base + (1 if index < remainder else 0) > 0]


def run_simulation(epochs, seed, workers, elo_file, features_output=None, match_model="auto", historical_matches_file=None):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
    model_bundle, model_status = build_match_model_bundle(structure, profiles, seed, mode=match_model, historical_matches_file=historical_matches_file)
    features = build_feature_dataframe(structure, profiles)
    if features_output:
        output_path = ROOT / features_output
        if pd is not None and hasattr(features, "to_csv"):
            features.to_csv(output_path, index=False)
        else:
            output_path.write_text(json.dumps(features, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sizes = chunk_sizes(epochs, workers)
    tasks = []
    offset = 0
    for index, size in enumerate(sizes):
        tasks.append((size, seed + 1009 * index + offset, structure, profiles, model_bundle))
        offset += size

    if workers == 1:
        chunks = [simulate_chunk(task) for task in tasks]
    else:
        chunks = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(simulate_chunk, task): task for task in tasks}
            for future in as_completed(future_map):
                chunks.append(future.result())

    team_results, player_results = merge_chunk_results(chunks, profiles, epochs)
    return {
        "metadata": {
            "epochs": epochs,
            "seed": seed,
            "workers": workers,
            "squad_file": SQUAD_FILE.name,
            "performance_file": PERFORMANCE_FILE.name,
            "structure_file": STRUCTURE_FILE.name,
            "elo_file": str(elo_file) if Path(elo_file).exists() else None,
            "elo_source": elo_source,
            "features_output": features_output,
            "model": "v2 event simulator: NT Elo/squad prior, pandas feature frame, optional sklearn random forest, 9-minute compressed possession events, fatigue, substitutions, cards, set pieces, game-state behavior, exact WC26 round calendar, extra time, penalties",
            "decision_forest_status": model_status,
            "historical_matches_file": str(historical_matches_file) if historical_matches_file else None,
            "compressed_time": {"regular_minutes": 9, "extra_time_minutes": 3},
        },
        "team_profiles": {
            team: {
                key: value
                for key, value in profile.items()
                if key
                in {
                    "squad_rating",
                    "average_rating",
                    "top_11_rating",
                    "top_18_rating",
                    "attack_score",
                    "midfield_score",
                    "defense_score",
                    "gk_score",
                    "possession_score",
                    "discipline_risk",
                    "foul_rate",
                    "data_confidence",
                    "nt_elo",
                    "elo_source",
                    "fifa_rank",
                    "confederation",
                }
            }
            for team, profile in profiles.items()
        },
        "results": team_results,
        "player_stats": player_results,
    }


def run_trace_tournament(seed, elo_file, match_model="auto", historical_matches_file=None):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
    model_bundle, model_status = build_match_model_bundle(structure, profiles, seed, mode=match_model, historical_matches_file=historical_matches_file)
    rng = random.Random(seed)
    trace = [
        "FIFA WORLD CUP 2026 - SINGLE SIMULATION TRACE",
        f"Seed: {seed}",
        "Clock: 9 compressed minutes for regulation, 3 compressed minutes for extra time",
        f"Teams: {len(profiles)}",
        f"Elo source: {elo_source}",
        f"Match model: {model_status['kind']} ({model_status.get('training_source', 'no_training')}, rows={model_status.get('training_rows', 0)})",
        "Model: v2 possession/event simulator with fouls, cards, set pieces, fatigue, substitutions, game-state behavior, extra time and penalties",
    ]
    group_results, stages, player_stats, team_event_totals = simulate_one_tournament(structure, profiles, rng, trace=trace, model_bundle=model_bundle)
    append_tournament_summary(trace, stages, player_stats, team_event_totals)
    return "\n".join(trace)


def parse_workers(value, epochs):
    if value == "auto":
        return max(1, min(12, os.cpu_count() or 1, epochs))
    workers = int(value)
    return max(1, min(workers, epochs))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260610)
    parser.add_argument("--workers", default="auto", help="Use 'auto' or an integer worker count. Ryzen 7 8845HS sweet spot is usually 8-12.")
    parser.add_argument("--elo-file", default=str(DEFAULT_ELO_FILE))
    parser.add_argument("--output", default="simulation_results_v2_1000.json")
    parser.add_argument("--features-output", default="simulation_features_v2.csv")
    parser.add_argument("--match-model", default="auto", choices=["auto", "random-forest", "heuristic"], help="Use sklearn random forest when available, or force the heuristic model.")
    parser.add_argument("--historical-matches", default=None, help="Optional CSV with team_a/team_b/goals_a/goals_b or home/away equivalent columns for supervised training.")
    parser.add_argument("--trace-one", action="store_true", help="Print one full tournament transcript and save it to --trace-output.")
    parser.add_argument("--trace-output", default="simulation_trace_v2.txt", help="Text file for --trace-one output. Use an empty string to skip saving.")
    args = parser.parse_args()

    if args.trace_one:
        transcript = run_trace_tournament(args.seed, args.elo_file, match_model=args.match_model, historical_matches_file=args.historical_matches)
        print(transcript)
        if args.trace_output:
            trace_path = ROOT / args.trace_output
            trace_path.write_text(transcript + "\n", encoding="utf-8")
            print(f"\nrecorded trace to {trace_path.name}")
        return

    workers = parse_workers(str(args.workers), args.epochs)
    results = run_simulation(args.epochs, args.seed, workers, args.elo_file, args.features_output, match_model=args.match_model, historical_matches_file=args.historical_matches)
    output_path = ROOT / args.output
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {output_path.name}")
    if args.features_output:
        print(f"wrote {args.features_output}")
    print(json.dumps(results["metadata"], indent=2))
    print("top champion probabilities:")
    for row in results["results"][:12]:
        print(f"{row['team']}: champion {row['champion_pct']}%, final {row['final_pct']}%, Elo {row['nt_elo']}, squad {row['squad_rating']}")


if __name__ == "__main__":
    main()
