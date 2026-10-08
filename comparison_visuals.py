"""Publication charts and a PDF for the frozen-forecast evaluation."""

import re
from html import escape

from reportlab.graphics import renderSVG, renderPDF
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

LABELS = {"primitive_eafc_poisson": "EAFC baseline",
          "v2_heuristic_nt_elo": "Heuristic v2",
          "v2_random_forest_nt_elo": "Random Forest v2"}
PALETTE = ["#23877e", "#b54a63", "#3579ad", "#dbad39", "#8063a5", "#67706c"]
TEAM_COLORS = dict(zip(["France", "Brazil", "Germany", "Spain", "Argentina", "Others"], PALETTE))
INK = "#202c32"
STAGE_LABELS = ["Last 32", "Last 16", "Quarter-final", "Semi-final", "Final", "Champion"]
STAGES = ["round_of_32", "round_of_16", "quarter_finals", "semi_finals", "final", "champion"]


def label(drawing, x, y, text, size=11, color=INK, anchor="start"):
    drawing.add(String(x, y, text, fontName="Helvetica", fontSize=size,
                       fillColor=colors.HexColor(color), textAnchor=anchor))


def base(title, subtitle, height=330):
    drawing = Drawing(900, height)
    drawing.add(Rect(0, 0, 900, height, fillColor=colors.white, strokeColor=None))
    label(drawing, 24, height - 30, title, 19)
    label(drawing, 24, height - 51, subtitle, 11, "#57666e")
    return drawing


def generate_charts(out, rows, scores, summaries):
    charts = []

    def save(name, title, caption, drawing):
        renderSVG.drawToFile(drawing, str(out / name))
        (out / "figures").mkdir(exist_ok=True)
        renderPDF.drawToFile(drawing, str(out / "figures" / name.replace(".svg", ".pdf")))
        charts.append((name, title, caption, drawing))

    d = base("How the comparison was made", "Saved forecasts are evaluated without retraining.", 235)
    boxes = [(25, "Frozen June forecasts", "4 models / 10,000 runs"),
             (250, "Verified FIFA outcomes", "48 teams / stage outcomes"),
             (475, "Probability evaluation", "Brier scores / top-k hits"),
             (700, "Comparison report", "Tables / charts / limitations")]
    for i, (x, title, detail) in enumerate(boxes):
        d.add(Rect(x, 90, 185, 77, fillColor=colors.HexColor("#eff5f5"), strokeColor=colors.HexColor("#b7c9cc")))
        label(d, x + 12, 137, title, 12)
        label(d, x + 12, 116, detail, 10)
        if i < 3:
            d.add(Line(x + 187, 128, x + 220, 128, strokeColor=colors.HexColor(INK)))
            d.add(Polygon([x + 220, 128, x + 213, 132, x + 213, 124], fillColor=colors.HexColor(INK)))
    label(d, 25, 38, "Outcome checks: 32 -> 16 -> 8 -> 4 -> 2 -> 1; CSV forecasts checked against original JSON.")
    save("evaluation_workflow.svg", "Evaluation workflow", "Frozen predictions and sourced outcomes feed the same scoring process.", d)

    d = base("Who each model expected to win", "Title probabilities (%); Spain is the actual champion. Identical colours identify the same team.", 355)
    for i, (model, model_label) in enumerate(LABELS.items()):
        x = 24 + i * 295
        subset = [r for r in rows if r["model_id"] == model]
        lookup = {r["team"]: float(r["champion_pct"]) for r in subset}
        teams = list(TEAM_COLORS)
        values = [lookup[t] for t in teams[:-1]]
        values.append(100 - sum(values))
        assert abs(sum(values) - 100) < 0.001 and all(v >= 0 for v in values)
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = x + 58, 126, 155, 155
        pie.data = values
        pie.labels = [""] * len(values)
        for j, team in enumerate(teams):
            pie.slices[j].fillColor = colors.HexColor(TEAM_COLORS[team])
            pie.slices[j].strokeColor = colors.white
        d.add(pie)
        label(d, x + 137, 294, model_label, 13, anchor="middle")
        for j, (team, value) in enumerate(zip(teams, values)):
            yy = 102 - (j // 2) * 23
            xx = x + (j % 2) * 145
            d.add(Rect(xx, yy - 2, 9, 9, fillColor=colors.HexColor(TEAM_COLORS[team]), strokeColor=None))
            label(d, xx + 14, yy, f"{team} {value:.2f}%", 10)
    save("champion_probability_pies.svg", "Champion probability distributions", "Each pie totals 100%. Others combines all teams outside the five named contenders.", d)

    d = base("Spain's forecast title probability", "Spain won; probabilities describe the forecast before the observed outcome.", 295)
    for i, (model, model_label) in enumerate(LABELS.items()):
        value = next(r["spain_champion_pct"] for r in summaries if r["model"] == model)
        y = 178 - i * 53
        label(d, 25, y + 9, model_label, 12)
        d.add(Rect(210, y, value / 25 * 540, 28, fillColor=colors.HexColor(PALETTE[i]), strokeColor=None))
        label(d, 220 + value / 25 * 540, y + 9, f"{value:.2f}%", 12)
    for value in range(0, 26, 5):
        label(d, 210 + value / 25 * 540, 39, f"{value}%", 10, anchor="middle")
    save("spain_title_probability.svg", "Spain's title chances", "Baseline: 10.26%; heuristic v2: 18.18%; Random Forest v2: 17.11%.", d)

    d = base("Forecast error across tournament stages", "Mean Brier score across 48 teams; lower is better. Six stages receive equal weight.", 385)
    for i, (model, model_label) in enumerate(LABELS.items()):
        for j, stage in enumerate(STAGES):
            value = next(r["brier_mean"] for r in scores if r["model"] == model and r["stage"] == stage)
            x = 80 + j * 133 + i * 28
            d.add(Rect(x, 91, 23, value / 0.18 * 210, fillColor=colors.HexColor(PALETTE[i]), strokeColor=None))
        mean = sum(r["brier_mean"] for r in scores if r["model"] == model and r["stage"] in STAGES) / 6
        d.add(Rect(43 + i * 285, 22, 10, 10, fillColor=colors.HexColor(PALETTE[i]), strokeColor=None))
        label(d, 60 + i * 285, 23, f"{model_label}: mean {mean:.4f}", 11)
    for value in [0, 0.05, 0.10, 0.15]:
        y = 91 + value / 0.18 * 210
        d.add(Line(64, y, 866, y, strokeColor=colors.HexColor("#d8e0e2"), strokeWidth=0.5))
        label(d, 54, y - 3, f"{value:.2f}", 10, anchor="end")
    for j, name in enumerate(STAGE_LABELS):
        label(d, 118 + j * 133, 69, name, 10, anchor="middle")
    save("stage_accuracy.svg", "Stage accuracy", "Heuristic v2 has the lowest combined advancement error in this tournament. Stage base rates differ, so compare models within a stage.", d)

    d = base("Forecasts versus actual advancement", "Random Forest v2; outlined cells indicate teams that actually reached the stage.", 490)
    teams = ["Spain", "Argentina", "England", "France", "Brazil", "Germany", "Norway", "Morocco", "Belgium", "Switzerland"]
    reached = {r["team"]: r for r in rows if r["model_id"] == "v2_random_forest_nt_elo"}
    actual = __import__("json").loads((out / "actual_outcomes.json").read_text())
    for j, name in enumerate(STAGE_LABELS):
        label(d, 215 + j * 112, 403, name, 10, anchor="middle")
    for i, team in enumerate(teams):
        y = 365 - i * 31
        label(d, 25, y + 10, team, 12)
        for j, stage in enumerate(STAGES):
            p = float(reached[team][stage + "_pct"])
            is_actual = team in actual["stages"][stage]
            colour = colors.Color(0.96 - 0.80 * p / 100, 0.97 - 0.45 * p / 100, 0.97 - 0.43 * p / 100)
            x = 161 + j * 112
            d.add(Rect(x, y, 108, 27, fillColor=colour, strokeColor=colors.HexColor(INK) if is_actual else colors.white, strokeWidth=2 if is_actual else 0.5))
            label(d, x + 54, y + 9, f"{p:.1f}%", 10, "#ffffff" if p > 65 else INK, "middle")
    label(d, 25, 28, "Darker fill = higher forecast probability. Outline = actual advancement. This is a selected-team view.", 10)
    save("forecast_outcome_heatmap.svg", "Forecasts and actual advancement", "Germany and Brazil had high predicted advancement, while Norway and Morocco exceeded their forecasts.", d)
    return charts


def write_pdf(out, text, charts):
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    styles["BodyText"].allowWidows = 0
    styles["BodyText"].allowOrphans = 0
    story = []
    chart_lookup = {name: drawing for name, _, _, drawing in charts}
    def scaled_chart(drawing):
        scaled = Drawing(510, drawing.height * 510 / 900)
        scaled.add(drawing)
        scaled.scale(510 / 900, 510 / 900)
        return scaled
    def friendly(value):
        for model, name in LABELS.items():
            value = value.replace(model, name)
        value = value.replace("v2_random_forest_squad_proxy_legacy", "Legacy RF")
        return value.replace("_", " ")
    for block in text.split("\n\n"):
        if block.startswith("### "):
            continue
        if block.startswith("!["):
            filename = re.fullmatch(r"!\[([^]]+)\]\(([^)]+)\)", block.strip())[2]
            story.append(scaled_chart(chart_lookup[filename]))
            continue
        if block.startswith("| "):
            lines = block.strip().splitlines()
            data = [[Paragraph(escape(friendly(c.strip())), styles["BodyText"]) for c in line.strip("|").split("|")] for line in [lines[0]] + lines[2:]]
            table = Table(data, repeatRows=1, colWidths=[510 / len(data[0])] * len(data[0]))
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1f0")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ccd6d9")), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
            story.extend([table, Spacer(1, 12)])
        elif block.startswith("#"):
            story.append(Paragraph(escape(block.lstrip("# ")), styles["Title"] if block.startswith("# ") else styles["Heading2"]))
        else:
            clean = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1 (\2)", block)
            story.extend([Paragraph(escape(clean).replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 9)])
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(42, 25, "World Cup 2026 | Frozen forecast evaluation | 8 October 2026")
        canvas.drawRightString(552, 25, str(doc.page))
    SimpleDocTemplate(str(out / "comparison_report.pdf"), pagesize=(595, 842), rightMargin=42, leftMargin=42, topMargin=40, bottomMargin=42).build(story, onFirstPage=footer, onLaterPages=footer)
