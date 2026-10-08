import argparse
import csv
import html
import json
import math
import os
import warnings
from collections import Counter
from datetime import date
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
warnings.filterwarnings("ignore", message="Could not find the number of physical cores.*", category=UserWarning)

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from simulate_world_cup_v2 import (
    DEFAULT_ELO_FILE,
    ML_FEATURE_NAMES,
    ROOT,
    STRUCTURE_FILE,
    build_synthetic_training_data,
    build_team_profiles,
    read_historical_training_data,
)

CLASS_ORDER = ["A", "B", "D"]
HISTORICAL_CANDIDATES = [
    ROOT / "historical_international_results.csv",
    ROOT / "international_results.csv",
    ROOT / "results.csv",
    ROOT / "external_data" / "international_results" / "results.csv",
    ROOT / "data" / "historical_international_results.csv",
    ROOT / "data" / "results.csv",
]
SIMULATION_TEAM_SUMMARY = ROOT / "simulation_10000_model_comparison" / "simulation_10000_model_team_summary.csv"

DATA_SOURCES = [
    {
        "name": "International football results",
        "purpose": "Historical match outcomes for supervised model training and calibration",
        "url": "https://raw.githubusercontent.com/martj42/international_results/master/results.csv",
        "local_filename": "external_data/international_results/results.csv or historical_international_results.csv",
        "expected_columns": "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral",
        "status": "download_blocked_in_workspace; place the CSV locally to activate historical training",
    },
    {
        "name": "World Football Elo Ratings",
        "purpose": "Time-aware national-team Elo before each match and current NT priors",
        "url": "https://www.eloratings.net/",
        "local_filename": "external_data/world_football_elo/international_football_elo_20260611.json; national_team_elo_snapshots.csv later",
        "expected_columns": "date,team,elo,source,source_url",
        "status": "baseline_imported_2026-06-11; historical time-aware Elo snapshots still needed",
    },
    {
        "name": "Current project squad/player data",
        "purpose": "Team strength, unit matchups, discipline priors, and tactical priors",
        "url": "",
        "local_filename": "guardian_world_cup_2026_player_guide.json; player_performance_data_statbunker.json",
        "expected_columns": "",
        "status": "available",
    },
]


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_float(value, default=np.nan):
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def markdown_table(df, max_rows=None):
    if df is None or df.empty:
        return "_No rows._"
    display = df.head(max_rows).copy() if max_rows else df.copy()
    display = display.fillna("")
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.4f}" if value != "" else "")
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


def find_historical_file(explicit_path=None):
    if explicit_path:
        path = Path(explicit_path)
        return path if path.exists() else None
    for candidate in HISTORICAL_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def historical_readiness(path, profiles):
    readiness = {
        "historical_file": str(path) if path else "",
        "status": "missing",
        "source_rows": 0,
        "usable_matches": 0,
        "skipped_rows": 0,
        "date_min": "",
        "date_max": "",
        "tournament_count": 0,
        "teams_seen": 0,
        "world_cup_team_coverage": 0,
        "missing_world_cup_teams": sorted(profiles),
        "notes": [],
        "recommended_local_filename": "historical_international_results.csv",
        "recommended_source_url": DATA_SOURCES[0]["url"],
    }
    if not path:
        readiness["notes"].append("No historical results CSV is present in the workspace.")
        return readiness

    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        readiness["status"] = "unreadable"
        readiness["notes"].append(f"Could not read CSV: {exc}")
        return readiness

    rows, labels, status = read_historical_training_data(path, profiles)
    columns = {column.lower(): column for column in frame.columns}
    team_cols = [columns.get("team_a") or columns.get("home_team") or columns.get("team"), columns.get("team_b") or columns.get("away_team") or columns.get("opponent")]
    teams_seen = set()
    for column in team_cols:
        if column and column in frame:
            teams_seen.update(str(value).strip() for value in frame[column].dropna())
    covered = sorted(set(profiles).intersection(teams_seen))
    readiness.update(
        {
            "status": "ready" if status.get("usable_matches", 0) >= 300 else "partial",
            "source_rows": int(status.get("source_rows", len(frame))),
            "usable_matches": int(status.get("usable_matches", 0)),
            "skipped_rows": int(status.get("skipped_rows", 0)),
            "teams_seen": len(teams_seen),
            "world_cup_team_coverage": len(covered),
            "missing_world_cup_teams": sorted(set(profiles).difference(teams_seen)),
        }
    )
    if columns.get("date"):
        dates = pd.to_datetime(frame[columns["date"]], errors="coerce").dropna()
        if not dates.empty:
            readiness["date_min"] = dates.min().date().isoformat()
            readiness["date_max"] = dates.max().date().isoformat()
    tournament_col = columns.get("tournament") or columns.get("competition")
    if tournament_col:
        readiness["tournament_count"] = int(frame[tournament_col].nunique(dropna=True))
    if readiness["status"] == "partial":
        readiness["notes"].append("Historical CSV was found but not enough usable three-class rows were available; synthetic calibration will still be blended in.")
    return readiness


def load_training_frame(seed, elo_file, historical_file):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
    historical_rows, historical_labels, historical_status = read_historical_training_data(historical_file, profiles)
    synthetic_rows, synthetic_labels = build_synthetic_training_data(structure, profiles, seed)
    if len(set(historical_labels)) >= 3 and len(historical_labels) >= 300:
        rows = historical_rows
        labels = historical_labels
        training_source = "historical_csv"
    else:
        rows = historical_rows + synthetic_rows
        labels = historical_labels + synthetic_labels
        training_source = "historical_plus_synthetic_calibration" if historical_rows else "synthetic_profile_calibration"
    frame = pd.DataFrame(rows, columns=ML_FEATURE_NAMES)
    frame["label"] = labels
    metadata = {
        "seed": seed,
        "elo_file": str(elo_file),
        "elo_source": elo_source,
        "training_source": training_source,
        "rows": len(frame),
        "historical_rows": len(historical_labels),
        "synthetic_rows": len(synthetic_labels),
        "historical_status": historical_status,
        "class_distribution": dict(Counter(labels)),
    }
    return frame, structure, profiles, metadata


def build_models(seed):
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=160,
            max_depth=9,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=1,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=180,
            max_depth=10,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=seed + 17,
            n_jobs=1,
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=180,
            learning_rate=0.04,
            max_leaf_nodes=31,
            l2_regularization=0.03,
            random_state=seed + 29,
        ),
        "logistic_l2": Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=6000, class_weight="balanced", random_state=seed + 43)),
            ]
        ),
        "calibrated_logistic_sigmoid": CalibratedClassifierCV(
            Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("model", LogisticRegression(max_iter=6000, class_weight="balanced", random_state=seed + 61)),
                ]
            ),
            method="sigmoid",
            cv=3,
        ),
    }


def aligned_proba(model, x):
    raw = model.predict_proba(x)
    classes = list(model.classes_)
    aligned = np.zeros((len(raw), len(CLASS_ORDER)), dtype=float)
    for class_index, label in enumerate(classes):
        if label in CLASS_ORDER:
            aligned[:, CLASS_ORDER.index(label)] = raw[:, class_index]
    row_sums = aligned.sum(axis=1)
    missing = row_sums == 0
    if missing.any():
        aligned[missing, :] = 1.0 / len(CLASS_ORDER)
        row_sums = aligned.sum(axis=1)
    return aligned / row_sums[:, None]


def predicted_labels(proba):
    return np.array([CLASS_ORDER[index] for index in np.argmax(proba, axis=1)])


def brier_multiclass(y_true, proba):
    one_hot = np.zeros_like(proba)
    for row_index, label in enumerate(y_true):
        one_hot[row_index, CLASS_ORDER.index(label)] = 1.0
    return float(np.mean(np.sum((proba - one_hot) ** 2, axis=1)))


def calibration_bins(model_name, y_true, proba, bins=10):
    confidence = np.max(proba, axis=1)
    predictions = predicted_labels(proba)
    correct = predictions == y_true
    rows = []
    total = len(y_true)
    ece = 0.0
    for bin_id in range(bins):
        low = bin_id / bins
        high = (bin_id + 1) / bins
        if bin_id == bins - 1:
            mask = (confidence >= low) & (confidence <= high)
        else:
            mask = (confidence >= low) & (confidence < high)
        count = int(mask.sum())
        if count:
            avg_conf = float(confidence[mask].mean())
            acc = float(correct[mask].mean())
            gap = abs(acc - avg_conf)
            ece += (count / total) * gap
        else:
            avg_conf = np.nan
            acc = np.nan
            gap = np.nan
        rows.append(
            {
                "model": model_name,
                "bin": bin_id + 1,
                "confidence_low": low,
                "confidence_high": high,
                "count": count,
                "avg_confidence": avg_conf,
                "accuracy": acc,
                "calibration_gap": gap,
                "ece_contribution": 0.0 if count == 0 else (count / total) * gap,
            }
        )
    return rows, ece


def evaluate_models(models, x_train, x_test, y_train, y_test):
    metrics = []
    bins = []
    trained = {}
    validation_probas = {}
    for name, model in models.items():
        model.fit(x_train, y_train)
        proba = aligned_proba(model, x_test)
        pred = predicted_labels(proba)
        bin_rows, ece = calibration_bins(name, y_test, proba)
        bins.extend(bin_rows)
        metrics.append(
            {
                "model": name,
                "train_rows": len(y_train),
                "test_rows": len(y_test),
                "accuracy": round(float(accuracy_score(y_test, pred)), 5),
                "balanced_accuracy": round(float(balanced_accuracy_score(y_test, pred)), 5),
                "log_loss": round(float(log_loss(y_test, proba, labels=CLASS_ORDER)), 5),
                "brier_multiclass": round(brier_multiclass(y_test, proba), 5),
                "ece": round(float(ece), 5),
            }
        )
        trained[name] = model
        validation_probas[name] = proba
    return pd.DataFrame(metrics).sort_values("log_loss"), pd.DataFrame(bins), trained, validation_probas


def ensemble_from_validation(metrics_df, validation_probas, y_test):
    usable = metrics_df[metrics_df["log_loss"] > 0].copy()
    usable["raw_weight"] = 1.0 / usable["log_loss"]
    usable["weight"] = usable["raw_weight"] / usable["raw_weight"].sum()
    ensemble = np.zeros_like(next(iter(validation_probas.values())))
    for row in usable.itertuples(index=False):
        ensemble += validation_probas[row.model] * row.weight
    pred = predicted_labels(ensemble)
    bin_rows, ece = calibration_bins("weighted_validation_ensemble", y_test, ensemble)
    ensemble_metrics = {
        "model": "weighted_validation_ensemble",
        "train_rows": int(metrics_df["train_rows"].max()),
        "test_rows": len(y_test),
        "accuracy": round(float(accuracy_score(y_test, pred)), 5),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_test, pred)), 5),
        "log_loss": round(float(log_loss(y_test, ensemble, labels=CLASS_ORDER)), 5),
        "brier_multiclass": round(brier_multiclass(y_test, ensemble), 5),
        "ece": round(float(ece), 5),
    }
    weights = usable[["model", "log_loss", "weight"]].sort_values("weight", ascending=False)
    return ensemble_metrics, weights, pd.DataFrame(bin_rows)


def feature_importance_rows(trained, feature_names):
    rows = []
    for model_name, model in trained.items():
        importances = getattr(model, "feature_importances_", None)
        if importances is None:
            continue
        total = float(np.sum(importances)) or 1.0
        for feature, value in zip(feature_names, importances):
            rows.append(
                {
                    "model": model_name,
                    "feature": feature,
                    "importance": float(value),
                    "normalized_importance": float(value) / total,
                }
            )
    return pd.DataFrame(rows).sort_values(["model", "normalized_importance"], ascending=[True, False])


def permutation_rows(trained, x_test, y_test, feature_names, seed, repeats):
    rows = []
    for model_name in ["random_forest", "extra_trees", "hist_gradient_boosting", "logistic_l2"]:
        model = trained.get(model_name)
        if model is None:
            continue
        try:
            result = permutation_importance(
                model,
                x_test,
                y_test,
                scoring="neg_log_loss",
                n_repeats=repeats,
                random_state=seed + len(rows) + 101,
                n_jobs=1,
            )
        except Exception as exc:
            rows.append({"model": model_name, "feature": "__permutation_failed__", "importance": np.nan, "std": np.nan, "error": str(exc)})
            continue
        for feature, mean, std in zip(feature_names, result.importances_mean, result.importances_std):
            rows.append(
                {
                    "model": model_name,
                    "feature": feature,
                    "permutation_importance_neg_log_loss_drop": float(mean),
                    "std": float(std),
                    "error": "",
                }
            )
    return pd.DataFrame(rows).sort_values(["model", "permutation_importance_neg_log_loss_drop"], ascending=[True, False])


def wilson_interval(pct_value, n, z=1.96):
    p = max(0.0, min(1.0, safe_float(pct_value, 0.0) / 100.0))
    if n <= 0:
        return np.nan, np.nan, np.nan
    denominator = 1.0 + (z * z / n)
    center = (p + (z * z) / (2 * n)) / denominator
    margin = z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / denominator
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    standard_error = math.sqrt(p * (1 - p) / n)
    return low * 100, high * 100, standard_error * 100


def simulation_uncertainty_rows(team_summary):
    if team_summary.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    stage_columns = [
        "round_of_32_pct",
        "round_of_16_pct",
        "quarter_finals_pct",
        "semi_finals_pct",
        "final_pct",
        "third_place_pct",
        "champion_pct",
    ]
    rows = []
    for row in team_summary.to_dict("records"):
        if not row.get("primary_comparison", True):
            continue
        n = 10000
        for stage in stage_columns:
            if stage not in row or pd.isna(row[stage]):
                continue
            low, high, se = wilson_interval(row[stage], n)
            rows.append(
                {
                    "model_id": row["model_id"],
                    "model_label": row["model_label"],
                    "team": row["team"],
                    "stage": stage.replace("_pct", ""),
                    "probability_pct": row[stage],
                    "standard_error_pct": se,
                    "ci95_low_pct": low,
                    "ci95_high_pct": high,
                }
            )
    uncertainty = pd.DataFrame(rows)
    champion = uncertainty[uncertainty["stage"] == "champion"].sort_values(["model_id", "probability_pct"], ascending=[True, False])

    primary = team_summary[team_summary["primary_comparison"] == True]
    matrix = primary.pivot_table(index="team", columns="model_id", values="champion_pct", aggfunc="first").reset_index()
    model_columns = [column for column in matrix.columns if column != "team"]
    matrix["simple_mean_champion_pct"] = matrix[model_columns].mean(axis=1)
    matrix["median_champion_pct"] = matrix[model_columns].median(axis=1)
    matrix["model_range_pct"] = matrix[model_columns].max(axis=1) - matrix[model_columns].min(axis=1)
    v2_cols = [column for column in model_columns if column.startswith("v2_")]
    if v2_cols:
        matrix["v2_event_model_mean_champion_pct"] = matrix[v2_cols].mean(axis=1)
    matrix = matrix.sort_values("simple_mean_champion_pct", ascending=False)
    return uncertainty, champion, matrix


def tactical_priors(profiles):
    rows = []
    for team, profile in sorted(profiles.items()):
        attack = profile["attack_score"]
        midfield = profile["midfield_score"]
        defense = profile["defense_score"]
        gk = profile["gk_score"]
        possession = profile["possession_score"]
        squad = profile["squad_rating"]
        discipline = profile["discipline_risk"]
        rows.append(
            {
                "team": team,
                "pressing_score": 0.42 * midfield + 0.34 * attack + 0.24 * possession - 7.5 * discipline,
                "counterattack_score": 0.52 * attack + 0.23 * defense + 0.25 * squad,
                "low_block_resilience": 0.46 * defense + 0.28 * gk + 0.26 * squad,
                "set_piece_attack_score": 0.38 * attack + 0.30 * midfield + 0.32 * squad,
                "width_progression_score": 0.62 * possession + 0.38 * attack,
                "tempo_score": 0.40 * attack + 0.34 * midfield + 0.26 * possession,
                "discipline_risk": discipline,
                "data_confidence": profile["data_confidence"],
            }
        )
    frame = pd.DataFrame(rows)
    score_columns = [column for column in frame.columns if column.endswith("_score") or column in {"low_block_resilience"}]
    for column in score_columns:
        frame[f"{column}_percentile"] = frame[column].rank(pct=True)
    return frame.sort_values("pressing_score", ascending=False)


def player_data_coverage(profiles):
    rows = []
    for team, profile in sorted(profiles.items()):
        players = profile["players"]
        confidences = [safe_float(player.get("source_confidence"), 0.0) for player in players]
        minutes = [safe_float(player.get("minutes"), 0.0) for player in players]
        source_counts = Counter(player.get("source") or "unknown" for player in players)
        low_confidence = [player["name"] for player in players if safe_float(player.get("source_confidence"), 0.0) < 0.55]
        no_minutes = [player["name"] for player in players if safe_float(player.get("minutes"), 0.0) <= 0]
        rows.append(
            {
                "team": team,
                "players": len(players),
                "avg_source_confidence": float(np.mean(confidences)) if confidences else 0.0,
                "min_source_confidence": float(np.min(confidences)) if confidences else 0.0,
                "players_below_0_55_confidence": len(low_confidence),
                "players_with_zero_minutes": len(no_minutes),
                "avg_minutes": float(np.mean(minutes)) if minutes else 0.0,
                "primary_sources": "; ".join(f"{source}:{count}" for source, count in source_counts.most_common(4)),
                "low_confidence_examples": "; ".join(low_confidence[:8]),
                "zero_minutes_examples": "; ".join(no_minutes[:8]),
            }
        )
    return pd.DataFrame(rows).sort_values(["avg_source_confidence", "players_below_0_55_confidence"], ascending=[True, False])


def html_escape(value):
    return html.escape("" if pd.isna(value) else str(value))


def dashboard_bar_rows(rows, label_column, value_column, color="#2563eb", scale_max=None):
    if rows.empty:
        return "<p>No rows.</p>"
    max_value = scale_max if scale_max is not None else max(float(rows[value_column].max()), 1.0)
    parts = []
    for row in rows.to_dict("records"):
        value = float(row[value_column])
        width = 100 * value / max_value if max_value else 0
        parts.append(
            f"""
            <div class="bar-row">
              <span>{html_escape(row[label_column])}</span>
              <div class="bar-track"><div class="bar" style="width:{width:.2f}%;background:{color}"></div></div>
              <strong>{value:.2f}</strong>
            </div>
            """
        )
    return "\n".join(parts)


def html_table(df, max_rows=12):
    if df.empty:
        return "<p>No rows.</p>"
    display = df.head(max_rows).copy().fillna("")
    headers = "".join(f"<th>{html_escape(column)}</th>" for column in display.columns)
    body = []
    for row in display.to_dict("records"):
        cells = "".join(f"<td>{html_escape(value)}</td>" for value in row.values())
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_dashboard(output_dir, metrics_df, champion_uncertainty_df, consensus_df, tactical_df, coverage_df, historical_status):
    top_models = metrics_df.sort_values("log_loss").head(6)
    top_consensus = consensus_df.head(10)
    top_tactical = tactical_df[["team", "pressing_score", "counterattack_score", "low_block_resilience", "tempo_score"]].head(10)
    low_coverage = coverage_df[["team", "avg_source_confidence", "players_below_0_55_confidence", "players_with_zero_minutes", "primary_sources"]].head(10)
    top_champions = champion_uncertainty_df.groupby("model_label", group_keys=False).head(6)[
        ["model_label", "team", "probability_pct", "ci95_low_pct", "ci95_high_pct"]
    ]
    best_model = top_models.iloc[0]
    best_team = top_consensus.iloc[0]
    cards = [
        ("Best validation model", f"{best_model['model']} ({best_model['log_loss']:.3f} log loss)"),
        ("Consensus leader", f"{best_team['team']} ({best_team['simple_mean_champion_pct']:.2f}%)"),
        ("Historical data", historical_status["status"]),
        ("Teams in tactical priors", str(len(tactical_df))),
    ]
    card_html = "\n".join(f"<div class='card'><span>{html_escape(label)}</span><strong>{html_escape(value)}</strong></div>" for label, value in cards)
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>FIFA WC26 Research Upgrade Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f8fafc; color: #0f172a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 4px; font-size: 30px; }}
    h2 {{ margin: 26px 0 12px; font-size: 20px; }}
    p {{ color: #475569; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0; }}
    .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #64748b; font-size: 12px; text-transform: uppercase; }}
    .card strong {{ display: block; margin-top: 8px; font-size: 18px; }}
    section {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 14px 0; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 13px; }}
    th {{ background: #f1f5f9; color: #475569; }}
    .bar-row {{ display: grid; grid-template-columns: 160px 1fr 70px; align-items: center; gap: 10px; margin: 9px 0; }}
    .bar-track {{ height: 16px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }}
    .bar {{ height: 100%; border-radius: 999px; }}
    @media (max-width: 900px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} .bar-row {{ grid-template-columns: 120px 1fr 60px; }} }}
  </style>
</head>
<body>
<main>
  <h1>FIFA WC26 Research Upgrade Dashboard</h1>
  <p>Calibration, uncertainty, ensemble consensus, tactical priors, and data coverage generated from the current project artifacts.</p>
  <div class="cards">{card_html}</div>
  <section>
    <h2>Validation Log Loss</h2>
    {dashboard_bar_rows(top_models, "model", "log_loss", "#dc2626", scale_max=max(top_models["log_loss"].max(), 1.0))}
  </section>
  <section>
    <h2>Consensus Champion Probability</h2>
    {dashboard_bar_rows(top_consensus, "team", "simple_mean_champion_pct", "#2563eb")}
  </section>
  <section>
    <h2>Champion Uncertainty</h2>
    {html_table(top_champions, max_rows=24)}
  </section>
  <section>
    <h2>Tactical Priors</h2>
    {html_table(top_tactical, max_rows=10)}
  </section>
  <section>
    <h2>Player Data Coverage To Improve First</h2>
    {html_table(low_coverage, max_rows=10)}
  </section>
</main>
</body>
</html>"""
    path = output_dir / "research_upgrade_dashboard.html"
    path.write_text(html_text, encoding="utf-8")
    return path


def write_templates(output_dir):
    historical_template = output_dir / "historical_matches_template.csv"
    elo_template = output_dir / "national_team_elo_snapshots_template.csv"
    with historical_template.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "team_a", "team_b", "goals_a", "goals_b", "tournament", "neutral", "city", "country", "source"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "date": "2022-12-18",
                "team_a": "Argentina",
                "team_b": "France",
                "goals_a": 3,
                "goals_b": 3,
                "tournament": "FIFA World Cup",
                "neutral": "TRUE",
                "city": "Lusail",
                "country": "Qatar",
                "source": "example_row",
            }
        )
    with elo_template.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "team", "elo", "source", "source_url"])
        writer.writeheader()
        writer.writerow({"date": "2026-06-11", "team": "France", "elo": 2063, "source": "World Football Elo Ratings", "source_url": "https://www.eloratings.net/"})
    return historical_template, elo_template


def write_report(output_dir, metadata, historical_status, metrics_df, weights_df, calibration_df, uncertainty_champion_df, consensus_df, tactical_df, coverage_df, dashboard_path):
    best_metrics = metrics_df.sort_values("log_loss").head(8)
    ece_summary = calibration_df.groupby("model", as_index=False).agg(total_bins=("bin", "count"), non_empty_bins=("count", lambda s: int((s > 0).sum())), ece=("ece_contribution", "sum")).sort_values("ece")
    top_uncertainty = uncertainty_champion_df.groupby("model_label", group_keys=False).head(8)
    top_tactical = tactical_df[["team", "pressing_score", "counterattack_score", "low_block_resilience", "set_piece_attack_score", "tempo_score", "data_confidence"]].head(12)
    low_coverage = coverage_df[["team", "avg_source_confidence", "players_below_0_55_confidence", "players_with_zero_minutes", "primary_sources"]].head(12)
    lines = [
        "# FIFA WC26 Research Upgrade Report",
        "",
        f"Generated: `{date.today().isoformat()}`",
        f"Training source: `{metadata['training_source']}`",
        f"Rows: `{metadata['rows']}`",
        f"Historical rows in model frame: `{metadata['historical_rows']}`",
        f"Synthetic rows in model frame: `{metadata['synthetic_rows']}`",
        f"Elo source: `{metadata['elo_source']}`",
        "",
        "## Historical Data Readiness",
        "",
        markdown_table(pd.DataFrame([historical_status])),
        "",
        "## Validation Metrics",
        "",
        markdown_table(best_metrics),
        "",
        "## Ensemble Weights",
        "",
        markdown_table(weights_df),
        "",
        "## Calibration Summary",
        "",
        markdown_table(ece_summary),
        "",
        "## Champion Probability Uncertainty",
        "",
        "Wilson 95% intervals are calculated from each stored 10,000-run tournament output.",
        "",
        markdown_table(top_uncertainty[["model_label", "team", "probability_pct", "standard_error_pct", "ci95_low_pct", "ci95_high_pct"]]),
        "",
        "## Cross-Model Champion Consensus",
        "",
        markdown_table(consensus_df.head(15)),
        "",
        "## Tactical Priors",
        "",
        "These are model-ready priors inferred from the current squad profile. They are not yet a substitute for real tactical event data.",
        "",
        markdown_table(top_tactical),
        "",
        "## Player Data Coverage",
        "",
        "These are the teams where better player-level source coverage would most improve confidence.",
        "",
        markdown_table(low_coverage),
        "",
        "## Dashboard",
        "",
        f"- `{dashboard_path.name}`",
        "",
        "## Data Source Manifest",
        "",
        markdown_table(pd.DataFrame(DATA_SOURCES)),
        "",
        "## Caveats",
        "",
        "- Direct web download is blocked in this workspace, so historical source files must be placed locally.",
        "- Until a real historical match CSV is supplied, supervised metrics explain the simulator's calibrated assumptions.",
        "- The current NT Elo baseline is a raw 2026-06-11 World Football Elo import; historical time-aware Elo snapshots would still improve backtesting.",
        "- Tactical priors are inferred from player/team profile strength and need real style data for validation.",
        "",
    ]
    path = output_dir / "research_upgrade_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Run calibration, uncertainty, ensemble, and data-readiness diagnostics for the FIFA WC26 simulator.")
    parser.add_argument("--seed", type=int, default=20260622)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--elo-file", default=str(DEFAULT_ELO_FILE))
    parser.add_argument("--historical-matches", default=None)
    parser.add_argument("--permutation-repeats", type=int, default=5)
    args = parser.parse_args()

    output_dir = ensure_dir(Path(args.output_dir) if args.output_dir else ROOT / f"research_upgrade_results_seed_{args.seed}")
    historical_file = find_historical_file(args.historical_matches)
    frame, structure, profiles, metadata = load_training_frame(args.seed, args.elo_file, historical_file)
    historical_status = historical_readiness(historical_file, profiles)

    x = frame[ML_FEATURE_NAMES].to_numpy(dtype=float)
    y = frame["label"].to_numpy()
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.25, random_state=args.seed, stratify=y)

    metrics_df, calibration_df, trained, validation_probas = evaluate_models(build_models(args.seed), x_train, x_test, y_train, y_test)
    ensemble_metrics, weights_df, ensemble_bins = ensemble_from_validation(metrics_df, validation_probas, y_test)
    metrics_df = pd.concat([metrics_df, pd.DataFrame([ensemble_metrics])], ignore_index=True).sort_values("log_loss")
    calibration_df = pd.concat([calibration_df, ensemble_bins], ignore_index=True)
    builtin_df = feature_importance_rows(trained, ML_FEATURE_NAMES)
    permutation_df = permutation_rows(trained, x_test, y_test, ML_FEATURE_NAMES, args.seed, args.permutation_repeats)

    team_summary = pd.read_csv(SIMULATION_TEAM_SUMMARY) if SIMULATION_TEAM_SUMMARY.exists() else pd.DataFrame()
    uncertainty_df, champion_uncertainty_df, consensus_df = simulation_uncertainty_rows(team_summary)
    tactical_df = tactical_priors(profiles)
    coverage_df = player_data_coverage(profiles)
    historical_template, elo_template = write_templates(output_dir)

    metadata.update(
        {
            "output_dir": str(output_dir),
            "historical_file": str(historical_file) if historical_file else "",
            "simulation_team_summary": str(SIMULATION_TEAM_SUMMARY) if SIMULATION_TEAM_SUMMARY.exists() else "",
            "historical_template": historical_template.name,
            "elo_snapshot_template": elo_template.name,
            "data_sources": DATA_SOURCES,
        }
    )

    artifacts = {
        "model_validation_metrics.csv": metrics_df,
        "ensemble_weights.csv": weights_df,
        "calibration_bins.csv": calibration_df,
        "feature_importance_builtin_research.csv": builtin_df,
        "feature_importance_permutation_research.csv": permutation_df,
        "simulation_stage_uncertainty.csv": uncertainty_df,
        "simulation_champion_uncertainty.csv": champion_uncertainty_df,
        "simulation_consensus_ensemble.csv": consensus_df,
        "team_tactical_priors.csv": tactical_df,
        "player_data_coverage.csv": coverage_df,
        "data_source_manifest.csv": pd.DataFrame(DATA_SOURCES),
    }
    for filename, dataframe in artifacts.items():
        dataframe.to_csv(output_dir / filename, index=False)
    (output_dir / "historical_data_readiness.json").write_text(json.dumps(historical_status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "research_pipeline_summary.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dashboard_path = write_dashboard(output_dir, metrics_df, champion_uncertainty_df, consensus_df, tactical_df, coverage_df, historical_status)
    report_path = write_report(output_dir, metadata, historical_status, metrics_df, weights_df, calibration_df, champion_uncertainty_df, consensus_df, tactical_df, coverage_df, dashboard_path)

    print(f"wrote {output_dir}")
    print(f"report {report_path.name}")
    print("best validation models:")
    for row in metrics_df.head(5).itertuples(index=False):
        print(f"{row.model}: log_loss {row.log_loss:.5f}, ece {row.ece:.5f}")


if __name__ == "__main__":
    main()
