"""Evaluate frozen tournament forecasts against source-verified 2026 outcomes."""

import csv
import hashlib
import html
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "actual_results_comparison"
INPUT = ROOT / "simulation_10000_model_comparison"
STAGES = {"round_of_32": 32, "round_of_16": 16, "quarter_finals": 8,
          "semi_finals": 4, "final": 2, "champion": 1, "third_place": 1,
          "fourth_place": 1}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def table(rows, columns):
    def cell(value):
        return f"{value:.4f}" if isinstance(value, float) else str(value)
    return "\n".join(["| " + " | ".join(columns) + " |",
                      "| " + " | ".join("---" for _ in columns) + " |"] +
                     ["| " + " | ".join(cell(row[c]) for c in columns) + " |" for row in rows])


def main():
    actual = json.loads((OUT / "actual_outcomes.json").read_text(encoding="utf-8"))
    rows = read_csv(INPUT / "simulation_10000_model_team_summary.csv")
    metadata = read_csv(INPUT / "simulation_10000_model_metadata.csv")
    stages = {key: set(value) for key, value in actual["stages"].items()}
    for stage, count in STAGES.items():
        assert len(stages[stage]) == count, stage
    ordered = list(STAGES)[:6]
    for earlier, later in zip(ordered, ordered[1:]):
        assert stages[later] <= stages[earlier]
    scores, team_rows, summaries, scorers = [], [], [], []
    players = read_csv(INPUT / "simulation_10000_model_player_leaders.csv")
    for meta in metadata:
        model = meta["model_id"]
        subset = [row for row in rows if row["model_id"] == model]
        assert len(subset) == 48 and len({r["team"] for r in subset}) == 48
        frozen = json.loads((ROOT / meta["file"]).read_text(encoding="utf-8"))
        assert frozen["metadata"]["epochs"] == int(meta["epochs"])
        raw_teams = {row["team"]: row for row in frozen["results"]}
        for row in subset:
            for stage in STAGES:
                assert abs(float(row[stage + "_pct"]) - raw_teams[row["team"]][stage + "_pct"]) < 0.0001
        assert stages["round_of_32"] <= {r["team"] for r in subset}
        ranked = sorted(subset, key=lambda row: (-float(row["champion_pct"]), row["team"]))
        winner = next(row for row in subset if row["team"] == "Spain")
        champion_probs = [float(row["champion_pct"]) / 100 for row in subset]
        assert abs(sum(champion_probs) - 1) < 0.001
        summaries.append({"model": model, "primary": meta["primary_comparison"],
                          "predicted_winner": ranked[0]["team"],
                          "spain_rank": next(i + 1 for i, row in enumerate(ranked) if row["team"] == "Spain"),
                          "spain_champion_pct": float(winner["champion_pct"]),
                          "champion_log_loss": -math.log(float(winner["champion_pct"]) / 100),
                          "champion_brier_sum": sum((p - int(row["team"] == "Spain")) ** 2 for p, row in zip(champion_probs, subset))})
        for stage, count in STAGES.items():
            probs = [float(row[stage + "_pct"]) / 100 for row in subset]
            assert all(0 <= p <= 1 for p in probs)
            outcomes = [int(row["team"] in stages[stage]) for row in subset]
            brier = sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / 48
            baseline = (count / 48) * (1 - count / 48)
            top = sorted(subset, key=lambda row: (-float(row[stage + "_pct"]), row["team"]))[:count]
            scores.append({"model": model, "stage": stage, "brier_mean": brier,
                           "uniform_brier": baseline, "brier_skill": 1 - brier / baseline,
                           "top_k_hits": sum(row["team"] in stages[stage] for row in top), "k": count})
            for row, p, y in zip(subset, probs, outcomes):
                team_rows.append({"model": model, "team": row["team"], "stage": stage,
                                  "forecast_pct": p * 100, "actual_reached": y,
                                  "absolute_error": abs(p - y), "squared_error": (p - y) ** 2})
        mbappe = next(row for row in players if row["model_id"] == model and row["category"] == "goals" and row["player"] == "Kylian Mbappe")
        scorers.append({"model": model, "mbappe_scorer_rank": int(mbappe["rank"]),
                        "predicted_mean_goals": float(mbappe["goals_per_tournament"]), "actual_goals": 10})
    write_csv("model_scores.csv", scores)
    write_csv("team_stage_comparison.csv", team_rows)
    write_csv("champion_comparison.csv", summaries)
    write_csv("scorer_comparison.csv", scorers)
    hashes = {meta["file"]: hashlib.sha256((ROOT / meta["file"]).read_bytes()).hexdigest() for meta in metadata}
    (OUT / "prediction_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    primary = [m["model_id"] for m in metadata if m["primary_comparison"] == "True"]
    primary_scores = [s for s in scores if s["model"] in primary]
    aggregate = [{"model": model, "mean_six_stage_brier": sum(s["brier_mean"] for s in primary_scores if s["model"] == model and s["stage"] in ordered) / 6} for model in primary]
    best = min(aggregate, key=lambda r: r["mean_six_stage_brier"])
    largest = sorted([r for r in team_rows if r["model"] in primary and r["stage"] in ["quarter_finals", "semi_finals", "final"]], key=lambda r: r["absolute_error"], reverse=True)[:12]
    from comparison_visuals import generate_charts
    from comparison_latex import write_latex
    charts = generate_charts(OUT, rows, scores, summaries)
    text = "\n\n".join([
        "# FIFA World Cup 2026: simulation versus actual results\n\nPrepared 8 October 2026. Evaluation of frozen June outputs; no models were retrained for this comparison.",
        "## Actual outcome\n\nSpain beat Argentina 1-0 after extra time. England took third place and France fourth. Kylian Mbapp\u00e9 won the Golden Boot with 10 goals. See the linked FIFA sources below and actual_outcomes.json for all stage memberships.",
        "## Main findings\n\nNone of the three primary models ranked Spain first, although all placed Spain in their leading contenders. The baseline favoured France; both v2 variants favoured Brazil. The actual champion therefore had meaningful forecast support, but the favourite was wrong. " + f"Across the six advancement stages, {best['model']} has the lowest mean Brier score ({best['mean_six_stage_brier']:.4f}) in this tournament.",
        "## Champion forecasts\n\n" + table(summaries, ["model", "primary", "predicted_winner", "spain_rank", "spain_champion_pct", "champion_log_loss", "champion_brier_sum"]),
        "## Stage evaluation\n\n" + table(primary_scores, ["model", "stage", "brier_mean", "brier_skill", "top_k_hits", "k"]),
        "## Combined advancement score\n\n" + table(aggregate, ["model", "mean_six_stage_brier"]),
        "## Biggest discrepancies\n\n" + table(largest, ["model", "team", "stage", "forecast_pct", "actual_reached", "absolute_error"]),
        "Germany exited in the round of 32 and Brazil in the round of 16, despite strong v2 forecasts. Norway, Morocco, Belgium and Switzerland reached the quarter-finals. These outcomes expose the concentration of probability on stronger rated teams. They suggest reviewing upset frequency, bracket effects and data coverage; one tournament cannot establish which mechanism caused an error.",
        "## Golden Boot comparison\n\n" + table(scorers, ["model", "mbappe_scorer_rank", "predicted_mean_goals", "actual_goals"]) + "\n\nScorer rank is based on expected aggregate goals, not the probability of winning the Golden Boot. A player's mean over many tournaments is different from their observed goals in a single tournament. This is a descriptive comparison, not a calibrated award forecast.",
        "## Method and interpretation\n\nEach saved percentage is divided by 100 and compared with a binary indicator of reaching that stage, across all 48 teams. Brier mean is mean((p-y)^2); lower is better. Brier skill compares with a uniform stage probability k/48. Top-k hits measures overlap between the k highest forecast teams and the k actual qualifiers. Equal probabilities use alphabetical ordering. Champion log loss is -ln(P(Spain)); champion Brier is the sum across 48 mutually exclusive outcomes. The six-stage aggregate gives equal weight to reaching the round of 32, round of 16, quarter-finals, semi-finals, final and winning. Bronze results are excluded from that aggregate. Advancement outcomes are dependent, so these scores are descriptive and do not imply 288 independent observations.",
        "## Forecast provenance and limits\n\nEach compared model ran 10,000 tournaments. The two primary v2 outputs used FIFA-rank-derived Elo-scale priors, not the raw World Football Elo file imported later. The legacy squad-proxy model is reported separately from the primary comparison. Training used synthetic profile calibration; historical-match predictive accuracy was not established. Seeds whose numbers resemble later dates are random-number seeds, not creation timestamps. Local file timestamps do not prove that forecasts were published before kickoff: the artifacts were saved around the start of the tournament, and v2 files were last modified on 11 June. Treat this as retrospective evaluation of saved forecasts, not an independently audited pre-tournament backtest. Do not rerun using post-tournament inputs and label those outputs original predictions.",
        "Wilson intervals in earlier reports measure Monte Carlo sampling error conditional on the model; they do not capture uncertainty about football assumptions. One observed tournament cannot establish calibration or statistical superiority. Saved files do not provide probabilities for every actual match or every player, so match-level log loss, full player-goal error and causal attribution are outside this report. Group-exit membership is inferred from absence in the verified round-of-32 field. Exact final rankings among teams eliminated at the same stage are not inferred.",
        "## Next research steps\n\n1. Backtest on multiple historical tournaments using team and player information available at each match date.\n2. Calibrate draw, goal and upset rates on real international results.\n3. Check bracket routing and stronger-team probability concentration.\n4. Improve low-confidence player coverage and evaluate Golden Boot probabilities separately from mean goals.\n5. Publish dated forecast snapshots before future tournaments.",
        "## Reproduce and audit\n\nRun `python compare_simulation_with_actuals.py` from the repository root. Inputs: simulation_10000_model_comparison CSV files and the four frozen simulation_results JSON files. Outputs: this report, a printable HTML version, model scores, all team-stage comparisons, champion and scorer tables, plus SHA-256 hashes of the frozen predictions. Source-name mappings are recorded in actual_outcomes.json.",
        "## Sources\n\n" + "\n".join(f"- [{label}]({url})" for label, url in actual["sources"].items())
    ]) + "\n"
    visual_section = "## Charts and diagrams\n\n" + "\n\n".join(
        f"### {title}\n\n![{title}]({name})\n\n{caption}" for name, title, caption, _ in charts)
    text = text.replace("## Champion forecasts", visual_section + "\n\n## Champion forecasts", 1)
    text = text.replace("# FIFA World Cup 2026: simulation versus actual results", "# FIFA World Cup 2026: simulation versus actual results\n\nFull research report: [comprehensive LaTeX PDF](comprehensive_report.pdf), including abstract, contents, model introductions and dataset provenance. [Dataset source register](dataset_sources.csv).", 1)
    (OUT / "comparison_report.md").write_text(text, encoding="utf-8")
    write_latex(OUT, summaries, scores, aggregate, largest, scorers, actual)
    blocks = []
    for block in text.split("\n\n"):
        if block.startswith("!["):
            match = re.fullmatch(r"!\[([^]]+)\]\(([^)]+)\)", block.strip())
            blocks.append(f'<figure><img src="{html.escape(match[2], quote=True)}" alt="{html.escape(match[1], quote=True)}"></figure>')
        elif block.startswith("| "):
            lines = block.splitlines()
            cells = lambda line, tag: "<tr>" + "".join(f"<{tag}>{html.escape(c.strip())}</{tag}>" for c in line.strip("|").split("|")) + "</tr>"
            blocks.append("<div class='table'><table>" + cells(lines[0], "th") + "".join(cells(line, "td") for line in lines[2:]) + "</table></div>")
        elif block.startswith("#"):
            heading, _, rest = block.partition("\n")
            level = len(heading) - len(heading.lstrip("#"))
            blocks.append(f"<h{level}>{html.escape(heading.lstrip('# '))}</h{level}>" + (f"<p>{html.escape(rest)}</p>" if rest else ""))
        else:
            blocks.append("<p>" + html.escape(block).replace("\n", "<br>") + "</p>")
    style = "body{font:16px/1.6 Arial,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#202124}h1{font-size:30px}h2{font-size:22px;margin-top:36px}.table{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%}th,td{padding:8px;border:1px solid #ddd;text-align:left}th{background:#edf2f3}@media print{body{margin:0;padding:0}table{font-size:9px}tr{break-inside:avoid}}"
    style += "figure{margin:20px 0}figure img{display:block;width:100%;height:auto}figure{break-inside:avoid}h3{font-size:18px}"
    (OUT / "comparison_report.html").write_text("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>World Cup 2026 forecast evaluation</title><style>" + style + "</style><body>" + "".join(blocks) + "</body></html>", encoding="utf-8")
    print(json.dumps({"models": len(metadata), "team_stage_rows": len(team_rows), "best_primary_advancement_model": best}, indent=2))


if __name__ == "__main__":
    main()
