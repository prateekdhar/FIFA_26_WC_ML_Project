# FIFA 26 World Cup Monte Carlo Project

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
| `generate_simulation_report.py` | Builds the visual HTML/SVG report |
| `run_clean_simulation_pipeline.py` | Runs the full rebuild, enrichment, simulation, and report pipeline |
| `guardian_world_cup_2026_player_guide.json` | Current enriched squad data |
| `world_cup_2026_simulation_structure.json` | Tournament structure and groups |
| `monte_carlo_simulation_report.md` | Written report for the current model |

## Ignored Files

Large or generated files are intentionally ignored:

- `eafc26_players.csv`
- `fifa_squadlists_english.pdf`
- `simulation_results_*.json`
- `simulation_report*/`

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

