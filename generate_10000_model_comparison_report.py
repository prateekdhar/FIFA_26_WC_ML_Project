import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "simulation_10000_model_comparison"

MODEL_RUNS = [
    {
        "model_id": "primitive_eafc_poisson",
        "label": "Primitive EAFC Poisson",
        "path": ROOT / "simulation_results_10000.json",
        "primary": True,
    },
    {
        "model_id": "v2_heuristic_nt_elo",
        "label": "V2 Heuristic Internal Forest + NT Elo",
        "path": ROOT / "simulation_results_v2_heuristic_10000.json",
        "primary": True,
    },
    {
        "model_id": "v2_random_forest_nt_elo",
        "label": "V2 sklearn Random Forest + NT Elo",
        "path": ROOT / "simulation_results_v2_rf_elo_10000.json",
        "primary": True,
    },
    {
        "model_id": "v2_random_forest_squad_proxy_legacy",
        "label": "V2 sklearn Random Forest + squad-proxy Elo legacy",
        "path": ROOT / "simulation_results_v2_rf_10000.json",
        "primary": False,
    },
]


TEAM_COLUMNS = [
    "model_id",
    "model_label",
    "primary_comparison",
    "team",
    "champion_pct",
    "final_pct",
    "semi_finals_pct",
    "quarter_finals_pct",
    "round_of_16_pct",
    "round_of_32_pct",
    "third_place_pct",
    "fourth_place_pct",
    "average_group_points",
    "average_group_goal_difference",
    "team_rating",
    "squad_rating",
    "nt_elo",
    "fouls_per_tournament",
    "yellow_cards_per_tournament",
    "red_cards_per_tournament",
    "substitutions_per_tournament",
    "set_piece_goals_per_tournament",
    "possession_tick_share",
]


def pct(value):
    if pd.isna(value):
        return ""
    return f"{float(value):.2f}%"


def num(value, digits=2):
    if pd.isna(value):
        return ""
    return f"{float(value):.{digits}f}"


def markdown_table(df, columns=None):
    if columns:
        df = df.loc[:, columns]
    if df.empty:
        return "_No rows._"
    display = df.copy().fillna("")
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.3f}" if value != "" else "")
        else:
            display[column] = display[column].astype(str)
    headers = [str(column) for column in display.columns]
    rows = display.values.tolist()
    widths = [
        max(len(header), *(len(str(row[index])) for row in rows))
        for index, header in enumerate(headers)
    ]

    def fmt_row(values):
        return "| " + " | ".join(str(value).ljust(widths[index]) for index, value in enumerate(values)) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([fmt_row(headers), separator, *(fmt_row(row) for row in rows)])


def load_runs():
    loaded = []
    for config in MODEL_RUNS:
        if not config["path"].exists():
            continue
        data = json.loads(config["path"].read_text(encoding="utf-8"))
        metadata = data.get("metadata", {})
        if metadata.get("epochs") != 10000:
            continue
        loaded.append({**config, "data": data, "metadata": metadata})
    return loaded


def team_rows(runs):
    rows = []
    for run in runs:
        for team in run["data"].get("results", []):
            row = {
                "model_id": run["model_id"],
                "model_label": run["label"],
                "primary_comparison": run["primary"],
                "team": team.get("team"),
            }
            for column in TEAM_COLUMNS:
                if column not in row:
                    row[column] = team.get(column)
            rows.append(row)
    return pd.DataFrame(rows, columns=TEAM_COLUMNS)


def metadata_rows(runs):
    rows = []
    for run in runs:
        metadata = run["metadata"]
        status = metadata.get("decision_forest_status") or {}
        rows.append(
            {
                "model_id": run["model_id"],
                "model_label": run["label"],
                "primary_comparison": run["primary"],
                "file": run["path"].name,
                "epochs": metadata.get("epochs"),
                "seed": metadata.get("seed"),
                "workers": metadata.get("workers", ""),
                "elo_source": metadata.get("elo_source", ""),
                "decision_forest_kind": status.get("kind", "none"),
                "training_source": status.get("training_source", ""),
                "training_rows": status.get("training_rows", ""),
                "training_accuracy": status.get("training_accuracy", ""),
                "features_output": metadata.get("features_output", ""),
            }
        )
    return pd.DataFrame(rows)


def player_leader_rows(runs, limit=15):
    rows = []
    for run in runs:
        players = pd.DataFrame(run["data"].get("player_stats", []))
        if players.empty:
            continue
        for column in ["goals", "assists", "goals_per_tournament", "assists_per_tournament"]:
            if column not in players.columns:
                players[column] = 0
        for category, sort_columns in {
            "goals": ["goals", "assists"],
            "assists": ["assists", "goals"],
        }.items():
            leaders = players.sort_values(sort_columns, ascending=False).head(limit)
            for rank, row in enumerate(leaders.to_dict("records"), start=1):
                rows.append(
                    {
                        "model_id": run["model_id"],
                        "model_label": run["label"],
                        "primary_comparison": run["primary"],
                        "category": category,
                        "rank": rank,
                        "player": row.get("name"),
                        "team": row.get("team"),
                        "position": row.get("position"),
                        "goals": row.get("goals", 0),
                        "assists": row.get("assists", 0),
                        "goals_per_tournament": row.get("goals_per_tournament", 0),
                        "assists_per_tournament": row.get("assists_per_tournament", 0),
                    }
                )
    return pd.DataFrame(rows)


def champion_matrix(team_df):
    matrix = team_df.pivot_table(index="team", columns="model_id", values="champion_pct", aggfunc="first").reset_index()
    model_columns = [column for column in matrix.columns if column != "team"]
    matrix["primary_average_champion_pct"] = matrix[
        [column for column in model_columns if column != "v2_random_forest_squad_proxy_legacy"]
    ].mean(axis=1)
    matrix["all_model_range_pct"] = matrix[model_columns].max(axis=1) - matrix[model_columns].min(axis=1)
    return matrix.sort_values("primary_average_champion_pct", ascending=False)


def top_by_model(team_df, n=12):
    return (
        team_df.sort_values(["model_id", "champion_pct"], ascending=[True, False])
        .groupby("model_id", group_keys=False)
        .head(n)
        .reset_index(drop=True)
    )


def write_report(output_dir, runs, metadata_df, team_df, matrix_df, players_df):
    primary_team_df = team_df[team_df["primary_comparison"] == True].copy()
    model_winners = (
        primary_team_df.sort_values(["model_id", "champion_pct"], ascending=[True, False])
        .groupby("model_id", group_keys=False)
        .head(1)
        [["model_label", "team", "champion_pct", "final_pct", "semi_finals_pct"]]
        .reset_index(drop=True)
    )
    consensus = matrix_df[
        ["team", "primary_average_champion_pct", "all_model_range_pct"]
        + [run["model_id"] for run in runs if run["primary"]]
    ].head(12)
    disagreements = matrix_df.sort_values("all_model_range_pct", ascending=False).head(12)
    top_champions = top_by_model(team_df, 10)[
        ["model_label", "team", "champion_pct", "final_pct", "semi_finals_pct", "average_group_points"]
    ]
    v2_events = team_df[
        (team_df["model_id"].isin(["v2_heuristic_nt_elo", "v2_random_forest_nt_elo"]))
        & (team_df["champion_pct"] > 0)
    ].sort_values(["model_id", "red_cards_per_tournament"], ascending=[True, False])[
        [
            "model_label",
            "team",
            "fouls_per_tournament",
            "yellow_cards_per_tournament",
            "red_cards_per_tournament",
            "substitutions_per_tournament",
            "possession_tick_share",
        ]
    ].groupby("model_label", group_keys=False).head(8)
    top_scorers = players_df[
        (players_df["primary_comparison"] == True) & (players_df["category"] == "goals") & (players_df["rank"] <= 8)
    ][["model_label", "rank", "player", "team", "position", "goals", "goals_per_tournament"]]
    top_assisters = players_df[
        (players_df["primary_comparison"] == True) & (players_df["category"] == "assists") & (players_df["rank"] <= 8)
    ][["model_label", "rank", "player", "team", "position", "assists", "assists_per_tournament"]]

    lines = [
        "# FIFA WC26 10,000-Simulation Model Report",
        "",
        "This report compares the stored 10,000-epoch runs across the project models. The primary comparison uses the current runs where available; the older Random Forest squad-proxy run is retained as a legacy reference.",
        "",
        "## Model Inventory",
        "",
        markdown_table(metadata_df),
        "",
        "## Top Winner Per Primary Model",
        "",
        markdown_table(model_winners),
        "",
        "## Consensus Champion Board",
        "",
        "Average champion probability is calculated across the primary runs: primitive EAFC Poisson, v2 heuristic with NT Elo, and v2 Random Forest with NT Elo.",
        "",
        markdown_table(consensus),
        "",
        "## Top Champion Probabilities By Model",
        "",
        markdown_table(top_champions),
        "",
        "## Biggest Model Disagreements",
        "",
        "These are the teams whose title probability moves most across all stored 10,000-run variants.",
        "",
        markdown_table(disagreements.head(12)),
        "",
        "## V2 Event-Model Discipline And Load Snapshot",
        "",
        markdown_table(v2_events),
        "",
        "## Top Scorers",
        "",
        markdown_table(top_scorers),
        "",
        "## Top Assisters",
        "",
        markdown_table(top_assisters),
        "",
        "## Caveats",
        "",
        "- The primitive model is intentionally simpler: EAFC-overall team strength plus Poisson goals.",
        "- The v2 Random Forest and v2 heuristic runs include compressed match events, possession, cards, fatigue, substitutions, set pieces, extra time, and penalties.",
        "- The current v2 NT Elo runs use the FIFA-rank-derived Elo-scale prior, not raw World Football Elo.",
        "- The Random Forest is trained on synthetic calibration rows because no historical international match CSV has been supplied yet.",
        "- The legacy v2 Random Forest squad-proxy file is included to preserve prior output, but it should not be treated as the main current RF estimate.",
        "",
    ]
    report_path = output_dir / "simulation_10000_models_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = load_runs()
    if not runs:
        raise SystemExit("No 10,000-epoch simulation result files were found.")

    metadata_df = metadata_rows(runs)
    team_df = team_rows(runs)
    players_df = player_leader_rows(runs)
    matrix_df = champion_matrix(team_df)

    metadata_df.to_csv(OUTPUT_DIR / "simulation_10000_model_metadata.csv", index=False)
    team_df.to_csv(OUTPUT_DIR / "simulation_10000_model_team_summary.csv", index=False)
    players_df.to_csv(OUTPUT_DIR / "simulation_10000_model_player_leaders.csv", index=False)
    matrix_df.to_csv(OUTPUT_DIR / "simulation_10000_model_champion_matrix.csv", index=False)
    report_path = write_report(OUTPUT_DIR, runs, metadata_df, team_df, matrix_df, players_df)

    print(f"wrote {report_path}")
    print("top primary winners:")
    primary = team_df[team_df["primary_comparison"] == True]
    for row in (
        primary.sort_values(["model_id", "champion_pct"], ascending=[True, False])
        .groupby("model_id", group_keys=False)
        .head(1)
        .itertuples(index=False)
    ):
        print(f"{row.model_label}: {row.team} {row.champion_pct:.2f}%")


if __name__ == "__main__":
    main()
