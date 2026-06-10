import argparse
import json
import math
import os
import random
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is available in the Codex runtime.
    pd = None


ROOT = Path(__file__).resolve().parent
SQUAD_FILE = ROOT / "guardian_world_cup_2026_player_guide.json"
PERFORMANCE_FILE = ROOT / "player_performance_data_statbunker.json"
STRUCTURE_FILE = ROOT / "world_cup_2026_simulation_structure.json"
DEFAULT_ELO_FILE = ROOT / "national_team_elo_ratings.json"

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


def load_elo_ratings(path):
    path = Path(path)
    if not path.exists():
        return {}, "squad_proxy"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("teams", data if isinstance(data, list) else {})
    ratings = {}
    if isinstance(rows, dict):
        for team, value in rows.items():
            if isinstance(value, dict):
                value = value.get("elo") or value.get("rating")
            ratings[team] = safe_float(value, 0.0)
    else:
        for row in rows:
            team = row.get("team") or row.get("country") or row.get("name")
            value = row.get("elo") or row.get("rating")
            if team:
                ratings[team] = safe_float(value, 0.0)
    ratings = {team: value for team, value in ratings.items() if value > 0}
    return ratings, data.get("metadata", {}).get("source", "national_team_elo_ratings.json")


def build_team_profiles(elo_file=DEFAULT_ELO_FILE):
    performance = json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
    elo_ratings, elo_source = load_elo_ratings(elo_file)
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
            }
        )
    return profiles, elo_source


def team_feature_row(match_id, stage, group_name, team, opponent, profiles, allow_draw, minute_scale, round_index):
    left = profiles[team]
    right = profiles[opponent]
    elo_diff = left["nt_elo"] - right["nt_elo"]
    return {
        "match_id": match_id,
        "stage": stage,
        "round_index": round_index,
        "group": group_name,
        "team": team,
        "opponent": opponent,
        "allow_draw": allow_draw,
        "compressed_minutes": minute_scale,
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
    }


def build_group_fixtures(structure):
    fixtures = []
    match_id = 1
    pairings = structure["group_stage"]["round_robin_pairings_by_seed"]
    for group_name, teams in structure["groups"].items():
        for pair_index, (left_seed, right_seed) in enumerate(pairings):
            matchday = pair_index // 2 + 1
            fixtures.append(
                {
                    "match_id": match_id,
                    "stage": "group",
                    "group": group_name,
                    "team_a": teams[left_seed - 1],
                    "team_b": teams[right_seed - 1],
                    "matchday": matchday,
                    "day_index": (matchday - 1) * 6 + ord(group_name) - ord("A"),
                    "allow_draw": True,
                }
            )
            match_id += 1
    fixtures.sort(key=lambda row: (row["matchday"], row["group"], row["match_id"]))
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


def expected_goal_model(team_a, team_b, profiles):
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
    strength = elo_diff / 430 + rating_diff / 9.5 + attack_diff / 13.0 - defense_diff / 18.0
    share_a = clamp(logistic(strength + forest["attack_shift"]), 0.18, 0.82)
    total_goals = clamp(2.55 * forest["tempo_multiplier"] + (left["attack_score"] + right["attack_score"] - 145) * 0.015, 1.65, 3.65)
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


def apply_fatigue(match_team, extra_time=False):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    red_load = max(0, 11 - len(active)) * 0.012
    for player in active:
        increment = (0.082 if not extra_time else 0.115) / max(0.78, player.get("stamina", 0.9)) + red_load
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


def maybe_substitute(match_team, tick, event_stats, extra_time=False):
    if match_team["substitutions"] >= match_team["max_substitutions"]:
        return
    if tick < 6 and not extra_time:
        return
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    if not active or not match_team["bench"]:
        return
    outgoing = max(active, key=substitution_need)
    threshold = 0.74 if not extra_time else 0.64
    if substitution_need(outgoing) < threshold and match_team["substitutions"] >= 3:
        return
    replacement = find_bench_replacement(match_team, outgoing)
    if replacement is None:
        return
    match_team["active"].remove(outgoing)
    match_team["active"].append(replacement)
    match_team["substitutions"] += 1
    event_stats[match_team["country"]]["substitutions"] += 1


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


def process_fouls(match_team, opponent, rng, event_stats, tick_scale=1.0):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    if not active:
        return
    team_foul_lambda = sum(player["foul_rate"] for player in active) / 9.0 * tick_scale
    fouls = poisson(clamp(team_foul_lambda, 0.0, 3.2), rng)
    event_stats[match_team["country"]]["fouls"] += fouls
    for _ in range(fouls):
        offender = weighted_choice(active, card_weight, rng)
        if offender is None:
            continue
        yellow_probability = clamp(0.075 + offender["card_risk"] * 0.42, 0.04, 0.28)
        direct_red_probability = clamp(0.004 + offender["card_risk"] * 0.025, 0.002, 0.025)
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
    if fouls and rng.random() < 0.35:
        event_stats[opponent["country"]]["set_piece_possessions"] += 1


def allocate_goal(match_team, rng, player_stats, include_assist=True):
    active = [player for player in match_team["active"] if not player.get("sent_off")]
    scorer = weighted_choice(active, scoring_weight, rng)
    if scorer is None:
        return
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


def simulate_period(team_a_state, team_b_state, base_xg_a, base_xg_b, possession_a, ticks, rng, event_stats, player_stats, extra_time=False):
    goals_a = 0
    goals_b = 0
    possession = "A" if rng.random() < possession_a else "B"
    scale = ticks / 9.0
    for tick in range(ticks):
        a_strength = active_strength(team_a_state)
        b_strength = active_strength(team_b_state)
        a_attack = active_strength(team_a_state, "attack")
        b_attack = active_strength(team_b_state, "attack")
        a_defense = active_strength(team_a_state, "defense")
        b_defense = active_strength(team_b_state, "defense")

        if possession == "A":
            event_stats[team_a_state["country"]]["possession_ticks"] += 1
            chance = base_xg_a / max(1, ticks) * clamp((a_attack - b_defense) / 32 + (a_strength - b_strength) / 55 + 1.0, 0.45, 1.75)
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
            process_fouls(team_b_state, team_a_state, rng, event_stats, tick_scale=scale * 1.05)
            if rng.random() < 0.38:
                process_fouls(team_a_state, team_b_state, rng, event_stats, tick_scale=scale * 0.45)
        else:
            process_fouls(team_a_state, team_b_state, rng, event_stats, tick_scale=scale * 1.05)
            if rng.random() < 0.38:
                process_fouls(team_b_state, team_a_state, rng, event_stats, tick_scale=scale * 0.45)

        apply_fatigue(team_a_state, extra_time=extra_time)
        apply_fatigue(team_b_state, extra_time=extra_time)
        maybe_substitute(team_a_state, tick, event_stats, extra_time=extra_time)
        maybe_substitute(team_b_state, tick, event_stats, extra_time=extra_time)
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


def simulate_match(team_a, team_b, profiles, rng, tournament_state, allow_draw, current_day, player_stats):
    xg_a, xg_b, possession_a, forest = expected_goal_model(team_a, team_b, profiles)
    state_a = initialize_match_team(team_a, profiles[team_a], tournament_state, current_day)
    state_b = initialize_match_team(team_b, profiles[team_b], tournament_state, current_day)
    event_stats = defaultdict(Counter)
    event_stats[team_a]["xg_model"] += xg_a
    event_stats[team_b]["xg_model"] += xg_b
    event_stats[team_a]["kickoffs"] += 1

    goals_a, goals_b = simulate_period(state_a, state_b, xg_a, xg_b, possession_a, 9, rng, event_stats, player_stats)
    resolution = "regular_time"
    winner = None
    penalty_score = None

    if not allow_draw and goals_a == goals_b:
        resolution = "extra_time"
        et_a, et_b = simulate_period(state_a, state_b, xg_a * 0.33, xg_b * 0.33, possession_a, 3, rng, event_stats, player_stats, extra_time=True)
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


def rank_table(table, profiles, rng):
    teams = list(table)
    rng.shuffle(teams)
    return sorted(
        teams,
        key=lambda team: (
            table[team]["points"],
            table[team]["goal_difference"],
            table[team]["goals_for"],
            table[team]["fair_play_points"],
            profiles[team]["nt_elo"],
        ),
        reverse=True,
    )


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
                f"Y/R {row.get('yellow_cards', 0)}/{row.get('red_cards', 0)}, subs {row.get('substitutions', 0)}"
            )


def simulate_group_stage(structure, profiles, rng, tournament_state, player_stats, team_event_totals, trace=None):
    fixtures = build_group_fixtures(structure)
    tables = {group_name: blank_table(teams) for group_name, teams in structure["groups"].items()}
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
        )
        record_result(tables[fixture["group"]], fixture["team_a"], fixture["team_b"], result["goals_a"], result["goals_b"], result["event_stats"])
        if trace is not None:
            append_match_trace(trace, f"M{fixture['match_id']:03d} Group {fixture['group']} MD{fixture['matchday']}", result)
        for team, stats in result["event_stats"].items():
            merge_counter_dict(team_event_totals[team], stats)

    qualifiers = []
    thirds = []
    performance_rows = []
    for group_name, table in tables.items():
        ranked = rank_table(table, profiles, rng)
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
    return qualifiers, group_results


def simulate_knockouts(qualified, profiles, rng, tournament_state, player_stats, team_event_totals, trace=None):
    stages = {
        "round_of_32": qualified[:],
        "round_of_16": [],
        "quarter_finals": [],
        "semi_finals": [],
        "final": [],
        "third_place_match": [],
        "third_place": None,
        "fourth_place": None,
        "champion": None,
    }
    current = qualified[:]
    current_day = 22
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
            team_a = current[i]
            team_b = current[-(i + 1)]
            result = simulate_match(team_a, team_b, profiles, rng, tournament_state, allow_draw=False, current_day=current_day, player_stats=player_stats)
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
        current_day += 4 if stage_index < 2 else 3

    stages["third_place_match"] = semi_losers
    third_result = simulate_match(semi_losers[0], semi_losers[1], profiles, rng, tournament_state, allow_draw=False, current_day=current_day + 2, player_stats=player_stats)
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


def simulate_one_tournament(structure, profiles, rng, trace=None):
    player_stats = defaultdict(lambda: {"team": None, "name": None, "position": None, "goals": 0, "assists": 0})
    team_event_totals = defaultdict(Counter)
    tournament_state = initial_tournament_state(profiles)
    qualified, group_results = simulate_group_stage(structure, profiles, rng, tournament_state, player_stats, team_event_totals, trace=trace)
    stages = simulate_knockouts(qualified, profiles, rng, tournament_state, player_stats, team_event_totals, trace=trace)
    return group_results, stages, player_stats, team_event_totals


def simulate_chunk(args):
    chunk_epochs, seed, structure, profiles = args
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
        group_results, stages, player_stats, tournament_events = simulate_one_tournament(structure, profiles, rng)
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


def run_simulation(epochs, seed, workers, elo_file, features_output=None):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
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
        tasks.append((size, seed + 1009 * index + offset, structure, profiles))
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
            "model": "v2 event simulator: NT Elo/squad prior, pandas feature frame, heuristic decision forest, 9-minute compressed possession events, fatigue, substitutions, cards, extra time, penalties",
            "decision_forest_status": "heuristic_internal_forest; sklearn is available, but this run is not yet using a trained RandomForest model",
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
                }
            }
            for team, profile in profiles.items()
        },
        "results": team_results,
        "player_stats": player_results,
    }


def run_trace_tournament(seed, elo_file):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
    rng = random.Random(seed)
    trace = [
        "FIFA WORLD CUP 2026 - SINGLE SIMULATION TRACE",
        f"Seed: {seed}",
        "Clock: 9 compressed minutes for regulation, 3 compressed minutes for extra time",
        f"Teams: {len(profiles)}",
        f"Elo source: {elo_source}",
        "Model: v2 possession/event simulator with fouls, cards, fatigue, substitutions, extra time and penalties",
    ]
    group_results, stages, player_stats, team_event_totals = simulate_one_tournament(structure, profiles, rng, trace=trace)
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
    parser.add_argument("--trace-one", action="store_true", help="Print one full tournament transcript and save it to --trace-output.")
    parser.add_argument("--trace-output", default="simulation_trace_v2.txt", help="Text file for --trace-one output. Use an empty string to skip saving.")
    args = parser.parse_args()

    if args.trace_one:
        transcript = run_trace_tournament(args.seed, args.elo_file)
        print(transcript)
        if args.trace_output:
            trace_path = ROOT / args.trace_output
            trace_path.write_text(transcript + "\n", encoding="utf-8")
            print(f"\nrecorded trace to {trace_path.name}")
        return

    workers = parse_workers(str(args.workers), args.epochs)
    results = run_simulation(args.epochs, args.seed, workers, args.elo_file, args.features_output)
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
