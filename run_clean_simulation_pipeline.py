import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
PDF = ROOT / "fifa_squadlists_english.pdf"


def run(args):
    print(">", " ".join(str(arg) for arg in args))
    subprocess.run(args, cwd=ROOT, check=True)


def validate_clean_squads():
    data = json.loads((ROOT / "guardian_world_cup_2026_player_guide.json").read_text(encoding="utf-8"))
    problems = []
    for team in data["teams"]:
        counts = {}
        for player in team["players"]:
            counts[player["position"]] = counts.get(player["position"], 0) + 1
        if len(team["players"]) != 26:
            problems.append((team["country"], f"players={len(team['players'])}"))
        if counts.get("GK", 0) < 3:
            problems.append((team["country"], f"goalkeepers={counts.get('GK', 0)}"))
    if len(data["teams"]) != 48:
        problems.append(("ALL", f"teams={len(data['teams'])}"))
    if problems:
        raise SystemExit(f"Squad validation failed: {problems[:20]}")


def validate_enriched_squads():
    data = json.loads((ROOT / "guardian_world_cup_2026_player_guide.json").read_text(encoding="utf-8"))
    unresolved = []
    for team in data["teams"]:
        for player in team["players"]:
            if player.get("position") in {"DF", "MF", "FW"} or "rating" not in player:
                unresolved.append((team["country"], player.get("name"), player.get("position"), player.get("rating")))
    if unresolved:
        raise SystemExit(f"Enrichment validation failed: {unresolved[:20]}")


def main():
    if not PDF.exists():
        raise SystemExit(
            f"Missing {PDF.name}. Save FIFA's official squad PDF at {PDF} first:\n"
            "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf"
        )
    run([PYTHON, "rebuild_squads_from_fifa_pdf.py", "--pdf", str(PDF)])
    validate_clean_squads()
    run([PYTHON, "enrich_squads_with_eafc.py"])
    validate_enriched_squads()
    run([PYTHON, "simulate_world_cup.py", "--epochs", "1000", "--seed", "20260605", "--output", "simulation_results_1000.json"])
    run([PYTHON, "generate_simulation_report.py"])
    print("clean simulation pipeline complete")


if __name__ == "__main__":
    main()
