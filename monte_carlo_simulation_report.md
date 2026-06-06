# FIFA World Cup 2026 Monte Carlo Simulation Report

## 1. Initial Monte Carlo Setup

This is our v0 Monte Carlo World Cup simulator.

The simulation repeatedly plays out the tournament using the current basic dataset:

- official FIFA 26-player squads
- EAFC/FIFA-style player ratings
- player positions
- the 2026 World Cup group structure

Each simulation epoch performs a full tournament:

1. Simulate every group-stage match.
2. Rank teams inside each group.
3. Advance the top two teams from every group.
4. Add the eight best third-place teams.
5. Simulate the knockout rounds.
6. Simulate the third-place playoff.
7. Record tournament outcomes.

The current production run uses 10,000 epochs. The results should be read as estimated probabilities, not predictions with certainty.

### Current Model

Team strength is derived from player ratings:

- best XI average
- top 18 squad depth
- full squad average

Match scores are generated with a Poisson goal model. Stronger teams receive higher expected goals, weaker teams lower expected goals. Knockout matches that are level are resolved through extra time and penalties.

Player goals and assists are assigned probabilistically using player position and rating. For example, strikers and wide forwards are more likely to score, while attacking midfielders and creators are more likely to assist.

### Current Limitations

This is still a primitive model. It does not yet account for:

- exact FIFA Round-of-32 bracket routing for third-place teams
- injuries or suspensions
- tactical matchups
- recent form
- club or international minutes
- defensive structure beyond overall team strength
- goalkeeper-specific shot-stopping effects
- penalty-taking quality
- travel, venue, climate, or rest
- SofaScore or real performance statistics

The model is useful as a baseline. Future improvements should replace or blend EAFC ratings with real performance metrics.

## 2. Data Status

The squad base was rebuilt from FIFA's official squad PDF:

- source file: `fifa_squadlists_english.pdf`
- squad JSON: `guardian_world_cup_2026_player_guide.json`
- teams: 48
- players: 1,248
- unresolved positions: 0
- missing ratings: 0

Rating coverage:

| Rating Source | Players |
|---|---:|
| EAFC matched ratings | 980 |
| Fallback ratings | 268 |
| Total | 1,248 |

Fallback ratings are used only where a confident EAFC match was not found.

## 3. Simulation Run

Run details:

| Field | Value |
|---|---:|
| Epochs | 10,000 |
| Seed | 20260605 |
| Results file | `simulation_results_10000.json` |
| Visual report | `simulation_report_10000/index.html` |

## 4. Champion Probabilities

Top teams by simulated title probability:

| Team | Champion | Final | Third Place | Team Rating |
|---|---:|---:|---:|---:|
| France | 12.50% | 20.41% | 7.53% | 85.815 |
| Spain | 10.26% | 17.77% | 6.65% | 84.592 |
| England | 8.55% | 15.12% | 6.70% | 83.987 |
| Brazil | 8.42% | 15.25% | 6.44% | 84.078 |
| Portugal | 8.39% | 15.28% | 6.32% | 83.958 |
| Germany | 8.11% | 15.19% | 7.23% | 84.078 |
| Argentina | 7.67% | 13.86% | 6.09% | 83.581 |
| Netherlands | 6.17% | 11.42% | 5.82% | 82.977 |
| Belgium | 4.47% | 8.92% | 4.68% | 81.442 |
| Croatia | 2.54% | 5.39% | 3.09% | 79.459 |
| Turkey | 2.13% | 4.88% | 2.68% | 79.199 |
| Morocco | 1.72% | 4.14% | 2.34% | 78.800 |

## 5. Player Output

Top simulated scorers:

| Player | Team | Goals Per Tournament |
|---|---|---:|
| Lautaro Martinez | Argentina | 1.449 |
| Kylian Mbappe | France | 1.446 |
| Romelu Lukaku | Belgium | 1.398 |
| Cristiano Ronaldo | Portugal | 1.391 |
| Julian Alvarez | Argentina | 1.385 |
| Mikel Oyarzabal | Spain | 1.254 |
| Harry Kane | England | 1.234 |
| Kai Havertz | Germany | 1.201 |
| Erling Haaland | Norway | 1.189 |
| Marcus Thuram | France | 1.188 |

Top simulated assist providers:

| Player | Team | Assists Per Tournament |
|---|---|---:|
| Jude Bellingham | England | 0.828 |
| Florian Wirtz | Germany | 0.792 |
| Jamal Musiala | Germany | 0.757 |
| Matheus Cunha | Brazil | 0.754 |
| Raphinha | Brazil | 0.751 |
| Mohamed Salah | Egypt | 0.734 |
| Adrien Rabiot | France | 0.727 |
| Francisco Trincao | Portugal | 0.690 |
| Rayan Cherki | France | 0.689 |
| Michael Olise | France | 0.681 |

## 6. Next Improvements

The next development phase should focus on improving the model rather than increasing epoch count.

Recommended next steps:

1. Replace fallback EAFC ratings where better public ratings are available.
2. Add exact FIFA knockout bracket routing.
3. Split team strength into attack, midfield, defence, and goalkeeper components.
4. Add player availability assumptions.
5. Add SofaScore-style recent performance metrics.
6. Recalibrate scoring rates against real international football goal distributions.
7. Add confidence intervals for all reported probabilities.

