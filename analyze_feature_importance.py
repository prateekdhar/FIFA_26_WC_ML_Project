import argparse
import json
import math
import os
import random
import warnings
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
warnings.filterwarnings(
    "ignore",
    message="Could not find the number of physical cores.*",
    category=UserWarning,
    module="joblib.*",
)

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from simulate_world_cup_v2 import (
    DEFAULT_ELO_FILE,
    ML_FEATURE_NAMES,
    ROOT,
    STRUCTURE_FILE,
    build_synthetic_training_data,
    build_team_profiles,
    read_historical_training_data,
    simulate_one_tournament,
)


FEATURE_GROUPS = {
    "team_strength": ["elo_diff", "squad_rating_diff"],
    "unit_matchups": ["attack_vs_defense", "defense_vs_attack", "midfield_diff", "gk_diff", "possession_diff"],
    "discipline": ["discipline_diff"],
    "data_quality": ["data_confidence_diff"],
    "host_context": ["host_diff", "altitude_factor"],
    "rest_fatigue_availability": ["rest_diff", "fatigue_diff", "lineup_replacements_diff"],
    "venue_climate_travel": ["travel_diff", "heat_index", "humidity", "venue_altitude_km"],
    "tournament_structure": ["stage_is_knockout", "allow_draw", "match_day_index"],
}


CLASS_LABELS = ["A", "B", "D"]


class FeatureMeanAblationWrapper:
    def __init__(self, model, feature_names, baseline_means, ablated_features):
        self.model = model
        self.feature_names = feature_names
        self.baseline_means = baseline_means
        self.ablated_features = set(ablated_features)
        self.classes_ = model.classes_

    def _ablate(self, x):
        x = np.asarray(x, dtype=float).copy()
        for feature in self.ablated_features:
            if feature in self.feature_names:
                index = self.feature_names.index(feature)
                x[:, index] = self.baseline_means[index]
        return x

    def predict_proba(self, x):
        return self.model.predict_proba(self._ablate(x))


def ensure_output_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_training_frame(seed, elo_file, historical_matches_file=None):
    structure = json.loads(STRUCTURE_FILE.read_text(encoding="utf-8"))
    profiles, elo_source = build_team_profiles(elo_file)
    historical_rows, historical_labels, historical_status = read_historical_training_data(historical_matches_file, profiles)
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
        "historical_status": historical_status,
        "synthetic_rows": len(synthetic_labels),
        "features": ML_FEATURE_NAMES,
        "feature_groups": FEATURE_GROUPS,
    }
    return frame, structure, profiles, metadata


def build_models(seed):
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=96,
            max_depth=8,
            min_samples_leaf=6,
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=1,
        ),
        "decision_tree_depth4": DecisionTreeClassifier(
            max_depth=4,
            min_samples_leaf=24,
            class_weight="balanced",
            random_state=seed,
        ),
        "logistic_l2": Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=5000, class_weight="balanced", random_state=seed)),
            ]
        ),
        "elastic_net_logistic": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        solver="saga",
                        l1_ratio=0.45,
                        max_iter=6000,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=160,
            learning_rate=0.045,
            max_leaf_nodes=31,
            l2_regularization=0.02,
            random_state=seed,
        ),
    }


def evaluate_model(name, model, x_train, x_test, y_train, y_test):
    model.fit(x_train, y_train)
    proba = model.predict_proba(x_test)
    pred = model.predict(x_test)
    return {
        "model": name,
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "accuracy": round(accuracy_score(y_test, pred), 5),
        "balanced_accuracy": round(balanced_accuracy_score(y_test, pred), 5),
        "log_loss": round(log_loss(y_test, proba, labels=list(model.classes_)), 5),
    }


def builtin_importance_rows(model_name, model, feature_names):
    rows = []
    importances = None
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif isinstance(model, Pipeline):
        final_model = model.named_steps.get("model")
        if hasattr(final_model, "coef_"):
            coefficients = np.abs(final_model.coef_)
            importances = coefficients.mean(axis=0)
    if importances is None:
        return rows
    total = float(np.sum(np.abs(importances))) or 1.0
    for feature, value in zip(feature_names, importances):
        rows.append(
            {
                "model": model_name,
                "feature": feature,
                "importance": float(value),
                "normalized_importance": float(abs(value) / total),
            }
        )
    return rows


def logistic_coefficient_rows(model_name, model, feature_names):
    if not isinstance(model, Pipeline):
        return []
    final_model = model.named_steps.get("model")
    if not hasattr(final_model, "coef_"):
        return []
    rows = []
    for class_index, class_name in enumerate(final_model.classes_):
        for feature, coefficient in zip(feature_names, final_model.coef_[class_index]):
            rows.append(
                {
                    "model": model_name,
                    "class": class_name,
                    "feature": feature,
                    "coefficient": float(coefficient),
                    "abs_coefficient": float(abs(coefficient)),
                }
            )
    return rows


def permutation_rows(model_name, model, x_test, y_test, feature_names, seed, repeats):
    result = permutation_importance(
        model,
        x_test,
        y_test,
        scoring="neg_log_loss",
        n_repeats=repeats,
        random_state=seed,
        n_jobs=1,
    )
    rows = []
    for feature, mean_value, std_value in zip(feature_names, result.importances_mean, result.importances_std):
        rows.append(
            {
                "model": model_name,
                "feature": feature,
                "permutation_importance_neg_log_loss_drop": float(mean_value),
                "std": float(std_value),
                "repeats": repeats,
            }
        )
    return rows


def local_occlusion_rows(model_name, model, x_test, y_test, feature_names, baseline_means, sample_size, seed):
    rng = np.random.default_rng(seed)
    if len(x_test) > sample_size:
        indexes = rng.choice(len(x_test), sample_size, replace=False)
    else:
        indexes = np.arange(len(x_test))
    x_sample = x_test[indexes].copy()
    y_sample = np.asarray(y_test)[indexes]
    base_proba = model.predict_proba(x_sample)
    class_to_index = {label: index for index, label in enumerate(model.classes_)}
    rows = []
    examples = []
    for feature_index, feature in enumerate(feature_names):
        occluded = x_sample.copy()
        occluded[:, feature_index] = baseline_means[feature_index]
        occluded_proba = model.predict_proba(occluded)
        true_deltas = []
        a_deltas = []
        for row_index, label in enumerate(y_sample):
            label_index = class_to_index[label]
            true_delta = base_proba[row_index, label_index] - occluded_proba[row_index, label_index]
            a_delta = base_proba[row_index, class_to_index.get("A", 0)] - occluded_proba[row_index, class_to_index.get("A", 0)]
            true_deltas.append(true_delta)
            a_deltas.append(a_delta)
            if len(examples) < 250:
                examples.append(
                    {
                        "model": model_name,
                        "sample_index": int(indexes[row_index]),
                        "feature": feature,
                        "true_label": str(label),
                        "base_true_probability": float(base_proba[row_index, label_index]),
                        "occluded_true_probability": float(occluded_proba[row_index, label_index]),
                        "true_probability_delta": float(true_delta),
                        "team_a_win_probability_delta": float(a_delta),
                    }
                )
        rows.append(
            {
                "model": model_name,
                "feature": feature,
                "mean_abs_true_probability_delta": float(np.mean(np.abs(true_deltas))),
                "mean_true_probability_delta": float(np.mean(true_deltas)),
                "mean_abs_team_a_probability_delta": float(np.mean(np.abs(a_deltas))),
            }
        )
    return rows, examples


def partial_dependence_rows(model_name, model, x_reference, feature_names, top_features, grid_points):
    rows = []
    ice_rows = []
    class_to_index = {label: index for index, label in enumerate(model.classes_)}
    sample_count = min(50, len(x_reference))
    ice_sample = x_reference[:sample_count].copy()
    for feature in top_features:
        feature_index = feature_names.index(feature)
        values = x_reference[:, feature_index]
        unique_values = np.unique(values)
        if len(unique_values) <= grid_points:
            grid = unique_values
        else:
            grid = np.quantile(values, np.linspace(0.05, 0.95, grid_points))
            grid = np.unique(grid)
        for value in grid:
            modified = x_reference.copy()
            modified[:, feature_index] = value
            proba = model.predict_proba(modified)
            row = {
                "model": model_name,
                "feature": feature,
                "value": float(value),
            }
            for class_name in model.classes_:
                row[f"mean_p_{class_name}"] = float(np.mean(proba[:, class_to_index[class_name]]))
            rows.append(row)

            ice_modified = ice_sample.copy()
            ice_modified[:, feature_index] = value
            ice_proba = model.predict_proba(ice_modified)
            for sample_index in range(sample_count):
                ice_rows.append(
                    {
                        "model": model_name,
                        "feature": feature,
                        "sample_index": sample_index,
                        "value": float(value),
                        "p_A": float(ice_proba[sample_index, class_to_index.get("A", 0)]),
                        "p_B": float(ice_proba[sample_index, class_to_index.get("B", 0)]),
                        "p_D": float(ice_proba[sample_index, class_to_index.get("D", 0)]),
                    }
                )
    return rows, ice_rows


def ablate_columns(x, feature_names, features, means):
    x = x.copy()
    for feature in features:
        if feature in feature_names:
            index = feature_names.index(feature)
            x[:, index] = means[index]
    return x


def group_ablation_validation_rows(x_train, x_test, y_train, y_test, feature_names, baseline_means, seed):
    rows = []
    baseline_model = RandomForestClassifier(
        n_estimators=96,
        max_depth=8,
        min_samples_leaf=6,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=1,
    )
    baseline_model.fit(x_train, y_train)
    baseline_proba = baseline_model.predict_proba(x_test)
    baseline_pred = baseline_model.predict(x_test)
    baseline_log_loss = log_loss(y_test, baseline_proba, labels=list(baseline_model.classes_))
    baseline_accuracy = accuracy_score(y_test, baseline_pred)

    for group_name, features in FEATURE_GROUPS.items():
        x_train_ablate = ablate_columns(x_train, feature_names, features, baseline_means)
        x_test_ablate = ablate_columns(x_test, feature_names, features, baseline_means)
        model = RandomForestClassifier(
            n_estimators=96,
            max_depth=8,
            min_samples_leaf=6,
            class_weight="balanced_subsample",
            random_state=seed + len(rows) + 19,
            n_jobs=1,
        )
        model.fit(x_train_ablate, y_train)
        proba = model.predict_proba(x_test_ablate)
        pred = model.predict(x_test_ablate)
        ablated_log_loss = log_loss(y_test, proba, labels=list(model.classes_))
        ablated_accuracy = accuracy_score(y_test, pred)
        rows.append(
            {
                "group": group_name,
                "features": "|".join(features),
                "baseline_log_loss": float(baseline_log_loss),
                "ablated_log_loss": float(ablated_log_loss),
                "log_loss_increase": float(ablated_log_loss - baseline_log_loss),
                "baseline_accuracy": float(baseline_accuracy),
                "ablated_accuracy": float(ablated_accuracy),
                "accuracy_drop": float(baseline_accuracy - ablated_accuracy),
            }
        )
    return rows


def run_simulation_ablation(structure, profiles, full_model, feature_names, baseline_means, x_train, y_train, seed, epochs):
    if epochs <= 0:
        return [], []
    scenario_rows = []
    champion_rows = []

    scenarios = {"baseline": []}
    scenarios.update(FEATURE_GROUPS)
    for scenario_index, (scenario, ablated_features) in enumerate(scenarios.items()):
        if scenario == "baseline":
            model = full_model
        else:
            x_ablate = ablate_columns(x_train, feature_names, ablated_features, baseline_means)
            model = RandomForestClassifier(
                n_estimators=96,
                max_depth=8,
                min_samples_leaf=6,
                class_weight="balanced_subsample",
                random_state=seed + 1000 + scenario_index,
                n_jobs=1,
            )
            model.fit(x_ablate, y_train)
            model = FeatureMeanAblationWrapper(model, feature_names, baseline_means, ablated_features)

        model_bundle = {"model": model, "feature_names": feature_names, "status": {"kind": "analysis_ablation"}}
        rng = random.Random(seed + 3000 + scenario_index * 997)
        champions = Counter()
        finalists = Counter()
        semifinalists = Counter()
        for _ in range(epochs):
            _group_results, stages, _player_stats, _team_events = simulate_one_tournament(
                structure,
                profiles,
                rng,
                model_bundle=model_bundle,
            )
            champions[stages["champion"]] += 1
            for team in stages["final"]:
                finalists[team] += 1
            for team in stages["semi_finals"]:
                semifinalists[team] += 1
        top_champion = champions.most_common(1)[0][0] if champions else None
        scenario_rows.append(
            {
                "scenario": scenario,
                "ablated_features": "|".join(ablated_features),
                "epochs": epochs,
                "top_champion": top_champion,
                "top_champion_pct": round(champions[top_champion] / epochs * 100, 4) if top_champion else 0,
            }
        )
        teams = sorted(set(champions) | set(finalists) | set(semifinalists))
        for team in teams:
            champion_rows.append(
                {
                    "scenario": scenario,
                    "team": team,
                    "champion_pct": round(champions[team] / epochs * 100, 4),
                    "final_pct": round(finalists[team] / epochs * 100, 4),
                    "semi_final_pct": round(semifinalists[team] / epochs * 100, 4),
                }
            )
    return scenario_rows, champion_rows


def save_chart_if_possible(output_dir, builtin_df, permutation_df, ablation_df):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    paths = []
    rf_builtin = builtin_df[builtin_df["model"] == "random_forest"].sort_values("normalized_importance", ascending=False).head(12)
    if not rf_builtin.empty:
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.barh(rf_builtin["feature"][::-1], rf_builtin["normalized_importance"][::-1])
        ax.set_title("Random Forest Built-in Feature Importance")
        ax.set_xlabel("Normalized importance")
        fig.tight_layout()
        path = output_dir / "random_forest_builtin_importance.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path.name)

    rf_perm = permutation_df[permutation_df["model"] == "random_forest"].sort_values("permutation_importance_neg_log_loss_drop", ascending=False).head(12)
    if not rf_perm.empty:
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.barh(rf_perm["feature"][::-1], rf_perm["permutation_importance_neg_log_loss_drop"][::-1])
        ax.set_title("Random Forest Permutation Importance")
        ax.set_xlabel("Log-loss increase when shuffled")
        fig.tight_layout()
        path = output_dir / "random_forest_permutation_importance.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path.name)

    if not ablation_df.empty:
        ablation_top = ablation_df.sort_values("log_loss_increase", ascending=False)
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.barh(ablation_top["group"][::-1], ablation_top["log_loss_increase"][::-1])
        ax.set_title("Feature Group Ablation")
        ax.set_xlabel("Validation log-loss increase")
        fig.tight_layout()
        path = output_dir / "feature_group_ablation.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path.name)
    return paths


def markdown_table(df):
    if df.empty:
        return "_No rows._"

    display = df.copy().fillna("")
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.6f}")
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


def write_report(output_dir, metadata, model_metrics, builtin_df, permutation_df, occlusion_df, ablation_df, simulation_scenarios, chart_files):
    rf_builtin = builtin_df[builtin_df["model"] == "random_forest"].sort_values("normalized_importance", ascending=False).head(10)
    rf_perm = permutation_df[permutation_df["model"] == "random_forest"].sort_values("permutation_importance_neg_log_loss_drop", ascending=False).head(10)
    occlusion = occlusion_df[occlusion_df["model"] == "random_forest"].sort_values("mean_abs_true_probability_delta", ascending=False).head(10)
    ablation = ablation_df.sort_values("log_loss_increase", ascending=False)

    lines = [
        "# FIFA WC26 Feature Importance Analysis",
        "",
        f"Seed: `{metadata['seed']}`",
        f"Training source: `{metadata['training_source']}`",
        f"Rows: `{metadata['rows']}`",
        f"Elo source: `{metadata['elo_source']}`",
        "",
        "Important caveat: if historical match data is not supplied, these results explain the simulator's assumptions, not verified real-world causality.",
        "",
        "## Model Metrics",
        "",
        markdown_table(model_metrics),
        "",
        "## Random Forest Built-In Top Features",
        "",
        markdown_table(rf_builtin[["feature", "normalized_importance"]]),
        "",
        "## Random Forest Permutation Top Features",
        "",
        markdown_table(rf_perm[["feature", "permutation_importance_neg_log_loss_drop", "std"]]),
        "",
        "## Local Occlusion Top Features",
        "",
        markdown_table(occlusion[["feature", "mean_abs_true_probability_delta", "mean_true_probability_delta"]]),
        "",
        "## Feature Group Ablation",
        "",
        markdown_table(ablation[["group", "log_loss_increase", "accuracy_drop"]]),
        "",
    ]
    if simulation_scenarios:
        lines.extend(
            [
                "## Tournament Simulation RF-Layer Ablation",
                "",
                "This ablates feature groups inside the Random Forest layer only; the hand-built xG mechanics still use their normal team-profile inputs.",
                "",
                markdown_table(pd.DataFrame(simulation_scenarios)),
                "",
            ]
        )
    if chart_files:
        lines.extend(["## Charts", ""])
        for chart in chart_files:
            lines.append(f"- `{chart}`")
        lines.append("")
    report_path = output_dir / "feature_importance_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Analyze model and simulator feature importance for FIFA WC26 predictions.")
    parser.add_argument("--seed", type=int, default=20260618)
    parser.add_argument("--elo-file", default=str(DEFAULT_ELO_FILE))
    parser.add_argument("--historical-matches", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--permutation-repeats", type=int, default=8)
    parser.add_argument("--pdp-grid-points", type=int, default=15)
    parser.add_argument("--top-pdp-features", type=int, default=8)
    parser.add_argument("--local-sample-size", type=int, default=300)
    parser.add_argument("--simulation-ablation-epochs", type=int, default=30)
    args = parser.parse_args()

    output_dir = ensure_output_dir(Path(args.output_dir) if args.output_dir else ROOT / f"feature_importance_results_seed_{args.seed}")
    frame, structure, profiles, metadata = load_training_frame(args.seed, args.elo_file, historical_matches_file=args.historical_matches)
    x = frame[ML_FEATURE_NAMES].to_numpy(dtype=float)
    y = frame["label"].to_numpy()
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=args.test_size,
        random_state=args.seed,
        stratify=y,
    )
    baseline_means = np.mean(x_train, axis=0)

    models = build_models(args.seed)
    metric_rows = []
    builtin_rows = []
    coefficient_rows = []
    permutation_all_rows = []
    trained_models = {}
    for name, model in models.items():
        metric_rows.append(evaluate_model(name, model, x_train, x_test, y_train, y_test))
        trained_models[name] = model
        builtin_rows.extend(builtin_importance_rows(name, model, ML_FEATURE_NAMES))
        coefficient_rows.extend(logistic_coefficient_rows(name, model, ML_FEATURE_NAMES))
        permutation_all_rows.extend(
            permutation_rows(name, model, x_test, y_test, ML_FEATURE_NAMES, args.seed + len(metric_rows), args.permutation_repeats)
        )

    model_metrics = pd.DataFrame(metric_rows).sort_values("log_loss")
    builtin_df = pd.DataFrame(builtin_rows).sort_values(["model", "normalized_importance"], ascending=[True, False])
    coefficient_df = pd.DataFrame(coefficient_rows).sort_values(["model", "class", "abs_coefficient"], ascending=[True, True, False])
    permutation_df = pd.DataFrame(permutation_all_rows).sort_values(["model", "permutation_importance_neg_log_loss_drop"], ascending=[True, False])

    rf_model = trained_models["random_forest"]
    top_features = (
        permutation_df[permutation_df["model"] == "random_forest"]
        .sort_values("permutation_importance_neg_log_loss_drop", ascending=False)["feature"]
        .head(args.top_pdp_features)
        .tolist()
    )
    if not top_features:
        top_features = builtin_df[builtin_df["model"] == "random_forest"].head(args.top_pdp_features)["feature"].tolist()

    occlusion_rows, occlusion_examples = local_occlusion_rows(
        "random_forest",
        rf_model,
        x_test,
        y_test,
        ML_FEATURE_NAMES,
        baseline_means,
        args.local_sample_size,
        args.seed,
    )
    pdp_rows, ice_rows = partial_dependence_rows("random_forest", rf_model, x_test, ML_FEATURE_NAMES, top_features, args.pdp_grid_points)
    ablation_rows = group_ablation_validation_rows(x_train, x_test, y_train, y_test, ML_FEATURE_NAMES, baseline_means, args.seed)
    simulation_scenarios, simulation_champions = run_simulation_ablation(
        structure,
        profiles,
        rf_model,
        ML_FEATURE_NAMES,
        baseline_means,
        x_train,
        y_train,
        args.seed,
        args.simulation_ablation_epochs,
    )

    occlusion_df = pd.DataFrame(occlusion_rows).sort_values("mean_abs_true_probability_delta", ascending=False)
    ablation_df = pd.DataFrame(ablation_rows).sort_values("log_loss_increase", ascending=False)
    chart_files = save_chart_if_possible(output_dir, builtin_df, permutation_df, ablation_df)

    artifacts = {
        "model_metrics.csv": model_metrics,
        "feature_importance_builtin.csv": builtin_df,
        "feature_importance_permutation.csv": permutation_df,
        "feature_importance_logistic_coefficients.csv": coefficient_df,
        "feature_importance_local_occlusion.csv": occlusion_df,
        "local_occlusion_examples.csv": pd.DataFrame(occlusion_examples),
        "partial_dependence.csv": pd.DataFrame(pdp_rows),
        "ice_curves.csv": pd.DataFrame(ice_rows),
        "feature_group_ablation_validation.csv": ablation_df,
        "feature_group_ablation_simulation_scenarios.csv": pd.DataFrame(simulation_scenarios),
        "feature_group_ablation_simulation_team_probs.csv": pd.DataFrame(simulation_champions),
    }
    for filename, dataframe in artifacts.items():
        dataframe.to_csv(output_dir / filename, index=False)

    metadata["class_distribution"] = dict(Counter(y))
    metadata["model_metrics"] = metric_rows
    metadata["top_features_for_pdp"] = top_features
    metadata["chart_files"] = chart_files
    metadata["simulation_ablation_epochs"] = args.simulation_ablation_epochs
    (output_dir / "analysis_summary.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path = write_report(output_dir, metadata, model_metrics, builtin_df, permutation_df, occlusion_df, ablation_df, simulation_scenarios, chart_files)

    print(f"wrote {output_dir}")
    print(f"report {report_path.name}")
    print("top permutation features:")
    for row in permutation_df[permutation_df["model"] == "random_forest"].head(8).itertuples(index=False):
        print(f"{row.feature}: {row.permutation_importance_neg_log_loss_drop:.5f}")


if __name__ == "__main__":
    main()
