import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "national_team_elo_ratings.json"
DEFAULT_STRUCTURE = ROOT / "world_cup_2026_simulation_structure.json"
DEFAULT_REPORT = ROOT / "national_team_elo_import_report.json"

DEFAULT_ALIASES = {
    "Bosnia & Herzegovina": ["Bosnia and Herzegovina", "Bosnia-Herzegovina", "Bosnia Herzegovina"],
    "Cape Verde": ["Cape Verde Islands"],
    "Curacao": ["Curaçao"],
    "Czech Republic": ["Czechia", "Czech Rep", "Czech Republic"],
    "DR Congo": ["Democratic Republic of Congo", "Congo DR", "Congo-Kinshasa"],
    "Ivory Coast": ["Cote d'Ivoire", "Côte d'Ivoire", "CIV"],
    "New Zealand": ["Aotearoa New Zealand"],
    "South Korea": ["Korea Republic", "Republic of Korea"],
    "Turkey": ["Türkiye", "Turkiye"],
    "United States": ["USA", "United States of America", "USMNT"],
}


def safe_float(value, default=0.0):
    if value is None:
        return default
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=None):
    number = safe_float(value, None)
    if number is None:
        return default
    return int(number)


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
    return sorted({str(alias).strip() for alias in aliases if str(alias).strip()})


def alias_lookup():
    lookup = {}
    for canonical, aliases in DEFAULT_ALIASES.items():
        lookup[canonical.casefold()] = canonical
        for alias in aliases:
            lookup[alias.casefold()] = canonical
    return lookup


def normalize_team_name(name, lookup):
    text = str(name or "").strip()
    if not text or text.casefold() in {"nan", "none"}:
        return ""
    return lookup.get(text.casefold(), text)


def rating_from_row(row, default_rating_type=None):
    if default_rating_type == "fifa_rank_derived_elo" and (row.get("fifa_rank") or row.get("rank")):
        return rank_to_estimated_elo(row.get("fifa_rank") or row.get("rank")), "fifa_rank_derived_elo", "fifa_rank"
    priority = [
        ("world_football_elo", "world_football_elo"),
        ("elo", row.get("rating_type") or default_rating_type or "elo"),
        ("rating", row.get("rating_type") or default_rating_type or "rating"),
        ("fifa_points", "fifa_points"),
        ("points", row.get("rating_type") or default_rating_type or "points"),
    ]
    for field, rating_type in priority:
        value = safe_float(row.get(field), 0.0)
        if value > 0:
            return round(value, 1), rating_type, field
    rank = row.get("fifa_rank") or row.get("rank")
    if rank:
        return rank_to_estimated_elo(rank), "fifa_rank_derived_elo", "fifa_rank"
    return 0.0, "missing", None


def read_csv_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json_rows(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("teams", data)
    if isinstance(rows, dict):
        output = []
        for team, row in rows.items():
            if isinstance(row, dict):
                output.append({"team": team, **row})
            else:
                output.append({"team": team, "elo": row})
        return output, data.get("metadata", {})
    if isinstance(rows, list):
        return rows, data.get("metadata", {}) if isinstance(data, dict) else {}
    raise ValueError(f"Unsupported JSON Elo shape in {path}")


def read_input_rows(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path), {}
    if suffix == ".json":
        return read_json_rows(path)
    raise ValueError("Input must be .csv or .json")


def read_existing(path):
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("teams", {}), data.get("metadata", {})


def merge_aliases(team, existing_aliases, imported_aliases):
    aliases = set(split_aliases(existing_aliases)) | set(split_aliases(imported_aliases))
    aliases.update(DEFAULT_ALIASES.get(team, []))
    aliases.discard(team)
    return sorted(aliases)


def build_team_rows(rows, lookup, default_rating_type=None):
    teams = {}
    skipped = []
    field_counts = {}
    for index, row in enumerate(rows, start=1):
        team = normalize_team_name(row.get("team") or row.get("country") or row.get("name"), lookup)
        if not team:
            skipped.append({"row": index, "reason": "missing_team"})
            continue
        rating, rating_type, source_field = rating_from_row(row, default_rating_type=default_rating_type)
        if rating <= 0:
            skipped.append({"row": index, "team": team, "reason": "missing_rating"})
            continue
        field_counts[source_field] = field_counts.get(source_field, 0) + 1
        aliases = merge_aliases(team, [], row.get("aliases"))
        fifa_rank = safe_int(row.get("fifa_rank") or row.get("rank"))
        output = {
            "elo": rating,
            "rating_type": rating_type,
            "confederation": row.get("confederation") or row.get("confed") or row.get("confederation_code"),
            "aliases": aliases,
        }
        if fifa_rank is not None:
            output["fifa_rank"] = fifa_rank
        if source_field:
            output["source_field"] = source_field
        teams[team] = {key: value for key, value in output.items() if value not in (None, "", [])}
    return teams, skipped, field_counts


def load_required_teams(structure_path):
    if not structure_path or not structure_path.exists():
        return []
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    return sorted({team for group in structure.get("groups", {}).values() for team in group})


def build_output(imported_teams, input_metadata, args, existing_teams=None):
    teams = {}
    if existing_teams and args.merge_existing:
        teams.update(existing_teams)
    for team, row in imported_teams.items():
        existing = teams.get(team, {})
        aliases = merge_aliases(team, existing.get("aliases"), row.get("aliases"))
        merged = {**existing, **row}
        if aliases:
            merged["aliases"] = aliases
        teams[team] = merged

    source = args.source or input_metadata.get("source") or "user_supplied_national_team_elo"
    metadata = {
        "source": source,
        "source_url": args.source_url or input_metadata.get("source_url"),
        "as_of": args.as_of or input_metadata.get("as_of") or date.today().isoformat(),
        "created_at": date.today().isoformat(),
        "rating_priority": [
            "world_football_elo",
            "elo",
            "rating",
            "fifa_points",
            "points",
            "fifa_rank_derived_elo",
        ],
        "notes": [
            "This file can contain every men's national team; the simulator consumes the teams present in the tournament structure.",
            "If a row only has fifa_rank/rank, elo is estimated as 2170 - 130 * ln(rank).",
        ],
    }
    if args.rating_type:
        metadata["default_rating_type"] = args.rating_type
    return {"metadata": {key: value for key, value in metadata.items() if value}, "teams": dict(sorted(teams.items()))}


def validate_output(data, required_teams):
    teams = data["teams"]
    missing_required = [team for team in required_teams if team not in teams]
    rating_type_counts = {}
    confederation_missing = []
    alias_count = 0
    for team, row in teams.items():
        rating_type = row.get("rating_type", "unknown")
        rating_type_counts[rating_type] = rating_type_counts.get(rating_type, 0) + 1
        if not row.get("confederation"):
            confederation_missing.append(team)
        alias_count += len(row.get("aliases", []))
    return {
        "team_count": len(teams),
        "alias_count": alias_count,
        "missing_required_teams": missing_required,
        "rating_type_counts": rating_type_counts,
        "teams_missing_confederation": confederation_missing,
    }


def main():
    parser = argparse.ArgumentParser(description="Import all-national-team Elo/rating data into simulator JSON format.")
    parser.add_argument("--input", required=True, help="CSV or JSON file with team, rating/Elo/FIFA fields.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--structure", default=str(DEFAULT_STRUCTURE), help="Optional tournament structure for coverage validation.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--merge-existing", action="store_true", help="Merge imported rows into existing output instead of replacing it.")
    parser.add_argument("--source", default=None)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--rating-type", default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    structure_path = Path(args.structure) if args.structure else None
    rows, input_metadata = read_input_rows(input_path)
    imported_teams, skipped_rows, field_counts = build_team_rows(rows, alias_lookup(), default_rating_type=args.rating_type)
    existing_teams, _existing_metadata = read_existing(output_path)
    output = build_output(imported_teams, input_metadata, args, existing_teams=existing_teams)
    required_teams = load_required_teams(structure_path)
    validation = validate_output(output, required_teams)

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {
        "input": str(input_path),
        "output": str(output_path),
        "source_rows": len(rows),
        "imported_team_rows": len(imported_teams),
        "skipped_rows": skipped_rows,
        "source_field_counts": field_counts,
        "validation": validation,
    }
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {output_path}")
    print(f"wrote {args.report}")
    print(f"teams: {validation['team_count']}; missing required: {len(validation['missing_required_teams'])}")


if __name__ == "__main__":
    main()
