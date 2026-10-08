# External Football Data

This folder is for source files that are too large or too external to hand-maintain in code.

## Historical Results

Preferred source:

- https://github.com/martj42/international_results
- Raw results CSV: https://raw.githubusercontent.com/martj42/international_results/master/results.csv

Save the raw file here:

```text
external_data/international_results/results.csv
```

Then normalize it for the simulator:

```powershell
python fetch_external_football_data.py
```

The normalized output is:

```text
historical_international_results.csv
```

The research pipeline will also read the raw file directly if the normalized file is not present.

## World Football Elo

Preferred source:

- https://www.eloratings.net/

Create a CSV with columns like:

```csv
team,world_football_elo,confederation,fifa_rank,aliases
France,2063,UEFA,3,France
```

Then import it:

```powershell
python fetch_external_football_data.py --world-football-elo-file world_football_elo_current.csv --as-of 2026-06-12
```

This updates:

```text
national_team_elo_ratings.json
national_team_elo_import_report.json
```
