import argparse
import hashlib
import html
import json
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_FILE = ROOT / "player_performance_manifest.json"
OUTPUT_FILE = ROOT / "player_performance_data_statbunker.json"
REVIEW_FILE = ROOT / "player_performance_data_statbunker_review.json"
CACHE_DIR = ROOT / ".cache" / "statbunker"
SCHEMA_VERSION = 2
STATBUNKER_BASE = "https://www.statbunker.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 FIFA26WCResearch/0.1"
)


DEFAULT_COMPETITIONS = [
    {
        "key": "premier_league_2025_26",
        "name": "Premier League 25/26",
        "comp_id": 776,
        "season": "2025/26",
        "competition_weight": 1.05,
    },
    {
        "key": "la_liga_2025_26",
        "name": "La Liga 25/26",
        "comp_id": 777,
        "season": "2025/26",
        "competition_weight": 1.05,
    },
    {
        "key": "serie_a_2025_26",
        "name": "Serie A 25/26",
        "comp_id": 785,
        "season": "2025/26",
        "competition_weight": 1.05,
    },
    {
        "key": "ligue_1_2025_26",
        "name": "Ligue 1 25/26",
        "comp_id": 787,
        "season": "2025/26",
        "competition_weight": 1.05,
    },
    {
        "key": "championship_2025_26",
        "name": "Sky Bet Championship 25/26",
        "comp_id": 779,
        "season": "2025/26",
        "competition_weight": 0.9,
    },
    {
        "key": "champions_league_2025_26",
        "name": "UEFA Champions League 25/26",
        "comp_id": 783,
        "season": "2025/26",
        "competition_weight": 1.15,
    },
    {
        "key": "conference_league_2025_26",
        "name": "UEFA Europa Conference League 25/26",
        "comp_id": 786,
        "season": "2025/26",
        "competition_weight": 1.0,
    },
]


DEFAULT_COMPETITION_TYPES = [
    "EPL",
    "LL",
    "SA",
    "BL",
    "LC",
    "EC",
    "SPL",
    "MLS",
    "DL",
    "ABUN",
    "SWSL",
    "DANSL",
    "UCL",
    "UCUP",
    "UECON",
    "COPA",
    "FWCC",
    "UEFANL",
    "WCQ",
    "WCQAF",
    "WCQAS",
    "WCQNCA",
    "WCQSA",
    "WCQE",
    "WCQOC",
    "ECCQ",
    "ACON",
    "Goldc",
    "ASCUP",
    "INT",
]


RECENCY_TERMS = ("25/26", "2025", "24/25", "2024")


PAGE_TYPES = {
    "overall": {
        "path": "/competitions/PlayerStandings",
        "required": {"players", "clubs"},
    },
    "fantasy": {
        "path": "/competitions/FantasyFootballPlayersStats",
        "required": {"players", "points"},
    },
    "clean_sheets": {
        "path": "/competitions/Top10KeepersCleanSheets",
        "required": {"players", "clubs", "cs"},
    },
}


OVERALL_COLUMNS = [
    "player",
    "club",
    "position",
    "appearances",
    "goals",
    "assists",
    "yellow_cards",
    "second_yellow_cards",
    "red_cards",
    "starts",
    "substitute_named",
    "came_on",
    "taken_off",
    "penalties_scored",
    "penalties_saved",
    "penalties_missed",
    "penalties_conceded",
    "own_goals",
]


FANTASY_COLUMNS = [
    "player",
    "fantasy_points",
    "club",
    "position",
    "starts",
    "goals",
    "assists",
    "clean_sheets",
    "clean_sheet_parts",
    "yellow_cards",
    "red_cards",
    "substitute_named",
    "came_on",
    "taken_off",
    "penalties_saved",
    "penalties_missed",
    "goals_conceded",
    "conceded_one_plus",
    "own_goals",
]


CLEAN_SHEET_COLUMNS = [
    "player",
    "club",
    "nationality",
    "clean_sheets",
    "appearances",
    "clean_sheet_percentage",
]


HEADER_ALIASES = {
    "players": "player",
    "player": "player",
    "clubs": "club",
    "club": "club",
    "position": "position",
    "total": "appearances",
    "goals": "goals",
    "a": "assists",
    "assists": "assists",
    "start": "starts",
    "sub": "substitute_named",
    "co": "came_on",
    "off": "taken_off",
    "pen s": "penalties_scored",
    "pen sv": "penalties_saved",
    "pen m": "penalties_missed",
    "pen c": "penalties_conceded",
    "og": "own_goals",
    "points": "fantasy_points",
    "cs": "clean_sheets",
    "cs part": "clean_sheet_parts",
    "goals conceded": "goals_conceded",
    "conceded 1+": "conceded_one_plus",
    "nationality": "nationality",
    "pld": "appearances",
    "%": "clean_sheet_percentage",
}


NUMERIC_FIELDS = {
    "appearances",
    "goals",
    "assists",
    "yellow_cards",
    "second_yellow_cards",
    "red_cards",
    "starts",
    "substitute_named",
    "came_on",
    "taken_off",
    "penalties_scored",
    "penalties_saved",
    "penalties_missed",
    "penalties_conceded",
    "own_goals",
    "fantasy_points",
    "clean_sheets",
    "clean_sheet_parts",
    "goals_conceded",
    "conceded_one_plus",
}


CLUB_TOKEN_DROP = {
    "fc",
    "cf",
    "sc",
    "afc",
    "ac",
    "as",
    "bk",
    "fk",
    "sk",
    "cd",
    "rc",
    "osc",
    "club",
    "calcio",
    "de",
    "the",
}


CLUB_ALIASES = {
    "bayern munchen": "bayern munich",
    "borussia monchengladbach": "monchengladbach",
    "fc bayern munchen": "bayern munich",
    "fc internazionale milano": "inter milan",
    "internazionale": "inter milan",
    "inter": "inter milan",
    "manchester utd": "manchester united",
    "man utd": "manchester united",
    "newcastle utd": "newcastle united",
    "nottingham": "nottingham forest",
    "olympique de marseille": "marseille",
    "olympique lyonnais": "lyon",
    "paris saint germain": "psg",
    "paris saint germain fc": "psg",
    "psv eindhoven": "psv",
    "rb leipzig": "leipzig",
    "real betis balompie": "real betis",
    "real sociedad de futbol": "real sociedad",
    "sporting cp": "sporting lisbon",
    "sporting clube de portugal": "sporting lisbon",
    "tottenham": "tottenham hotspur",
    "west ham": "west ham united",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(text):
    text = html.unescape(str(text or ""))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_") or "unknown"


def compact_spaces(text):
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


def strip_club_country(club):
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", str(club or "")).strip()


def canonical_club_text(club):
    cleaned = norm(strip_club_country(club))
    return CLUB_ALIASES.get(cleaned, cleaned)


def text_tokens(text):
    return set(norm(text).split())


def club_tokens(club):
    return {token for token in text_tokens(canonical_club_text(club)) if token not in CLUB_TOKEN_DROP}


def name_score(left, right):
    left_tokens = text_tokens(left)
    right_tokens = text_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return max(0.86, overlap)
    compact_left = "".join(sorted(left_tokens))
    compact_right = "".join(sorted(right_tokens))
    if compact_left == compact_right:
        return max(0.96, overlap)
    return overlap


def club_score(left, right):
    left_tokens = club_tokens(left)
    right_tokens = club_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def source_name_counts(source_rows):
    counts = {}
    for row in source_rows:
        key = norm(row.get("player"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def parse_int(value):
    text = compact_spaces(value)
    if not text or text in {"-", "--", "---", "----", "-----"}:
        return 0
    text = text.replace(",", "")
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else 0


def parse_percent(value):
    text = compact_spaces(value).replace("%", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_div(numerator, denominator):
    return round(float(numerator) / denominator, 4) if denominator else None


def source_cache_path(url):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    parsed = urllib.parse.urlparse(url)
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"{parsed.path}_{parsed.query}").strip("_")[:100]
    return CACHE_DIR / f"{stem}_{digest}.html"


def request_headers():
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": STATBUNKER_BASE + "/",
        "Connection": "close",
    }


def polite_sleep(delay, jitter):
    if delay <= 0 and jitter <= 0:
        return
    time.sleep(max(0.0, delay + random.uniform(0, jitter)))


def fetch_url(url, args):
    cache_path = source_cache_path(url)
    if cache_path.exists() and not args.refresh_cache:
        return {"url": url, "from_cache": True, "body": cache_path.read_text(encoding="utf-8"), "error": None}
    if args.cache_only:
        return {"url": url, "from_cache": False, "body": None, "error": "cache miss"}

    req = urllib.request.Request(url, headers=request_headers())
    last_error = None
    for attempt in range(args.max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            cache_path.write_text(body, encoding="utf-8")
            polite_sleep(args.delay, args.jitter)
            return {"url": url, "from_cache": False, "body": body, "error": None}
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code in {429, 503} and attempt < args.max_retries:
                time.sleep(args.rate_limit_backoff * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt < args.max_retries:
                time.sleep(min(15.0, 2.0 * (attempt + 1)))
                continue
            break
    return {"url": url, "from_cache": False, "body": None, "error": last_error}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table_stack = []
        self.current_rows = None
        self.current_row = None
        self.current_cell = None
        self.current_links = None
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.table_stack.append(tag)
            if len(self.table_stack) == 1:
                self.current_rows = []
            return
        if not self.table_stack:
            return
        if tag == "tr" and self.current_rows is not None and len(self.table_stack) == 1:
            self.current_row = []
            return
        if tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = []
            self.current_links = []
            self.in_cell = True
            return
        if tag == "a" and self.in_cell and attrs.get("href"):
            self.current_links.append(attrs.get("href"))
            return
        if tag == "img" and self.in_cell:
            alt = attrs.get("alt") or attrs.get("title")
            if alt:
                self.current_cell.append(f" {alt} ")

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_cell:
            text = compact_spaces("".join(self.current_cell))
            self.current_row.append({"text": text, "links": list(self.current_links)})
            self.current_cell = None
            self.current_links = None
            self.in_cell = False
            return
        if tag == "tr" and self.current_row is not None:
            if any(cell["text"] for cell in self.current_row):
                self.current_rows.append(self.current_row)
            self.current_row = None
            return
        if tag == "table" and self.table_stack:
            self.table_stack.pop()
            if not self.table_stack and self.current_rows is not None:
                self.tables.append(self.current_rows)
                self.current_rows = None

    def handle_data(self, data):
        if self.in_cell and data:
            self.current_cell.append(data)


def parse_tables(markup):
    parser = TableParser()
    parser.feed(markup or "")
    return parser.tables


def header_key(text):
    cleaned = norm(text)
    cleaned = cleaned.replace("yellow card", "yellow cards")
    cleaned = cleaned.replace("red and yellow card", "second yellow cards")
    cleaned = cleaned.replace("red card", "red cards")
    return cleaned


def find_stat_table(tables, page_type):
    required = PAGE_TYPES[page_type]["required"]
    for table in tables:
        for header_index, row in enumerate(table[:8]):
            header_texts = [header_key(cell["text"]) for cell in row]
            header_set = set(header_texts)
            if required <= header_set or required <= set(" ".join(header_texts).split()):
                return header_texts, table[header_index + 1 :]
    return [], []


def positional_columns(page_type):
    if page_type == "overall":
        return OVERALL_COLUMNS
    if page_type == "fantasy":
        return FANTASY_COLUMNS
    if page_type == "clean_sheets":
        return CLEAN_SHEET_COLUMNS
    raise ValueError(f"Unknown page type: {page_type}")


def mapped_columns(headers, page_type, width):
    columns = []
    used = {}
    for header in headers[:width]:
        alias = HEADER_ALIASES.get(header, header.replace(" ", "_"))
        if not alias:
            alias = f"field_{len(columns)}"
        count = used.get(alias, 0)
        used[alias] = count + 1
        columns.append(alias if count == 0 else f"{alias}_{count + 1}")
    fallback = positional_columns(page_type)
    if len(columns) < min(width, 4) or "player" not in columns:
        columns = fallback[:width]
    if len(columns) < width:
        columns.extend(f"field_{index}" for index in range(len(columns), width))
    return columns[:width]


def normalize_row(row, columns, page_type, competition, source_url):
    cells = [cell["text"] for cell in row if compact_spaces(cell["text"]).lower() != "more"]
    if not cells:
        return None
    columns = mapped_columns(columns, page_type, len(cells))
    mapped = {}
    for column, value in zip(columns, cells):
        if column in NUMERIC_FIELDS:
            mapped[column] = parse_int(value)
        elif column == "clean_sheet_percentage":
            mapped[column] = parse_percent(value)
        else:
            mapped[column] = compact_spaces(value)

    player_name = mapped.get("player")
    if not player_name or norm(player_name) in {"players", "all positions"}:
        return None
    if not any(field in mapped for field in ["club", "position", "goals", "clean_sheets", "fantasy_points"]):
        return None

    mapped["competition"] = competition["name"]
    mapped["competition_key"] = competition["key"]
    mapped["competition_id"] = competition["comp_id"]
    mapped["season"] = competition["season"]
    mapped["competition_weight"] = competition.get("competition_weight", 1.0)
    mapped["page_type"] = page_type
    mapped["source_url"] = source_url
    return mapped


def parse_statbunker_page(markup, page_type, competition, source_url):
    headers, rows = find_stat_table(parse_tables(markup), page_type)
    parsed = []
    for row in rows:
        record = normalize_row(row, headers, page_type, competition, source_url)
        if record:
            parsed.append(record)
    return parsed


def parse_select_options(markup, select_name):
    match = re.search(
        r"<select[^>]+name=[\"']{}[\"'][^>]*>(.*?)</select>".format(re.escape(select_name)),
        markup or "",
        re.I | re.S,
    )
    if not match:
        return []
    options = []
    for option in re.finditer(r"<option([^>]*)>(.*?)</option>", match.group(1), re.I | re.S):
        attrs = option.group(1)
        value_match = re.search(r"value=[\"']?([^\"'\s>]+)", attrs, re.I)
        value = html.unescape(value_match.group(1)) if value_match else ""
        label = compact_spaces(re.sub(r"<.*?>", "", option.group(2)))
        selected = "selected" in attrs.lower()
        if value and value != "-1" and label:
            options.append({"value": value, "label": label, "selected": selected})
    return options


def selected_recent_competitions(options, limit=1):
    if not options:
        return []
    selected = []
    for term in RECENCY_TERMS:
        for option in options:
            if term in option["label"] and option not in selected:
                selected.append(option)
                if len(selected) >= limit:
                    return selected
    for option in options:
        if option["selected"] and option not in selected:
            selected.append(option)
            if len(selected) >= limit:
                return selected
    for option in options:
        if option not in selected:
            selected.append(option)
            if len(selected) >= limit:
                return selected
    return selected


def competition_type_url(comp_type, page_type="overall"):
    path = PAGE_TYPES[page_type]["path"]
    return f"{STATBUNKER_BASE}{path}?comp_type={urllib.parse.quote(comp_type)}"


def discover_competitions(args):
    competitions = []
    seen_ids = set()
    for comp_type in args.competition_types:
        url = competition_type_url(comp_type, "overall")
        fetched = fetch_url(url, args)
        if fetched["error"] or not fetched["body"]:
            print(f"discovery_error: {comp_type} ({fetched['error']})")
            continue
        options = selected_recent_competitions(parse_select_options(fetched["body"], "comp_id"), args.seasons_per_type)
        if not options:
            print(f"discovery_no_competition: {comp_type}")
            continue
        for option in options:
            try:
                comp_id = int(option["value"])
            except ValueError:
                continue
            if comp_id in seen_ids:
                continue
            seen_ids.add(comp_id)
            competitions.append(
                {
                    "key": slugify(f"{option['label']} {comp_type}"),
                    "name": option["label"],
                    "comp_id": comp_id,
                    "season": option["label"],
                    "competition_weight": 1.0,
                    "comp_type": comp_type,
                    "discovered": True,
                }
            )
    return competitions


def normalized_source_url(url):
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(STATBUNKER_BASE, html.unescape(url)))
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    ordered = urllib.parse.urlencode(sorted(query))
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", ordered, ""))


def page_links(markup, page_type, competition):
    path = PAGE_TYPES[page_type]["path"].lower()
    comp_id = str(competition["comp_id"])
    links = set()
    for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"']", markup or "", re.I):
        url = normalized_source_url(match.group(1))
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path.lower() != path.lower():
            continue
        if query.get("comp_id") != comp_id:
            continue
        if url != competition_url(competition, page_type):
            links.add(url)
    return links


def competition_url(competition, page_type):
    path = PAGE_TYPES[page_type]["path"]
    return normalized_source_url(f"{STATBUNKER_BASE}{path}?comp_id={competition['comp_id']}")


def selected_competitions(args):
    competitions = discover_competitions(args) if args.discover_competitions else list(DEFAULT_COMPETITIONS)
    if not competitions:
        competitions = list(DEFAULT_COMPETITIONS)
    if args.competitions:
        wanted = {norm(item) for part in args.competitions for item in part.split(",") if item.strip()}
        competitions = [
            comp
            for comp in competitions
            if norm(comp["key"]) in wanted or norm(comp["name"]) in wanted or str(comp["comp_id"]) in wanted
        ]
    if args.max_competitions is not None:
        competitions = competitions[: max(0, args.max_competitions)]
    return competitions


def selected_page_types(args):
    if not args.pages:
        return ["overall", "clean_sheets"]
    page_types = []
    for value in args.pages:
        page_types.extend(item.strip() for item in value.split(",") if item.strip())
    unknown = sorted(set(page_types) - set(PAGE_TYPES))
    if unknown:
        raise SystemExit(f"Unknown page type(s): {', '.join(unknown)}")
    return page_types


def fetch_source_rows(args):
    rows = []
    attempts = []
    competitions = selected_competitions(args)
    args._selected_competitions = competitions
    page_types = selected_page_types(args)
    for competition in competitions:
        for page_type in page_types:
            pending = [competition_url(competition, page_type)]
            seen_urls = set()
            page_count = 0
            total_rows = 0
            errors = []
            from_cache_count = 0
            while pending and page_count < args.max_pages_per_table:
                url = normalized_source_url(pending.pop(0))
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                fetched = fetch_url(url, args)
                page_count += 1
                if fetched["from_cache"]:
                    from_cache_count += 1
                if fetched["error"]:
                    errors.append({"url": url, "error": fetched["error"]})
                    continue
                if not fetched["body"]:
                    continue
                parsed = parse_statbunker_page(fetched["body"], page_type, competition, url)
                rows.extend(parsed)
                total_rows += len(parsed)
                for link in sorted(page_links(fetched["body"], page_type, competition)):
                    if link not in seen_urls and link not in pending:
                        pending.append(link)
            attempt = {
                "competition": competition["name"],
                "competition_key": competition["key"],
                "competition_id": competition["comp_id"],
                "page_type": page_type,
                "url": competition_url(competition, page_type),
                "page_count": page_count,
                "from_cache_count": from_cache_count,
                "status": "error" if errors and not total_rows else ("parsed" if total_rows else "no_rows"),
                "errors": errors,
                "row_count": total_rows,
            }
            attempts.append(attempt)
            print(
                f"{attempt['status']}: {competition['name']} {page_type} "
                f"({attempt['row_count']} rows, {attempt['page_count']} pages)"
            )
    deduped = {}
    for row in rows:
        key = (
            row.get("competition_key"),
            row.get("page_type"),
            norm(row.get("player")),
            norm(row.get("club")),
            row.get("position"),
        )
        if key not in deduped:
            deduped[key] = row
    return list(deduped.values()), attempts


def player_match_score(player, row, name_counts=None):
    player_name = player.get("name", "")
    row_name = row.get("player", "")
    ns = name_score(player_name, row_name)
    if len(text_tokens(player_name)) <= 1 and ns < 1.0:
        return 0.0

    cs = club_score(player.get("club"), row.get("club"))
    score = ns * 0.82 + cs * 0.18
    if ns >= 0.96:
        score = max(score, ns)
    if ns >= 0.99 and (name_counts or {}).get(norm(row_name), 0) == 1:
        score = max(score, 0.92)
    if ns >= 0.74 and cs >= 0.85:
        score = max(score, 0.86)
    if ns >= 0.86 and cs >= 0.5:
        score += 0.03
    if ns >= 0.86 and row.get("nationality") and norm(row.get("nationality")) == norm(player.get("country")):
        score += 0.03
    return round(min(score, 1.0), 4)


def scored_candidate_rows(player, source_rows, threshold, name_counts=None):
    candidates = []
    for row in source_rows:
        score = player_match_score(player, row, name_counts)
        if score >= threshold:
            enriched = dict(row)
            enriched["source_match_score"] = score
            enriched["source_name_score"] = name_score(player.get("name"), row.get("player"))
            enriched["source_club_score"] = club_score(player.get("club"), row.get("club"))
            enriched["manifest_name"] = player["name"]
            enriched["manifest_club"] = player.get("club")
            candidates.append(enriched)
    return sorted(candidates, key=lambda item: item["source_match_score"], reverse=True)


def candidate_rows(player, source_rows, threshold, name_counts=None):
    candidates = scored_candidate_rows(player, source_rows, threshold, name_counts)
    return best_rows_by_source(candidates)


def best_rows_by_source(candidates):
    best_by_source = {}
    for row in candidates:
        key = (row["competition_key"], row["page_type"])
        if key not in best_by_source or row["source_match_score"] > best_by_source[key]["source_match_score"]:
            best_by_source[key] = row
    return sorted(best_by_source.values(), key=lambda item: (item["competition_key"], item["page_type"]))


def review_candidates(player, source_rows, args, name_counts=None, scored_candidates=None):
    candidates = scored_candidates
    if candidates is None:
        candidates = scored_candidate_rows(player, source_rows, args.review_threshold, name_counts)
    slim = []
    for row in candidates[: args.max_review_candidates]:
        slim.append(
            {
                "source_match_score": row["source_match_score"],
                "source_name_score": row["source_name_score"],
                "source_club_score": row["source_club_score"],
                "player": row.get("player"),
                "club": row.get("club"),
                "competition": row.get("competition"),
                "page_type": row.get("page_type"),
                "appearances": row.get("appearances"),
                "goals": row.get("goals"),
                "assists": row.get("assists"),
                "source_url": row.get("source_url"),
            }
        )
    return slim


def sum_field(rows, field, page_type="overall"):
    return sum(int(row.get(field) or 0) for row in rows if row.get("page_type") == page_type)


def weighted_sum_field(rows, field, page_type="overall"):
    return round(
        sum((row.get(field) or 0) * float(row.get("competition_weight", 1.0)) for row in rows if row.get("page_type") == page_type),
        3,
    )


def aggregate_stats(matches):
    overall_rows = [row for row in matches if row["page_type"] == "overall"]
    fantasy_rows = [row for row in matches if row["page_type"] == "fantasy"]
    clean_rows = [row for row in matches if row["page_type"] == "clean_sheets"]
    appearances = sum_field(overall_rows, "appearances")
    starts = sum_field(overall_rows, "starts")
    goals = sum_field(overall_rows, "goals")
    assists = sum_field(overall_rows, "assists")
    yellow_cards = sum_field(overall_rows, "yellow_cards")
    red_cards = sum_field(overall_rows, "red_cards") + sum_field(overall_rows, "second_yellow_cards")
    own_goals = sum_field(overall_rows, "own_goals")
    clean_sheets = sum(row.get("clean_sheets") or 0 for row in clean_rows)
    goalkeeper_appearances = sum(row.get("appearances") or 0 for row in clean_rows)

    competitions = sorted({row["competition"] for row in matches})
    return {
        "source_match_count": len(matches),
        "competitions": competitions,
        "appearances": appearances,
        "starts": starts,
        "goals": goals,
        "assists": assists,
        "goal_contributions": goals + assists,
        "yellow_cards": yellow_cards,
        "red_cards": red_cards,
        "own_goals": own_goals,
        "penalties_scored": sum_field(overall_rows, "penalties_scored"),
        "penalties_missed": sum_field(overall_rows, "penalties_missed"),
        "penalties_saved": sum_field(overall_rows, "penalties_saved"),
        "penalties_conceded": sum_field(overall_rows, "penalties_conceded"),
        "weighted_goals": weighted_sum_field(overall_rows, "goals"),
        "weighted_assists": weighted_sum_field(overall_rows, "assists"),
        "fantasy_points": sum(row.get("fantasy_points") or 0 for row in fantasy_rows),
        "clean_sheets": clean_sheets,
        "goalkeeper_clean_sheet_appearances": goalkeeper_appearances,
        "per_appearance": {
            "goals": safe_div(goals, appearances),
            "assists": safe_div(assists, appearances),
            "goal_contributions": safe_div(goals + assists, appearances),
            "cards": safe_div(yellow_cards + red_cards, appearances),
        },
        "goalkeeper_clean_sheet_rate": safe_div(clean_sheets, goalkeeper_appearances),
    }


def derived_scores(summary, player):
    appearances = summary["appearances"]
    goal_contribution_rate = summary["per_appearance"]["goal_contributions"] or 0.0
    card_rate = summary["per_appearance"]["cards"] or 0.0
    availability = min(1.0, appearances / 30.0)
    attacking = min(1.5, goal_contribution_rate * 2.5)
    goalkeeper = summary["goalkeeper_clean_sheet_rate"]
    confidence = min(1.0, (summary["source_match_count"] / 3.0) * 0.35 + availability * 0.65)
    return {
        "availability_score": round(availability, 4),
        "attacking_output_score": round(attacking, 4),
        "discipline_risk_score": round(min(1.0, card_rate * 2.0), 4),
        "goalkeeper_clean_sheet_score": round(goalkeeper, 4) if goalkeeper is not None else None,
        "free_data_confidence": round(confidence, 4),
        "notes": [
            "StatBunker does not provide SofaScore-style match ratings in these public tables.",
            "Scores are simple normalizations of appearances, goal output, discipline, and goalkeeper clean sheets.",
        ],
    }


def empty_record(player, status, reason=None):
    record = {
        "player_key": player["player_key"],
        "country": player["country"],
        "name": player["name"],
        "club": player.get("club"),
        "position": player.get("position"),
        "official_position": player.get("official_position"),
        "eafc_rating": player.get("eafc_rating"),
        "collection_status": status,
        "sources": {},
        "statbunker_summary": {},
        "derived_scores": {},
    }
    if reason:
        record["reason"] = reason
    return record


def collect_player(player, source_rows, source_reachable, args, name_counts=None):
    if not source_reachable:
        return empty_record(player, "primary_source_unreachable", "StatBunker pages could not be fetched.")
    scored = scored_candidate_rows(player, source_rows, args.review_threshold, name_counts)
    matches = best_rows_by_source([row for row in scored if row["source_match_score"] >= args.identity_threshold])
    if not matches:
        record = empty_record(player, "identity_not_matched", "No confident StatBunker name/club match.")
        review = review_candidates(player, source_rows, args, name_counts, scored)
        if review:
            record["review_candidates"] = review
        return record
    top_match = max(matches, key=lambda row: row["source_match_score"])
    top_score = top_match["source_match_score"]
    near_top = [
        row
        for row in matches
        if top_score - row["source_match_score"] <= args.ambiguity_margin
        and norm(row.get("club")) != norm(top_match.get("club"))
    ]
    if len(near_top) > 1 and top_score < args.high_confidence_threshold:
        record = empty_record(player, "identity_ambiguous", "Multiple plausible StatBunker candidates.")
        record["review_candidates"] = review_candidates(player, source_rows, args, name_counts, scored)
        return record
    summary = aggregate_stats(matches)
    return {
        "player_key": player["player_key"],
        "country": player["country"],
        "name": player["name"],
        "club": player.get("club"),
        "position": player.get("position"),
        "official_position": player.get("official_position"),
        "eafc_rating": player.get("eafc_rating"),
        "collection_status": "stats_collected",
        "sources": {"statbunker": matches},
        "statbunker_summary": summary,
        "derived_scores": derived_scores(summary, player),
    }


def build_metadata(args, players, source_rows, attempts):
    counts = {}
    for attempt in attempts:
        counts[attempt["status"]] = counts.get(attempt["status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "source_manifest": Path(args.manifest).name,
        "source": "StatBunker public football player tables",
        "source_url": STATBUNKER_BASE,
        "output_player_count": len(players),
        "source_row_count": len(source_rows),
        "page_types": selected_page_types(args),
        "competitions": getattr(args, "_selected_competitions", []),
        "source_attempt_status_counts": dict(sorted(counts.items())),
        "rate_limit_policy": {
            "delay_seconds": args.delay,
            "jitter_seconds": args.jitter,
            "max_retries": args.max_retries,
        },
        "limitations": [
            "This is a free fallback source with competition aggregate tables, not a full event or ratings provider.",
            "Minutes, xG, xA, progressive passing, tackles, saves, and match ratings are not available from the default public pages.",
            "Player identity matching is based on name, club, and nationality where present; ambiguous names should be reviewed.",
        ],
        "source_attempts": attempts,
    }


def selected_players(players, start, limit):
    end = None if limit is None else start + limit
    return players[start:end]


def write_output(args, players, source_rows, attempts, records):
    payload = {
        "metadata": build_metadata(args, players, source_rows, attempts),
        "players": records,
    }
    counts = {}
    for record in records:
        counts[record["collection_status"]] = counts.get(record["collection_status"], 0) + 1
    payload["metadata"]["collection_status_counts"] = dict(sorted(counts.items()))
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_review_output(args, records):
    review_rows = []
    for record in records:
        if record.get("review_candidates"):
            review_rows.append(
                {
                    "player_key": record.get("player_key"),
                    "country": record.get("country"),
                    "name": record.get("name"),
                    "club": record.get("club"),
                    "position": record.get("position"),
                    "collection_status": record.get("collection_status"),
                    "reason": record.get("reason"),
                    "candidates": record.get("review_candidates"),
                }
            )
    payload = {
        "metadata": {
            "created_at": now_iso(),
            "source_output": Path(args.output).name,
            "review_player_count": len(review_rows),
            "notes": [
                "These are near-threshold or ambiguous StatBunker candidates.",
                "They are not auto-applied unless the confidence rule marks them as matched.",
            ],
        },
        "players": review_rows,
    }
    Path(args.review_output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def self_test():
    competition = DEFAULT_COMPETITIONS[0]
    markup = """
    <table>
      <thead><tr><th>Players</th><th>Clubs</th><th>Position</th><th>Total</th><th>Goals</th><th>A</th>
      <th>Yellow Card</th><th>Red and Yellow Card</th><th>Red Card</th><th>Start</th><th>Sub</th><th>CO</th>
      <th>Off</th><th>Pen S</th><th>Pen SV</th><th>Pen M</th><th>Pen C</th><th>OG</th><th>More</th></tr></thead>
      <tbody><tr><td>Example Forward</td><td>Arsenal</td><td>Forward</td><td>30</td><td>12</td><td>5</td>
      <td>2</td><td>0</td><td>0</td><td>28</td><td>2</td><td>2</td><td>10</td><td>1</td><td>0</td><td>1</td><td>0</td><td>0</td><td>More</td></tr></tbody>
    </table>
    """
    rows = parse_statbunker_page(markup, "overall", competition, "https://example.test")
    assert rows and rows[0]["player"] == "Example Forward"
    assert rows[0]["appearances"] == 30 and rows[0]["goals"] == 12 and rows[0]["assists"] == 5
    player = {"name": "Example Forward", "club": "Arsenal (ENG)", "country": "Exampleland"}
    assert player_match_score(player, rows[0]) >= 0.95
    print("self-test passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_FILE))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    parser.add_argument("--review-output", default=str(REVIEW_FILE))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--competitions", action="append", help="Comma-separated competition keys, names, or IDs.")
    parser.add_argument(
        "--competition-types",
        action="append",
        default=None,
        help="Comma-separated StatBunker competition type codes to discover.",
    )
    parser.add_argument("--no-discover-competitions", dest="discover_competitions", action="store_false")
    parser.set_defaults(discover_competitions=True)
    parser.add_argument("--seasons-per-type", type=int, default=2)
    parser.add_argument("--max-competitions", type=int, default=None)
    parser.add_argument("--max-pages-per-table", type=int, default=12)
    parser.add_argument("--pages", action="append", default=None)
    parser.add_argument("--identity-threshold", type=float, default=0.82)
    parser.add_argument("--review-threshold", type=float, default=0.68)
    parser.add_argument("--max-review-candidates", type=int, default=8)
    parser.add_argument("--ambiguity-margin", type=float, default=0.04)
    parser.add_argument("--high-confidence-threshold", type=float, default=0.94)
    parser.add_argument("--delay", type=float, default=6.0)
    parser.add_argument("--jitter", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--rate-limit-backoff", type=float, default=90.0)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.competition_types:
        args.competition_types = [
            item.strip()
            for part in args.competition_types
            for item in part.split(",")
            if item.strip()
        ]
    else:
        args.competition_types = list(DEFAULT_COMPETITION_TYPES)

    if args.self_test:
        self_test()
        return

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    players = selected_players(manifest["players"], args.start, args.limit)
    source_rows, attempts = fetch_source_rows(args)
    source_reachable = any(attempt["status"] in {"parsed", "no_rows"} for attempt in attempts)
    name_counts = source_name_counts(source_rows)

    records = [collect_player(player, source_rows, source_reachable, args, name_counts) for player in players]
    write_output(args, players, source_rows, attempts, records)
    write_review_output(args, records)
    print(f"wrote {args.output}")
    print(f"wrote {args.review_output}")


if __name__ == "__main__":
    main()
