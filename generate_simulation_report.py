import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


COLORS = {
    "blue": "#2563eb",
    "green": "#16a34a",
    "amber": "#d97706",
    "red": "#dc2626",
    "purple": "#7c3aed",
    "slate": "#334155",
    "grid": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#64748b",
}


def pct(value):
    return f"{value:.1f}%"


def write(path, content):
    path.write_text(content, encoding="utf-8")


def bar_chart(report_dir, rows, label_key, value_key, title, filename, color=COLORS["blue"], width=980, row_h=30):
    rows = rows[:20]
    left = 190
    right = 80
    top = 58
    height = top + len(rows) * row_h + 44
    max_v = max(row[value_key] for row in rows) or 1
    plot_w = width - left - right
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700" fill="{COLORS["text"]}">{html.escape(title)}</text>',
    ]
    for i, row in enumerate(rows):
        y = top + i * row_h
        value = row[value_key]
        bar_w = plot_w * value / max_v
        label = html.escape(str(row[label_key]))
        parts.append(f'<text x="24" y="{y + 20}" font-family="Arial" font-size="14" fill="{COLORS["text"]}">{label}</text>')
        parts.append(f'<rect x="{left}" y="{y + 5}" width="{bar_w:.2f}" height="18" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{left + bar_w + 8:.2f}" y="{y + 20}" font-family="Arial" font-size="13" fill="{COLORS["muted"]}">{value:.2f}</text>')
    parts.append("</svg>")
    path = report_dir / filename
    write(path, "\n".join(parts))
    return filename


def stage_heatmap(report_dir, rows):
    stages = [
        ("round_of_32_pct", "R32"),
        ("round_of_16_pct", "R16"),
        ("quarter_finals_pct", "QF"),
        ("semi_finals_pct", "SF"),
        ("final_pct", "Final"),
        ("third_place_pct", "3rd"),
        ("champion_pct", "Win"),
    ]
    rows = rows[:]
    width = 980
    left = 180
    top = 72
    cell_w = 96
    cell_h = 30
    height = top + len(rows) * cell_h + 44
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700" fill="{COLORS["text"]}">Stage Probability Heatmap</text>',
    ]
    for j, (_, label) in enumerate(stages):
        x = left + j * cell_w
        parts.append(f'<text x="{x + cell_w / 2}" y="58" text-anchor="middle" font-family="Arial" font-size="13" font-weight="700" fill="{COLORS["muted"]}">{label}</text>')
    for i, row in enumerate(rows):
        y = top + i * cell_h
        parts.append(f'<text x="24" y="{y + 20}" font-family="Arial" font-size="14" fill="{COLORS["text"]}">{html.escape(row["team"])}</text>')
        for j, (key, _) in enumerate(stages):
            value = row[key]
            intensity = min(1.0, value / 100)
            blue = int(245 - intensity * 145)
            green = int(249 - intensity * 118)
            red = int(239 - intensity * 202)
            x = left + j * cell_w
            parts.append(f'<rect x="{x}" y="{y + 3}" width="{cell_w - 8}" height="23" rx="3" fill="rgb({red},{green},{blue})"/>')
            parts.append(f'<text x="{x + (cell_w - 8) / 2}" y="{y + 20}" text-anchor="middle" font-family="Arial" font-size="12" fill="{COLORS["text"]}">{pct(value)}</text>')
    parts.append("</svg>")
    filename = "stage_probability_heatmap.svg"
    write(report_dir / filename, "\n".join(parts))
    return filename


def scatter_chart(report_dir, rows):
    width = 980
    height = 560
    left = 70
    right = 42
    top = 60
    bottom = 60
    xs = [row["team_rating"] for row in rows]
    ys = [row["champion_pct"] for row in rows]
    min_x, max_x = min(xs) - 1, max(xs) + 1
    min_y, max_y = 0, max(ys) + 2
    plot_w = width - left - right
    plot_h = height - top - bottom

    def xmap(value):
        return left + (value - min_x) / (max_x - min_x) * plot_w

    def ymap(value):
        return top + plot_h - (value - min_y) / (max_y - min_y) * plot_h

    top_labels = {row["team"] for row in sorted(rows, key=lambda r: r["champion_pct"], reverse=True)[:10]}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700" fill="{COLORS["text"]}">Team Rating vs Champion Probability</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="{COLORS["grid"]}"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="{COLORS["grid"]}"/>',
        f'<text x="{left + plot_w / 2}" y="{height - 18}" text-anchor="middle" font-family="Arial" font-size="13" fill="{COLORS["muted"]}">EAFC-derived team rating</text>',
        f'<text x="18" y="{top + plot_h / 2}" transform="rotate(-90 18 {top + plot_h / 2})" text-anchor="middle" font-family="Arial" font-size="13" fill="{COLORS["muted"]}">Champion probability</text>',
    ]
    for row in rows:
        x = xmap(row["team_rating"])
        y = ymap(row["champion_pct"])
        radius = 4 + min(8, row["round_of_32_pct"] / 14)
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{COLORS["purple"]}" opacity="0.72"/>')
        if row["team"] in top_labels:
            parts.append(f'<text x="{x + 8:.2f}" y="{y - 6:.2f}" font-family="Arial" font-size="12" fill="{COLORS["text"]}">{html.escape(row["team"])}</text>')
    parts.append("</svg>")
    filename = "rating_vs_champion.svg"
    write(report_dir / filename, "\n".join(parts))
    return filename


def html_report(data, chart_files):
    top_results = data["results"][:12]
    top_goals = sorted(data["player_stats"], key=lambda r: (r["goals"], r["assists"], r["rating"]), reverse=True)[:12]
    top_assists = sorted(data["player_stats"], key=lambda r: (r["assists"], r["goals"], r["rating"]), reverse=True)[:12]
    metadata = data["metadata"]
    cards = [
        ("Epochs", metadata["epochs"]),
        ("Matched Ratings", f'{metadata["rating_match_summary"]["matched"]}/{metadata["rating_match_summary"]["total"]}'),
        ("Fallback Ratings", metadata["rating_match_summary"]["fallback"]),
        ("Top Champion", f'{top_results[0]["team"]} ({pct(top_results[0]["champion_pct"])})'),
    ]
    card_html = "\n".join(f'<div class="card"><span>{label}</span><strong>{value}</strong></div>' for label, value in cards)

    def table(rows, columns):
        head = "".join(f"<th>{html.escape(label)}</th>" for label, _ in columns)
        body = []
        for row in rows:
            cells = "".join(f"<td>{html.escape(str(row[key]))}</td>" for _, key in columns)
            body.append(f"<tr>{cells}</tr>")
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    top_team_table = table(
        top_results,
        [("Team", "team"), ("Rating", "team_rating"), ("R32 %", "round_of_32_pct"), ("Final %", "final_pct"), ("3rd %", "third_place_pct"), ("Win %", "champion_pct")],
    )
    scorer_table = table(top_goals, [("Player", "name"), ("Team", "team"), ("Pos", "position"), ("Goals", "goals"), ("G/Tourn", "goals_per_tournament")])
    assist_table = table(top_assists, [("Player", "name"), ("Team", "team"), ("Pos", "position"), ("Assists", "assists"), ("A/Tourn", "assists_per_tournament")])

    charts = "\n".join(f'<section><img src="{file}" alt="{file}"></section>' for file in chart_files)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>World Cup 2026 Simulation Report</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #0f172a; background: #f8fafc; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    p {{ color: #475569; line-height: 1.45; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
    .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .card strong {{ display: block; margin-top: 8px; font-size: 20px; }}
    section {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; margin: 16px 0; padding: 14px; overflow-x: auto; }}
    img {{ max-width: 100%; height: auto; display: block; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #e2e8f0; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 14px; }}
    th {{ color: #475569; background: #f1f5f9; }}
    @media (max-width: 800px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
<main>
  <h1>World Cup 2026 Simulation Report</h1>
  <p>Primitive 1,000-epoch simulation using EAFC-derived player ratings, Poisson match scoring, and player-level goal/assist attribution.</p>
  <div class="cards">{card_html}</div>
  {charts}
  <h2>Top Teams</h2>
  {top_team_table}
  <h2>Top Simulated Scorers</h2>
  {scorer_table}
  <h2>Top Simulated Assisters</h2>
  {assist_table}
</main>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="simulation_results_1000.json")
    parser.add_argument("--report-dir", default="simulation_report")
    args = parser.parse_args()

    results_file = ROOT / args.results
    report_dir = ROOT / args.report_dir
    report_dir.mkdir(exist_ok=True)
    data = json.loads(results_file.read_text(encoding="utf-8"))
    chart_files = [
        bar_chart(report_dir, data["results"], "team", "champion_pct", "Champion Probability, Top 20", "champion_probability.svg", COLORS["blue"]),
        stage_heatmap(report_dir, data["results"]),
        scatter_chart(report_dir, data["results"]),
        bar_chart(
            report_dir,
            sorted(data["player_stats"], key=lambda r: (r["goals"], r["assists"], r["rating"]), reverse=True),
            "name",
            "goals",
            "Top Simulated Goalscorers, Aggregate Goals",
            "top_scorers.svg",
            COLORS["green"],
        ),
        bar_chart(
            report_dir,
            sorted(data["player_stats"], key=lambda r: (r["assists"], r["goals"], r["rating"]), reverse=True),
            "name",
            "assists",
            "Top Simulated Assist Providers, Aggregate Assists",
            "top_assisters.svg",
            COLORS["amber"],
        ),
    ]
    write(report_dir / "index.html", html_report(data, chart_files))
    write(report_dir / "topline_summary.json", json.dumps({
        "metadata": data["metadata"],
        "top_teams": data["results"][:12],
        "top_scorers": sorted(data["player_stats"], key=lambda r: (r["goals"], r["assists"], r["rating"]), reverse=True)[:20],
        "top_assisters": sorted(data["player_stats"], key=lambda r: (r["assists"], r["goals"], r["rating"]), reverse=True)[:20],
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {report_dir / 'index.html'}")
    print(f"wrote {report_dir / 'topline_summary.json'}")


if __name__ == "__main__":
    main()
