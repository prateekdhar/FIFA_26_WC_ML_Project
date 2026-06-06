import argparse
import csv
import difflib
import json
import math
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SQUAD_FILE = ROOT / "guardian_world_cup_2026_player_guide.json"
STRUCTURE_FILE = ROOT / "world_cup_2026_simulation_structure.json"
EAFC_FILE = ROOT / "eafc26_players.csv"

DETAILED_POSITIONS = {
    "GK",
    "LB",
    "CB",
    "RB",
    "LWB",
    "RWB",
    "CDM",
    "CM",
    "CAM",
    "LM",
    "RM",
    "LW",
    "RW",
    "CF",
    "ST",
}
DEFENDERS = {"LB", "CB", "RB", "LWB", "RWB"}
MIDFIELDERS = {"CDM", "CM", "CAM", "LM", "RM"}
FORWARDS = {"LW", "RW", "CF", "ST"}

COUNTRY_ALIAS = {
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde": "Cabo Verde",
    "Czech Republic": "Czechia",
    "DR Congo": "Congo DR",
    "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "Korea Republic",
    "Turkey": "Türkiye",
}

NAME_FIXES = {
    "Vinicius Jr": "Vinícius Júnior",
    "Mathew Ryan": "Matthew Ryan",
    "Maxi Araujo": "Maximiliano Araújo",
    "Matias Vina": "Matías Viña",
    "Darwin Nunez": "Darwin Núñez",
    "Federico Vinas": "Federico Viñas",
}


def norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def compact(text):
    return norm(text).replace(" ", "")


def token_sorted(text):
    return " ".join(sorted(norm(text).split()))


def score_name(roster_name, row):
    roster_name = NAME_FIXES.get(roster_name, roster_name)
    n = norm(roster_name)
    c = compact(roster_name)
    ts = token_sorted(roster_name)
    best = 0.0
    for name in (row["long_name"], row["short_name"]):
        rn = norm(name)
        if not rn:
            continue
        rc = compact(name)
        rts = token_sorted(name)
        if rn == n or rc == c:
            best = max(best, 1.0)
        if rts == ts:
            best = max(best, 0.985)
        if n and (n in rn or rn in n):
            best = max(best, 0.935)
        nt = n.split()
        rt = rn.split()
        if len(nt) >= 2 and len(rt) >= 2 and nt[-1] == rt[-1] and nt[0][:1] == rt[0][:1]:
            best = max(best, 0.955)
        best = max(best, difflib.SequenceMatcher(None, n, rn).ratio())
    return best


def load_eafc_rows():
    by_nation = defaultdict(list)
    exact = {}
    with EAFC_FILE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                overall = int(row.get("overall") or 0)
            except ValueError:
                continue
            if overall <= 0:
                continue
            row["_overall"] = overall
            by_nation[row.get("nationality_name", "")].append(row)
            for name in (row.get("long_name", ""), row.get("short_name", "")):
                key = compact(name)
                if key and (key not in exact or overall > exact[key]["_overall"]):
                    exact[key] = row
    for rows in by_nation.values():
        rows.sort(key=lambda item: item["_overall"], reverse=True)
    return by_nation, exact


def match_player(country, player_name, by_nation, exact):
    nationality = COUNTRY_ALIAS.get(country, country)
    candidates = by_nation.get(nationality, [])
    if candidates:
        score, row = max(((score_name(player_name, row), row) for row in candidates), key=lambda item: (item[0], item[1]["_overall"]))
        if score >= 0.72:
            return row["_overall"], "country_name", round(score, 3)
    key = compact(NAME_FIXES.get(player_name, player_name))
    row = exact.get(key)
    if row:
        return row["_overall"], "global_exact", 1.0
    return None, "fallback", 0.0


def fallback_rating(position):
    if position == "GK":
        return 68
    if position in DEFENDERS:
        return 68
    if position in MIDFIELDERS:
        return 69
    if position in FORWARDS:
        return 69
    return 68


def build_team_profiles():
    squads = json.loads(SQUAD_FILE.read_text(encoding="utf-8"))
    by_nation, exact = load_eafc_rows()
    profiles = {}
    match_summary = {"matched": 0, "fallback": 0, "total": 0}

    for team in squads["teams"]:
        country = team["country"]
        players = []
        for player in team["players"]:
            position = player["position"]
            if "rating" in player:
                rating = int(player["rating"])
                source = player.get("rating_source", "squad_file")
                score = player.get("rating_match_score", 1.0)
                if str(source).startswith("fallback"):
                    match_summary["fallback"] += 1
                else:
                    match_summary["matched"] += 1
            else:
                rating, source, score = match_player(country, player["name"], by_nation, exact)
                if rating is None:
                    rating = fallback_rating(position)
                    match_summary["fallback"] += 1
                else:
                    match_summary["matched"] += 1
            match_summary["total"] += 1
            players.append(
                {
                    "name": player["name"],
                    "position": position,
                    "rating": rating,
                    "rating_source": source,
                    "match_score": score,
                }
            )

        overall = team_strength(players)
        profiles[country] = {
            "players": players,
            "team_rating": round(overall, 3),
            "average_rating": round(sum(p["rating"] for p in players) / len(players), 3),
            "top_11_average": round(sum(p["rating"] for p in best_xi(players)) / 11, 3),
            "top_18_average": round(sum(p["rating"] for p in sorted(players, key=lambda p: p["rating"], reverse=True)[:18]) / 18, 3),
        }
    return profiles, match_summary


def best_xi(players):
    selected = []
    remaining = sorted(players, key=lambda p: p["rating"], reverse=True)

    def take(predicate, count):
        taken = []
        for player in list(remaining):
            if len(taken) >= count:
                break
            if predicate(player):
                taken.append(player)
                remaining.remove(player)
        return taken

    selected += take(lambda p: p["position"] == "GK", 1)
    selected += take(lambda p: p["position"] in DEFENDERS, 4)
    selected += take(lambda p: p["position"] in MIDFIELDERS, 3)
    selected += take(lambda p: p["position"] in FORWARDS, 3)
    selected += remaining[: 11 - len(selected)]
    return selected[:11]


def team_strength(players):
    top_11 = best_xi(players)
    top_18 = sorted(players, key=lambda p: p["rating"], reverse=True)[:18]
    squad_avg = sum(p["rating"] for p in players) / len(players)
    top_11_avg = sum(p["rating"] for p in top_11) / len(top_11)
    top_18_avg = sum(p["rating"] for p in top_18) / len(top_18)
    return 0.62 * top_11_avg + 0.28 * top_18_avg + 0.10 * squad_avg


def poisson(lam, rng):
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def expected_goals(rating_a, rating_b):
    diff = rating_a - rating_b
    a = 1.28 + diff * 0.045
    b = 1.28 - diff * 0.045
    return max(0.25, min(3.4, a)), max(0.25, min(3.4, b))


def scoring_weight(player):
    position_weight = {
        "GK": 0.01,
        "LB": 0.10,
        "CB": 0.14,
        "RB": 0.10,
        "LWB": 0.16,
        "RWB": 0.16,
        "CDM": 0.18,
        "CM": 0.30,
        "CAM": 0.62,
        "LM": 0.48,
        "RM": 0.48,
        "LW": 0.86,
        "RW": 0.86,
        "CF": 0.98,
        "ST": 1.18,
    }.get(player["position"], 0.25)
    return position_weight * max(0.2, (player["rating"] - 55) / 35)


def assist_weight(player):
    position_weight = {
        "GK": 0.01,
        "LB": 0.22,
        "CB": 0.05,
        "RB": 0.22,
        "LWB": 0.35,
        "RWB": 0.35,
        "CDM": 0.30,
        "CM": 0.55,
        "CAM": 1.00,
        "LM": 0.84,
        "RM": 0.84,
        "LW": 0.78,
        "RW": 0.78,
        "CF": 0.48,
        "ST": 0.34,
    }.get(player["position"], 0.30)
    return position_weight * max(0.2, (player["rating"] - 55) / 35)


def weighted_choice(items, weight_fn, rng):
    weights = [max(0.001, weight_fn(item)) for item in items]
    total = sum(weights)
    pick = rng.random() * total
    running = 0.0
    for item, weight in zip(items, weights):
        running += weight
        if running >= pick:
            return item
    return items[-1]


def allocate_goal_events(team, goals, profiles, rng, player_stats, include_assists=True):
    players = profiles[team]["players"]
    for _ in range(goals):
        scorer = weighted_choice(players, scoring_weight, rng)
        key = f"{team}|{scorer['name']}"
        player_stats[key]["team"] = team
        player_stats[key]["name"] = scorer["name"]
        player_stats[key]["position"] = scorer["position"]
        player_stats[key]["rating"] = scorer["rating"]
        player_stats[key]["goals"] += 1

        if include_assists and rng.random() < 0.72:
            candidates = [player for player in players if player["name"] != scorer["name"]]
            assister = weighted_choice(candidates, assist_weight, rng)
            assist_key = f"{team}|{assister['name']}"
            player_stats[assist_key]["team"] = team
            player_stats[assist_key]["name"] = assister["name"]
            player_stats[assist_key]["position"] = assister["position"]
            player_stats[assist_key]["rating"] = assister["rating"]
            player_stats[assist_key]["assists"] += 1


def simulate_match(team_a, team_b, profiles, rng, allow_draw, player_stats=None):
    xg_a, xg_b = expected_goals(profiles[team_a]["team_rating"], profiles[team_b]["team_rating"])
    goals_a = poisson(xg_a, rng)
    goals_b = poisson(xg_b, rng)
    if player_stats is not None:
        allocate_goal_events(team_a, goals_a, profiles, rng, player_stats)
        allocate_goal_events(team_b, goals_b, profiles, rng, player_stats)
    if allow_draw or goals_a != goals_b:
        return goals_a, goals_b, None

    et_a = poisson(max(0.05, xg_a * 0.28), rng)
    et_b = poisson(max(0.05, xg_b * 0.28), rng)
    goals_a += et_a
    goals_b += et_b
    if player_stats is not None:
        allocate_goal_events(team_a, et_a, profiles, rng, player_stats)
        allocate_goal_events(team_b, et_b, profiles, rng, player_stats)
    if goals_a != goals_b:
        return goals_a, goals_b, "extra_time"

    rating_a = profiles[team_a]["team_rating"]
    rating_b = profiles[team_b]["team_rating"]
    p_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 18))
    if rng.random() < p_a:
        if player_stats is not None:
            allocate_goal_events(team_a, 1, profiles, rng, player_stats, include_assists=False)
        return goals_a + 1, goals_b, "penalties"
    if player_stats is not None:
        allocate_goal_events(team_b, 1, profiles, rng, player_stats, include_assists=False)
    return goals_a, goals_b + 1, "penalties"


def blank_table(group):
    return {
        team: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0, "goal_difference": 0, "points": 0}
        for team in group
    }


def record_result(table, team_a, team_b, goals_a, goals_b):
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


def rank_table(table, rng):
    teams = list(table)
    rng.shuffle(teams)
    return sorted(teams, key=lambda t: (table[t]["points"], table[t]["goal_difference"], table[t]["goals_for"]), reverse=True)


def simulate_group_stage(structure, profiles, rng, player_stats):
    qualifiers = []
    thirds = []
    performance_rows = []
    group_results = {}
    pairings = structure["group_stage"]["round_robin_pairings_by_seed"]

    for group_name, teams in structure["groups"].items():
        table = blank_table(teams)
        for left_seed, right_seed in pairings:
            team_a = teams[left_seed - 1]
            team_b = teams[right_seed - 1]
            goals_a, goals_b, _ = simulate_match(team_a, team_b, profiles, rng, allow_draw=True, player_stats=player_stats)
            record_result(table, team_a, team_b, goals_a, goals_b)
        ranked = rank_table(table, rng)
        group_results[group_name] = {"ranking": ranked, "table": table}
        qualifiers.extend(ranked[:2])
        thirds.append(ranked[2])
        for team in ranked:
            performance_rows.append((team, table[team]))

    thirds.sort(key=lambda t: (next(row for team, row in performance_rows if team == t)["points"], next(row for team, row in performance_rows if team == t)["goal_difference"], next(row for team, row in performance_rows if team == t)["goals_for"]), reverse=True)
    qualifiers.extend(thirds[:8])

    qualifiers.sort(
        key=lambda team: (
            next(row for candidate, row in performance_rows if candidate == team)["points"],
            next(row for candidate, row in performance_rows if candidate == team)["goal_difference"],
            next(row for candidate, row in performance_rows if candidate == team)["goals_for"],
            profiles[team]["team_rating"],
        ),
        reverse=True,
    )
    return qualifiers, group_results


def simulate_knockouts(qualified, profiles, rng, player_stats):
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
    next_stage_names = ["round_of_16", "quarter_finals", "semi_finals", "final", "champion"]
    semi_final_losers = []
    for stage_name in next_stage_names:
        winners = []
        for i in range(len(current) // 2):
            team_a = current[i]
            team_b = current[-(i + 1)]
            goals_a, goals_b, _ = simulate_match(team_a, team_b, profiles, rng, allow_draw=False, player_stats=player_stats)
            winner = team_a if goals_a > goals_b else team_b
            loser = team_b if winner == team_a else team_a
            winners.append(winner)
            if stage_name == "final":
                semi_final_losers.append(loser)
        if stage_name == "champion":
            stages["champion"] = winners[0]
        else:
            stages[stage_name] = winners[:]
        current = winners
    stages["third_place_match"] = semi_final_losers
    goals_a, goals_b, _ = simulate_match(semi_final_losers[0], semi_final_losers[1], profiles, rng, allow_draw=False, player_stats=player_stats)
    if goals_a > goals_b:
        stages["third_place"] = semi_final_losers[0]
        stages["fourth_place"] = semi_final_losers[1]
    else:
        stages["third_place"] = semi_final_losers[1]
        stages["fourth_place"] = semi_final_losers[0]
    return stages


def run_simulation(epochs, seed):
    rng = random.Random(seed)
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, match_summary = build_team_profiles()
    teams = sorted(profiles)
    counts = {
        team: {"round_of_32": 0, "round_of_16": 0, "quarter_finals": 0, "semi_finals": 0, "final": 0, "third_place_match": 0, "third_place": 0, "fourth_place": 0, "champion": 0}
        for team in teams
    }
    group_points = {team: 0 for team in teams}
    group_goal_difference = {team: 0 for team in teams}
    player_stats = defaultdict(lambda: {"team": None, "name": None, "position": None, "rating": None, "goals": 0, "assists": 0})

    for _ in range(epochs):
        qualified, group_results = simulate_group_stage(structure, profiles, rng, player_stats)
        for group in group_results.values():
            for team, row in group["table"].items():
                group_points[team] += row["points"]
                group_goal_difference[team] += row["goal_difference"]

        stages = simulate_knockouts(qualified, profiles, rng, player_stats)
        for team in stages["round_of_32"]:
            counts[team]["round_of_32"] += 1
        for team in stages["round_of_16"]:
            counts[team]["round_of_16"] += 1
        for team in stages["quarter_finals"]:
            counts[team]["quarter_finals"] += 1
        for team in stages["semi_finals"]:
            counts[team]["semi_finals"] += 1
        for team in stages["final"]:
            counts[team]["final"] += 1
        for team in stages["third_place_match"]:
            counts[team]["third_place_match"] += 1
        counts[stages["third_place"]]["third_place"] += 1
        counts[stages["fourth_place"]]["fourth_place"] += 1
        counts[stages["champion"]]["champion"] += 1

    team_results = []
    for team in teams:
        team_results.append(
            {
                "team": team,
                "team_rating": profiles[team]["team_rating"],
                "average_group_points": round(group_points[team] / epochs, 3),
                "average_group_goal_difference": round(group_goal_difference[team] / epochs, 3),
                **{f"{stage}_pct": round(value / epochs * 100, 2) for stage, value in counts[team].items()},
            }
        )
    team_results.sort(key=lambda row: (row["champion_pct"], row["final_pct"], row["team_rating"]), reverse=True)
    player_results = [
        {
            **row,
            "goals_per_tournament": round(row["goals"] / epochs, 3),
            "assists_per_tournament": round(row["assists"] / epochs, 3),
        }
        for row in player_stats.values()
        if row["name"]
    ]
    player_results.sort(key=lambda row: (row["goals"], row["assists"], row["rating"]), reverse=True)

    return {
        "metadata": {
            "epochs": epochs,
            "seed": seed,
            "squad_file": SQUAD_FILE.name,
            "structure_file": STRUCTURE_FILE.name,
            "ratings_file": EAFC_FILE.name,
            "model": "Primitive EAFC-overall team strength, Poisson goals, group-stage performance seeding for knockouts",
            "rating_match_summary": match_summary,
        },
        "team_ratings": {team: profiles[team] for team in teams},
        "results": team_results,
        "player_stats": player_results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260605)
    parser.add_argument("--output", default="simulation_results_1000.json")
    args = parser.parse_args()

    results = run_simulation(args.epochs, args.seed)
    output_path = ROOT / args.output
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {output_path.name}")
    print(json.dumps(results["metadata"], indent=2))
    print("top champion probabilities:")
    for row in results["results"][:12]:
        print(f"{row['team']}: champion {row['champion_pct']}%, final {row['final_pct']}%, rating {row['team_rating']}")


if __name__ == "__main__":
    main()
