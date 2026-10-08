# Comprehensive Research Report

Open `comprehensive_report.pdf` for the current expanded report. The older
`comparison_report.pdf` is the previous, shorter edition.

The current report includes an abstract, contents, figure and table lists,
project introduction, dataset provenance, model definitions and equations,
research diagnostics, actual-result evaluation, limitations, conclusions,
15 numbered references, and a reproduction guide. Mbappé is accented in display
text; archived matching identifiers remain unchanged.

## Compile the Source Package

Keep `comparison_report.tex` beside the `figures` folder and run:

```text
pdflatex -interaction=nonstopmode -halt-on-error -jobname=comprehensive_report comparison_report.tex
```

Repeat until the contents and citations settle, normally two or three passes.
The source package includes every figure PDF and does not require the original
data files merely to typeset the report.

## Regenerate From the Repository

Run `python compare_simulation_with_actuals.py` at the repository root, then
compile as above. Regeneration requires the frozen prediction inputs, comparison
CSVs, combined player-data file and `report_templates` directory. The source
register is `dataset_sources.csv`; it explicitly identifies provenance gaps and
distinguishes later imports and planned datasets from used inputs.
