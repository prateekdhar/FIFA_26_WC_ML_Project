import csv
import difflib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SQUAD_FILE = ROOT / "guardian_world_cup_2026_player_guide.json"
EAFC_FILE = ROOT / "eafc26_players.csv"

COUNTRY_ALIAS = {
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde": "Cabo Verde",
    "Czech Republic": "Czechia",
    "DR Congo": "Congo DR",
    "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "Korea Republic",
    "Turkey": "Türkiye",
    "United States": "United States",
}

POSITION_ALIAS = {
    "GK": "GK",
    "LB": "LB",
    "LWB": "LWB",
    "CB": "CB",
    "LCB": "CB",
    "RCB": "CB",
    "RB": "RB",
    "RWB": "RWB",
    "CDM": "CDM",
    "LDM": "CDM",
    "RDM": "CDM",
    "DM": "CDM",
    "CM": "CM",
    "LCM": "CM",
    "RCM": "CM",
    "CAM": "CAM",
    "LAM": "CAM",
    "RAM": "CAM",
    "AM": "CAM",
    "LM": "LM",
    "RM": "RM",
    "LW": "LW",
    "RW": "RW",
    "LF": "LW",
    "RF": "RW",
    "CF": "CF",
    "ST": "ST",
    "LS": "ST",
    "RS": "ST",
}
DEFAULT_POSITION = {"DF": "CB", "MF": "CM", "FW": "ST", "GK": "GK"}
DEFAULT_RATING = {"GK": 68, "DF": 68, "MF": 69, "FW": 69}


def norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def compact(text):
    return norm(text).replace(" ", "")


def token_sorted(text):
    return " ".join(sorted(norm(text).split()))


def club_similarity(fifa_club, eafc_club):
    fifa_club = norm(re.sub(r"\([A-Z]{3}\)", "", fifa_club or ""))
    eafc_club = norm(eafc_club or "")
    if not fifa_club or not eafc_club:
        return 0.0
    if fifa_club in eafc_club or eafc_club in fifa_club:
        return 1.0
    return difflib.SequenceMatcher(None, fifa_club, eafc_club).ratio()


def clean_display_name(name):
    parts = name.split()
    if len(parts) >= 3 and parts[0].isupper():
        prefix = norm(parts[0])
        rest_tokens = norm(" ".join(parts[1:])).split()
        if prefix in rest_tokens:
            return " ".join(parts[1:])
    return name


def normalize_position(pos):
    pos = (pos or "").strip().upper()
    if not pos or pos in {"SUB", "RES"}:
        return None
    return POSITION_ALIAS.get(pos)


def row_position(row):
    for key in ["nation_position"]:
        pos = normalize_position(row.get(key))
        if pos:
            return pos
    for part in (row.get("player_positions") or "").split(","):
        pos = normalize_position(part)
        if pos:
            return pos
    return normalize_position(row.get("club_position"))


def score_name(player_name, row):
    n = norm(player_name)
    c = compact(player_name)
    ts = token_sorted(player_name)
    best = 0.0
    for candidate in [row.get("long_name", ""), row.get("short_name", "")]:
        rn = norm(candidate)
        if not rn:
            continue
        rc = compact(candidate)
        rts = token_sorted(candidate)
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
        best = max(best, difflib.SequenceMatcher(None, ts, rts).ratio())
    return best


def load_eafc():
    by_nation = defaultdict(list)
    exact = {}
    all_rows = []
    with EAFC_FILE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            pos = row_position(row)
            if not pos:
                continue
            try:
                rating = int(row.get("overall") or 0)
            except ValueError:
                continue
            if rating <= 0:
                continue
            row["_position"] = pos
            row["_rating"] = rating
            by_nation[row.get("nationality_name", "")].append(row)
            all_rows.append(row)
            for name in [row.get("long_name", ""), row.get("short_name", "")]:
                key = compact(name)
                if key and (key not in exact or rating > exact[key]["_rating"]):
                    exact[key] = row
    for rows in by_nation.values():
        rows.sort(key=lambda row: row["_rating"], reverse=True)
    return by_nation, exact, all_rows


def full_token_global_club_match(player_name, fifa_club, all_rows):
    player_tokens = set(norm(player_name).split())
    if not player_tokens:
        return None, 0.0
    best = None
    best_score = 0.0
    for row in all_rows:
        long_name_tokens = set(norm(row.get("long_name", "")).split())
        if not player_tokens.issubset(long_name_tokens):
            continue
        score = club_similarity(fifa_club, row.get("club_name", ""))
        if score > best_score or (score == best_score and best and row["_rating"] > best["_rating"]):
            best = row
            best_score = score
    if best and best_score >= 0.75:
        return best, round(best_score, 3)
    return None, best_score


def find_match(country, player_name, fifa_club, by_nation, exact, all_rows):
    nationality = COUNTRY_ALIAS.get(country, country)
    candidates = by_nation.get(nationality, [])
    if candidates:
        score, row = max(((score_name(player_name, row), row) for row in candidates), key=lambda item: (item[0], item[1]["_rating"]))
        if score >= 0.72:
            return row, "eafc26_country_name", round(score, 3)
    row = exact.get(compact(player_name))
    if row:
        return row, "eafc26_global_exact", 1.0
    row, score = full_token_global_club_match(player_name, fifa_club, all_rows)
    if row:
        return row, "eafc26_global_name_club", score
    return None, "fallback", 0.0


def main():
    data = json.loads(SQUAD_FILE.read_text(encoding="utf-8"))
    by_nation, exact, all_rows = load_eafc()
    summary = {
        "total_players": 0,
        "matched": 0,
        "fallback": 0,
        "fallback_examples": [],
        "by_country": {},
    }

    for team in data["teams"]:
        country = team["country"]
        country_summary = {"players": 0, "matched": 0, "fallback": 0}
        for player in team["players"]:
            player["name"] = clean_display_name(player["name"])
            official_position = player["position"]
            row, source, score = find_match(country, player["name"], player.get("club"), by_nation, exact, all_rows)
            if row:
                player["position"] = row["_position"]
                player["rating"] = row["_rating"]
                player["rating_source"] = source
                player["rating_match_score"] = score
                summary["matched"] += 1
                country_summary["matched"] += 1
            else:
                player["position"] = DEFAULT_POSITION[official_position]
                player["rating"] = DEFAULT_RATING[official_position]
                player["rating_source"] = "fallback_by_official_position"
                player["rating_match_score"] = 0.0
                summary["fallback"] += 1
                country_summary["fallback"] += 1
                if len(summary["fallback_examples"]) < 40:
                    summary["fallback_examples"].append({"country": country, "name": player["name"], "position": player["position"], "rating": player["rating"]})
            player["official_position"] = official_position
            summary["total_players"] += 1
            country_summary["players"] += 1
        summary["by_country"][country] = country_summary

    unresolved = [p for t in data["teams"] for p in t["players"] if p["position"] in {"DF", "MF", "FW"} or "rating" not in p]
    if unresolved:
        raise SystemExit(f"Unresolved player enrichment count: {len(unresolved)}")

    data.setdefault("metadata", {})["position_granularity"] = "Detailed EAFC-style positions for every player."
    data["metadata"]["rating_source"] = "EAFC26 local player dataset eafc26_players.csv; fallback by official FIFA broad position where no confident match exists."
    data["metadata"]["enrichment_summary"] = summary
    data["metadata"]["player_fields"] = ["name", "position", "official_position", "club", "rating", "rating_source", "rating_match_score"]
    data["metadata"]["position_codes"] = {
        "GK": "Goalkeeper",
        "LB": "Left back",
        "CB": "Centre back",
        "RB": "Right back",
        "LWB": "Left wing back",
        "RWB": "Right wing back",
        "CDM": "Defensive midfielder",
        "CM": "Central midfielder",
        "CAM": "Attacking midfielder",
        "LM": "Left midfielder",
        "RM": "Right midfielder",
        "LW": "Left winger",
        "RW": "Right winger",
        "CF": "Centre forward",
        "ST": "Striker",
    }
    SQUAD_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"by_country", "fallback_examples"}}, indent=2))


if __name__ == "__main__":
    main()
