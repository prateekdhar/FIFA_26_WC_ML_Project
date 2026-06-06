import argparse
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
DEFAULT_PDF = ROOT / "fifa_squadlists_english.pdf"
DEFAULT_OUTPUT = ROOT / "guardian_world_cup_2026_player_guide.json"

COUNTRY_NAME_FIXES = {
    "Bosnia And Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
    "Curaçao": "Curacao",
    "Czechia": "Czech Republic",
    "Côte D'Ivoire": "Ivory Coast",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Türkiye": "Turkey",
    "USA": "United States",
}

POSITION_CODES = {"GK", "DF", "MF", "FW"}


def normalize_country(name):
    return COUNTRY_NAME_FIXES.get(name, name)


def is_player_line(line):
    return bool(re.match(r"^\s*\d+\s*(GK|DF|MF|FW)\s+", line))


def fix_pdf_spacing(text):
    text = text.replace("\x00", "i")
    return re.sub(r"\b([A-Z])\s+([A-Z][A-Z]+)", r"\1\2", text).strip()


def is_surname_token(token):
    letters = [ch for ch in token if ch.isalpha()]
    return bool(letters) and (token.upper() == token or (len(token) > 2 and token[0].isupper() and token[1].islower() and token[2:].upper() == token[2:]))


def display_name_from_player_name(player_name):
    player_name = fix_pdf_spacing(player_name)
    parts = player_name.split()
    if len(parts) < 2:
        return player_name.title()
    surname = [parts[0]]
    index = 1
    while index < len(parts) and is_surname_token(parts[index]):
        surname.append(parts[index])
        index += 1
    given = parts[index:] or [surname[-1]]
    return " ".join(given + [part.title() if part.upper() == part else part for part in surname])


def split_player_line(line):
    line = fix_pdf_spacing(line)
    m = re.match(r"^\s*\d+\s*(GK|DF|MF|FW)\s+(.+?)\s{2,}.+?\s{2,}.+?\s{2,}.+?\s{2,}(\d{2}/\d{2}/\d{4})(.+?)\s+(\d{2,3})\s*$", line)
    if not m:
        raise ValueError(f"Could not parse player line: {line}")
    position, player_name, _dob, club, _height = m.groups()
    name = display_name_from_player_name(player_name)
    club = club.strip()

    return {
        "name": name,
        "position": position,
        "club": club or None,
    }


def extract_pdf(pdf_path):
    reader = PdfReader(str(pdf_path))
    teams = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        country = None
        for line in lines:
            m = re.search(r"SQUAD LIST\s*([^(]+)\s*\(([A-Z]{3})\)", line)
            if m:
                country = normalize_country(m.group(1).strip())
                break
        if country is None:
            for line in lines:
                m = re.match(r"^(.+?)\s+\(([A-Z]{3})\)$", line)
                if m:
                    country = normalize_country(m.group(1).strip())
                    break
        if country is None:
            raise ValueError(f"Could not identify country on page {len(teams) + 1}")

        players = [split_player_line(line) for line in lines if is_player_line(line)]
        if len(players) != 26:
            raise ValueError(f"{country}: expected 26 players, got {len(players)}")
        teams.append({"country": country, "players": players})

    if len(teams) != 48:
        raise ValueError(f"Expected 48 teams, got {len(teams)}")
    return sorted(teams, key=lambda team: team["country"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(
            f"Missing {pdf_path}. Download FIFA's official PDF from "
            "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf "
            "and save it at that path."
        )

    teams = extract_pdf(pdf_path)
    out = {
        "metadata": {
            "created_at": "2026-06-05",
            "competition": "FIFA World Cup 2026",
            "source": "FIFA official SquadLists-English.pdf, Version 1, 2026-06-03 11:30 UTC",
            "source_url": "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf",
            "team_count": len(teams),
            "player_count": sum(len(team["players"]) for team in teams),
            "player_fields": ["name", "position", "club"],
            "position_codes": {"GK": "Goalkeeper", "DF": "Defender", "MF": "Midfielder", "FW": "Forward"},
        },
        "teams": teams,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"teams={out['metadata']['team_count']} players={out['metadata']['player_count']}")


if __name__ == "__main__":
    main()
