# Raw World Football Elo Research Note

Requested as-of date: 2026-06-11.

Current active snapshot: 2026-06-11.

Status: complete raw Elo export imported.

## What Was Found

A complete user-supplied World Football Elo export was provided at:

```text
C:\Users\prate\Downloads\international_football_elo_20260611.json
```

It has been copied into the project at:

```text
external_data/world_football_elo/international_football_elo_20260611.json
```

The export contains 177 national teams with `rank`, `country`, `code`, `elo`, and `confederation` fields. The active simulator Elo file has now been regenerated from this export.

## Import Result

The import wrote:

```text
national_team_elo_ratings.json
national_team_elo_import_report.json
```

Validation summary:

```text
source rows: 177
imported team rows: 177
missing World Cup teams: 0
rating type: world_football_elo
skipped rows: 0
teams missing confederation: 0
```

The previous FIFA-rank-derived fallback file was preserved at:

```text
external_data/world_football_elo/national_team_elo_ratings_fifa_rank_fallback_20260611.json
```

## Provisional Top-20 Snapshot

Before the full export was provided, the closest public snapshot found through the available readers was a top-20 table dated 2026-06-10. That provisional extraction is still stored for audit purposes at:

```text
world_football_elo_2026-06-10_top20.csv
```

It should not be used as the active simulator source because the full 2026-06-11 export is now available and covers every tournament team.

## Coverage

The simulator needs ratings for all 48 World Cup 2026 tournament teams. The full 2026-06-11 raw Elo export covers all 48.

Top tournament teams after import:

```text
Spain 2157
Argentina 2115
France 2063
England 2024
Brazil 1991
Portugal 1989
Colombia 1982
Netherlands 1948
Ecuador 1938
Germany 1932
Norway 1914
Croatia 1912
```

Lowest tournament teams after import:

```text
New Zealand 1465
Curacao 1434
Iraq 1422
Cape Verde 1413
Haiti 1346
```

## Current Project Status

The project file `national_team_elo_ratings.json` now contains raw World Football Elo ratings from the 2026-06-11 full export.

## Recommended Next Step

Run a fresh simulation batch so the result artifacts reflect the real raw Elo baseline rather than the previous FIFA-rank-derived fallback:

```powershell
python simulate_world_cup_v2.py --epochs 10000 --workers auto --elo-file national_team_elo_ratings.json --match-model auto
```
