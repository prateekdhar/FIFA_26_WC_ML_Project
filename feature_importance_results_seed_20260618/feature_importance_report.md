# FIFA WC26 Feature Importance Analysis

Seed: `20260618`
Training source: `synthetic_profile_calibration`
Rows: `6768`
Elo source: `FIFA/Coca-Cola Men's World Ranking ranks converted to Elo-scale prior`

Important caveat: if historical match data is not supplied, these results explain the simulator's assumptions, not verified real-world causality.

## Model Metrics

| model                  | train_rows | test_rows | accuracy | balanced_accuracy | log_loss |
| ---------------------- | ---------- | --------- | -------- | ----------------- | -------- |
| random_forest          | 5076       | 1692      | 0.663710 | 0.570090          | 0.810230 |
| hist_gradient_boosting | 5076       | 1692      | 0.677300 | 0.543400          | 0.822510 |
| elastic_net_logistic   | 5076       | 1692      | 0.624700 | 0.570990          | 0.838610 |
| logistic_l2            | 5076       | 1692      | 0.624700 | 0.570990          | 0.838720 |
| decision_tree_depth4   | 5076       | 1692      | 0.610520 | 0.543210          | 0.873070 |

## Random Forest Built-In Top Features

| feature           | normalized_importance |
| ----------------- | --------------------- |
| squad_rating_diff | 0.166759              |
| attack_vs_defense | 0.132113              |
| possession_diff   | 0.121846              |
| defense_vs_attack | 0.095559              |
| midfield_diff     | 0.090098              |
| elo_diff          | 0.070440              |
| gk_diff           | 0.062150              |
| discipline_diff   | 0.034445              |
| fatigue_diff      | 0.033847              |
| humidity          | 0.032841              |

## Random Forest Permutation Top Features

| feature              | permutation_importance_neg_log_loss_drop | std      |
| -------------------- | ---------------------------------------- | -------- |
| squad_rating_diff    | 0.059052                                 | 0.003246 |
| possession_diff      | 0.033473                                 | 0.002067 |
| attack_vs_defense    | 0.027042                                 | 0.002493 |
| midfield_diff        | 0.016115                                 | 0.001355 |
| defense_vs_attack    | 0.014665                                 | 0.001356 |
| elo_diff             | 0.010531                                 | 0.001999 |
| gk_diff              | 0.005373                                 | 0.000932 |
| data_confidence_diff | 0.001867                                 | 0.000743 |
| travel_diff          | 0.001748                                 | 0.001020 |
| match_day_index      | 0.000802                                 | 0.000501 |

## Local Occlusion Top Features

| feature              | mean_abs_true_probability_delta | mean_true_probability_delta |
| -------------------- | ------------------------------- | --------------------------- |
| squad_rating_diff    | 0.087754                        | 0.062047                    |
| possession_diff      | 0.055300                        | 0.040886                    |
| attack_vs_defense    | 0.041428                        | 0.026771                    |
| midfield_diff        | 0.037553                        | 0.024631                    |
| defense_vs_attack    | 0.035628                        | 0.023225                    |
| elo_diff             | 0.024529                        | 0.011675                    |
| gk_diff              | 0.020592                        | 0.008934                    |
| match_day_index      | 0.012947                        | 0.006335                    |
| discipline_diff      | 0.010064                        | -0.001173                   |
| data_confidence_diff | 0.010034                        | 0.002844                    |

## Feature Group Ablation

| group                     | log_loss_increase | accuracy_drop |
| ------------------------- | ----------------- | ------------- |
| unit_matchups             | 0.022751          | 0.012411      |
| team_strength             | 0.005472          | 0.005319      |
| rest_fatigue_availability | 0.004660          | 0.000000      |
| discipline                | 0.003308          | -0.001773     |
| venue_climate_travel      | 0.002088          | -0.001182     |
| tournament_structure      | 0.001340          | -0.002955     |
| host_context              | 0.000451          | -0.001773     |
| data_quality              | 0.000145          | 0.004728      |

## Tournament Simulation RF-Layer Ablation

This ablates feature groups inside the Random Forest layer only; the hand-built xG mechanics still use their normal team-profile inputs.

| scenario                  | ablated_features                                                          | epochs | top_champion | top_champion_pct |
| ------------------------- | ------------------------------------------------------------------------- | ------ | ------------ | ---------------- |
| baseline                  |                                                                           | 30     | Brazil       | 23.333300        |
| team_strength             | elo_diff|squad_rating_diff                                                | 30     | France       | 30.000000        |
| unit_matchups             | attack_vs_defense|defense_vs_attack|midfield_diff|gk_diff|possession_diff | 30     | Brazil       | 30.000000        |
| discipline                | discipline_diff                                                           | 30     | France       | 36.666700        |
| data_quality              | data_confidence_diff                                                      | 30     | Brazil       | 26.666700        |
| host_context              | host_diff|altitude_factor                                                 | 30     | Germany      | 23.333300        |
| rest_fatigue_availability | rest_diff|fatigue_diff|lineup_replacements_diff                           | 30     | France       | 23.333300        |
| venue_climate_travel      | travel_diff|heat_index|humidity|venue_altitude_km                         | 30     | France       | 23.333300        |
| tournament_structure      | stage_is_knockout|allow_draw|match_day_index                              | 30     | Brazil       | 23.333300        |
