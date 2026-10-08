import argparse
import csv
import json
import shutil
import urllib.request
from datetime import date
from pathlib import Path

from import_national_team_elo import (
    DEFAULT_OUTPUT as DEFAULT_ELO_OUTPUT,
    DEFAULT_REPORT as DEFAULT_ELO_REPORT,
    DEFAULT_STRUCTURE,
    alias_lookup,
    build_output,
    build_team_rows,
    load_required_teams,
    read_existing,
    read_input_rows,
    validate_output,
)


ROOT = Path(__file__).resolve().parent
EXTERNAL_DIR = ROOT / "external_data" / "international_results"
DEFAULT_RAW_RESULTS = EXTERNAL_DIR / "results.csv"
DEFAULT_NORMALIZED_RESULTS = ROOT / "historical_international_results.csv"
DEFAULT_MANIFEST = ROOT / "external_football_data_manifest.json"
DEFAULT_ELO_TEMPLATE = ROOT / "world_football_elo_current_template.csv"

INTERNATIONAL_RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
INTERNATIONAL_RESULTS_REPO = "https://github.com/martj42/international_results"
WORLD_FOOTBALL_ELO_URL = "https://www.eloratings.net/"


def download_file(url, output_path, timeout=60):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FIFA-WC26-simulation-data-loader/1.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with output_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return output_path


def bool_text(value):
    text = str(value).strip().lower()
    return "TRUE" if text in {"true", "1", "yes", "y"} else "FALSE"


def normalize_international_results(raw_path, normalized_path):
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    source_rows = 0
    written_rows = 0
    skipped_rows = 0
    teams = set()
    tournaments = set()
    date_min = None
    date_max = None
    output_columns = [
        "date",
        "team_a",
        "team_b",
        "goals_a",
        "goals_b",
        "tournament",
        "neutral",
        "city",
        "country",
        "source",
    ]
    with raw_path.open("r", encoding="utf-8-sig", newline="") as source, normalized_path.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=output_columns)
        writer.writeheader()
        required = {"date", "home_team", "away_team", "home_score", "away_score", "tournament", "neutral"}
        missing = sorted(required.difference(reader.fieldnames or []))
        if missing:
            raise ValueError(f"{raw_path} is missing required columns: {', '.join(missing)}")
        for row in reader:
            source_rows += 1
            if not row.get("home_team") or not row.get("away_team"):
                skipped_rows += 1
                continue
            try:
                goals_a = int(float(row["home_score"]))
                goals_b = int(float(row["away_score"]))
            except (TypeError, ValueError):
                skipped_rows += 1
                continue
            match_date = row.get("date", "").strip()
            if match_date:
                date_min = match_date if date_min is None or match_date < date_min else date_min
                date_max = match_date if date_max is None or match_date > date_max else date_max
            team_a = row["home_team"].strip()
            team_b = row["away_team"].strip()
            tournament = row.get("tournament", "").strip()
            teams.update([team_a, team_b])
            if tournament:
                tournaments.add(tournament)
            writer.writerow(
                {
                    "date": match_date,
                    "team_a": team_a,
                    "team_b": team_b,
                    "goals_a": goals_a,
                    "goals_b": goals_b,
                    "tournament": tournament,
                    "neutral": bool_text(row.get("neutral")),
                    "city": row.get("city", "").strip(),
                    "country": row.get("country", "").strip(),
                    "source": "martj42/international_results:results.csv",
                }
            )
            written_rows += 1
    return {
        "raw_file": str(raw_path),
        "normalized_file": str(normalized_path),
        "source_rows": source_rows,
        "written_rows": written_rows,
        "skipped_rows": skipped_rows,
        "teams": len(teams),
        "tournaments": len(tournaments),
        "date_min": date_min,
        "date_max": date_max,
        "source_repo": INTERNATIONAL_RESULTS_REPO,
        "source_url": INTERNATIONAL_RESULTS_URL,
    }


def write_elo_template(path=DEFAULT_ELO_TEMPLATE):
    rows = [
        {
            "team": "Spain",
            "world_football_elo": 2172,
            "confederation": "UEFA",
            "fifa_rank": 1,
            "aliases": "Spain",
        },
        {
            "team": "Argentina",
            "world_football_elo": 2113,
            "confederation": "CONMEBOL",
            "fifa_rank": 2,
            "aliases": "Argentina",
        },
        {
            "team": "France",
            "world_football_elo": 2063,
            "confederation": "UEFA",
            "fifa_rank": 3,
            "aliases": "France",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team", "world_football_elo", "confederation", "fifa_rank", "aliases"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def import_world_football_elo(input_path, output_path, report_path, source, source_url, as_of, merge_existing=True):
    rows, input_metadata = read_input_rows(input_path)
    imported_teams, skipped, field_counts = build_team_rows(rows, alias_lookup(), default_rating_type="world_football_elo")
    existing_teams, _existing_metadata = read_existing(output_path)
    args = argparse.Namespace(
        source=source,
        source_url=source_url,
        as_of=as_of,
        rating_type="world_football_elo",
        merge_existing=merge_existing,
    )
    data = build_output(imported_teams, input_metadata, args, existing_teams=existing_teams)
    required_teams = load_required_teams(DEFAULT_STRUCTURE)
    validation = validate_output(data, required_teams)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {
        "input": str(input_path),
        "output": str(output_path),
        "source": source,
        "source_url": source_url,
        "as_of": as_of,
        "imported_team_count": len(imported_teams),
        "skipped_rows": skipped,
        "field_counts": field_counts,
        **validation,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_manifest(path, results_status=None, elo_status=None):
    manifest = {
        "created_at": date.today().isoformat(),
        "sources": {
            "international_results": {
                "repo": INTERNATIONAL_RESULTS_REPO,
                "raw_results_url": INTERNATIONAL_RESULTS_URL,
                "raw_results_file": str(DEFAULT_RAW_RESULTS),
                "normalized_results_file": str(DEFAULT_NORMALIZED_RESULTS),
                "status": results_status or {},
            },
            "world_football_elo": {
                "source_url": WORLD_FOOTBALL_ELO_URL,
                "template_file": str(DEFAULT_ELO_TEMPLATE),
                "target_file": str(DEFAULT_ELO_OUTPUT),
                "status": elo_status or {},
                "note": "Use a local CSV/JSON with team and world_football_elo columns, then run this script with --world-football-elo-file.",
            },
        },
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Fetch and normalize external football data for the FIFA WC26 simulator.")
    parser.add_argument("--download-international-results", action="store_true", help="Download martj42/international_results results.csv.")
    parser.add_argument("--raw-results", default=str(DEFAULT_RAW_RESULTS), help="Raw martj42 results.csv path.")
    parser.add_argument("--results-url", default=INTERNATIONAL_RESULTS_URL)
    parser.add_argument("--normalized-results", default=str(DEFAULT_NORMALIZED_RESULTS), help="Simulator-ready historical match CSV.")
    parser.add_argument("--world-football-elo-file", default=None, help="CSV/JSON with team and world_football_elo columns.")
    parser.add_argument("--elo-output", default=str(DEFAULT_ELO_OUTPUT))
    parser.add_argument("--elo-report", default=str(DEFAULT_ELO_REPORT))
    parser.add_argument("--elo-source", default="World Football Elo Ratings")
    parser.add_argument("--elo-source-url", default=WORLD_FOOTBALL_ELO_URL)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--no-merge-existing-elo", action="store_true")
    parser.add_argument("--write-templates", action="store_true")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()

    results_status = {}
    elo_status = {}
    raw_results = Path(args.raw_results)
    normalized_results = Path(args.normalized_results)

    if args.download_international_results:
        try:
            download_file(args.results_url, raw_results)
            results_status["downloaded"] = True
        except Exception as exc:
            results_status["downloaded"] = False
            results_status["download_error"] = str(exc)

    if raw_results.exists():
        try:
            results_status.update(normalize_international_results(raw_results, normalized_results))
        except Exception as exc:
            results_status["normalized"] = False
            results_status["normalize_error"] = str(exc)
    elif args.download_international_results:
        results_status.setdefault("normalized", False)
        results_status.setdefault("normalize_error", "Raw results file was not available after download attempt.")

    if args.write_templates or args.world_football_elo_file:
        elo_status["template_file"] = str(write_elo_template())

    if args.world_football_elo_file:
        elo_input = Path(args.world_football_elo_file)
        if elo_input.exists():
            try:
                elo_status.update(
                    import_world_football_elo(
                        elo_input,
                        Path(args.elo_output),
                        Path(args.elo_report),
                        args.elo_source,
                        args.elo_source_url,
                        args.as_of,
                        merge_existing=not args.no_merge_existing_elo,
                    )
                )
            except Exception as exc:
                elo_status["imported"] = False
                elo_status["import_error"] = str(exc)
        else:
            elo_status["imported"] = False
            elo_status["import_error"] = f"Missing Elo file: {elo_input}"

    manifest = write_manifest(Path(args.manifest), results_status=results_status, elo_status=elo_status)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
