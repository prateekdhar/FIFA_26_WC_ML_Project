# FIFA WC26 10,000-Simulation Model Report

This report compares the stored 10,000-epoch runs across the project models. The primary comparison uses the current runs where available; the older Random Forest squad-proxy run is retained as a legacy reference.

## Model Inventory

| model_id                            | model_label                                       | primary_comparison | file                                       | epochs | seed     | workers | elo_source                                                            | decision_forest_kind      | training_source               | training_rows | training_accuracy | features_output                            |
| ----------------------------------- | ------------------------------------------------- | ------------------ | ------------------------------------------ | ------ | -------- | ------- | --------------------------------------------------------------------- | ------------------------- | ----------------------------- | ------------- | ----------------- | ------------------------------------------ |
| primitive_eafc_poisson              | Primitive EAFC Poisson                            | True               | simulation_results_10000.json              | 10000  | 20260605 |         |                                                                       | none                      |                               |               |                   |                                            |
| v2_heuristic_nt_elo                 | V2 Heuristic Internal Forest + NT Elo             | True               | simulation_results_v2_heuristic_10000.json | 10000  | 20260620 | 8       | FIFA/Coca-Cola Men's World Ranking ranks converted to Elo-scale prior | heuristic_internal_forest |                               | 0             |                   | simulation_features_v2_heuristic_10000.csv |
| v2_random_forest_nt_elo             | V2 sklearn Random Forest + NT Elo                 | True               | simulation_results_v2_rf_elo_10000.json    | 10000  | 20260621 | 8       | FIFA/Coca-Cola Men's World Ranking ranks converted to Elo-scale prior | sklearn_random_forest     | synthetic_profile_calibration | 6768          | 0.7301            | simulation_features_v2_rf_elo_10000.csv    |
| v2_random_forest_squad_proxy_legacy | V2 sklearn Random Forest + squad-proxy Elo legacy | False              | simulation_results_v2_rf_10000.json        | 10000  | 20260618 | 8       | squad_proxy                                                           | sklearn_random_forest     | synthetic_profile_calibration | 6768          |                   | simulation_features_v2_rf_10000.csv        |

## Top Winner Per Primary Model

| model_label                           | team   | champion_pct | final_pct | semi_finals_pct |
| ------------------------------------- | ------ | ------------ | --------- | --------------- |
| Primitive EAFC Poisson                | France | 12.500       | 20.410    | 32.030          |
| V2 Heuristic Internal Forest + NT Elo | Brazil | 19.230       | 40.720    | 66.300          |
| V2 sklearn Random Forest + NT Elo     | Brazil | 20.090       | 42.090    | 68.770          |

## Consensus Champion Board

Average champion probability is calculated across the primary runs: primitive EAFC Poisson, v2 heuristic with NT Elo, and v2 Random Forest with NT Elo.

| team        | primary_average_champion_pct | all_model_range_pct | primitive_eafc_poisson | v2_heuristic_nt_elo | v2_random_forest_nt_elo |
| ----------- | ---------------------------- | ------------------- | ---------------------- | ------------------- | ----------------------- |
| France      | 17.017                       | 15.870              | 12.500                 | 19.090              | 19.460                  |
| Brazil      | 15.913                       | 11.670              | 8.420                  | 19.230              | 20.090                  |
| Germany     | 15.387                       | 11.640              | 8.110                  | 18.300              | 19.750                  |
| Spain       | 15.183                       | 7.920               | 10.260                 | 18.180              | 17.110                  |
| Argentina   | 7.707                        | 1.590               | 7.670                  | 8.520               | 6.930                   |
| England     | 6.823                        | 7.570               | 8.550                  | 5.160               | 6.760                   |
| Portugal    | 5.700                        | 4.680               | 8.390                  | 4.360               | 4.350                   |
| Netherlands | 4.617                        | 2.790               | 6.170                  | 4.300               | 3.380                   |
| Belgium     | 2.320                        | 3.370               | 4.470                  | 1.390               | 1.100                   |
| Turkey      | 0.893                        | 2.120               | 2.130                  | 0.300               | 0.250                   |
| Croatia     | 0.883                        | 2.490               | 2.540                  | 0.050               | 0.060                   |
| Switzerland | 0.653                        | 1.530               | 1.550                  | 0.170               | 0.240                   |

## Top Champion Probabilities By Model

| model_label                                       | team        | champion_pct | final_pct | semi_finals_pct | average_group_points |
| ------------------------------------------------- | ----------- | ------------ | --------- | --------------- | -------------------- |
| Primitive EAFC Poisson                            | France      | 12.500       | 20.410    | 32.030          | 6.121                |
| Primitive EAFC Poisson                            | Spain       | 10.260       | 17.770    | 28.450          | 6.174                |
| Primitive EAFC Poisson                            | England     | 8.550        | 15.120    | 25.720          | 5.853                |
| Primitive EAFC Poisson                            | Brazil      | 8.420        | 15.250    | 25.970          | 5.768                |
| Primitive EAFC Poisson                            | Portugal    | 8.390        | 15.280    | 25.390          | 5.864                |
| Primitive EAFC Poisson                            | Germany     | 8.110        | 15.190    | 26.490          | 6.054                |
| Primitive EAFC Poisson                            | Argentina   | 7.670        | 13.860    | 24.110          | 5.844                |
| Primitive EAFC Poisson                            | Netherlands | 6.170        | 11.420    | 21.320          | 5.556                |
| Primitive EAFC Poisson                            | Belgium     | 4.470        | 8.920     | 17.100          | 6.012                |
| Primitive EAFC Poisson                            | Croatia     | 2.540        | 5.390     | 11.770          | 4.767                |
| V2 Heuristic Internal Forest + NT Elo             | Brazil      | 19.230       | 40.720    | 66.300          | 7.501                |
| V2 Heuristic Internal Forest + NT Elo             | France      | 19.090       | 27.870    | 38.130          | 7.986                |
| V2 Heuristic Internal Forest + NT Elo             | Germany     | 18.300       | 41.270    | 68.690          | 7.695                |
| V2 Heuristic Internal Forest + NT Elo             | Spain       | 18.180       | 27.510    | 39.250          | 7.900                |
| V2 Heuristic Internal Forest + NT Elo             | Argentina   | 8.520        | 17.250    | 45.080          | 7.893                |
| V2 Heuristic Internal Forest + NT Elo             | England     | 5.160        | 9.700     | 26.390          | 7.886                |
| V2 Heuristic Internal Forest + NT Elo             | Portugal    | 4.360        | 8.430     | 23.240          | 7.745                |
| V2 Heuristic Internal Forest + NT Elo             | Netherlands | 4.300        | 10.080    | 20.860          | 7.718                |
| V2 Heuristic Internal Forest + NT Elo             | Belgium     | 1.390        | 4.640     | 11.520          | 8.051                |
| V2 Heuristic Internal Forest + NT Elo             | Turkey      | 0.300        | 2.200     | 8.850           | 5.711                |
| V2 sklearn Random Forest + NT Elo                 | Brazil      | 20.090       | 42.090    | 68.770          | 7.683                |
| V2 sklearn Random Forest + NT Elo                 | Germany     | 19.750       | 42.930    | 72.370          | 7.769                |
| V2 sklearn Random Forest + NT Elo                 | France      | 19.460       | 29.440    | 39.970          | 8.021                |
| V2 sklearn Random Forest + NT Elo                 | Spain       | 17.110       | 26.650    | 39.220          | 7.916                |
| V2 sklearn Random Forest + NT Elo                 | Argentina   | 6.930        | 14.160    | 36.990          | 7.919                |
| V2 sklearn Random Forest + NT Elo                 | England     | 6.760        | 13.480    | 34.500          | 7.854                |
| V2 sklearn Random Forest + NT Elo                 | Portugal    | 4.350        | 8.440     | 23.560          | 7.801                |
| V2 sklearn Random Forest + NT Elo                 | Netherlands | 3.380        | 8.730     | 19.700          | 7.734                |
| V2 sklearn Random Forest + NT Elo                 | Belgium     | 1.100        | 3.730     | 10.170          | 8.085                |
| V2 sklearn Random Forest + NT Elo                 | Turkey      | 0.250        | 1.990     | 8.960           | 6.029                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | France      | 28.370       | 42.470    | 60.620          | 8.088                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Spain       | 14.380       | 27.650    | 48.490          | 7.992                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | England     | 12.730       | 25.630    | 46.470          | 8.002                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Brazil      | 11.550       | 23.220    | 43.590          | 7.802                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Germany     | 10.880       | 22.910    | 43.990          | 7.951                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Portugal    | 9.030        | 20.010    | 40.290          | 7.946                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Argentina   | 7.450        | 17.260    | 38.260          | 8.010                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Netherlands | 3.830        | 11.800    | 30.690          | 7.819                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Belgium     | 1.600        | 6.620     | 23.720          | 8.107                |
| V2 sklearn Random Forest + squad-proxy Elo legacy | Croatia     | 0.050        | 0.460     | 3.380           | 5.361                |

## Biggest Model Disagreements

These are the teams whose title probability moves most across all stored 10,000-run variants.

| team        | primitive_eafc_poisson | v2_heuristic_nt_elo | v2_random_forest_nt_elo | v2_random_forest_squad_proxy_legacy | primary_average_champion_pct | all_model_range_pct |
| ----------- | ---------------------- | ------------------- | ----------------------- | ----------------------------------- | ---------------------------- | ------------------- |
| France      | 12.500                 | 19.090              | 19.460                  | 28.370                              | 17.017                       | 15.870              |
| Brazil      | 8.420                  | 19.230              | 20.090                  | 11.550                              | 15.913                       | 11.670              |
| Germany     | 8.110                  | 18.300              | 19.750                  | 10.880                              | 15.387                       | 11.640              |
| Spain       | 10.260                 | 18.180              | 17.110                  | 14.380                              | 15.183                       | 7.920               |
| England     | 8.550                  | 5.160               | 6.760                   | 12.730                              | 6.823                        | 7.570               |
| Portugal    | 8.390                  | 4.360               | 4.350                   | 9.030                               | 5.700                        | 4.680               |
| Belgium     | 4.470                  | 1.390               | 1.100                   | 1.600                               | 2.320                        | 3.370               |
| Netherlands | 6.170                  | 4.300               | 3.380                   | 3.830                               | 4.617                        | 2.790               |
| Croatia     | 2.540                  | 0.050               | 0.060                   | 0.050                               | 0.883                        | 2.490               |
| Turkey      | 2.130                  | 0.300               | 0.250                   | 0.010                               | 0.893                        | 2.120               |
| Morocco     | 1.720                  | 0.150               | 0.080                   | 0.020                               | 0.650                        | 1.700               |
| Uruguay     | 1.600                  | 0.030               | 0.010                   | 0.000                               | 0.547                        | 1.600               |

## V2 Event-Model Discipline And Load Snapshot

| model_label                           | team        | fouls_per_tournament | yellow_cards_per_tournament | red_cards_per_tournament | substitutions_per_tournament | possession_tick_share |
| ------------------------------------- | ----------- | -------------------- | --------------------------- | ------------------------ | ---------------------------- | --------------------- |
| V2 Heuristic Internal Forest + NT Elo | Mexico      | 63.638               | 11.893                      | 2.521                    | 17.064                       | 0.526                 |
| V2 Heuristic Internal Forest + NT Elo | Algeria     | 47.947               | 9.377                       | 2.068                    | 14.107                       | 0.483                 |
| V2 Heuristic Internal Forest + NT Elo | South Korea | 49.502               | 8.711                       | 1.766                    | 15.740                       | 0.512                 |
| V2 Heuristic Internal Forest + NT Elo | Brazil      | 63.684               | 8.971                       | 1.516                    | 23.480                       | 0.618                 |
| V2 Heuristic Internal Forest + NT Elo | Turkey      | 47.847               | 7.189                       | 1.340                    | 18.096                       | 0.555                 |
| V2 Heuristic Internal Forest + NT Elo | Croatia     | 43.989               | 6.871                       | 1.248                    | 16.362                       | 0.520                 |
| V2 Heuristic Internal Forest + NT Elo | Morocco     | 40.078               | 6.043                       | 1.130                    | 15.641                       | 0.507                 |
| V2 Heuristic Internal Forest + NT Elo | Argentina   | 63.388               | 8.408                       | 1.086                    | 21.543                       | 0.590                 |
| V2 sklearn Random Forest + NT Elo     | Mexico      | 60.101               | 11.313                      | 2.390                    | 16.340                       | 0.518                 |
| V2 sklearn Random Forest + NT Elo     | Algeria     | 47.986               | 9.353                       | 2.061                    | 14.062                       | 0.483                 |
| V2 sklearn Random Forest + NT Elo     | South Korea | 49.176               | 8.647                       | 1.751                    | 15.583                       | 0.510                 |
| V2 sklearn Random Forest + NT Elo     | Brazil      | 64.780               | 9.097                       | 1.513                    | 23.718                       | 0.620                 |
| V2 sklearn Random Forest + NT Elo     | Turkey      | 48.916               | 7.349                       | 1.376                    | 18.302                       | 0.557                 |
| V2 sklearn Random Forest + NT Elo     | Croatia     | 44.303               | 6.965                       | 1.250                    | 16.422                       | 0.521                 |
| V2 sklearn Random Forest + NT Elo     | Morocco     | 39.325               | 5.941                       | 1.115                    | 15.313                       | 0.502                 |
| V2 sklearn Random Forest + NT Elo     | Argentina   | 61.455               | 8.216                       | 1.045                    | 20.927                       | 0.583                 |

## Top Scorers

| model_label                           | rank | player            | team        | position | goals | goals_per_tournament |
| ------------------------------------- | ---- | ----------------- | ----------- | -------- | ----- | -------------------- |
| Primitive EAFC Poisson                | 1    | Lautaro Martinez  | Argentina   | ST       | 14488 | 1.449                |
| Primitive EAFC Poisson                | 2    | Kylian Mbappe     | France      | ST       | 14465 | 1.446                |
| Primitive EAFC Poisson                | 3    | Romelu Lukaku     | Belgium     | ST       | 13982 | 1.398                |
| Primitive EAFC Poisson                | 4    | Cristiano Ronaldo | Portugal    | ST       | 13914 | 1.391                |
| Primitive EAFC Poisson                | 5    | Julian Alvarez    | Argentina   | ST       | 13850 | 1.385                |
| Primitive EAFC Poisson                | 6    | Mikel Oyarzabal   | Spain       | ST       | 12543 | 1.254                |
| Primitive EAFC Poisson                | 7    | Harry Kane        | England     | ST       | 12340 | 1.234                |
| Primitive EAFC Poisson                | 8    | Kai Havertz       | Germany     | ST       | 12013 | 1.201                |
| V2 Heuristic Internal Forest + NT Elo | 1    | Kylian Mbappe     | France      | ST       | 29459 | 2.946                |
| V2 Heuristic Internal Forest + NT Elo | 2    | Lautaro Martinez  | Argentina   | ST       | 27394 | 2.739                |
| V2 Heuristic Internal Forest + NT Elo | 3    | Cristiano Ronaldo | Portugal    | ST       | 27192 | 2.719                |
| V2 Heuristic Internal Forest + NT Elo | 4    | Harry Kane        | England     | ST       | 26287 | 2.629                |
| V2 Heuristic Internal Forest + NT Elo | 5    | Romelu Lukaku     | Belgium     | ST       | 25402 | 2.540                |
| V2 Heuristic Internal Forest + NT Elo | 6    | Julian Alvarez    | Argentina   | ST       | 24486 | 2.449                |
| V2 Heuristic Internal Forest + NT Elo | 7    | Memphis Depay     | Netherlands | ST       | 24123 | 2.412                |
| V2 Heuristic Internal Forest + NT Elo | 8    | Ousmane Dembele   | France      | RW       | 23753 | 2.375                |
| V2 sklearn Random Forest + NT Elo     | 1    | Kylian Mbappe     | France      | ST       | 29035 | 2.904                |
| V2 sklearn Random Forest + NT Elo     | 2    | Cristiano Ronaldo | Portugal    | ST       | 27205 | 2.720                |
| V2 sklearn Random Forest + NT Elo     | 3    | Harry Kane        | England     | ST       | 26795 | 2.679                |
| V2 sklearn Random Forest + NT Elo     | 4    | Lautaro Martinez  | Argentina   | ST       | 25929 | 2.593                |
| V2 sklearn Random Forest + NT Elo     | 5    | Romelu Lukaku     | Belgium     | ST       | 24906 | 2.491                |
| V2 sklearn Random Forest + NT Elo     | 6    | Kai Havertz       | Germany     | ST       | 23545 | 2.354                |
| V2 sklearn Random Forest + NT Elo     | 7    | Vinicius Junior   | Brazil      | LW       | 23539 | 2.354                |
| V2 sklearn Random Forest + NT Elo     | 8    | Memphis Depay     | Netherlands | ST       | 23319 | 2.332                |

## Top Assisters

| model_label                           | rank | player            | team     | position | assists | assists_per_tournament |
| ------------------------------------- | ---- | ----------------- | -------- | -------- | ------- | ---------------------- |
| Primitive EAFC Poisson                | 1    | Jude Bellingham   | England  | CAM      | 8275    | 0.828                  |
| Primitive EAFC Poisson                | 2    | Florian Wirtz     | Germany  | CAM      | 7921    | 0.792                  |
| Primitive EAFC Poisson                | 3    | Jamal Musiala     | Germany  | CAM      | 7570    | 0.757                  |
| Primitive EAFC Poisson                | 4    | Matheus Cunha     | Brazil   | CAM      | 7544    | 0.754                  |
| Primitive EAFC Poisson                | 5    | Raphinha          | Brazil   | LM       | 7507    | 0.751                  |
| Primitive EAFC Poisson                | 6    | Mohamed Salah     | Egypt    | RM       | 7336    | 0.734                  |
| Primitive EAFC Poisson                | 7    | Adrien Rabiot     | France   | CAM      | 7274    | 0.727                  |
| Primitive EAFC Poisson                | 8    | Francisco Trincao | Portugal | CAM      | 6904    | 0.690                  |
| V2 Heuristic Internal Forest + NT Elo | 1    | Florian Wirtz     | Germany  | CAM      | 18142   | 1.814                  |
| V2 Heuristic Internal Forest + NT Elo | 2    | Jamal Musiala     | Germany  | CAM      | 16958   | 1.696                  |
| V2 Heuristic Internal Forest + NT Elo | 3    | Lamine Yamal      | Spain    | RM       | 16455   | 1.645                  |
| V2 Heuristic Internal Forest + NT Elo | 4    | Raphinha          | Brazil   | LM       | 16358   | 1.636                  |
| V2 Heuristic Internal Forest + NT Elo | 5    | Jude Bellingham   | England  | CAM      | 16031   | 1.603                  |
| V2 Heuristic Internal Forest + NT Elo | 6    | Joshua Kimmich    | Germany  | CM       | 15206   | 1.521                  |
| V2 Heuristic Internal Forest + NT Elo | 7    | Michael Olise     | France   | RM       | 14818   | 1.482                  |
| V2 Heuristic Internal Forest + NT Elo | 8    | Ousmane Dembele   | France   | RW       | 14537   | 1.454                  |
| V2 sklearn Random Forest + NT Elo     | 1    | Florian Wirtz     | Germany  | CAM      | 18160   | 1.816                  |
| V2 sklearn Random Forest + NT Elo     | 2    | Jamal Musiala     | Germany  | CAM      | 16935   | 1.694                  |
| V2 sklearn Random Forest + NT Elo     | 3    | Raphinha          | Brazil   | LM       | 16517   | 1.652                  |
| V2 sklearn Random Forest + NT Elo     | 4    | Lamine Yamal      | Spain    | RM       | 16250   | 1.625                  |
| V2 sklearn Random Forest + NT Elo     | 5    | Jude Bellingham   | England  | CAM      | 16175   | 1.617                  |
| V2 sklearn Random Forest + NT Elo     | 6    | Joshua Kimmich    | Germany  | CM       | 15167   | 1.517                  |
| V2 sklearn Random Forest + NT Elo     | 7    | Michael Olise     | France   | RM       | 14271   | 1.427                  |
| V2 sklearn Random Forest + NT Elo     | 8    | Ousmane Dembele   | France   | RW       | 14172   | 1.417                  |

## Caveats

- The primitive model is intentionally simpler: EAFC-overall team strength plus Poisson goals.
- The v2 Random Forest and v2 heuristic runs include compressed match events, possession, cards, fatigue, substitutions, set pieces, extra time, and penalties.
- The current v2 NT Elo runs use the FIFA-rank-derived Elo-scale prior, not raw World Football Elo.
- The Random Forest is trained on synthetic calibration rows because no historical international match CSV has been supplied yet.
- The legacy v2 Random Forest squad-proxy file is included to preserve prior output, but it should not be treated as the main current RF estimate.
