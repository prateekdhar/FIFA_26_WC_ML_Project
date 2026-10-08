# FIFA WC26 Research Upgrade Report

Generated: `2026-06-12`
Training source: `synthetic_profile_calibration`
Rows: `6768`
Historical rows in model frame: `0`
Synthetic rows in model frame: `6768`
Elo source: `FIFA/Coca-Cola Men's World Ranking ranks converted to Elo-scale prior`

## Historical Data Readiness

| historical_file | status  | source_rows | usable_matches | skipped_rows | date_min | date_max | tournament_count | teams_seen | world_cup_team_coverage | missing_world_cup_teams                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | notes                                                      | recommended_local_filename           | recommended_source_url                                                             |
| --------------- | ------- | ----------- | -------------- | ------------ | -------- | -------- | ---------------- | ---------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------- |
|                 | missing | 0           | 0              | 0            |          |          | 0                | 0          | 0                       | ['Algeria', 'Argentina', 'Australia', 'Austria', 'Belgium', 'Bosnia & Herzegovina', 'Brazil', 'Canada', 'Cape Verde', 'Colombia', 'Croatia', 'Curacao', 'Czech Republic', 'DR Congo', 'Ecuador', 'Egypt', 'England', 'France', 'Germany', 'Ghana', 'Haiti', 'Iran', 'Iraq', 'Ivory Coast', 'Japan', 'Jordan', 'Mexico', 'Morocco', 'Netherlands', 'New Zealand', 'Norway', 'Panama', 'Paraguay', 'Portugal', 'Qatar', 'Saudi Arabia', 'Scotland', 'Senegal', 'South Africa', 'South Korea', 'Spain', 'Sweden', 'Switzerland', 'Tunisia', 'Turkey', 'United States', 'Uruguay', 'Uzbekistan'] | ['No historical results CSV is present in the workspace.'] | historical_international_results.csv | https://raw.githubusercontent.com/martj42/international_results/master/results.csv |

## Validation Metrics

| model                        | train_rows | test_rows | accuracy | balanced_accuracy | log_loss | brier_multiclass | ece    |
| ---------------------------- | ---------- | --------- | -------- | ----------------- | -------- | ---------------- | ------ |
| calibrated_logistic_sigmoid  | 5076       | 1692      | 0.6921   | 0.5498            | 0.7586   | 0.4338           | 0.0568 |
| weighted_validation_ensemble | 5076       | 1692      | 0.6903   | 0.5718            | 0.7733   | 0.4432           | 0.0757 |
| random_forest                | 5076       | 1692      | 0.6708   | 0.5889            | 0.7945   | 0.4583           | 0.0863 |
| hist_gradient_boosting       | 5076       | 1692      | 0.6891   | 0.5573            | 0.8016   | 0.4499           | 0.0439 |
| extra_trees                  | 5076       | 1692      | 0.6590   | 0.6014            | 0.8189   | 0.4768           | 0.1110 |
| logistic_l2                  | 5076       | 1692      | 0.6235   | 0.5800            | 0.8280   | 0.4849           | 0.0967 |

## Ensemble Weights

| model                       | log_loss | weight |
| --------------------------- | -------- | ------ |
| calibrated_logistic_sigmoid | 0.7586   | 0.2108 |
| random_forest               | 0.7945   | 0.2013 |
| hist_gradient_boosting      | 0.8016   | 0.1995 |
| extra_trees                 | 0.8189   | 0.1953 |
| logistic_l2                 | 0.8280   | 0.1931 |

## Calibration Summary

| model                        | total_bins | non_empty_bins | ece    |
| ---------------------------- | ---------- | -------------- | ------ |
| hist_gradient_boosting       | 10         | 7              | 0.0439 |
| calibrated_logistic_sigmoid  | 10         | 6              | 0.0568 |
| weighted_validation_ensemble | 10         | 7              | 0.0757 |
| random_forest                | 10         | 7              | 0.0864 |
| logistic_l2                  | 10         | 7              | 0.0967 |
| extra_trees                  | 10         | 7              | 0.1110 |

## Champion Probability Uncertainty

Wilson 95% intervals are calculated from each stored 10,000-run tournament output.

| model_label                           | team        | probability_pct | standard_error_pct | ci95_low_pct | ci95_high_pct |
| ------------------------------------- | ----------- | --------------- | ------------------ | ------------ | ------------- |
| Primitive EAFC Poisson                | France      | 12.5000         | 0.3307             | 11.8662      | 13.1626       |
| Primitive EAFC Poisson                | Spain       | 10.2600         | 0.3034             | 9.6804       | 10.8701       |
| Primitive EAFC Poisson                | England     | 8.5500          | 0.2796             | 8.0177       | 9.1141        |
| Primitive EAFC Poisson                | Brazil      | 8.4200          | 0.2777             | 7.8916       | 8.9804        |
| Primitive EAFC Poisson                | Portugal    | 8.3900          | 0.2772             | 7.8625       | 8.9495        |
| Primitive EAFC Poisson                | Germany     | 8.1100          | 0.2730             | 7.5909       | 8.6613        |
| Primitive EAFC Poisson                | Argentina   | 7.6700          | 0.2661             | 7.1645       | 8.2080        |
| Primitive EAFC Poisson                | Netherlands | 6.1700          | 0.2406             | 5.7150       | 6.6586        |
| V2 Heuristic Internal Forest + NT Elo | Brazil      | 19.2300         | 0.3941             | 18.4694      | 20.0142       |
| V2 Heuristic Internal Forest + NT Elo | France      | 19.0900         | 0.3930             | 18.3316      | 19.8721       |
| V2 Heuristic Internal Forest + NT Elo | Germany     | 18.3000         | 0.3867             | 17.5544      | 19.0700       |
| V2 Heuristic Internal Forest + NT Elo | Spain       | 18.1800         | 0.3857             | 17.4363      | 18.9481       |
| V2 Heuristic Internal Forest + NT Elo | Argentina   | 8.5200          | 0.2792             | 7.9886       | 9.0832        |
| V2 Heuristic Internal Forest + NT Elo | England     | 5.1600          | 0.2212             | 4.7434       | 5.6111        |
| V2 Heuristic Internal Forest + NT Elo | Portugal    | 4.3600          | 0.2042             | 3.9770       | 4.7781        |
| V2 Heuristic Internal Forest + NT Elo | Netherlands | 4.3000          | 0.2029             | 3.9196       | 4.7155        |
| V2 sklearn Random Forest + NT Elo     | Brazil      | 20.0900         | 0.4007             | 19.3162      | 20.8867       |
| V2 sklearn Random Forest + NT Elo     | Germany     | 19.7500         | 0.3981             | 18.9814      | 20.5419       |
| V2 sklearn Random Forest + NT Elo     | France      | 19.4600         | 0.3959             | 18.6958      | 20.2476       |
| V2 sklearn Random Forest + NT Elo     | Spain       | 17.1100         | 0.3766             | 16.3845      | 17.8607       |
| V2 sklearn Random Forest + NT Elo     | Argentina   | 6.9300          | 0.2540             | 6.4486       | 7.4445        |
| V2 sklearn Random Forest + NT Elo     | England     | 6.7600          | 0.2511             | 6.2843       | 7.2689        |
| V2 sklearn Random Forest + NT Elo     | Portugal    | 4.3500          | 0.2040             | 3.9674       | 4.7676        |
| V2 sklearn Random Forest + NT Elo     | Netherlands | 3.3800          | 0.1807             | 3.0433       | 3.7525        |

## Cross-Model Champion Consensus

| team        | primitive_eafc_poisson | v2_heuristic_nt_elo | v2_random_forest_nt_elo | simple_mean_champion_pct | median_champion_pct | model_range_pct | v2_event_model_mean_champion_pct |
| ----------- | ---------------------- | ------------------- | ----------------------- | ------------------------ | ------------------- | --------------- | -------------------------------- |
| France      | 12.5000                | 19.0900             | 19.4600                 | 17.0167                  | 19.0900             | 6.9600          | 19.2750                          |
| Brazil      | 8.4200                 | 19.2300             | 20.0900                 | 15.9133                  | 19.2300             | 11.6700         | 19.6600                          |
| Germany     | 8.1100                 | 18.3000             | 19.7500                 | 15.3867                  | 18.3000             | 11.6400         | 19.0250                          |
| Spain       | 10.2600                | 18.1800             | 17.1100                 | 15.1833                  | 17.1100             | 7.9200          | 17.6450                          |
| Argentina   | 7.6700                 | 8.5200              | 6.9300                  | 7.7067                   | 7.6700              | 1.5900          | 7.7250                           |
| England     | 8.5500                 | 5.1600              | 6.7600                  | 6.8233                   | 6.7600              | 3.3900          | 5.9600                           |
| Portugal    | 8.3900                 | 4.3600              | 4.3500                  | 5.7000                   | 4.3600              | 4.0400          | 4.3550                           |
| Netherlands | 6.1700                 | 4.3000              | 3.3800                  | 4.6167                   | 4.3000              | 2.7900          | 3.8400                           |
| Belgium     | 4.4700                 | 1.3900              | 1.1000                  | 2.3200                   | 1.3900              | 3.3700          | 1.2450                           |
| Turkey      | 2.1300                 | 0.3000              | 0.2500                  | 0.8933                   | 0.3000              | 1.8800          | 0.2750                           |
| Croatia     | 2.5400                 | 0.0500              | 0.0600                  | 0.8833                   | 0.0600              | 2.4900          | 0.0550                           |
| Switzerland | 1.5500                 | 0.1700              | 0.2400                  | 0.6533                   | 0.2400              | 1.3800          | 0.2050                           |
| Morocco     | 1.7200                 | 0.1500              | 0.0800                  | 0.6500                   | 0.1500              | 1.6400          | 0.1150                           |
| Norway      | 1.5900                 | 0.1100              | 0.1300                  | 0.6100                   | 0.1300              | 1.4800          | 0.1200                           |
| Uruguay     | 1.6000                 | 0.0300              | 0.0100                  | 0.5467                   | 0.0300              | 1.5900          | 0.0200                           |

## Tactical Priors

These are model-ready priors inferred from the current squad profile. They are not yet a substitute for real tactical event data.

| team        | pressing_score | counterattack_score | low_block_resilience | set_piece_attack_score | tempo_score | data_confidence |
| ----------- | -------------- | ------------------- | -------------------- | ---------------------- | ----------- | --------------- |
| Spain       | 88.5100        | 86.6602             | 86.7795              | 88.0812                | 88.8434     | 0.9370          |
| England     | 88.0220        | 87.3617             | 85.0990              | 88.0766                | 88.6262     | 0.9520          |
| Germany     | 87.9069        | 85.8915             | 85.8793              | 87.3502                | 88.2286     | 0.8730          |
| Portugal    | 87.4149        | 86.1172             | 85.0678              | 87.1544                | 87.8218     | 0.8590          |
| France      | 87.0709        | 88.9613             | 87.7063              | 88.1440                | 87.9909     | 0.9020          |
| Brazil      | 86.6949        | 86.3881             | 87.9977              | 86.7786                | 87.3289     | 0.8600          |
| Argentina   | 86.3443        | 86.8092             | 85.0418              | 87.0218                | 87.3628     | 0.8310          |
| Netherlands | 86.0377        | 85.1800             | 83.0993              | 85.9619                | 86.4775     | 0.9200          |
| Belgium     | 85.5341        | 84.4306             | 85.3028              | 85.2340                | 85.9113     | 0.7810          |
| Norway      | 82.8457        | 82.0569             | 78.0645              | 82.9632                | 83.6527     | 0.7810          |
| Croatia     | 82.6733        | 81.8624             | 80.5089              | 82.8428                | 83.4633     | 0.6920          |
| Turkey      | 82.2499        | 80.6743             | 79.7290              | 82.0635                | 82.8716     | 0.6960          |

## Player Data Coverage

These are the teams where better player-level source coverage would most improve confidence.

| team                 | avg_source_confidence | players_below_0_55_confidence | players_with_zero_minutes | primary_sources                                                    |
| -------------------- | --------------------- | ----------------------------- | ------------------------- | ------------------------------------------------------------------ |
| Panama               | 0.5009                | 18                            | 24                        | statbunker:18; wikipedia:4; transfermarkt:4                        |
| Senegal              | 0.5852                | 14                            | 25                        | statbunker:24; wikipedia:1; transfermarkt:1                        |
| Mexico               | 0.6333                | 11                            | 17                        | statbunker:15; transfermarkt:10; wikipedia:1                       |
| Scotland             | 0.6363                | 11                            | 24                        | statbunker:23; transfermarkt:2; wikipedia:1                        |
| Canada               | 0.6437                | 11                            | 21                        | statbunker:17; transfermarkt:7; wikipedia:2                        |
| Ivory Coast          | 0.6449                | 10                            | 22                        | statbunker:19; transfermarkt:6; wikipedia:1                        |
| Czech Republic       | 0.6489                | 11                            | 22                        | statbunker:19; transfermarkt:5; wikipedia:2                        |
| United States        | 0.6586                | 10                            | 23                        | statbunker:19; transfermarkt:5; wikipedia:2                        |
| Australia            | 0.6691                | 11                            | 14                        | transfermarkt:12; statbunker:11; wikipedia:3                       |
| Qatar                | 0.6696                | 12                            | 22                        | statbunker:12; wikipedia:8; transfermarkt:4; manual_web_research:2 |
| Bosnia & Herzegovina | 0.6739                | 9                             | 19                        | statbunker:13; transfermarkt:7; wikipedia:6                        |
| Ecuador              | 0.6750                | 10                            | 20                        | statbunker:16; transfermarkt:8; wikipedia:2                        |

## Dashboard

- `research_upgrade_dashboard.html`

## Data Source Manifest

| name                              | purpose                                                                 | url                                                                                | local_filename                                                                          | expected_columns                                                               | status                                                                                                     |
| --------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| International football results    | Historical match outcomes for supervised model training and calibration | https://raw.githubusercontent.com/martj42/international_results/master/results.csv | external_data/international_results/results.csv or historical_international_results.csv | date,home_team,away_team,home_score,away_score,tournament,city,country,neutral | download_blocked_in_workspace; place the CSV locally to activate historical training                       |
| World Football Elo Ratings        | Time-aware national-team Elo before each match and current NT priors    | https://www.eloratings.net/                                                        | external_data/world_football_elo/international_football_elo_20260611.json; national_team_elo_snapshots.csv later | date,team,elo,source,source_url                                                | baseline_imported_2026-06-11; historical time-aware Elo snapshots still needed; rerun simulations for raw-Elo result artifacts |
| Current project squad/player data | Team strength, unit matchups, discipline priors, and tactical priors    |                                                                                    | guardian_world_cup_2026_player_guide.json; player_performance_data_statbunker.json      |                                                                                | available                                                                                                  |

## Caveats

- Direct web download is blocked in this workspace, so historical source files must be placed locally.
- Until a real historical match CSV is supplied, supervised metrics explain the simulator's calibrated assumptions.
- Post-run update: the current NT Elo file now uses a complete 2026-06-11 raw World Football Elo baseline. Historical time-aware Elo snapshots would still improve backtesting, and stored simulation outputs should be regenerated for raw-Elo result artifacts.
- Tactical priors are inferred from player/team profile strength and need real style data for validation.
