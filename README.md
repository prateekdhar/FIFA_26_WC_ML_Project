# FIFA 26 World Cup Monte Carlo Project

## Retrospective Comparison With Actual Results

The [October 2026 evaluation report](actual_results_comparison/comparison_report.md)
compares four frozen 10,000-run forecasts with FIFA's final tournament outcomes.
The folder includes a printable HTML report, all 48 teams' stage comparisons,
model scores, scorer comparisons, source links, and prediction SHA-256 hashes.
The [comprehensive research PDF](actual_results_comparison/comprehensive_report.pdf) includes
an evaluation diagram, title-probability pie charts, accuracy bar charts, and
a heatmap of forecasts against actual advancement. The PDF is typeset from
[LaTeX source](actual_results_comparison/comparison_report.tex), with numbered
figures, equations, publication-style tables, an abstract, a table of contents,
model introductions, dataset provenance and cited references. The accompanying
[dataset register](actual_results_comparison/dataset_sources.csv) distinguishes
used inputs, later imports and planned sources. Chart generation uses ReportLab.
After regenerating the analysis, compile `comparison_report.tex` with `pdflatex`
from the `actual_results_comparison` directory, passing
`-jobname=comprehensive_report`; keep its `figures/` folder alongside it.
Repeat compilation until contents pages and references settle.
Regenerate with `python compare_simulation_with_actuals.py`.
The script verifies that the comparison CSVs match the frozen JSON results.
Spain won; the primary models gave Spain title probabilities of 10.26%, 18.18%,
and 17.11%. The heuristic v2 model had the lowest mean advancement Brier score
in this tournament. Read the report's provenance and evaluation limits before
treating this as an audited pre-tournament backtest.

This project is a first-pass Monte Carlo simulator for the FIFA World Cup 2026.

The current version uses:

- FIFA's official squad list PDF as the squad source
- EAFC/FIFA-style player ratings as the primitive player-strength metric
- detailed player positions where available
- a Poisson goal model for match simulation
- 10,000 tournament epochs for probability estimates

## Current Status

This is the **first iteration** of the project. The model is intentionally simple so we can inspect behavior before adding richer football data.

Current simulation flow:

1. Parse official FIFA squads.
2. Enrich players with EAFC ratings and detailed positions.
3. Build team strength from best XI, top 18, and full squad average.
4. Simulate group-stage matches.
5. Advance top two teams plus the eight best third-place teams.
6. Simulate knockouts, final, and third-place playoff.
7. Generate JSON results and an HTML/SVG report.

## Important Files

| File | Purpose |
|---|---|
| `rebuild_squads_from_fifa_pdf.py` | Parses FIFA's official squad PDF into JSON |
| `enrich_squads_with_eafc.py` | Adds EAFC ratings and detailed positions |
| `simulate_world_cup.py` | Runs the Monte Carlo tournament simulation |
| `simulate_world_cup_v2.py` | Runs the second-generation event simulator with player performance data, rating priors, Random Forest support, venue/travel/climate context, bracket routing, possession, fatigue, cards, substitutions, extra time, penalties, and CPU-parallel workers |
| `analyze_feature_importance.py` | Trains comparison models and writes feature-importance, ablation, partial-dependence, ICE, and local-explanation study outputs |
| `generate_10000_model_comparison_report.py` | Compares all stored 10,000-epoch simulation model outputs and writes a Markdown report plus CSV study tables |
| `run_research_upgrade_pipeline.py` | Runs the research layer: historical-data readiness, calibration metrics, ensemble weights, uncertainty intervals, tactical priors, player-data coverage, and a local dashboard |
| `fetch_external_football_data.py` | Fetches/normalizes `martj42/international_results` and imports World Football Elo CSV/JSON files into the simulator |
| `generate_shareable_latex_report.py` | Builds the shareable project report PDF and matching LaTeX source from stored outputs |
| `import_national_team_elo.py` | Imports all-national-team Elo/rating data from CSV or JSON into the simulator rating-prior format |
| `generate_simulation_report.py` | Builds the visual HTML/SVG report |
| `run_clean_simulation_pipeline.py` | Runs the full rebuild, enrichment, simulation, and report pipeline |
| `collect_player_performance_data.py` | Slowly collects SofaScore website performance data for the second model iteration |
| `collect_player_performance_data_edge.py` | Experimental browser-assisted fallback for SofaScore profile pages when direct requests return 403 |
| `collect_player_performance_data_providers.py` | Key-based provider collector for Sportmonks, API-Football/API-Sports, and FootyStats |
| `collect_player_performance_data_statbunker.py` | Free StatBunker fallback collector for public competition player tables |
| `performance_data_config.json` | Defines recency, competition, and knockout weighting for performance data |
| `player_performance_manifest.json` | Player manifest used by the performance collector |
| `guardian_world_cup_2026_player_guide.json` | Current enriched squad data |
| `world_cup_2026_simulation_structure.json` | Tournament structure and groups |
| `national_team_elo_ratings.json` | FIFA-rank-derived Elo-scale team prior with confederation metadata |
| `national_team_elo_import_report.json` | Validation report from the last rating-prior import |
| `national_team_elo_template.csv` | Minimal CSV template for importing all-national-team rating data |
| `world_cup_2026_venue_context.json` | Venue-region, heat, humidity, altitude, and travel-load modelling priors |
| `monte_carlo_simulation_report.md` | Written report for the current model |

## Ignored Files

Large or generated files are intentionally ignored:

- `eafc26_players.csv`
- `fifa_squadlists_english.pdf`
- `simulation_results_*.json`
- `simulation_features_*.csv`
- `simulation_trace_*.txt`
- `simulation_report*/`
- `player_performance_data*.json`
- `.cache/`

This keeps the GitHub repository lighter. To fully rerun the pipeline, place these local source files in the project folder:

- `fifa_squadlists_english.pdf`
- `eafc26_players.csv`

## Running The Pipeline

```bash
python run_clean_simulation_pipeline.py
```

This runs the default 1,000-epoch clean pipeline.

For a 10,000-epoch run:

```bash
python simulate_world_cup.py --epochs 10000 --seed 20260605 --output simulation_results_10000.json
python generate_simulation_report.py --results simulation_results_10000.json --report-dir simulation_report_10000
```

## Running The V2 Event Simulator

The v2 simulator keeps the original baseline intact and adds a more detailed match engine:

- squad/player performance data as a roster-strength layer
- national-team rating prior from `national_team_elo_ratings.json`, currently an official FIFA-rank-derived Elo-scale estimate with confederation metadata
- pandas feature export for model inspection, including host/rest/calendar/venue/travel/climate context
- optional scikit-learn Random Forest outcome layer with synthetic profile calibration, supervised training from a historical match CSV, or a blend of both
- compressed match time: 90 minutes as 9 simulated minutes, extra time as 3 simulated minutes
- possession, fouls, yellow cards, red cards, second yellows, removals, substitutions, fatigue, set-piece goals, game-state behavior, extra time, and penalties
- date-aware FIFA 2026 group and knockout calendar for rest-day modelling
- host-country advantage markers for the United States, Mexico, and Canada, plus group-level venue-region climate/travel priors
- FIFA-style group ranking with head-to-head tie-breaker support before overall goal difference
- constrained Round-of-32 routing: group winners/runners-up are placed into fixed bracket slots and third-place teams are assigned only to allowed opponent slots
- CPU-parallel tournament batches

Recommended run for an 8-core / 16-thread CPU:

```powershell
python simulate_world_cup_v2.py --epochs 1000 --workers 8 --seed 20260610 --match-model random-forest --output simulation_results_v2_1000.json --features-output simulation_features_v2.csv
```

Use `--match-model heuristic` for the faster deterministic internal forest. Use `--historical-matches path/to/matches.csv` to train the Random Forest from rows with `team_a`, `team_b`, `goals_a`, and `goals_b` columns, or equivalent `home_team`, `away_team`, `home_goals`, and `away_goals` columns. The reader also accepts common aliases such as `Czechia`, `USA`, `Korea Republic`, and `Cote d'Ivoire`. If the historical file is small, it is blended with synthetic calibration rows instead of being discarded.

To watch and record one full tournament in the console:

```powershell
python simulate_world_cup_v2.py --trace-one --seed 20260612 --match-model random-forest --trace-output simulation_trace_v2_seed_20260612.txt
```

## Comparing 10,000-Run Model Outputs

The current comparison report is stored in:

```text
simulation_10000_model_comparison/
```

It compares:

- primitive EAFC Poisson, 10,000 runs
- v2 heuristic internal forest with NT Elo, 10,000 runs
- v2 sklearn Random Forest with NT Elo, 10,000 runs
- legacy v2 sklearn Random Forest with squad-proxy Elo, retained as a reference

Regenerate the report and CSV tables:

```powershell
python generate_10000_model_comparison_report.py
```

Key outputs:

| File | Purpose |
|---|---|
| `simulation_10000_models_report.md` | Human-readable comparison report |
| `simulation_10000_model_metadata.csv` | Model/file/seed/input metadata |
| `simulation_10000_model_team_summary.csv` | Long team-stage probabilities and v2 event metrics by model |
| `simulation_10000_model_champion_matrix.csv` | Wide team champion-probability comparison |
| `simulation_10000_model_player_leaders.csv` | Top scorer and assister leaderboards by model |

## Research Upgrade Pipeline

The current research upgrade run is stored in:

```text
research_upgrade_results_seed_20260622/
```

Regenerate it:

```powershell
python run_research_upgrade_pipeline.py --seed 20260622 --output-dir research_upgrade_results_seed_20260622
```

This pipeline adds:

- historical match data readiness checks
- validation metrics: accuracy, balanced accuracy, log loss, multiclass Brier score, and calibration error
- model ensemble weights from validation log loss
- calibration-bin tables
- feature importance from built-in tree importances and permutation importance
- Wilson 95% uncertainty intervals for all stored 10,000-run stage probabilities
- cross-model champion consensus
- tactical priors inferred from current team profiles
- player-data coverage diagnostics
- historical match and Elo snapshot CSV templates
- a local HTML dashboard

Key outputs:

| File | Purpose |
|---|---|
| `research_upgrade_report.md` | Human-readable research summary |
| `research_upgrade_dashboard.html` | Local dashboard for quick review |
| `model_validation_metrics.csv` | Validation metrics for the candidate models and weighted ensemble |
| `ensemble_weights.csv` | Validation-loss-based model weights |
| `calibration_bins.csv` | Confidence-bin calibration table |
| `simulation_stage_uncertainty.csv` | Wilson uncertainty intervals for every team/stage/model |
| `simulation_champion_uncertainty.csv` | Champion-only uncertainty intervals |
| `simulation_consensus_ensemble.csv` | Cross-model champion consensus table |
| `team_tactical_priors.csv` | Tactical priors inferred from squad profiles |
| `player_data_coverage.csv` | Team-level player data coverage and weak spots |
| `historical_matches_template.csv` | Template for supervised match-training data |
| `national_team_elo_snapshots_template.csv` | Template for time-aware Elo snapshots |
| `data_source_manifest.csv` | Recommended data sources and expected local filenames |

## Shareable Report

The current shareable report is stored in:

```text
shareable_project_report/
```

Regenerate it:

```powershell
python generate_shareable_latex_report.py
```

Outputs:

| File | Purpose |
|---|---|
| `fifa_wc26_project_report.pdf` | Shareable PDF summary of the full project state |
| `fifa_wc26_project_report.tex` | Matching LaTeX source for recompilation or editing |

## Feature Importance Analysis

Use `analyze_feature_importance.py` to study which model factors are driving predictions. It trains a Random Forest plus comparison models, then stores:

- model metrics
- built-in Random Forest importance
- permutation importance
- logistic coefficients
- local occlusion explanations
- partial-dependence and ICE curves
- validation feature-group ablations
- tournament-simulation ablations of the Random Forest layer

Current saved run:

```text
feature_importance_results_seed_20260618/
```

Rerun the analysis:

```powershell
python analyze_feature_importance.py --seed 20260618 --simulation-ablation-epochs 30 --output-dir feature_importance_results_seed_20260618
```

Key outputs:

| File | Purpose |
|---|---|
| `feature_importance_report.md` | Human-readable summary of the stored run |
| `model_metrics.csv` | Accuracy, balanced accuracy, and log loss for each model |
| `feature_importance_permutation.csv` | Model-agnostic feature importance from shuffled features |
| `feature_importance_builtin.csv` | Native tree feature importances where available |
| `feature_importance_logistic_coefficients.csv` | Directional logistic-model coefficients by class |
| `feature_importance_local_occlusion.csv` | Average prediction movement when each feature is neutralized |
| `local_occlusion_examples.csv` | Match-level examples behind the local occlusion scores |
| `partial_dependence.csv` | Average response curves for top Random Forest features |
| `ice_curves.csv` | Per-match response curves for those top features |
| `feature_group_ablation_validation.csv` | Validation log-loss and accuracy impact when feature groups are removed |
| `feature_group_ablation_simulation_scenarios.csv` | Champion-probability scenario summary from RF-layer ablation |
| `feature_group_ablation_simulation_team_probs.csv` | Team-level champion probabilities by ablation scenario |
| `analysis_summary.json` | Metadata for the run |

Important caveat: until real historical international match data is supplied with `--historical-matches`, these outputs explain the simulator's calibrated assumptions rather than verified real-world causality.

## Importing National-Team Elo

`national_team_elo_ratings.json` can contain every men's national team, not only the 48 World Cup teams. The simulator consumes whichever teams are present in `world_cup_2026_simulation_structure.json`, while aliases from the rating file are also used by historical-match training.

Preferred rating priority:

1. `world_football_elo`
2. `elo` or `rating`
3. `fifa_points` or `points`
4. `fifa_rank` / `rank`, converted with `2170 - 130 * ln(rank)`
5. squad proxy fallback if no rating exists

Accepted CSV columns:

```csv
team,world_football_elo,elo,rating,fifa_points,fifa_rank,confederation,aliases
France,2063,,,,3,UEFA,France
United States,1834,,,,15,CONCACAF,USA|United States of America
```

Import a full all-NT file:

```powershell
python import_national_team_elo.py --input all_national_team_elo.csv --output national_team_elo_ratings.json --source "World Football Elo Ratings" --source-url "https://www.eloratings.net/" --as-of 2026-06-11
```

If the input file contains FIFA ranks rather than raw Elo:

```powershell
python import_national_team_elo.py --input fifa_rankings.csv --output national_team_elo_ratings.json --rating-type fifa_rank_derived_elo --source "FIFA/Coca-Cola Men's World Ranking" --source-url "https://inside.fifa.com/fifa-world-ranking/men"
```

The importer writes `national_team_elo_import_report.json` with team count, skipped rows, missing World Cup teams, rating-type counts, and missing confederations.

## Adding External Historical Results And Elo

The project is now wired for `martj42/international_results`:

- repo: `https://github.com/martj42/international_results`
- raw CSV: `https://raw.githubusercontent.com/martj42/international_results/master/results.csv`

If network access is available, fetch and normalize the source:

```powershell
python fetch_external_football_data.py --download-international-results
```

If network access is blocked, download `results.csv` in a browser and place it here:

```text
external_data/international_results/results.csv
```

Then normalize it:

```powershell
python fetch_external_football_data.py
```

The simulator-ready output is:

```text
historical_international_results.csv
```

For World Football Elo, create a CSV from `https://www.eloratings.net/` using the template:

```text
world_football_elo_current_template.csv
```

Import it:

```powershell
python fetch_external_football_data.py --world-football-elo-file world_football_elo_current.csv --as-of 2026-06-12
```

This updates `national_team_elo_ratings.json` and writes `national_team_elo_import_report.json`.

## V2 Factors Still To Model

The current v2 simulator covers the main tournament mechanics, plus an optional Random Forest layer, rating prior file, venue/travel/climate priors, and constrained knockout routing. The next realism gains should come from better source quality and calibration:

- raw World Football Elo or FIFA points instead of the current FIFA-rank-derived Elo-scale estimate
- exact match-by-match venue, kickoff time, travel, heat, humidity, and time-zone effects beyond the current group-level priors
- player availability, injuries, minutes load, current form, late squad changes, and pre-tournament suspensions
- tactical matchups: formations, pressing, low blocks, counterattacks, aerial threat, wing dependence, and set-piece vulnerability
- richer set pieces: corners, dangerous free kicks, penalties won, aerial targets, and dead-ball specialists
- goalkeeper-specific traits: shot-stopping, cross claiming, distribution, error risk, and penalty saving
- named referee assignments rather than simulated strictness
- official FIFA third-place combination lookup table if FIFA publishes one; current routing enforces allowed slot constraints
- calibration against historical World Cups, continental tournaments, NT Elo results, and bookmaker odds
- a fully supervised Random Forest or gradient-boosted model trained on real international match outcomes

## Collecting Performance Data

The second iteration uses a slow, resumable website collector. It discovers public SofaScore profile pages through ordinary web-search result pages, then pulls each profile page. If Python is blocked on an HTML page, the collector falls back to installed Edge/Chrome in headless mode. Direct SofaScore JSON endpoints can be tried separately, but they often return `403 Forbidden` outside a browser session.

The default run is intentionally slow to reduce rate-limit pressure:

```bash
python collect_player_performance_data.py --output player_performance_data.json
```

With the default delay, a full 1,248-player collection can run for many hours and should be left to resume from its cache if interrupted.

Useful smaller probes:

```bash
python collect_player_performance_data.py --limit 5 --output player_performance_data_probe.json
python collect_player_performance_data.py --start 100 --limit 50 --output player_performance_data.json
```

The collector writes regular checkpoints and reuses cached responses, so interrupted runs can be started again with the same command. By default it writes every 5 players to avoid Windows/OneDrive file-lock issues; use `--write-every 1` for maximum checkpoint frequency.

If local Python cannot verify certificates, rerun with `--allow-insecure-tls`. To retry the blocked SofaScore JSON endpoints anyway, pass `--discovery-mode api --api-details`.

If every direct request returns `403 Forbidden`, SofaScore is blocking automated collection. The browser-assisted fallback is experimental; it opens a normal Edge window with a temporary profile and attempts to read public SofaScore profile pages:

```bash
python collect_player_performance_data_edge.py --limit 3 --output player_performance_data_edge_probe.json
python collect_player_performance_data_edge.py --output player_performance_data.json
```

This fallback can recover profile-level evidence such as page rating summaries and competition appearance counts, but it is not a substitute for full match-level provider data.

### SofaScore Browser Request Probe

Use this only as a small access test before spending more time on SofaScore. It replays a real browser request copied from Edge/Chrome DevTools and checks whether the same session can access SofaScore JSON without `403 Forbidden`.

1. Open a SofaScore player page in Edge/Chrome.
2. Open DevTools, go to Network, refresh the page, and click a SofaScore `api/v1` request.
3. Copy it as `cURL (bash)`.
4. Save the copied command to `.cache/sofascore_browser_request.curl`. The `.cache/` folder is ignored by Git.
5. Run:

```bash
python probe_sofascore_browser_request.py --dry-run
python probe_sofascore_browser_request.py --player-id SOFASCORE_PLAYER_ID
```

The probe writes `.cache/sofascore_browser_probe_result.json` with response status and parsed JSON summaries. Browser cookies and authorization-like headers are redacted from the result file.

If SofaScore remains blocked, use a different provider rather than continuing to retry the same endpoint. Paid or key-based providers such as Sportmonks, API-Football, FootyStats, or TheStatsAPI are better suited for the full second-iteration dataset.

### Free StatBunker Collector

StatBunker is the current free fallback. It uses public competition player tables for appearances, starts, goals, assists, cards, penalties, fantasy points where requested, and goalkeeper clean sheets. It does not provide SofaScore-style match ratings, xG, xA, minutes, tackles, saves, or full event data in the default public pages.

Small probe:

```bash
python collect_player_performance_data_statbunker.py --limit 20 --max-competitions 2 --delay 2 --jitter 1 --output player_performance_data_statbunker_probe.json
```

Full free-data run:

```bash
python collect_player_performance_data_statbunker.py --output player_performance_data_statbunker.json
```

To include StatBunker's fantasy table as a rough cross-position output signal:

```bash
python collect_player_performance_data_statbunker.py --pages overall,clean_sheets,fantasy --output player_performance_data_statbunker.json
```

### Provider Collector

Use this when you have an API key. Keys are read from environment variables and are not written to output files or cache filenames.

Sportmonks:

```powershell
$env:SPORTMONKS_API_TOKEN="YOUR_TOKEN"
python collect_player_performance_data_providers.py --providers sportmonks --limit 5 --output player_performance_data_providers_probe.json
```

API-Football / API-Sports:

```powershell
$env:API_SPORTS_KEY="YOUR_KEY"
python collect_player_performance_data_providers.py --providers api_football --api-football-season 2025 --limit 5 --output player_performance_data_providers_probe.json
```

FootyStats needs season IDs first:

```powershell
$env:FOOTYSTATS_API_KEY="YOUR_KEY"
python collect_player_performance_data_providers.py --providers footystats --footystats-season-id 2012 --limit 5 --output player_performance_data_providers_probe.json
```

FootyStats offers an example key for sample league testing, but it will not cover our World Cup squads:

```powershell
python collect_player_performance_data_providers.py --providers footystats --footystats-example --footystats-season-id 2012 --limit 5 --output player_performance_data_footystats_example.json
```

## Model Limitations

This v0 model does not yet account for:

- exact FIFA Round-of-32 bracket routing for third-place combinations
- injuries or suspensions
- recent form
- tactics and matchup effects
- venue, travel, climate, or rest
- SofaScore-style player performance metrics
- goalkeeper-specific shot-stopping
- calibrated penalty-taker quality

These are intended future improvements.

## Next Improvement Ideas

1. Replace fallback ratings with more complete public player metrics.
2. Split team strength into attack, midfield, defence, and goalkeeper components.
3. Add exact FIFA bracket routing.
4. Calibrate scoring using real international match data.
5. Blend EAFC ratings with SofaScore or recent-performance statistics.
6. Add confidence intervals around probabilities.
