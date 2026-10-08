"""Generate a typeset evaluation report from the same checked comparison data."""

import csv
import json
from pathlib import Path

LABELS = {"primitive_eafc_poisson": "EAFC baseline",
          "v2_heuristic_nt_elo": "Heuristic v2",
          "v2_random_forest_nt_elo": "Random Forest v2",
          "v2_random_forest_squad_proxy_legacy": "Legacy RF"}
STAGES = {"round_of_32": "Last 32", "round_of_16": "Last 16",
          "quarter_finals": "Quarter-final", "semi_finals": "Semi-final",
          "final": "Final", "champion": "Champion",
          "third_place": "Third place", "fourth_place": "Fourth place"}


def esc(text):
    mapping = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
               "_": r"\_", "{": r"\{", "}": r"\}",
               "\\": r"\textbackslash{}", "~": r"\textasciitilde{}"}
    return "".join(mapping.get(c, c) for c in str(text))


def table(headers, rows, alignment, caption):
    return "\n".join([r"\begin{table}[ht]", r"\centering\small",
                       r"\caption{" + caption + "}",
                       r"\begin{tabular}{" + alignment + "}", r"\toprule",
                       " & ".join(headers) + r" \\", r"\midrule"] +
                      [" & ".join(esc(v) for v in row) + r" \\" for row in rows] +
                      [r"\bottomrule", r"\end{tabular}", r"\end{table}"])


def figure(name, caption, width="\\linewidth"):
    return (r"\begin{figure}[ht]\centering" + "\n" +
            r"\includegraphics[width=" + width + "]{figures/" + name + ".pdf}\n" +
            r"\caption{" + caption + "}\n" + r"\end{figure}")


def write_latex(out, summaries, scores, aggregate, largest, scorers, actual):
    root = Path(__file__).resolve().parent
    performance = json.loads((root / "player_performance_data_statbunker.json").read_text(encoding="utf-8"))
    counts = performance["metadata"]["player_statistics_summary"]["source_counts"]
    source_table = table(["Primary source", "Players", r"Share (\%)"],
                         [[name.replace("_", " ").title(), count, f"{count / 1248 * 100:.1f}"] for name, count in counts.items()],
                         "lrr", r"Primary player-statistics sources in the combined input.\label{tab:coverage}")
    with (root / "simulation_10000_model_comparison" / "simulation_10000_model_metadata.csv").open(encoding="utf-8-sig", newline="") as handle:
        runs = list(csv.DictReader(handle))
    run_table = table(["Model", "Runs", "Seed", "Rating prior"],
                      [[LABELS[r["model_id"]], r["epochs"], r["seed"], "EAFC only" if r["model_id"] == "primitive_eafc_poisson" else "Squad proxy" if r["primary_comparison"] == "False" else "FIFA rank-derived"] for r in runs],
                      "lrrl", "Frozen forecast inventory. Seeds are identifiers, not dates of publication.")
    background = (root / "report_templates" / "comparison_background.tex").read_text(encoding="utf-8").replace("@@SOURCE_TABLE@@", source_table).replace("@@RUN_TABLE@@", run_table)
    references = (root / "report_templates" / "comparison_references.tex").read_text(encoding="utf-8")
    dataset_rows = [
        ["squads", "FIFA", "fifa_squadlists_english.pdf", "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf", "Used to build working squads", "Local metadata: 2026-06-03; live PDF has later July timestamp"],
        ["ratings", "EAFC local export", "eafc26_players.csv", "", "Player overall ratings and detailed positions", "18405 rows; update field 2025-09-19; exact upstream URL and licence unrecorded"],
        ["performance", "StatBunker", "player_performance_data_statbunker.json", "https://www.statbunker.com/competitions/PlayerStandings?comp_id=776", "Main public statistics input; supplemented by other sources", "19923 source rows are not unique players; example endpoint from manifest"],
        ["supplement", "salimt/football-datasets", "player_performance_data_statbunker.json", "https://github.com/salimt/football-datasets", "Transfermarkt-derived CSV enrichment", "Provider repository recorded; exact dataset commit unrecorded"],
        ["supplement", "English Wikipedia", "player_performance_data_statbunker.json", "https://en.wikipedia.org/w/api.php", "Player biography aggregate statistics", "Individual URLs in records; no universal recent-season coverage"],
        ["supplement", "Manual web research", "remaining_player_manual_research.json", "", "Partial identity and statistics supplementation", "Per-player evidence recorded; no single dataset URL"],
        ["supplement", "SofaScore", "player_performance_data_statbunker.json", "https://www.sofascore.com/player/razzaghinia-amirmohammad/1500737", "Two primary-source player rows", "Example of two profile URLs in reconstruction metadata; not broad provider coverage"],
        ["saved_prior", "FIFA ranking", "external_data/world_football_elo/national_team_elo_ratings_fifa_rank_fallback_20260611.json", "https://inside.fifa.com/fifa-world-ranking/men", "Rank-derived prior declared in primary v2 outputs", "Ranking as-of 2025-11-19; transformed locally to Elo scale"],
        ["later_input", "World Football Elo", "external_data/world_football_elo/international_football_elo_20260611.json", "https://www.eloratings.net/", "Later import; not used in evaluated v2 artifacts", "177 teams as-of 2026-06-11; user-supplied export"],
        ["planned_input", "martj42/international_results", "external_football_data_manifest.json", "https://github.com/martj42/international_results", "Planned historical training input", "June download failed; zero historical training rows in evaluated forest"],
        ["structure", "FIFA draw", "world_cup_2026_simulation_structure.json", "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/final-draw-results", "Tournament groups", "URL recorded in local metadata"],
        ["structure_reference", "The Guardian", "world_cup_2026_simulation_structure.json", "https://www.theguardian.com/football/ng-interactive/2026/jun/04/world-cup-2026-complete-player-guide", "Reference recorded in tournament metadata", "Active squad JSON identifies FIFA PDF as source despite inherited Guardian filename"],
        ["context", "Project modelling assumptions", "world_cup_2026_venue_context.json", "", "Venue-region heat humidity altitude and travel priors", "Not observed match weather or full team itineraries"],
    ]
    for key, url in actual["sources"].items():
        dataset_rows.append(["evaluation", "FIFA " + key, "actual_results_comparison/actual_outcomes.json", url, "Observed outcomes only", "Verified 2026-10-08; not used to retrain forecasts"])
    with (out / "dataset_sources.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "source", "local_artifact", "source_url", "role", "provenance_note"])
        writer.writerows(dataset_rows)
    champion_rows = [[LABELS[r["model"]], r["predicted_winner"], r["spain_rank"],
                      f"{r['spain_champion_pct']:.2f}", f"{r['champion_log_loss']:.3f}",
                      f"{r['champion_brier_sum']:.3f}"] for r in summaries]
    score_rows = []
    for stage, stage_name in STAGES.items():
        selected = [next(r for r in scores if r["model"] == model and r["stage"] == stage) for model in list(LABELS)[:3]]
        score_rows.append([stage_name] + [f"{r['brier_mean']:.4f}" for r in selected] +
                          [" / ".join(f"{r['top_k_hits']}/{r['k']}" for r in selected)])
    miss_rows = [[LABELS[r["model"]], r["team"], STAGES[r["stage"]],
                  f"{r['forecast_pct']:.2f}", "Yes" if r["actual_reached"] else "No"] for r in largest]
    parts = [r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{graphicx,array,amsmath,xcolor}
\setlength{\oddsidemargin}{-2.4mm}
\setlength{\evensidemargin}{-2.4mm}
\setlength{\textwidth}{164mm}
\setlength{\topmargin}{-14mm}
\setlength{\headheight}{15pt}
\setlength{\headsep}{6mm}
\setlength{\textheight}{240mm}
\setlength{\footskip}{12mm}
\newcommand{\toprule}{\noalign{\hrule height 0.8pt}\noalign{\vskip 3pt}}
\newcommand{\midrule}{\noalign{\vskip 2pt}\noalign{\hrule height 0.4pt}\noalign{\vskip 3pt}}
\newcommand{\bottomrule}{\noalign{\vskip 3pt}\noalign{\hrule height 0.8pt}}
\usepackage{url}
\setcounter{tocdepth}{2}
\definecolor{accent}{HTML}{23877E}
\definecolor{ink}{HTML}{202C32}
\urlstyle{same}
\def\UrlBreaks{\do\/\do\-\do\_\do\?\do\=\do\.}
\makeatletter
\def\ps@reportstyle{\def\@oddhead{\small\color{ink}FIFA World Cup 2026\hfil Forecast evaluation}\let\@evenhead\@oddhead\def\@oddfoot{\small 8 October 2026\hfil\thepage}\let\@evenfoot\@oddfoot}
\long\def\@makecaption#1#2{\vskip 6pt{\small\textbf{#1.} #2\par}\vskip 4pt}
\makeatother
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}
\setlength{\tabcolsep}{6pt}
\renewcommand{\arraystretch}{1.18}
\setlength{\textfloatsep}{12pt}
\setlength{\intextsep}{12pt}
\pagestyle{reportstyle}
\emergencystretch=2em
\begin{document}
\thispagestyle{plain}
{\color{accent}\small RESEARCH REPORT}\par
\vspace{8pt}
{\LARGE\bfseries FIFA World Cup 2026\par}
\vspace{4pt}
{\Large Simulation Forecasts Versus Actual Results\par}
\vspace{8pt}
{\small Prepared 8 October 2026\quad|\quad Four models\quad|\quad 10,000 runs per model}
\vspace{10pt}
\hrule
""", background, r"""
\section{Evaluation Design}
The comparison joins frozen forecast percentages with binary indicators of actual
advancement for each of the 48 teams. The analysis verifies that the comparison
CSVs match the original JSON outputs and that the observed stage memberships
are nested correctly. FIFA's knockout results supply advancement membership
\cite{outcome-knockouts}. The main comparison contains 1,536 team-stage rows:
four models, 48 teams and eight reported outcomes per team.
""",
             figure("evaluation_workflow", "Workflow for evaluating saved forecasts against sourced tournament outcomes."),
             r"""\subsection{Probability Scores}
For team $t$ at stage $s$, let $p_{t,s}$ be the forecast probability and
$y_{t,s}\in\{0,1\}$ indicate whether that team reached the stage.
\begin{align}
\mathrm{BS}_s &= \frac{1}{48}\sum_{t=1}^{48}(p_{t,s}-y_{t,s})^2,\\
\mathrm{Skill}_s &= 1-\frac{\mathrm{BS}_s}{q_s(1-q_s)},\qquad q_s=\frac{k_s}{48},\\
\mathrm{LL}_{\mathrm{champion}} &= -\ln p_{\mathrm{Spain},\mathrm{champion}}.
\end{align}
Lower Brier score and log loss are better. Positive skill indicates improvement
over a uniform stage probability. The categorical champion Brier score is the
\emph{sum} across 48 outcomes; advancement Brier scores are \emph{means}.

The combined advancement score is the equally weighted mean over six stages:
last 32, last 16, quarter-finals, semi-finals, final and champion. Third- and
fourth-place outcomes are reported separately.
\subsection{Top-$k$ Overlap}
For a stage admitting $k$ teams, the analysis counts how many of the $k$ highest
forecast teams actually reached it. Equal probabilities use alphabetical ordering.
This ranking measure complements probability scores but does not assess calibration.
\clearpage
\section{Championship Forecasts}
Spain had substantial probability in each primary forecast, but no primary model
selected Spain as its favourite. A likely contender winning is compatible with
the forecast even when the highest-ranked team's prediction is incorrect.
""",
             figure("champion_probability_pies", r"Title-probability distributions for the three primary models. Each pie totals 100\%; Others combines all teams outside the five named contenders."),
             table(["Model", "Favourite", "Spain rank", r"Spain (\%)", "Log loss", "Brier sum"], champion_rows, "llrrrr", "Forecast support for the actual champion. Legacy RF is a reference model."),
             figure("spain_title_probability", "Spain's title probability across the primary models.", "0.9\\linewidth"),
             r"""\clearpage
\section{Advancement Accuracy}
The richer heuristic model improves the combined score relative to the baseline,
but the improvement is not uniform across stages. The baseline has lower Brier
error at the quarter-final, semi-final and final stages.
""",
             figure("stage_accuracy", "Stage-wise mean Brier scores. Compare models within a stage because the stage base rates differ."),
             table(["Stage", "Baseline", "Heuristic", "RF", "Top-$k$ hits (B / H / RF)"], score_rows, "lrrrl", "Advancement error and top-ranked qualifier overlap across the three primary models."),
             table(["Primary model", "Mean six-stage Brier"], [[LABELS[r["model"]], f"{r['mean_six_stage_brier']:.4f}"] for r in aggregate], "lr", "Equal-weight combined advancement scores; lower is better."),
             r"""\clearpage
\section{Where Forecasts and Outcomes Diverged}
""",
             figure("forecast_outcome_heatmap", "Random Forest v2 probabilities for selected teams. Outlined cells indicate actual advancement; darker fills indicate higher forecast probability."),
             r"""Germany exited in the last 32 and Brazil in the last 16 despite high v2
advancement probabilities. Norway, Morocco, Belgium and Switzerland reached
the quarter-finals. The selected-team heatmap illustrates both overestimation
of highly rated contenders and underestimation of unexpected progress.

These discrepancies suggest reviewing upset frequency, bracket effects and
player-data coverage. The observed outcomes alone cannot identify which
mechanism caused a forecast error.
""",
             table(["Model", "Team", "Stage", r"Forecast (\%)", "Reached?"], miss_rows[:8], "lllrl", "Eight largest absolute discrepancies among primary-model quarter-final, semi-final and final forecasts."),
             r"""\clearpage
\section{Player Scoring and Interpretation}
Kylian Mbapp\'{e} won the Golden Boot with 10 goals. Both primary v2 models ranked
him first by expected aggregate goals; the baseline ranked him second.
""",
             table(["Model", r"Mbapp\'{e} rank", "Mean goals", "Actual goals"], [[LABELS[r["model"]], r["mbappe_scorer_rank"], f"{r['predicted_mean_goals']:.3f}", r["actual_goals"]] for r in scorers], "lrrr", "Expected scoring rank and mean goals versus one observed tournament."),
             r"""Expected goals over many simulated tournaments and observed goals in a single
tournament are different quantities. A mean of approximately three goals does
not predict that the player must score three. Similarly, a ranking by expected
goals is not the probability of winning the Golden Boot. This comparison is
descriptive; award forecasting would require a separate probability calculation.
\section{Provenance, Limitations and Next Steps}
\subsection{Forecast Provenance}
Each model ran 10,000 tournaments. The two primary v2 artifacts used
FIFA-rank-derived Elo-scale priors, rather than the raw World Football Elo data
imported later. Random Forest training used synthetic profile calibration;
historical-match predictive accuracy was not established.

Seeds that resemble dates are random-number seeds, not creation timestamps.
The artifacts were saved around the start of the tournament and the v2 files
were last modified on 11 June. Local timestamps do not prove publication before
kickoff. This report therefore evaluates saved forecasts retrospectively.
\subsection{Statistical and Data Limits}
Advancement indicators are dependent; six stages across 48 teams are not 288
independent observations. One tournament cannot establish calibration or model
superiority. Wilson intervals in prior reports measure Monte Carlo sampling
error conditional on model assumptions, not uncertainty about those assumptions.

Saved outputs do not supply probabilities for every actual match or every
player. Match-level log loss and full player-goal errors are outside scope.
Group-stage exits are inferred from absence in the verified last-32 field.
Rankings among teams eliminated at the same stage are not inferred.
\clearpage
\subsection{Recommended Research Work}
\begin{enumerate}
\item Backtest several historical tournaments using information available at each match date.
\item Calibrate goal, draw and upset rates on real international results.
\item Review bracket routing and concentration of probability on stronger teams.
\item Improve low-confidence player coverage and model Golden Boot probabilities separately.
\item Publish dated forecast snapshots before future tournaments.
\end{enumerate}
\subsection{Reproducibility}
Run \texttt{python compare\_simulation\_with\_actuals.py} from the repository root.
The analysis regenerates CSV score tables, Markdown and HTML reports, charts
and this LaTeX source. Compile the source from the report folder using
\texttt{pdflatex -jobname=comprehensive\_report}\par
\texttt{comparison\_report.tex}\par
Repeat until contents pages and cross-references settle.

Supporting data: \texttt{actual\_outcomes.json}, \texttt{model\_scores.csv},\par
\texttt{team\_stage\_comparison.csv}, \texttt{champion\_comparison.csv},\par
\texttt{scorer\_comparison.csv}, \texttt{prediction\_sha256.json}.\par
The hashes identify the frozen inputs. Figure PDFs are supplied in the
\texttt{figures/} folder.
\section{Conclusion}
The project establishes an inspectable chain from data collection to simulated
tournaments and retrospective evaluation. Spain was a credible contender in
every primary forecast, but the favoured team was wrong in each case. Heuristic
v2 achieved the best combined advancement score on this tournament, while the
baseline performed better at some later stages. The RF extension did not deliver
a consistent improvement over the heuristic engine.

The most useful next step is stronger validation: chronologically separated
historical data, measured match context, controlled model comparisons and
published forecast snapshots. These improvements would make it possible to
distinguish the benefits of richer football information from the effects of
hand-set assumptions and synthetic training.
""", references, r"""
\end{document}
"""]
    (out / "comparison_report.tex").write_text("\n\n".join(parts), encoding="utf-8")
