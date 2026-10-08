import json
import math
import textwrap
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "shareable_project_report"
PDF_PATH = OUTPUT_DIR / "fifa_wc26_project_report.pdf"
TEX_PATH = OUTPUT_DIR / "fifa_wc26_project_report.tex"

RESEARCH_DIR = ROOT / "research_upgrade_results_seed_20260622"
COMPARISON_DIR = ROOT / "simulation_10000_model_comparison"
FEATURE_DIR = ROOT / "feature_importance_results_seed_20260618"


def read_csv(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def read_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value, digits=2):
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.{digits}f}%"


def num(value, digits=3):
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):.{digits}f}"


def clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value)
    return text.replace("\n", " ").strip()


def pdf_escape(value):
    return xml_escape(clean(value))


def latex_escape(value):
    text = clean(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def compact_columns(df, columns, rename=None, limit=None):
    if df.empty:
        return pd.DataFrame()
    rename = rename or {}
    output = df[[column for column in columns if column in df.columns]].copy()
    output = output.rename(columns=rename)
    if limit:
        output = output.head(limit)
    return output


def format_table_values(df, percent_cols=None, number_cols=None):
    percent_cols = set(percent_cols or [])
    number_cols = set(number_cols or [])
    formatted = df.copy()
    for column in formatted.columns:
        if column in percent_cols:
            formatted[column] = formatted[column].map(lambda value: pct(value))
        elif column in number_cols:
            formatted[column] = formatted[column].map(lambda value: num(value))
        else:
            formatted[column] = formatted[column].map(clean)
    return formatted


def load_report_data():
    model_metrics = read_csv(RESEARCH_DIR / "model_validation_metrics.csv")
    ensemble_weights = read_csv(RESEARCH_DIR / "ensemble_weights.csv")
    consensus = read_csv(RESEARCH_DIR / "simulation_consensus_ensemble.csv")
    champion_uncertainty = read_csv(RESEARCH_DIR / "simulation_champion_uncertainty.csv")
    tactical = read_csv(RESEARCH_DIR / "team_tactical_priors.csv")
    coverage = read_csv(RESEARCH_DIR / "player_data_coverage.csv")
    source_manifest = read_csv(RESEARCH_DIR / "data_source_manifest.csv")
    research_summary = read_json(RESEARCH_DIR / "research_pipeline_summary.json", {})
    historical_status = read_json(RESEARCH_DIR / "historical_data_readiness.json", {})

    model_metadata = read_csv(COMPARISON_DIR / "simulation_10000_model_metadata.csv")
    champion_matrix = read_csv(COMPARISON_DIR / "simulation_10000_model_champion_matrix.csv")
    player_leaders = read_csv(COMPARISON_DIR / "simulation_10000_model_player_leaders.csv")

    feature_metrics = read_csv(FEATURE_DIR / "model_metrics.csv")
    feature_permutation = read_csv(FEATURE_DIR / "feature_importance_permutation.csv")
    feature_ablation = read_csv(FEATURE_DIR / "feature_group_ablation_validation.csv")
    feature_summary = read_json(FEATURE_DIR / "analysis_summary.json", {})

    elo_report = read_json(ROOT / "national_team_elo_import_report.json", {})
    elo_ratings = read_json(ROOT / "national_team_elo_ratings.json", {})
    external_manifest = read_json(ROOT / "external_football_data_manifest.json", {})
    squad_quality = read_json(ROOT / "squad_data_quality_report.json", {})

    return {
        "model_metrics": model_metrics,
        "ensemble_weights": ensemble_weights,
        "consensus": consensus,
        "champion_uncertainty": champion_uncertainty,
        "tactical": tactical,
        "coverage": coverage,
        "source_manifest": source_manifest,
        "research_summary": research_summary,
        "historical_status": historical_status,
        "model_metadata": model_metadata,
        "champion_matrix": champion_matrix,
        "player_leaders": player_leaders,
        "feature_metrics": feature_metrics,
        "feature_permutation": feature_permutation,
        "feature_ablation": feature_ablation,
        "feature_summary": feature_summary,
        "elo_report": elo_report,
        "elo_ratings": elo_ratings,
        "external_manifest": external_manifest,
        "squad_quality": squad_quality,
    }


def elo_validation(data):
    report = data.get("elo_report", {})
    return report.get("validation", report)


def elo_rating_type_counts(data):
    validation = elo_validation(data)
    return validation.get("rating_type_counts", {})


def elo_rating_type_summary(data):
    counts = elo_rating_type_counts(data)
    if not counts:
        return "unknown"
    return ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))


def elo_status_sentence(data):
    report = data.get("elo_report", {})
    ratings = data.get("elo_ratings", {})
    validation = elo_validation(data)
    counts = elo_rating_type_counts(data)
    team_count = validation.get("team_count", report.get("imported_team_rows", "unknown"))
    missing_required = validation.get("missing_required_teams", [])
    as_of = ratings.get("metadata", {}).get("as_of", "unknown date")
    source = ratings.get("metadata", {}).get("source", "unknown source")
    if counts.get("world_football_elo"):
        return (
            f"The current import report contains {team_count} teams from raw World Football Elo "
            f"as of {as_of}, sourced as {source}. Missing required World Cup teams: {len(missing_required)}."
        )
    return (
        f"The current import report contains {team_count} teams and {len(missing_required)} missing required "
        "World Cup teams. The active rating type is not raw World Football Elo yet; current rating types are "
        f"{elo_rating_type_summary(data)}."
    )


def table_to_latex(df, caption, label=None):
    if df.empty:
        return f"\\paragraph{{{latex_escape(caption)}}} No rows available.\n"
    columns = list(df.columns)
    column_width = max(0.08, min(0.28, 0.94 / max(1, len(columns))))
    alignment = "".join(f"p{{{column_width:.3f}\\linewidth}}" for _ in columns)
    lines = [
        "\\begin{longtable}{" + alignment + "}",
        f"\\caption{{{latex_escape(caption)}}}" + (f"\\label{{{label}}}" if label else "") + r"\\",
        "\\toprule",
        " & ".join(latex_escape(column) for column in columns) + r" \\",
        "\\midrule",
        "\\endfirsthead",
        "\\toprule",
        " & ".join(latex_escape(column) for column in columns) + r" \\",
        "\\midrule",
        "\\endhead",
    ]
    for row in df.itertuples(index=False):
        lines.append(" & ".join(latex_escape(value) for value in row) + r" \\")
    lines.extend(["\\bottomrule", "\\end{longtable}", ""])
    return "\n".join(lines)


def bullet_latex(items):
    lines = ["\\begin{itemize}"]
    for item in items:
        lines.append(f"  \\item {latex_escape(item)}")
    lines.append("\\end{itemize}")
    return "\n".join(lines)


def subsection_latex(title, paragraphs=None, bullets=None):
    paragraphs = paragraphs or []
    bullets = bullets or []
    lines = [f"\\section{{{latex_escape(title)}}}"]
    lines.extend(latex_escape(paragraph) for paragraph in paragraphs)
    if bullets:
        lines.append(bullet_latex(bullets))
    return "\n\n".join(lines)


def detailed_sections(data):
    research = data["research_summary"]
    historical = data["historical_status"]
    squad_quality = data.get("squad_quality", {})
    elo_report = data.get("elo_report", {})
    feature_summary = data.get("feature_summary", {})
    best_validation = ""
    if not data["model_metrics"].empty:
        row = data["model_metrics"].sort_values("log_loss").iloc[0]
        best_validation = f"The best current validation model is {row['model']} with log loss {row['log_loss']:.5f}, accuracy {row['accuracy']:.5f}, and expected calibration error {row['ece']:.5f}."
    top_consensus = ""
    if not data["consensus"].empty:
        leaders = data["consensus"].head(4)
        top_consensus = "The leading consensus teams across the primary 10,000-run models are " + ", ".join(
            f"{row.team} ({row.simple_mean_champion_pct:.2f}%)" for row in leaders.itertuples(index=False)
        ) + "."
    return [
        {
            "title": "1. Project Objective And Starting Point",
            "paragraphs": [
                "The project began as a question: can we build a FIFA World Cup 2026 simulator that is transparent enough to inspect, flexible enough to improve, and rich enough to study why teams become likely winners rather than only outputting a champion list?",
                "The first target was not a perfect prediction engine. The first target was a reproducible baseline: take squads, attach player strength, simulate a tournament thousands of times, store probabilities, and then progressively replace assumptions with better data. That framing matters because every later improvement keeps the earlier baseline available for comparison.",
                "The workspace now contains a complete chain from squad parsing and enrichment to event simulation, machine-learning outcome layers, feature analysis, uncertainty reporting, and external-data ingestion. The report below explains that chain from scratch.",
            ],
            "bullets": [
                "Tournament scope: the 48-team FIFA World Cup 2026 structure.",
                "Core outputs: team stage probabilities, champion probabilities, player scoring/assist leaderboards, event totals, feature importances, calibration tables, and data-quality diagnostics.",
                "Philosophy: keep every assumption auditable and every generated result stored as JSON, CSV, Markdown, LaTeX, or PDF.",
            ],
        },
        {
            "title": "2. Raw Data Foundations",
            "paragraphs": [
                "The project starts from squad and rating information. The squad file is guardian_world_cup_2026_player_guide.json, which represents the active 48-team, 1,248-player working squad dataset. The original baseline also depends on fifa_squadlists_english.pdf and eafc26_players.csv, which are large local source files and are intentionally ignored by Git.",
                "The squad rebuild path is handled by rebuild_squads_from_fifa_pdf.py. The enrichment path is handled by enrich_squads_with_eafc.py. Together, those scripts establish team rosters, player names, official positions, and EAFC/FIFA-style ratings or fallback ratings where no confident EAFC match exists.",
                f"The latest squad quality report checks {squad_quality.get('team_count', 48)} teams and {squad_quality.get('player_count', 1248)} players. It currently marks the data as {squad_quality.get('status', 'unknown')} with {squad_quality.get('issue_count', 'unknown')} squad-shape issues, mostly position-distribution anomalies that should be refreshed against the official PDF before treating player-level outputs as final.",
            ],
            "bullets": [
                "The primitive baseline uses EAFC-style player ratings as its main strength signal.",
                "The v2 simulator uses the richer player-performance dataset player_performance_data_statbunker.json when building effective ratings and event tendencies.",
                "The project keeps large generated and source files outside Git where practical, but keeps scripts, templates, and reports in the workspace.",
            ],
        },
        {
            "title": "3. Player Performance Data Collection",
            "paragraphs": [
                "The second phase tried to move beyond static ratings. Several collectors were created because public football data is fragmented and often blocked for automated access. collect_player_performance_data.py targets SofaScore-style profile evidence; collect_player_performance_data_edge.py tries browser-assisted access when direct requests are blocked; collect_player_performance_data_providers.py supports key-based providers such as Sportmonks, API-Football/API-Sports, and FootyStats; collect_player_performance_data_statbunker.py collects public StatBunker competition tables.",
                "StatBunker became the current free fallback. It gives useful public player-table data such as appearances, goals, assists, cards, penalties, fantasy points where requested, and goalkeeper clean-sheet data. It does not fully solve the problem because it lacks many event-level metrics such as xG, xA, pressures, carries, tackles, saves, and SofaScore-style match ratings.",
                "Because player coverage is uneven, the research pipeline now creates player_data_coverage.csv. This explicitly identifies teams where low-confidence players or zero-minute players weaken the model. That turns data quality into a measurable object rather than a vague concern.",
            ],
            "bullets": [
                "SofaScore access was unreliable because direct endpoints often return 403 outside a browser session.",
                "Browser-assisted collection can recover some profile evidence, but is not a robust full dataset.",
                "Paid/key-based providers remain the best future route for complete player-level event data.",
                "Current lowest-confidence coverage includes Panama, Senegal, Mexico, Scotland, Canada, Ivory Coast, Czech Republic, and the United States.",
            ],
        },
        {
            "title": "4. Primitive Baseline Simulator",
            "paragraphs": [
                "The first working model is simulate_world_cup.py. It exists as an intentionally simple baseline. Each tournament epoch simulates the group stage, ranks group tables, advances top-two teams plus the eight best third-place teams, simulates knockouts, simulates the third-place match, and stores team and player outputs.",
                "Team strength in this baseline is built from best XI average, top-18 depth, and full-squad average. Match goals are generated from a Poisson model. Knockout draws are resolved through extra time and penalties. Player goals and assists are assigned probabilistically using player position and rating.",
                "The primitive 10,000-run output is simulation_results_10000.json, with a visual report in simulation_report_10000. It remains valuable because it tells us what the simplest rating-and-goals model thinks before later event, Elo, and ML layers alter the result.",
            ],
            "bullets": [
                "Primitive champion leader: France at 12.50%.",
                "Other high primitive probabilities include Spain, England, Brazil, Portugal, Germany, Argentina, and the Netherlands.",
                "This model does not include possession, fatigue, cards, travel, climate, Random Forest adjustment, player availability, or calibrated historical supervision.",
            ],
        },
        {
            "title": "5. V2 Event Simulator",
            "paragraphs": [
                "simulate_world_cup_v2.py is the major modelling upgrade. It keeps the tournament structure but changes the match engine from a simple Poisson-only model into a compressed event simulator. A 90-minute match is represented by 9 simulated minutes, and extra time is represented by 3 simulated minutes.",
                "The v2 engine adds possession, fouls, yellow cards, red cards, second yellows, player removals, substitutions, fatigue, set-piece goals, game-state behavior, extra time, penalties, rest-day context, date-aware scheduling, host-country signals, venue/climate/travel priors, and constrained Round-of-32 routing.",
                "Only the team with possession can score during an event tick. Cards and fatigue alter team state. Red cards and second yellows remove players. Substitutes are modelled as fresher than tired starters. These mechanics are still simplified, but they are much closer to the match process we want to study than the primitive baseline.",
            ],
            "bullets": [
                "The engine exports pandas-compatible feature frames for inspection.",
                "It can run CPU-parallel tournament batches, which is why 10,000-run v2 simulations were practical on the Ryzen 7 8845HS.",
                "It supports a heuristic internal forest or scikit-learn Random Forest match outcome layer.",
            ],
        },
        {
            "title": "6. National-Team Elo And Rating Priors",
            "paragraphs": [
                "The simulator now reads national_team_elo_ratings.json as a national-team prior. The file can contain all national teams, not just the World Cup teams. The simulator consumes the teams in the tournament structure, while aliases help historical match training match names such as USA, Czechia, Korea Republic, and Cote d'Ivoire.",
                elo_status_sentence(data),
                "The active ratings now come from external_data/world_football_elo/international_football_elo_20260611.json. The earlier FIFA-rank-derived fallback was preserved in external_data/world_football_elo for audit and rollback.",
            ],
            "bullets": [
                "Preferred priority: world_football_elo first, then elo/rating, then FIFA points, then FIFA rank-derived Elo, then squad proxy fallback.",
                "World Football Elo source is configured as https://www.eloratings.net/.",
                "A template exists at world_football_elo_current_template.csv.",
            ],
        },
        {
            "title": "7. Historical Match Data Path",
            "paragraphs": [
                "The Random Forest and research pipeline are prepared for supervised historical match training, but the local workspace does not yet contain the historical results CSV. The chosen source is martj42/international_results, specifically its results.csv with date, home_team, away_team, home_score, away_score, tournament, city, country, and neutral columns.",
                "fetch_external_football_data.py can download and normalize that CSV when network access is available. In this workspace, direct access to raw.githubusercontent.com is blocked, so the manifest records the failed download and tells us where the raw file should be placed: external_data/international_results/results.csv.",
                f"The current research pipeline therefore reports historical data readiness as {historical.get('status', 'missing')}, with {historical.get('usable_matches', 0)} usable historical matches. As a result, model validation currently measures the simulator's synthetic/profile calibration, not real-world historical predictive performance.",
            ],
            "bullets": [
                "Once results.csv is placed locally, fetch_external_football_data.py normalizes it into historical_international_results.csv.",
                "simulate_world_cup_v2.py and analyze_feature_importance.py already accept --historical-matches.",
                "If the historical file is small, the project blends it with synthetic calibration rows instead of discarding it.",
            ],
        },
        {
            "title": "8. Random Forest And Model Training Layer",
            "paragraphs": [
                "The machine-learning layer was introduced so we can study factors rather than only simulate outcomes. The Random Forest consumes match-level feature differences: Elo difference, squad rating difference, attack-versus-defense, defense-versus-attack, midfield difference, goalkeeper difference, possession difference, discipline difference, data confidence, host context, rest, fatigue, lineup replacements, altitude, travel, heat, humidity, venue altitude, stage type, draw allowance, and match-day index.",
                f"In the current feature-importance run, the training source is {feature_summary.get('training_source', 'unknown')} with {feature_summary.get('rows', 'unknown')} rows. These are synthetic profile-calibration rows because historical match data is not yet present.",
                best_validation or "Validation metrics are available in model_validation_metrics.csv.",
            ],
            "bullets": [
                "Random Forest is used as one model, not the only model.",
                "The research layer also trains Extra Trees, histogram gradient boosting, logistic regression, and calibrated logistic regression.",
                "The ensemble weights are derived from validation log loss so stronger validation models receive slightly higher influence.",
            ],
        },
        {
            "title": "9. 10,000-Run Simulation Comparisons",
            "paragraphs": [
                "The project now stores comparable 10,000-run outputs for three primary model families: primitive EAFC Poisson, v2 heuristic internal forest with NT Elo, and v2 scikit-learn Random Forest with NT Elo. It also preserves a legacy v2 Random Forest run that used squad-proxy Elo before the NT Elo import.",
                top_consensus or "The consensus champion table is stored in simulation_consensus_ensemble.csv.",
                "generate_10000_model_comparison_report.py turns those runs into a common table structure. That matters because each raw simulation JSON has a slightly different schema, and the comparison report provides a single long team summary, champion matrix, metadata file, and player leaderboards.",
            ],
            "bullets": [
                "Primitive EAFC Poisson top winner: France.",
                "V2 heuristic with NT Elo top winner: Brazil.",
                "V2 Random Forest with NT Elo top winner: Brazil.",
                "The v2 event models concentrate more probability among Brazil, Germany, France, and Spain than the primitive model does.",
            ],
        },
        {
            "title": "10. Feature Importance And Explainability",
            "paragraphs": [
                "analyze_feature_importance.py was added to answer a more important research question: which factors actually drive the model's predictions? It trains several comparison models, exports Random Forest trees, calculates built-in tree importances, permutation importances, logistic coefficients, local occlusion effects, partial dependence, ICE curves, validation group ablations, and tournament simulation ablation scenarios.",
                "The strongest Random Forest permutation features are squad_rating_diff, possession_diff, attack_vs_defense, midfield_diff, defense_vs_attack, elo_diff, and gk_diff. Local occlusion tells a similar story: neutralizing squad rating, possession, attacking matchup, midfield, and defensive matchup moves the model's true-class probabilities the most.",
                "At the group level, unit_matchups is the most important ablation group. This group includes attack_vs_defense, defense_vs_attack, midfield_diff, gk_diff, and possession_diff. In plain English, the model is not only looking at which team is stronger overall; it cares about how specific units match up.",
            ],
            "bullets": [
                "Feature importance outputs live in feature_importance_results_seed_20260618.",
                "Random Forest trees were exported to text and JSON for inspection.",
                "The feature report warns that current importances explain simulator assumptions until real historical rows are supplied.",
            ],
        },
        {
            "title": "11. Calibration, Uncertainty, And Ensemble Research Layer",
            "paragraphs": [
                "run_research_upgrade_pipeline.py adds a research layer on top of the simulator outputs. It trains comparison models, evaluates accuracy, balanced accuracy, log loss, multiclass Brier score, and expected calibration error, then writes calibration bins and ensemble weights.",
                "It also computes Wilson 95 percent uncertainty intervals for every stored 10,000-run stage probability. This changes how probabilities should be read: Brazil at about 20 percent is not a single exact truth; it is an estimate with simulation uncertainty and model uncertainty.",
                "The pipeline also writes tactical priors and player data coverage diagnostics. Tactical priors are inferred from current squad profiles, so they are useful modelling features but should not be mistaken for validated event-style data.",
            ],
            "bullets": [
                "Current best validation log loss: calibrated_logistic_sigmoid.",
                "Current strongest calibration by ECE: histogram gradient boosting in the stored research report.",
                "Consensus ensemble and uncertainty tables live in research_upgrade_results_seed_20260622.",
            ],
        },
        {
            "title": "12. How To Read The Results",
            "paragraphs": [
                "The results should be read as model-conditioned tournament probabilities. They are not declarations of what will happen. Every number depends on the current squad data, current player-performance coverage, current Elo prior, current fixture assumptions, and current match engine.",
                "The most useful result is not just the top champion. The useful result is how different model families disagree. For example, the primitive baseline gives France the highest title chance, while both v2 event models make Brazil the top title candidate. That disagreement tells us that event-engine assumptions and rating priors materially affect the output.",
                "The player leaderboards are especially sensitive to squad-shape and player-data quality. They are good for checking whether the simulator behaves plausibly, but they should not be shared as final player award predictions until the squad quality issues and player coverage weaknesses are resolved.",
            ],
            "bullets": [
                "Use consensus tables for a conservative model-family view.",
                "Use uncertainty intervals to avoid over-reading small percentage differences.",
                "Use feature importance and ablation tables to understand model behavior.",
                "Use coverage tables to decide what data to improve next.",
            ],
        },
        {
            "title": "13. Reproducible Build Ledger",
            "paragraphs": [
                "This section records what was actually built in the workspace. It is included so the report can be shared with someone who has not watched the project evolve conversation by conversation.",
                "The project did not jump straight to a Random Forest. It moved through a deliberate sequence: establish a squad dataset, build a primitive baseline, enrich player evidence, add a more realistic event engine, add rating priors, add machine-learning layers, run comparable 10,000 simulations, explain the model, and finally add research diagnostics and external-data ingestion.",
            ],
            "bullets": [
                "Created or maintained rebuild_squads_from_fifa_pdf.py to parse FIFA squad-list inputs into the working squad JSON.",
                "Created or maintained enrich_squads_with_eafc.py to attach EAFC/FIFA-style player ratings, detailed positions, and fallback ratings.",
                "Ran the primitive simulator simulate_world_cup.py and generated simulation_results_10000.json plus simulation_report_10000.",
                "Created generate_simulation_report.py for the original HTML/SVG simulation report.",
                "Built performance data collectors for SofaScore-style pages, browser-assisted fallback, key-based providers, and StatBunker public tables.",
                "Stored player_performance_data_statbunker.json as the current free public performance-data layer.",
                "Created simulate_world_cup_v2.py with possession, fouls, cards, removals, fatigue, substitutions, set pieces, compressed match time, extra time, penalties, rest, venue, climate, travel, and bracket routing.",
                "Added --trace-one output so one simulated tournament can be watched and recorded in the console.",
                "Added CPU-parallel v2 tournament execution for large runs on the Ryzen 7 8845HS.",
                "Created import_national_team_elo.py and national_team_elo_ratings.json to support all-national-team rating priors and aliases.",
                "Created world_cup_2026_venue_context.json for group-level and knockout-level venue, climate, altitude, and travel priors.",
                "Added scikit-learn Random Forest support with synthetic calibration and optional historical CSV training.",
                "Exported Random Forest trees to readable text and JSON using export_random_forest_trees.py.",
                "Ran 10,000 simulations for primitive EAFC Poisson, v2 heuristic with NT Elo, and v2 Random Forest with NT Elo.",
                "Created generate_10000_model_comparison_report.py to compare all stored 10,000-run model outputs.",
                "Created analyze_feature_importance.py to compute model metrics, feature importance, local occlusion, PDP/ICE, and ablation studies.",
                "Created run_research_upgrade_pipeline.py for calibration, ensemble weights, uncertainty intervals, tactical priors, player-data coverage, source manifests, and a local dashboard.",
                "Created fetch_external_football_data.py to normalize martj42/international_results and import World Football Elo CSV/JSON files.",
                "Created generate_shareable_latex_report.py to produce this PDF and matching LaTeX source from the stored outputs.",
            ],
        },
        {
            "title": "14. What The Stored Files Mean",
            "paragraphs": [
                "The project stores raw model outputs separately from reports. This is intentional: reports can be regenerated, while CSV and JSON outputs remain the auditable data behind those reports.",
                "The most important folder for current study is research_upgrade_results_seed_20260622. It contains validation metrics, calibration bins, uncertainty intervals, consensus champion probabilities, tactical priors, player coverage, and the local HTML dashboard. The most important folder for model comparison is simulation_10000_model_comparison. The most important folder for feature interpretation is feature_importance_results_seed_20260618.",
            ],
            "bullets": [
                "simulation_10000_model_team_summary.csv is the long table of team stage probabilities by model.",
                "simulation_10000_model_champion_matrix.csv is the wide title-probability comparison across models.",
                "simulation_consensus_ensemble.csv is the current primary cross-model champion consensus.",
                "simulation_stage_uncertainty.csv gives Wilson intervals for all stage probabilities.",
                "model_validation_metrics.csv compares candidate predictive models on accuracy, balanced accuracy, log loss, Brier score, and calibration error.",
                "feature_importance_permutation.csv gives model-agnostic feature importance by shuffling each feature.",
                "feature_group_ablation_validation.csv estimates how much validation performance drops when a feature group is neutralized.",
                "player_data_coverage.csv identifies which teams most need better player-level data before player outputs should be trusted.",
                "external_football_data_manifest.json records the configured historical-results and World Football Elo sources.",
            ],
        },
    ]


def detailed_sections_latex(data):
    return "\n\n".join(subsection_latex(section["title"], section.get("paragraphs"), section.get("bullets")) for section in detailed_sections(data))


def generate_latex(data):
    model_metrics = format_table_values(
        compact_columns(
            data["model_metrics"],
            ["model", "accuracy", "balanced_accuracy", "log_loss", "brier_multiclass", "ece"],
            {
                "balanced_accuracy": "balanced acc.",
                "brier_multiclass": "Brier",
            },
            limit=8,
        ),
        number_cols=["accuracy", "balanced acc.", "log_loss", "Brier", "ece"],
    )
    ensemble = format_table_values(compact_columns(data["ensemble_weights"], ["model", "log_loss", "weight"], limit=8), number_cols=["log_loss", "weight"])
    consensus = format_table_values(
        compact_columns(
            data["consensus"],
            ["team", "simple_mean_champion_pct", "median_champion_pct", "model_range_pct", "v2_event_model_mean_champion_pct"],
            {
                "simple_mean_champion_pct": "mean title %",
                "median_champion_pct": "median title %",
                "model_range_pct": "model range",
                "v2_event_model_mean_champion_pct": "v2 mean title %",
            },
            limit=12,
        ),
        percent_cols=["mean title %", "median title %", "model range", "v2 mean title %"],
    )
    current_models = format_table_values(
        compact_columns(
            data["model_metadata"],
            ["model_label", "file", "epochs", "seed", "elo_source", "decision_forest_kind", "training_rows"],
            {
                "model_label": "model",
                "decision_forest_kind": "forest",
            },
        )
    )
    uncertainty = data["champion_uncertainty"].copy()
    if not uncertainty.empty:
        uncertainty = uncertainty.sort_values(["model_label", "probability_pct"], ascending=[True, False]).groupby("model_label", group_keys=False).head(5)
    uncertainty = format_table_values(
        compact_columns(
            uncertainty,
            ["model_label", "team", "probability_pct", "ci95_low_pct", "ci95_high_pct"],
            {"model_label": "model", "probability_pct": "title %", "ci95_low_pct": "95% low", "ci95_high_pct": "95% high"},
        ),
        percent_cols=["title %", "95% low", "95% high"],
    )
    rf_perm = data["feature_permutation"]
    if not rf_perm.empty and "model" in rf_perm.columns:
        rf_perm = rf_perm[rf_perm["model"] == "random_forest"].sort_values("permutation_importance_neg_log_loss_drop", ascending=False)
    rf_perm = format_table_values(
        compact_columns(
            rf_perm,
            ["feature", "permutation_importance_neg_log_loss_drop", "std"],
            {"permutation_importance_neg_log_loss_drop": "perm. log-loss delta"},
            limit=10,
        ),
        number_cols=["perm. log-loss delta", "std"],
    )
    ablation = format_table_values(
        compact_columns(
            data["feature_ablation"].sort_values("log_loss_increase", ascending=False) if not data["feature_ablation"].empty else data["feature_ablation"],
            ["group", "log_loss_increase", "accuracy_drop"],
            {"log_loss_increase": "log-loss increase", "accuracy_drop": "accuracy drop"},
        ),
        number_cols=["log-loss increase", "accuracy drop"],
    )
    tactical = format_table_values(
        compact_columns(
            data["tactical"],
            ["team", "pressing_score", "counterattack_score", "low_block_resilience", "set_piece_attack_score", "tempo_score", "data_confidence"],
            {
                "pressing_score": "pressing",
                "counterattack_score": "counter",
                "low_block_resilience": "low block",
                "set_piece_attack_score": "set pieces",
                "tempo_score": "tempo",
                "data_confidence": "confidence",
            },
            limit=12,
        ),
        number_cols=["pressing", "counter", "low block", "set pieces", "tempo", "confidence"],
    )
    coverage = format_table_values(
        compact_columns(
            data["coverage"],
            ["team", "avg_source_confidence", "players_below_0_55_confidence", "players_with_zero_minutes", "primary_sources"],
            {
                "avg_source_confidence": "avg confidence",
                "players_below_0_55_confidence": "low conf. players",
                "players_with_zero_minutes": "zero-minute players",
            },
            limit=10,
        ),
        number_cols=["avg confidence"],
    )
    scorers = data["player_leaders"]
    if not scorers.empty:
        scorers = scorers[(scorers["primary_comparison"] == True) & (scorers["category"] == "goals") & (scorers["rank"] <= 5)]
    scorers = format_table_values(
        compact_columns(
            scorers,
            ["model_label", "rank", "player", "team", "goals_per_tournament"],
            {"model_label": "model", "goals_per_tournament": "goals/tourn."},
        ),
        number_cols=["goals/tourn."],
    )
    assisters = data["player_leaders"]
    if not assisters.empty:
        assisters = assisters[(assisters["primary_comparison"] == True) & (assisters["category"] == "assists") & (assisters["rank"] <= 5)]
    assisters = format_table_values(
        compact_columns(
            assisters,
            ["model_label", "rank", "player", "team", "assists_per_tournament"],
            {"model_label": "model", "assists_per_tournament": "assists/tourn."},
        ),
        number_cols=["assists/tourn."],
    )
    source_manifest = compact_columns(data["source_manifest"], ["name", "purpose", "local_filename", "status"])

    historical_status = data["historical_status"]
    elo_report = data["elo_report"]
    external_sources = data["external_manifest"].get("sources", {})
    generated = date.today().isoformat()

    body = [
        r"\documentclass[10pt]{article}",
        r"\usepackage[margin=0.65in]{geometry}",
        r"\usepackage{booktabs,longtable,array,xcolor,hyperref}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{lmodern}",
        r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{6pt}",
        r"\title{\textbf{FIFA World Cup 2026 Simulation Project}\\Data, Models, Results, and Research State}",
        r"\author{Generated from the local FIFA\_WC\_26 workspace}",
        rf"\date{{{latex_escape(generated)}}}",
        r"\begin{document}",
        r"\maketitle",
        r"\tableofcontents",
        r"\newpage",
        r"\section{Executive Summary}",
        "This project is now a multi-layer FIFA World Cup 2026 simulation and analysis system. It includes a primitive EAFC/Poisson baseline, a second-generation event simulator with possession, fatigue, substitutions, cards, extra time, penalties, venue and schedule context, a scikit-learn Random Forest outcome layer, a heuristic internal forest, 10,000-run model comparisons, feature importance analysis, calibration diagnostics, uncertainty intervals, tactical priors, and external-data ingestion paths.",
        bullet_latex(
            [
                "Current primary champion consensus across the three 10,000-run primary models begins with France, Brazil, Germany, and Spain.",
                "The current validation layer ranks calibrated logistic regression first by log loss, followed by the weighted validation ensemble and Random Forest.",
                "The Random Forest feature study identifies squad strength, possession edge, attack-versus-defense, midfield edge, defense-versus-attack, and Elo difference as the strongest individual signals.",
                "The project now has a complete 2026-06-11 raw World Football Elo export imported locally; martj42/international_results is still awaiting a local results.csv because direct network access is blocked.",
                "The stored 10,000-run result artifacts should be rerun before they are treated as final raw-Elo simulation probabilities.",
                "Until real historical match data is supplied, model results explain calibrated assumptions more than validated real-world causality.",
            ]
        ),
        r"\newpage",
        detailed_sections_latex(data),
        r"\newpage",
        r"\section{Current Artifacts}",
        table_to_latex(current_models, "Stored 10,000-run model outputs"),
        r"\section{10,000 Simulation Results}",
        table_to_latex(consensus, "Cross-model champion consensus"),
        table_to_latex(uncertainty, "Champion probability uncertainty, Wilson 95 percent intervals"),
        r"\section{Validation, Calibration, and Ensemble}",
        table_to_latex(model_metrics, "Validation metrics from the research upgrade pipeline"),
        table_to_latex(ensemble, "Validation-loss-based ensemble weights"),
        r"\section{Feature Importance}",
        f"The feature-importance run used {latex_escape(data['feature_summary'].get('training_source', 'unknown'))} with {latex_escape(data['feature_summary'].get('rows', ''))} rows.",
        table_to_latex(rf_perm, "Random Forest permutation feature importance"),
        table_to_latex(ablation, "Feature group ablation on validation loss"),
        r"\section{Player and Tactical Layer}",
        table_to_latex(tactical, "Top tactical priors inferred from current team profiles"),
        table_to_latex(coverage, "Player data coverage weak spots"),
        table_to_latex(scorers, "Top simulated scorers by primary model"),
        table_to_latex(assisters, "Top simulated assisters by primary model"),
        r"\section{External Data and Elo}",
        f"Historical data readiness status: {latex_escape(historical_status.get('status', 'unknown'))}. Usable historical matches currently detected: {latex_escape(historical_status.get('usable_matches', 0))}.",
        elo_status_sentence(data),
        table_to_latex(format_table_values(source_manifest), "External data manifest"),
        r"\subsection{Configured Sources}",
        bullet_latex(
            [
                f"International results repo: {external_sources.get('international_results', {}).get('repo', 'https://github.com/martj42/international_results')}",
                f"International results raw CSV: {external_sources.get('international_results', {}).get('raw_results_url', 'https://raw.githubusercontent.com/martj42/international_results/master/results.csv')}",
                f"World Football Elo source: {external_sources.get('world_football_elo', {}).get('source_url', 'https://www.eloratings.net/')}",
                "Expected local historical file: external_data/international_results/results.csv or historical_international_results.csv",
                "Active Elo import file: external_data/world_football_elo/international_football_elo_20260611.json.",
            ]
        ),
        r"\section{What Is Still Missing}",
        bullet_latex(
            [
                "Raw historical international match results are not yet present locally because the workspace cannot reach raw.githubusercontent.com.",
                "Time-aware Elo snapshots before every historical match are not yet present; the current active Elo file is a 2026-06-11 tournament-baseline snapshot.",
                "The existing 10,000-run probability artifacts predate the full raw Elo import and should be regenerated for a clean raw-Elo study.",
                "The Random Forest remains synthetically calibrated until enough real historical rows are available.",
                "Tactical priors are inferred from squad profiles and need real event/style data for validation.",
                "Player-level data coverage is uneven; Panama, Senegal, Mexico, Scotland, Canada, Ivory Coast, Czech Republic, and the United States are among the teams where better player data would improve confidence.",
            ]
        ),
        r"\section{Reproduction Commands}",
        r"\begin{verbatim}",
        "python fetch_external_football_data.py --download-international-results",
        "python import_national_team_elo.py --input external_data/world_football_elo/international_football_elo_20260611.json --as-of 2026-06-11 --rating-type world_football_elo",
        "python run_research_upgrade_pipeline.py --seed 20260622 --output-dir research_upgrade_results_seed_20260622",
        "python generate_10000_model_comparison_report.py",
        "python analyze_feature_importance.py --seed 20260618 --simulation-ablation-epochs 30 --output-dir feature_importance_results_seed_20260618",
        r"\end{verbatim}",
        r"\section{Shareable File Index}",
        bullet_latex(
            [
                "shareable_project_report/fifa_wc26_project_report.pdf",
                "shareable_project_report/fifa_wc26_project_report.tex",
                "research_upgrade_results_seed_20260622/research_upgrade_report.md",
                "simulation_10000_model_comparison/simulation_10000_models_report.md",
                "feature_importance_results_seed_20260618/feature_importance_report.md",
                "external_football_data_manifest.json",
            ]
        ),
        r"\end{document}",
    ]
    return "\n\n".join(body) + "\n"


def make_styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(name="TitleCenter", parent=base["Title"], alignment=TA_CENTER, fontSize=21, leading=26, spaceAfter=12))
    base.add(ParagraphStyle(name="Subtitle", parent=base["Normal"], alignment=TA_CENTER, fontSize=10, textColor=colors.HexColor("#475569"), spaceAfter=18))
    base.add(ParagraphStyle(name="Small", parent=base["Normal"], fontSize=7.4, leading=9.0))
    base.add(ParagraphStyle(name="SmallBold", parent=base["Small"], fontName="Helvetica-Bold"))
    base.add(ParagraphStyle(name="SectionHead", parent=base["Heading1"], fontSize=15, leading=18, textColor=colors.HexColor("#0f172a"), spaceBefore=12, spaceAfter=8))
    base.add(ParagraphStyle(name="SubHead", parent=base["Heading2"], fontSize=11, leading=14, textColor=colors.HexColor("#334155"), spaceBefore=10, spaceAfter=6))
    base.add(ParagraphStyle(name="BodyTight", parent=base["BodyText"], fontSize=9.2, leading=12, alignment=TA_LEFT))
    return base


def para(text, style):
    return Paragraph(pdf_escape(text), style)


def pdf_table(df, styles, col_widths=None, repeat_rows=1):
    if df.empty:
        return para("No rows available.", styles["BodyTight"])
    display = df.copy().fillna("")
    data = [[Paragraph(f"<b>{pdf_escape(column)}</b>", styles["Small"]) for column in display.columns]]
    for row in display.to_dict("records"):
        data.append([Paragraph(pdf_escape(value), styles["Small"]) for value in row.values()])
    if col_widths is None:
        usable_width = landscape(A4)[0] - 2.2 * cm
        col_widths = [usable_width / len(display.columns)] * len(display.columns)
    table = Table(data, colWidths=col_widths, repeatRows=repeat_rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def bullet_pdf(items, styles):
    return ListFlowable(
        [ListItem(Paragraph(pdf_escape(item), styles["BodyTight"]), leftIndent=12) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=14,
    )


def add_section(story, styles, title):
    story.append(Paragraph(title, styles["SectionHead"]))


def add_subhead(story, styles, title):
    story.append(Paragraph(title, styles["SubHead"]))


def add_detailed_sections_pdf(story, styles, data):
    for index, section in enumerate(detailed_sections(data), start=1):
        if index in {4, 8, 11}:
            story.append(PageBreak())
        add_section(story, styles, section["title"])
        for paragraph in section.get("paragraphs", []):
            story.append(para(paragraph, styles["BodyTight"]))
            story.append(Spacer(1, 3))
        if section.get("bullets"):
            story.append(bullet_pdf(section["bullets"], styles))
            story.append(Spacer(1, 5))


def generate_pdf(data):
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=landscape(A4),
        leftMargin=1.1 * cm,
        rightMargin=1.1 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.0 * cm,
        title="FIFA WC26 Project Report",
        author="FIFA_WC_26 workspace",
    )
    story = [
        Paragraph("FIFA World Cup 2026 Simulation Project", styles["TitleCenter"]),
        Paragraph("Data, Models, Results, and Research State", styles["Subtitle"]),
        para(f"Generated from the local FIFA_WC_26 workspace on {date.today().isoformat()}.", styles["BodyTight"]),
        Spacer(1, 8),
    ]

    model_metrics = format_table_values(
        compact_columns(data["model_metrics"], ["model", "accuracy", "balanced_accuracy", "log_loss", "brier_multiclass", "ece"], {"balanced_accuracy": "balanced acc.", "brier_multiclass": "Brier"}, limit=8),
        number_cols=["accuracy", "balanced acc.", "log_loss", "Brier", "ece"],
    )
    ensemble = format_table_values(compact_columns(data["ensemble_weights"], ["model", "log_loss", "weight"], limit=8), number_cols=["log_loss", "weight"])
    consensus = format_table_values(
        compact_columns(data["consensus"], ["team", "simple_mean_champion_pct", "median_champion_pct", "model_range_pct", "v2_event_model_mean_champion_pct"], {"simple_mean_champion_pct": "mean title %", "median_champion_pct": "median title %", "model_range_pct": "range", "v2_event_model_mean_champion_pct": "v2 mean %"}, limit=14),
        percent_cols=["mean title %", "median title %", "range", "v2 mean %"],
    )
    current_models = format_table_values(compact_columns(data["model_metadata"], ["model_label", "epochs", "seed", "elo_source", "decision_forest_kind", "training_rows"], {"model_label": "model", "decision_forest_kind": "forest"}))
    uncertainty = data["champion_uncertainty"].copy()
    if not uncertainty.empty:
        uncertainty = uncertainty.sort_values(["model_label", "probability_pct"], ascending=[True, False]).groupby("model_label", group_keys=False).head(5)
    uncertainty = format_table_values(compact_columns(uncertainty, ["model_label", "team", "probability_pct", "ci95_low_pct", "ci95_high_pct"], {"model_label": "model", "probability_pct": "title %", "ci95_low_pct": "95% low", "ci95_high_pct": "95% high"}), percent_cols=["title %", "95% low", "95% high"])
    rf_perm = data["feature_permutation"]
    if not rf_perm.empty and "model" in rf_perm.columns:
        rf_perm = rf_perm[rf_perm["model"] == "random_forest"].sort_values("permutation_importance_neg_log_loss_drop", ascending=False)
    rf_perm = format_table_values(compact_columns(rf_perm, ["feature", "permutation_importance_neg_log_loss_drop", "std"], {"permutation_importance_neg_log_loss_drop": "perm. delta"}, limit=10), number_cols=["perm. delta", "std"])
    ablation = format_table_values(compact_columns(data["feature_ablation"].sort_values("log_loss_increase", ascending=False) if not data["feature_ablation"].empty else data["feature_ablation"], ["group", "log_loss_increase", "accuracy_drop"], {"log_loss_increase": "loss increase", "accuracy_drop": "acc. drop"}), number_cols=["loss increase", "acc. drop"])
    tactical = format_table_values(compact_columns(data["tactical"], ["team", "pressing_score", "counterattack_score", "low_block_resilience", "set_piece_attack_score", "tempo_score", "data_confidence"], {"pressing_score": "pressing", "counterattack_score": "counter", "low_block_resilience": "low block", "set_piece_attack_score": "set pieces", "tempo_score": "tempo", "data_confidence": "confidence"}, limit=12), number_cols=["pressing", "counter", "low block", "set pieces", "tempo", "confidence"])
    coverage = format_table_values(compact_columns(data["coverage"], ["team", "avg_source_confidence", "players_below_0_55_confidence", "players_with_zero_minutes", "primary_sources"], {"avg_source_confidence": "avg confidence", "players_below_0_55_confidence": "low conf.", "players_with_zero_minutes": "zero min."}, limit=10), number_cols=["avg confidence"])
    source_manifest = compact_columns(data["source_manifest"], ["name", "purpose", "local_filename", "status"])
    scorers = data["player_leaders"]
    if not scorers.empty:
        scorers = scorers[(scorers["primary_comparison"] == True) & (scorers["category"] == "goals") & (scorers["rank"] <= 5)]
    scorers = format_table_values(compact_columns(scorers, ["model_label", "rank", "player", "team", "goals_per_tournament"], {"model_label": "model", "goals_per_tournament": "goals/tourn."}), number_cols=["goals/tourn."])
    assisters = data["player_leaders"]
    if not assisters.empty:
        assisters = assisters[(assisters["primary_comparison"] == True) & (assisters["category"] == "assists") & (assisters["rank"] <= 5)]
    assisters = format_table_values(compact_columns(assisters, ["model_label", "rank", "player", "team", "assists_per_tournament"], {"model_label": "model", "assists_per_tournament": "assists/tourn."}), number_cols=["assists/tourn."])

    add_section(story, styles, "Executive Summary")
    story.append(
        para(
            "This project is now a multi-layer FIFA World Cup 2026 simulation and analysis system with primitive, event-based, heuristic, Random Forest, ensemble, calibration, uncertainty, tactical-prior, and external-data-ingestion layers.",
            styles["BodyTight"],
        )
    )
    story.append(
        bullet_pdf(
            [
                "Primary champion consensus begins with France, Brazil, Germany, and Spain.",
                "The best current validation log loss is from calibrated logistic regression, followed by the weighted ensemble and Random Forest.",
                "Random Forest explanations point first to squad rating, possession edge, attack-versus-defense, midfield edge, defense-versus-attack, and Elo difference.",
                "External historical results and World Football Elo ingestion are wired, but the source files are not yet locally present because network access is blocked.",
            ],
            styles,
        )
    )

    story.append(PageBreak())
    add_detailed_sections_pdf(story, styles, data)
    story.append(PageBreak())

    add_section(story, styles, "Model Inventory")
    story.append(pdf_table(current_models, styles, [6.0 * cm, 1.5 * cm, 1.7 * cm, 7.0 * cm, 4.2 * cm, 2.0 * cm]))

    add_section(story, styles, "10,000 Simulation Results")
    add_subhead(story, styles, "Cross-Model Champion Consensus")
    story.append(pdf_table(consensus, styles, [3.0 * cm, 3.0 * cm, 3.0 * cm, 2.6 * cm, 3.0 * cm]))
    add_subhead(story, styles, "Champion Uncertainty")
    story.append(pdf_table(uncertainty, styles, [6.2 * cm, 3.1 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm]))

    story.append(PageBreak())
    add_section(story, styles, "Validation, Calibration, and Ensemble")
    story.append(pdf_table(model_metrics, styles, [5.3 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.0 * cm, 1.8 * cm]))
    add_subhead(story, styles, "Ensemble Weights")
    story.append(pdf_table(ensemble, styles, [6.2 * cm, 2.2 * cm, 2.2 * cm]))

    add_section(story, styles, "Feature Importance")
    story.append(pdf_table(rf_perm, styles, [5.0 * cm, 3.0 * cm, 2.0 * cm]))
    add_subhead(story, styles, "Feature Group Ablation")
    story.append(pdf_table(ablation, styles, [6.0 * cm, 3.0 * cm, 2.5 * cm]))

    story.append(PageBreak())
    add_section(story, styles, "Player and Tactical Layer")
    story.append(pdf_table(tactical, styles, [3.0 * cm, 2.0 * cm, 2.0 * cm, 2.0 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm]))
    add_subhead(story, styles, "Player Data Coverage Weak Spots")
    story.append(pdf_table(coverage, styles, [3.0 * cm, 2.2 * cm, 1.8 * cm, 1.8 * cm, 9.0 * cm]))

    story.append(PageBreak())
    add_section(story, styles, "Player Leaderboards")
    story.append(pdf_table(scorers, styles, [6.0 * cm, 1.2 * cm, 4.3 * cm, 3.0 * cm, 2.0 * cm]))
    add_subhead(story, styles, "Top Assisters")
    story.append(pdf_table(assisters, styles, [6.0 * cm, 1.2 * cm, 4.3 * cm, 3.0 * cm, 2.0 * cm]))

    add_section(story, styles, "External Data and Elo")
    story.append(
        para(
            f"Historical data readiness: {data['historical_status'].get('status', 'unknown')}. Usable historical matches detected: {data['historical_status'].get('usable_matches', 0)}. {elo_status_sentence(data)}",
            styles["BodyTight"],
        )
    )
    story.append(pdf_table(format_table_values(source_manifest), styles, [4.0 * cm, 7.0 * cm, 7.0 * cm, 7.0 * cm]))

    add_section(story, styles, "Caveats and Next Inputs")
    story.append(
        bullet_pdf(
            [
                "Place martj42 results.csv at external_data/international_results/results.csv, then run fetch_external_football_data.py.",
                "Use the imported 2026-06-11 World Football Elo snapshot as the current tournament baseline; add time-aware Elo snapshots later if historical backtesting needs match-date priors.",
                "Rerun the 10,000-simulation model comparison now that raw Elo is active.",
                "Rerun the research pipeline after those files exist so the model can move from synthetic calibration toward historical supervision.",
            ],
            styles,
        )
    )

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)


def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(doc.leftMargin, 0.45 * cm, "FIFA_WC_26 simulation project report")
    canvas.drawRightString(landscape(A4)[0] - doc.rightMargin, 0.45 * cm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_report_data()
    TEX_PATH.write_text(generate_latex(data), encoding="utf-8")
    generate_pdf(data)
    print(f"wrote {PDF_PATH}")
    print(f"wrote {TEX_PATH}")


if __name__ == "__main__":
    main()
