import argparse
import base64
import hashlib
import html
import http.cookiejar
import json
import math
import random
import re
import ssl
import subprocess
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
CONFIG_FILE = ROOT / "performance_data_config.json"
OUTPUT_FILE = ROOT / "player_performance_data.json"
CACHE_DIR = ROOT / ".cache" / "performance_sources"
CA_BUNDLE_FILE = ROOT / ".cache" / "windows_root_ca_bundle.pem"
BROWSER_PROFILE_DIR = ROOT / ".cache" / "browser_profile"
SCHEMA_VERSION = 2


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 FIFA26WCResearch/0.3"
)
API_BASES = [
    "https://www.sofascore.com/api/v1",
    "https://api.sofascore.com/api/v1",
]
BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


COMPLETED_STATUSES = {
    "stats_collected",
    "profile_collected",
    "identity_matched_stats_unavailable",
}


class SourceUnavailable(RuntimeError):
    pass


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "td", "th"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "td", "th"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())
            self.parts.append(" ")

    def text(self):
        compact_lines = []
        for line in "".join(self.parts).splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                compact_lines.append(line)
        return "\n".join(compact_lines)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", norm(text)).strip("-")


def strip_club_country(club):
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", club or "").strip()


def name_score(left, right):
    left_tokens = set(norm(left).split())
    right_tokens = set(norm(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    compact_left = "".join(sorted(left_tokens))
    compact_right = "".join(sorted(right_tokens))
    if compact_left == compact_right:
        return max(0.96, overlap)
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return max(0.86, overlap)
    return overlap


def source_cache_path(url, suffix):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    parsed = urllib.parse.urlparse(url)
    stem = f"{parsed.netloc}{parsed.path}_{parsed.query}"
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "_", stem).strip("_")[:95]
    return CACHE_DIR / f"{stem}_{digest}.{suffix}"


def polite_sleep(delay_seconds, jitter_seconds):
    if delay_seconds <= 0 and jitter_seconds <= 0:
        return
    time.sleep(max(0.0, delay_seconds + random.uniform(0, jitter_seconds)))


def request_headers(accept, url=None):
    is_json = "json" in accept
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.sofascore.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "close",
    }
    if is_json:
        headers.update(
            {
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }
        )
    else:
        headers.update(
            {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Upgrade-Insecure-Requests": "1",
            }
        )
    return headers


def make_url_opener(args):
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=args.ssl_context),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )


def warm_up_sofascore_session(args):
    if args.skip_session_warmup:
        return
    try:
        req = urllib.request.Request(
            "https://www.sofascore.com/",
            headers=request_headers("text/html,application/xhtml+xml,*/*", "https://www.sofascore.com/"),
        )
        with args.opener.open(req, timeout=min(args.timeout, 20)) as response:
            response.read(512)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def build_windows_ca_bundle():
    if not hasattr(ssl, "enum_certificates"):
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CA_BUNDLE_FILE.exists():
        return CA_BUNDLE_FILE
    pem_parts = []
    seen = set()
    for store_name in ("ROOT", "CA"):
        try:
            certs = ssl.enum_certificates(store_name)
        except OSError:
            continue
        for cert_bytes, encoding, trust in certs:
            if encoding != "x509_asn" or cert_bytes in seen:
                continue
            if trust is not True and isinstance(trust, set) and "1.3.6.1.5.5.7.3.1" not in trust:
                continue
            seen.add(cert_bytes)
            pem_parts.append(ssl.DER_cert_to_PEM_cert(cert_bytes))
    if not pem_parts:
        return None
    CA_BUNDLE_FILE.write_text("\n".join(pem_parts), encoding="ascii")
    return CA_BUNDLE_FILE


def make_ssl_context(args):
    if args.allow_insecure_tls:
        return ssl._create_unverified_context()
    ca_bundle = build_windows_ca_bundle()
    if ca_bundle:
        return ssl.create_default_context(cafile=str(ca_bundle))
    return ssl.create_default_context()


def detect_browser_path():
    for path in BROWSER_CANDIDATES:
        if path.exists():
            return path
    return None


def fetch_html_with_browser(url, args):
    if args.no_browser_html or not args.browser_path:
        return {"url": url, "from_cache": False, "body": None, "error": "browser HTML fallback disabled"}
    cache_path = source_cache_path(url + "#browser", "html")
    if cache_path.exists() and not args.refresh_cache:
        return {
            "url": url,
            "from_cache": True,
            "body": cache_path.read_text(encoding="utf-8"),
            "error": None,
        }
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.browser_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={BROWSER_PROFILE_DIR}",
        "--dump-dom",
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.browser_timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"url": url, "from_cache": False, "body": None, "error": str(exc)}
    if result.returncode != 0 and not result.stdout.strip():
        return {"url": url, "from_cache": False, "body": None, "error": (result.stderr or "").strip()}
    body = result.stdout
    if body.strip():
        cache_path.write_text(body, encoding="utf-8")
        polite_sleep(args.delay, args.jitter)
        return {"url": url, "from_cache": False, "body": body, "error": None}
    return {"url": url, "from_cache": False, "body": None, "error": "browser returned empty page"}


def fetch_url(url, *, accept, suffix, args):
    cache_path = source_cache_path(url, suffix)
    if cache_path.exists() and not args.refresh_cache:
        return {
            "url": url,
            "from_cache": True,
            "body": cache_path.read_text(encoding="utf-8"),
            "error": None,
        }

    errors = []
    for attempt in range(args.max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=request_headers(accept, url))
            with args.opener.open(req, timeout=args.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            cache_path.write_text(body, encoding="utf-8")
            polite_sleep(args.delay, args.jitter)
            return {"url": url, "from_cache": False, "body": body, "error": None}
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code}: {exc.reason}")
            if exc.code == 429 and attempt < args.max_retries:
                retry_after = exc.headers.get("Retry-After")
                wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else args.rate_limit_backoff
                time.sleep(wait_seconds * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(str(exc))
            if attempt < args.max_retries:
                time.sleep(min(30.0, 2.0 * (attempt + 1)))
                continue
            break

    return {"url": url, "from_cache": False, "body": None, "error": "; ".join(errors)}


def fetch_json(url, args):
    fetched = fetch_url(url, accept="application/json,text/plain,*/*", suffix="json", args=args)
    if fetched["error"]:
        return {"data": None, "error": fetched["error"], "url": url}
    try:
        return {"data": json.loads(fetched["body"]), "error": None, "url": url}
    except json.JSONDecodeError as exc:
        return {"data": None, "error": f"invalid JSON: {exc}", "url": url}


def fetch_html(url, args):
    fetched = fetch_url(url, accept="text/html,application/xhtml+xml,*/*", suffix="html", args=args)
    if not fetched["error"]:
        return {"html": fetched["body"], "error": None, "url": url}
    browser_fetched = fetch_html_with_browser(url, args)
    if not browser_fetched["error"]:
        return {"html": browser_fetched["body"], "error": None, "url": url}
    return {
        "html": None,
        "error": f"{fetched['error']} | browser fallback: {browser_fetched['error']}",
        "url": url,
    }


def flatten_search_results(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    candidates = []
    for key in ["results", "entities", "players", "data", "items"]:
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.extend(flatten_search_results(value))
    for value in data.values():
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            nested_type = str(value.get("type") or value.get("entityType") or "").lower()
            if "player" in nested_type or {"id", "name"} <= set(value.keys()):
                candidates.append(value)
    return candidates


def candidate_country(entity):
    country = entity.get("country") or entity.get("nationality")
    if isinstance(country, dict):
        return country.get("name") or country.get("alpha2") or country.get("slug")
    return country


def candidate_team(entity):
    team = entity.get("team")
    if isinstance(team, dict):
        return team.get("name") or team.get("shortName")
    return entity.get("teamName") or entity.get("team")


def extract_sofascore_player_candidate(item):
    if not isinstance(item, dict):
        return None
    entity = item.get("entity") if isinstance(item.get("entity"), dict) else item.get("player")
    if not isinstance(entity, dict):
        entity = item
    entity_type = str(item.get("type") or entity.get("type") or entity.get("entityType") or "").lower()
    if entity_type and "player" not in entity_type and entity.get("position") is None:
        return None
    player_id = entity.get("id") or entity.get("playerId")
    name = entity.get("name") or entity.get("shortName") or entity.get("displayName")
    if not player_id or not name:
        return None
    slug = entity.get("slug") or slugify(str(name))
    return {
        "id": int(player_id) if str(player_id).isdigit() else player_id,
        "name": name,
        "slug": slug,
        "team": candidate_team(entity),
        "country": candidate_country(entity),
        "position": entity.get("position"),
        "url": f"https://www.sofascore.com/football/player/{slug}/{player_id}",
    }


def score_candidate(player, candidate):
    score = name_score(player["name"], candidate["name"])
    player_country = norm(player.get("country"))
    candidate_nation = norm(candidate.get("country"))
    if player_country and candidate_nation:
        if player_country == candidate_nation:
            score += 0.08
        elif player_country in candidate_nation or candidate_nation in player_country:
            score += 0.04
    player_club = norm(strip_club_country(player.get("club")))
    candidate_club = norm(candidate.get("team"))
    if player_club and candidate_club and (player_club in candidate_club or candidate_club in player_club):
        score += 0.06
    return min(score, 1.0)


def candidate_from_profile_url(url):
    decoded = html.unescape(urllib.parse.unquote(url))
    match = re.search(r"https?://(?:www\.)?sofascore\.com/football/player/([^/?#\"'<>\s]+)/(\d+)", decoded)
    if not match:
        return None
    slug, player_id = match.groups()
    name = re.sub(r"[-_]+", " ", slug).strip().title()
    return {
        "id": int(player_id),
        "name": name,
        "slug": slug,
        "team": None,
        "country": None,
        "position": None,
        "url": f"https://www.sofascore.com/football/player/{slug}/{player_id}",
    }


def decode_search_redirect(value):
    value = urllib.parse.unquote(html.unescape(value or ""))
    if value.startswith("http"):
        return value
    if value.startswith("a1"):
        value = value[2:]
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("utf-8", errors="ignore")
    except (ValueError, OSError):
        return value
    return decoded


def extract_sofascore_profile_candidates(markup):
    candidates = []
    seen = set()
    for raw_url in re.findall(r"https?://(?:www\.)?sofascore\.com/football/player/[^\"'<>\s)]+/\d+", markup or ""):
        candidate = candidate_from_profile_url(raw_url)
        if candidate and candidate["url"] not in seen:
            seen.add(candidate["url"])
            candidates.append(candidate)
    for encoded in re.findall(r"[?&](?:uddg|url|u)=([^&\"'<>]+)", markup or ""):
        candidate = candidate_from_profile_url(decode_search_redirect(encoded))
        if candidate and candidate["url"] not in seen:
            seen.add(candidate["url"])
            candidates.append(candidate)
    return candidates


def web_search_urls(player):
    club = strip_club_country(player.get("club"))
    queries = [
        f'site:sofascore.com/football/player "{player["name"]}"',
        f'site:sofascore.com/football/player "{player["name"]}" "{player.get("country", "")}"',
    ]
    if club:
        queries.append(f'site:sofascore.com/football/player "{player["name"]}" "{club}"')
    urls = []
    for query in dict.fromkeys(queries):
        quoted = urllib.parse.quote(query)
        urls.append(f"https://duckduckgo.com/html/?q={quoted}")
        urls.append(f"https://www.bing.com/search?q={quoted}")
    return urls


def search_sofascore_player_web(player, args):
    best = None
    best_score = 0.0
    errors = []
    reached_source = False
    for url in web_search_urls(player):
        result = fetch_html(url, args)
        if result["error"]:
            errors.append({"url": url, "error": result["error"]})
            continue
        reached_source = True
        for candidate in extract_sofascore_profile_candidates(result["html"]):
            current_score = score_candidate(player, candidate)
            if current_score > best_score:
                best = candidate
                best_score = current_score
        if best_score >= 0.92:
            break

    if best and best_score >= args.identity_threshold:
        best["match_score"] = round(best_score, 3)
        best["discovery_source"] = "web_search"
        return {"status": "matched", "candidate": best, "errors": errors}
    if errors and all("HTTP 403" in error.get("error", "") for error in errors):
        status = "search_source_forbidden"
    else:
        status = "not_matched" if reached_source else "search_source_unreachable"
    return {"status": status, "candidate": None, "errors": errors}


def search_sofascore_player_api(player, args):
    queries = [player["name"]]
    if player.get("country"):
        queries.append(f"{player['name']} {player['country']}")
    best = None
    best_score = 0.0
    errors = []
    reached_source = False

    for query in dict.fromkeys(queries):
        quoted = urllib.parse.quote(query)
        for base in API_BASES:
            url = f"{base}/search/all?q={quoted}"
            result = fetch_json(url, args)
            if result["error"]:
                errors.append({"url": url, "error": result["error"]})
                continue
            reached_source = True
            for item in flatten_search_results(result["data"]):
                candidate = extract_sofascore_player_candidate(item)
                if not candidate:
                    continue
                current_score = score_candidate(player, candidate)
                if current_score > best_score:
                    best = candidate
                    best_score = current_score
            break
        if best_score >= 0.98:
            break

    if best and best_score >= args.identity_threshold:
        best["match_score"] = round(best_score, 3)
        best["discovery_source"] = "sofascore_api"
        return {"status": "matched", "candidate": best, "errors": errors}
    if errors and all("HTTP 403" in error.get("error", "") for error in errors):
        status = "source_forbidden"
    else:
        status = "not_matched" if reached_source else "source_unreachable"
    return {
        "status": status,
        "candidate": None,
        "errors": errors,
    }


def search_sofascore_player(player, args):
    modes = [args.discovery_mode]
    attempts = {}
    for mode in modes:
        result = search_sofascore_player_web(player, args) if mode == "web" else search_sofascore_player_api(player, args)
        attempts[mode] = {"status": result["status"], "errors": result["errors"]}
        if result["candidate"]:
            result["attempts"] = attempts
            return result
    last = result
    last["attempts"] = attempts
    return last


def html_to_text(markup):
    parser = VisibleTextParser()
    parser.feed(markup or "")
    return html.unescape(parser.text())


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_regex(pattern, text, flags=0, group=1):
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return match.group(group).strip()


def parse_competition_appearances(text):
    appearances = []
    seen = set()
    pattern = r"([A-Z][A-Za-z0-9 .&'()/+-]{2,70}?)\s+(\d+)\s+appearances?"
    for match in re.finditer(pattern, text):
        competition = re.sub(r"^(Injured|Suspended|Doubtful|Questionable)\s+", "", match.group(1)).strip()
        competition = re.sub(r"^(Show more|Loading|Matches)\s+", "", competition).strip()
        markers = [
            "Preferred foot",
            "Position",
            "Shirt number",
            "Number",
            "Market value",
            "Injured",
            "Suspended",
            "Doubtful",
            "Questionable",
        ]
        changed = True
        while changed:
            changed = False
            for marker in markers:
                if marker in competition:
                    competition = competition.split(marker, 1)[1].strip()
                    changed = True
        if len(competition) < 3 or "Summary" in competition:
            continue
        key = norm(competition)
        if key in seen:
            continue
        seen.add(key)
        appearances.append({"competition": competition, "appearances": int(match.group(2))})
    return appearances


def parse_profile_page(markup, url):
    text = html_to_text(markup)
    compact = re.sub(r"\s+", " ", text)
    title = first_regex(r"<title>(.*?)</title>", markup or "", re.I | re.S)
    profile = {
        "source_url": url,
        "page_title": html.unescape(re.sub(r"\s+", " ", title).strip()) if title else None,
        "summary_last_12_months_rating": parse_float(
            first_regex(r"Summary \(last 12 months\)\s+([0-9](?:\.[0-9])?)", compact)
        ),
        "last_match_rating": parse_float(
            first_regex(r"received\s+([0-9](?:\.[0-9])?)\s+Sofascore rating", compact, re.I)
        ),
        "last_match_text": first_regex(r"Last player match was\s+(.+?)\s+and\s+.+?received", compact, re.I),
        "height_cm": parse_int(first_regex(r"Height\s+(\d+)\s*cm", compact, re.I)),
        "preferred_foot": first_regex(r"Preferred foot\s+(Right|Left|Both)", compact, re.I),
        "broad_position": first_regex(r"Position\s+([A-Z]{1,3})\b", compact),
        "shirt_number": parse_int(first_regex(r"(?:Shirt number|Number)\s+(\d+)", compact, re.I)),
        "market_value": first_regex(r"Market value\s+([0-9.]+[MK]?\s*(?:EUR|\u20ac))", compact, re.I),
        "competition_appearances": parse_competition_appearances(text),
    }
    return {key: value for key, value in profile.items() if value not in (None, [], "")}


def fetch_sofascore_api_path(path, args):
    path = path if path.startswith("/") else f"/{path}"
    errors = []
    for base in API_BASES:
        result = fetch_json(f"{base}{path}", args)
        if result["error"]:
            errors.append({"url": result["url"], "error": result["error"]})
            continue
        return {"data": result["data"], "errors": errors, "url": result["url"]}
    return {"data": None, "errors": errors, "url": None}


def fetch_player_api_profile(player_id, args):
    result = fetch_sofascore_api_path(f"/player/{player_id}", args)
    if not result["data"]:
        return {"profile": None, "errors": result["errors"]}
    data = result["data"].get("player") if isinstance(result["data"], dict) else result["data"]
    if not isinstance(data, dict):
        return {"profile": None, "errors": result["errors"]}
    profile = {
        "source_url": result["url"],
        "id": data.get("id"),
        "name": data.get("name") or data.get("shortName"),
        "slug": data.get("slug"),
        "position": data.get("position"),
        "country": candidate_country(data),
        "team": candidate_team(data),
        "date_of_birth_timestamp": data.get("dateOfBirthTimestamp"),
        "height": data.get("height"),
        "preferred_foot": data.get("preferredFoot"),
        "shirt_number": data.get("jerseyNumber"),
    }
    return {"profile": {k: v for k, v in profile.items() if v is not None}, "errors": result["errors"]}


def fetch_recent_events(player_id, args):
    events = []
    errors = []
    seen = set()
    for page in range(args.recent_event_pages):
        result = fetch_sofascore_api_path(f"/player/{player_id}/events/last/{page}", args)
        errors.extend(result["errors"])
        data = result["data"]
        if not isinstance(data, dict):
            continue
        page_events = data.get("events") or data.get("data") or []
        if not isinstance(page_events, list):
            continue
        for event in page_events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            events.append(event)
    events.sort(key=lambda item: item.get("startTimestamp") or 0, reverse=True)
    return {"events": events, "errors": errors}


def scalar_stats(data):
    if not isinstance(data, dict):
        return {}
    stats = data.get("statistics") if isinstance(data.get("statistics"), dict) else data
    flattened = {}
    for key, value in stats.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flattened[key] = value
        elif isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, (str, int, float, bool)) or nested_value is None:
                    flattened[f"{key}.{nested_key}"] = nested_value
    return flattened


def extract_rating_from_stats(stats):
    flattened = scalar_stats(stats)
    for key in ["rating", "averageRating", "sofaScoreRating", "totalRating"]:
        value = parse_float(flattened.get(key))
        if value is not None:
            return value
    return None


def event_team_name(event, side):
    team = event.get(f"{side}Team")
    if isinstance(team, dict):
        return team.get("name") or team.get("shortName")
    return None


def event_competition(event):
    tournament = event.get("tournament") if isinstance(event.get("tournament"), dict) else {}
    unique = tournament.get("uniqueTournament") if isinstance(tournament.get("uniqueTournament"), dict) else {}
    return unique.get("name") or tournament.get("name")


def event_context(event):
    tournament = event.get("tournament") if isinstance(event.get("tournament"), dict) else {}
    unique = tournament.get("uniqueTournament") if isinstance(tournament.get("uniqueTournament"), dict) else {}
    season = event.get("season") if isinstance(event.get("season"), dict) else {}
    if not unique.get("id") or not season.get("id"):
        return None
    return {
        "unique_tournament_id": unique.get("id"),
        "unique_tournament": unique.get("name"),
        "season_id": season.get("id"),
        "season": season.get("name") or season.get("year"),
    }


def stage_key(event):
    round_info = event.get("roundInfo") if isinstance(event.get("roundInfo"), dict) else {}
    text = norm(" ".join(str(x) for x in [round_info.get("name"), round_info.get("round"), event_competition(event)] if x))
    if "final" in text and "semi" not in text:
        return "final"
    if "semi" in text:
        return "semi_final"
    if "quarter" in text:
        return "quarter_final"
    if "round of 16" in text or "last 16" in text:
        return "round_of_16"
    if "round of 32" in text or "last 32" in text:
        return "round_of_32"
    return "league_or_group"


def competition_key(name):
    text = norm(name)
    if "friendly" in text and "club" in text:
        return "club_friendly"
    if "friendly" in text:
        return "international_friendly"
    if ("world cup" in text or "world championship" in text) and "qual" not in text:
        return "world_cup"
    if "qual" in text and ("world" in text or "wc" in text):
        return "world_cup_qualifier"
    if "champions league" in text:
        return "champions_league"
    if any(token in text for token in ["laliga", "premier league", "bundesliga", "serie a", "ligue 1"]):
        return "top_five_league"
    if any(token in text for token in ["cup", "copa", "pokal"]):
        return "domestic_cup"
    return "domestic_league"


def compact_event(event, stats=None):
    timestamp = event.get("startTimestamp")
    start_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat() if timestamp else None
    round_info = event.get("roundInfo") if isinstance(event.get("roundInfo"), dict) else {}
    status = event.get("status") if isinstance(event.get("status"), dict) else {}
    row = {
        "event_id": event.get("id"),
        "date": start_date,
        "competition": event_competition(event),
        "season": (event.get("season") or {}).get("name") if isinstance(event.get("season"), dict) else None,
        "round": round_info.get("name") or round_info.get("round"),
        "stage_key": stage_key(event),
        "home_team": event_team_name(event, "home"),
        "away_team": event_team_name(event, "away"),
        "home_score": (event.get("homeScore") or {}).get("current") if isinstance(event.get("homeScore"), dict) else None,
        "away_score": (event.get("awayScore") or {}).get("current") if isinstance(event.get("awayScore"), dict) else None,
        "status": status.get("type") or status.get("description"),
        "rating": extract_rating_from_stats(stats) if stats else None,
        "statistics": scalar_stats(stats) if stats else {},
    }
    return {key: value for key, value in row.items() if value not in (None, {}, "")}


def fetch_event_player_stats(player_id, events, args):
    rows = []
    errors = []
    for event in events[: args.recent_match_stats]:
        event_id = event.get("id")
        if not event_id:
            continue
        result = fetch_sofascore_api_path(f"/event/{event_id}/player/{player_id}/statistics", args)
        errors.extend(result["errors"])
        rows.append(compact_event(event, result["data"]))
    if args.recent_match_stats == 0:
        rows = [compact_event(event) for event in events]
    return {"matches": rows, "errors": errors}


def fetch_season_aggregates(player_id, events, args):
    contexts = []
    seen = set()
    for event in events:
        context = event_context(event)
        if not context:
            continue
        key = (context["unique_tournament_id"], context["season_id"])
        if key in seen:
            continue
        seen.add(key)
        contexts.append(context)
        if len(contexts) >= args.max_season_contexts:
            break

    aggregates = []
    errors = []
    for context in contexts:
        result = fetch_sofascore_api_path(
            "/player/{player_id}/unique-tournament/{tournament_id}/season/{season_id}/statistics/overall".format(
                player_id=player_id,
                tournament_id=context["unique_tournament_id"],
                season_id=context["season_id"],
            ),
            args,
        )
        errors.extend(result["errors"])
        if result["data"]:
            aggregates.append(
                {
                    "context": context,
                    "source_url": result["url"],
                    "statistics": scalar_stats(result["data"]),
                }
            )
    return {"aggregates": aggregates, "errors": errors}


def recency_weight(date_iso, half_life_days):
    if not date_iso:
        return 1.0
    try:
        match_date = datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
    except ValueError:
        return 1.0
    age_days = max(0.0, (datetime.now(timezone.utc) - match_date).total_seconds() / 86400)
    return math.pow(0.5, age_days / half_life_days)


def derive_scores(record, config):
    half_life = config.get("collection_windows", {}).get("preferred_recent_half_life_days", 90)
    competition_weights = config.get("competition_weights", {})
    stage_weights = config.get("stage_weights", {})

    weighted = []
    knockout = []
    for match in record.get("recent_matches", []):
        rating = parse_float(match.get("rating"))
        if rating is None:
            continue
        c_weight = competition_weights.get(competition_key(match.get("competition", "")), 1.0)
        s_weight = stage_weights.get(match.get("stage_key"), 1.0)
        weight = recency_weight(match.get("date"), half_life) * c_weight * s_weight
        weighted.append((rating, weight))
        if match.get("stage_key") != "league_or_group":
            knockout.append((rating, weight))

    profile_rating = (record.get("profile") or {}).get("summary_last_12_months_rating")
    if weighted:
        recent_form_score = sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted)
        confidence = "high" if len(weighted) >= 8 else "medium"
    elif profile_rating is not None:
        recent_form_score = parse_float(profile_rating)
        confidence = "low_profile_only"
    else:
        recent_form_score = None
        confidence = "uncollected"

    if knockout:
        knockout_score = sum(value * weight for value, weight in knockout) / sum(weight for _, weight in knockout)
    else:
        knockout_score = None

    adjustment = None
    if recent_form_score is not None:
        adjustment = round((recent_form_score - 6.8) * 4.0, 3)

    record["derived"] = {
        "recent_form_score": round(recent_form_score, 3) if recent_form_score is not None else None,
        "knockout_score": round(knockout_score, 3) if knockout_score is not None else None,
        "performance_adjustment": adjustment,
        "rating_evidence_matches": len(weighted),
        "confidence": confidence,
    }


def empty_stats_record(player):
    return {
        "player_key": player["player_key"],
        "country": player["country"],
        "name": player["name"],
        "club": player.get("club"),
        "position": player.get("position"),
        "eafc_rating": player.get("eafc_rating"),
        "sources": {},
        "profile": {},
        "season_aggregates": [],
        "recent_matches": [],
        "derived": {
            "recent_form_score": None,
            "knockout_score": None,
            "performance_adjustment": None,
            "rating_evidence_matches": 0,
            "confidence": "uncollected",
        },
        "collection_status": "pending",
        "collected_at": None,
    }


def collect_player(player, config, args):
    record = empty_stats_record(player)
    record["collected_at"] = now_iso()
    record["source_attempts"] = {}

    sofascore = search_sofascore_player(player, args)
    record["source_attempts"]["sofascore_discovery"] = sofascore.get("attempts") or {
        "combined": {"status": sofascore["status"], "errors": sofascore["errors"]}
    }
    if not sofascore["candidate"]:
        if sofascore["status"] in {"source_unreachable", "search_source_unreachable"}:
            record["collection_status"] = "primary_source_unreachable"
        elif sofascore["status"] in {"source_forbidden", "search_source_forbidden"}:
            record["collection_status"] = "primary_source_forbidden"
        else:
            record["collection_status"] = "identity_not_matched"
        return record

    candidate = sofascore["candidate"]
    player_id = candidate["id"]
    record["sources"]["sofascore"] = candidate

    page = fetch_html(candidate["url"], args)
    if page["error"]:
        record["source_attempts"]["sofascore_profile_page"] = {"status": "error", "errors": [page]}
    else:
        record["profile"].update(parse_profile_page(page["html"], candidate["url"]))
        record["source_attempts"]["sofascore_profile_page"] = {"status": "collected", "errors": []}

    if args.api_details:
        api_profile = fetch_player_api_profile(player_id, args)
        record["source_attempts"]["sofascore_player_api"] = {
            "status": "collected" if api_profile["profile"] else "unavailable",
            "errors": api_profile["errors"],
        }
        if api_profile["profile"]:
            record["sources"]["sofascore_api_profile"] = api_profile["profile"]

        recent_events = fetch_recent_events(player_id, args)
        record["source_attempts"]["sofascore_recent_events"] = {
            "status": "collected" if recent_events["events"] else "unavailable",
            "errors": recent_events["errors"],
        }

        match_stats = fetch_event_player_stats(player_id, recent_events["events"], args)
        record["recent_matches"] = match_stats["matches"]
        record["source_attempts"]["sofascore_match_stats"] = {
            "status": "collected" if any(match.get("statistics") for match in match_stats["matches"]) else "unavailable",
            "errors": match_stats["errors"],
        }

        aggregates = fetch_season_aggregates(player_id, recent_events["events"], args)
        record["season_aggregates"] = aggregates["aggregates"]
        record["source_attempts"]["sofascore_season_aggregates"] = {
            "status": "collected" if aggregates["aggregates"] else "unavailable",
            "errors": aggregates["errors"],
        }
    else:
        record["source_attempts"]["sofascore_api_details"] = {
            "status": "skipped",
            "errors": [],
            "reason": "Direct SofaScore JSON endpoints are blocked in this environment; pass --api-details to try them.",
        }

    derive_scores(record, config)
    if record["season_aggregates"] or any(match.get("statistics") for match in record["recent_matches"]):
        record["collection_status"] = "stats_collected"
    elif record["profile"]:
        record["collection_status"] = "profile_collected"
    else:
        record["collection_status"] = "identity_matched_stats_unavailable"
    return record


def build_output_metadata(args, player_count):
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "source_manifest": Path(args.manifest).name,
        "config": Path(args.config).name,
        "player_count": player_count,
        "status": "website_collection",
        "primary_source": "SofaScore website and SofaScore website JSON endpoints",
        "discovery_mode": args.discovery_mode,
        "api_details_enabled": args.api_details,
        "browser_html_fallback": None if args.no_browser_html else str(args.browser_path) if args.browser_path else None,
        "rate_limit_policy": {
            "delay_seconds": args.delay,
            "jitter_seconds": args.jitter,
            "max_retries": args.max_retries,
            "rate_limit_backoff_seconds": args.rate_limit_backoff,
        },
        "persistence_policy": {
            "write_every_players": args.write_every,
            "windows_file_lock_retries": 30,
        },
        "notes": [
            "The collector is slow by design and writes regular checkpoints so the run can be resumed.",
            "If this environment cannot reach the website, affected players are marked primary_source_unreachable instead of identity_not_matched.",
            "Recent ratings are weighted by recency, competition importance, and knockout stage where match-level ratings are available.",
            "Direct SofaScore JSON endpoints are optional because they may return 403 outside a browser session.",
        ],
    }


def load_existing_records(output_path):
    path = Path(output_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if data.get("metadata", {}).get("schema_version") != SCHEMA_VERSION:
        return {}
    return {record["player_key"]: record for record in data.get("players", []) if record.get("player_key")}


def atomic_write_json(path, payload):
    path = Path(path)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    last_error = None
    for attempt in range(30):
        suffix = f".{int(time.time() * 1000)}.{random.randint(1000, 9999)}.tmp"
        tmp_path = path.with_name(path.name + suffix)
        try:
            tmp_path.write_text(text, encoding="utf-8")
            try:
                tmp_path.replace(path)
                return
            except PermissionError as exc:
                last_error = exc
                try:
                    path.write_text(text, encoding="utf-8")
                    tmp_path.unlink(missing_ok=True)
                    return
                except OSError as fallback_exc:
                    last_error = fallback_exc
        except OSError as exc:
            last_error = exc
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        time.sleep(min(10.0, 0.5 + attempt * 0.25))

    recovery_path = path.with_name(f"{path.stem}.recovery-{datetime.now().strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    recovery_path.write_text(text, encoding="utf-8")
    raise PermissionError(
        f"Could not replace {path} after repeated retries. "
        f"Wrote recovery data to {recovery_path}. Last error: {last_error}"
    )


def write_output(path, args, players, records_by_key):
    payload = {
        "metadata": build_output_metadata(args, len(players)),
        "players": [records_by_key.get(player["player_key"], empty_stats_record(player)) for player in players],
    }
    counts = {}
    for record in payload["players"]:
        counts[record["collection_status"]] = counts.get(record["collection_status"], 0) + 1
    payload["metadata"]["collection_status_counts"] = dict(sorted(counts.items()))
    atomic_write_json(path, payload)


def selected_players(players, start, limit):
    end = None if limit is None else start + limit
    return players[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_FILE))
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=12.0)
    parser.add_argument("--jitter", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--rate-limit-backoff", type=float, default=300.0)
    parser.add_argument("--identity-threshold", type=float, default=0.74)
    parser.add_argument("--discovery-mode", choices=["web", "api"], default="web")
    parser.add_argument("--recent-event-pages", type=int, default=1)
    parser.add_argument("--recent-match-stats", type=int, default=4)
    parser.add_argument("--max-season-contexts", type=int, default=4)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-complete", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--allow-insecure-tls", action="store_true")
    parser.add_argument("--api-details", action="store_true")
    parser.add_argument("--no-browser-html", action="store_true")
    parser.add_argument("--browser-timeout", type=float, default=45.0)
    parser.add_argument("--skip-session-warmup", action="store_true")
    parser.add_argument("--write-every", type=int, default=5)
    args = parser.parse_args()
    args.ssl_context = make_ssl_context(args)
    args.opener = make_url_opener(args)
    args.browser_path = detect_browser_path()
    args.write_every = max(1, args.write_every)
    warm_up_sofascore_session(args)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    players = manifest["players"]
    worklist = selected_players(players, args.start, args.limit)
    records_by_key = {} if args.no_resume else load_existing_records(args.output)

    for player in players:
        records_by_key.setdefault(player["player_key"], empty_stats_record(player))

    write_output(args.output, args, players, records_by_key)
    for offset, player in enumerate(worklist, start=1):
        absolute_index = args.start + offset
        existing = records_by_key.get(player["player_key"])
        if (
            existing
            and existing.get("collection_status") in COMPLETED_STATUSES
            and not args.refresh_complete
            and not args.refresh_cache
        ):
            print(f"[{absolute_index}/{len(players)}] {player['country']} - {player['name']} (already collected)")
            continue
        print(f"[{absolute_index}/{len(players)}] {player['country']} - {player['name']}")
        records_by_key[player["player_key"]] = collect_player(player, config, args)
        if offset % args.write_every == 0:
            write_output(args.output, args, players, records_by_key)

    write_output(args.output, args, players, records_by_key)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
