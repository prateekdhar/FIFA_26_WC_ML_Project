import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from integrate_transfermarkt_data import DEFAULT_ALIASES, club_score, load_name_aliases, name_variants, norm, player_search_names


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "player_performance_data_statbunker.json"
DEFAULT_OUTPUT = ROOT / "player_performance_data_statbunker.json"
DEFAULT_REVIEW = ROOT / "player_performance_data_wikipedia_review.json"
CACHE_DIR = ROOT / ".cache" / "wikipedia"
API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "FIFA_WC_26 local research/0.1 (basic Wikipedia fallback)"


COUNTRY_QUERY_ALIAS = {
    "Bosnia & Herzegovina": "Bosnia Herzegovina",
    "Cape Verde": "Cape Verde",
    "Curacao": "Curacao",
    "Czech Republic": "Czech Republic",
    "DR Congo": "DR Congo",
    "Ivory Coast": "Ivory Coast",
    "South Korea": "South Korea",
    "United States": "United States",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def cache_path(prefix, key):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{prefix}_{digest}.json"


def api_get(params, cache_prefix, delay, max_retries=3):
    query = urllib.parse.urlencode(params)
    path = cache_path(cache_prefix, query)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            if delay:
                time.sleep(delay)
            return data
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < max_retries:
                time.sleep(max(20.0, delay * 20) * (attempt + 1))
                continue
            print(f"warning: wikipedia request failed with HTTP {exc.code}; skipping uncached query")
            return {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(max(2.0, delay * 5) * (attempt + 1))
                continue
            print(f"warning: wikipedia request failed ({exc}); skipping uncached query")
            return {}
    print(f"warning: wikipedia request failed ({last_error}); skipping uncached query")
    return {}


def split_particle_tokens(name):
    parts = []
    for token in str(name or "").split():
        low = token.lower()
        split = False
        for prefix in ["el", "al", "abu", "abd", "abdel", "abdul"]:
            if low.startswith(prefix) and len(low) > len(prefix) + 3:
                parts.extend([token[: len(prefix)], token[len(prefix) :]])
                split = True
                break
        if not split:
            parts.append(token)
    return " ".join(parts)


def search_queries(player, aliases=None):
    country = COUNTRY_QUERY_ALIAS.get(player.get("country"), player.get("country") or "")
    names = set(player_search_names(player, aliases))
    for name in list(names):
        names.add(split_particle_tokens(name))
        for variant in name_variants(name):
            names.add(variant)
    queries = []
    for name in names:
        if not name:
            continue
        queries.append(f'"{name}" footballer {country}')
        queries.append(f"{name} footballer {country}")
    return list(dict.fromkeys(queries))


def search_pages(player, args):
    results = []
    seen = set()
    for query in search_queries(player):
        data = api_get(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": args.search_limit,
                "format": "json",
            },
            "search",
            args.delay,
        )
        for row in data.get("query", {}).get("search", []):
            pageid = row.get("pageid")
            if pageid and pageid not in seen:
                seen.add(pageid)
                results.append({"pageid": pageid, "title": row.get("title")})
    return results


def fetch_page(pageid, args):
    data = api_get(
        {
            "action": "query",
            "prop": "revisions|categories|info",
            "rvprop": "content",
            "rvslots": "main",
            "pageids": pageid,
            "cllimit": 50,
            "format": "json",
            "formatversion": 2,
        },
        "page",
        args.delay,
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    page = pages[0]
    revisions = page.get("revisions") or []
    text = ""
    if revisions:
        text = revisions[0].get("slots", {}).get("main", {}).get("content", "")
    return {
        "pageid": page.get("pageid"),
        "title": page.get("title"),
        "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(page.get('title', '')).replace(' ', '_'))}",
        "categories": [cat.get("title", "") for cat in page.get("categories", [])],
        "wikitext": text,
    }


def search_and_fetch_pages(player, args, aliases=None):
    pages = []
    seen = set()
    for query in search_queries(player, aliases)[: args.max_queries]:
        data = api_get(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": args.search_limit,
                "prop": "revisions|categories|info",
                "rvprop": "content",
                "rvslots": "main",
                "cllimit": 50,
                "format": "json",
                "formatversion": 2,
            },
            "search_pages",
            args.delay,
        )
        for page in data.get("query", {}).get("pages", []):
            pageid = page.get("pageid")
            if pageid in seen:
                continue
            seen.add(pageid)
            revisions = page.get("revisions") or []
            text = ""
            if revisions:
                text = revisions[0].get("slots", {}).get("main", {}).get("content", "")
            pages.append(
                {
                    "pageid": pageid,
                    "title": page.get("title"),
                    "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(page.get('title', '')).replace(' ', '_'))}",
                    "categories": [cat.get("title", "") for cat in page.get("categories", [])],
                    "wikitext": text,
                }
            )
    return pages


def strip_refs(text):
    text = re.sub(r"<ref[^>/]*/>", "", text or "", flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.I | re.S)
    return text


def clean_markup(text):
    text = strip_refs(str(text or ""))
    text = re.sub(r"\{\{birth date and age\|(\d{4})\|(\d{1,2})\|(\d{1,2}).*?\}\}", r"\1-\2-\3", text, flags=re.I)
    text = re.sub(r"\{\{birth date\|(\d{4})\|(\d{1,2})\|(\d{1,2}).*?\}\}", r"\1-\2-\3", text, flags=re.I)
    text = re.sub(r"\[\[([^|\]]+)\|([^]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"''+", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_infobox_fields(wikitext):
    fields = {}
    for match in re.finditer(r"^\|\s*([^=|{}]+?)\s*=\s*(.*)$", wikitext or "", re.M):
        key = match.group(1).strip().lower().replace("-", "_")
        value = match.group(2).strip()
        if key and value:
            fields[key] = clean_markup(value)
    return fields


def parse_int(value):
    text = clean_markup(value)
    match = re.search(r"-?\d+", text.replace(",", ""))
    return int(match.group(0)) if match else 0


def numbered_rows(fields, prefix_map, max_index=40):
    rows = []
    for index in range(1, max_index + 1):
        row = {}
        for out_key, field_prefix in prefix_map.items():
            value = fields.get(f"{field_prefix}{index}")
            if value is not None:
                row[out_key] = value
        if row:
            rows.append(row)
    return rows


def parse_wikipedia_stats(page):
    fields = parse_infobox_fields(page["wikitext"])
    senior_rows = numbered_rows(
        fields,
        {"years": "years", "team": "clubs", "appearances": "caps", "goals": "goals"},
    )
    national_rows = numbered_rows(
        fields,
        {"years": "nationalyears", "team": "nationalteam", "caps": "nationalcaps", "goals": "nationalgoals"},
    )
    for row in senior_rows:
        row["appearances"] = parse_int(row.get("appearances"))
        row["goals"] = parse_int(row.get("goals"))
    for row in national_rows:
        row["caps"] = parse_int(row.get("caps"))
        row["goals"] = parse_int(row.get("goals"))
    senior_appearances = sum(row.get("appearances", 0) for row in senior_rows)
    senior_goals = sum(row.get("goals", 0) for row in senior_rows)
    national_caps = sum(row.get("caps", 0) for row in national_rows)
    national_goals = sum(row.get("goals", 0) for row in national_rows)
    return {
        "pageid": page["pageid"],
        "title": page["title"],
        "url": page["url"],
        "infobox_name": fields.get("name"),
        "full_name": fields.get("full_name"),
        "birth_date": fields.get("birth_date"),
        "height": fields.get("height"),
        "position": fields.get("position"),
        "current_club": fields.get("currentclub"),
        "club_career": senior_rows,
        "national_team": national_rows,
        "summary": {
            "senior_appearances": senior_appearances,
            "senior_goals": senior_goals,
            "national_caps": national_caps,
            "national_goals": national_goals,
        },
        "last_updates": {
            "club": fields.get("club_update") or fields.get("pcupdate"),
            "national_team": fields.get("nationalteam_update") or fields.get("ntupdate"),
        },
    }


def compact_name_score(left, right):
    if not left or not right:
        return 0.0
    left_variants = {norm(left).replace(" ", ""), norm(split_particle_tokens(left)).replace(" ", "")}
    right_variants = {norm(right).replace(" ", ""), norm(split_particle_tokens(right)).replace(" ", "")}
    best = 0.0
    for lvar in left_variants:
        for rvar in right_variants:
            if not lvar or not rvar:
                continue
            if lvar == rvar:
                best = max(best, 1.0)
            if lvar in rvar or rvar in lvar:
                best = max(best, 0.92)
            best = max(best, SequenceMatcher(None, lvar, rvar).ratio())
    return best


def score_page(player, page, stats, aliases=None):
    text = page["wikitext"]
    categories = " ".join(page.get("categories") or [])
    is_footballer = bool(re.search(r"Infobox football biography|footballer|association football", text + " " + categories, re.I))
    name_candidates = [page.get("title"), stats.get("infobox_name"), stats.get("full_name")]
    ns = max(
        compact_name_score(search_name, candidate)
        for search_name in player_search_names(player, aliases)
        for candidate in name_candidates
        if candidate
    )
    country = COUNTRY_QUERY_ALIAS.get(player.get("country"), player.get("country") or "")
    country_score = 1.0 if norm(country) and norm(country) in norm(text + " " + categories) else 0.0
    club_candidates = [stats.get("current_club")] + [row.get("team") for row in stats.get("club_career", [])]
    cs = max([club_score(player.get("club"), candidate) for candidate in club_candidates if candidate] or [0.0])
    has_stats = bool(stats["club_career"] or stats["national_team"])
    score = ns * 0.68 + country_score * 0.12 + cs * 0.1 + (0.07 if is_footballer else 0.0) + (0.03 if has_stats else 0.0)
    return {
        "score": round(min(score, 1.0), 4),
        "name_score": round(ns, 4),
        "country_score": country_score,
        "club_score": round(cs, 4),
        "is_footballer": is_footballer,
        "has_stats": has_stats,
    }


def wikipedia_statistics(stats, score):
    summary = stats["summary"]
    return {
        "source": "wikipedia",
        "data_status": "basic_infobox_stats_collected",
        "confidence": score["score"],
        "recent": {
            "appearances": None,
            "minutes_played": None,
            "goals": None,
            "assists": None,
            "goal_contributions": None,
            "yellow_cards": None,
            "red_cards": None,
            "clean_sheets": None,
            "goals_conceded": None,
            "per_90": {},
            "per_appearance": {},
        },
        "career": {
            "senior_appearances": summary["senior_appearances"],
            "senior_goals": summary["senior_goals"],
            "national_caps": summary["national_caps"],
            "national_goals": summary["national_goals"],
        },
        "competitions": [],
        "teams": [row.get("team") for row in stats.get("club_career", []) if row.get("team")],
        "notes": [
            "Wikipedia infobox stats are basic career aggregates and may lag the article update date.",
            "No recent-season breakdown or minutes are available from this fallback.",
        ],
    }


def collect_for_player(player, args):
    candidates = []
    aliases = getattr(args, "alias_map", {})
    for page in search_and_fetch_pages(player, args, aliases):
        stats = parse_wikipedia_stats(page)
        score = score_page(player, page, stats, aliases)
        if score["is_footballer"] and score["has_stats"] and score["name_score"] >= args.min_name_score:
            candidates.append({"score": score, "stats": stats})
    candidates.sort(key=lambda row: row["score"]["score"], reverse=True)
    if not candidates:
        return None, []
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    ambiguous = second and top["score"]["score"] - second["score"]["score"] < args.ambiguity_margin and top["score"]["score"] < args.high_confidence_threshold
    if top["score"]["score"] >= args.identity_threshold and not ambiguous:
        return top, candidates
    return None, candidates


def run(args):
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    review = []
    collected = 0
    considered = 0
    players = data.get("players", [])
    for player in players:
        if player.get("player_statistics", {}).get("source") != "none":
            continue
        if player.get("sources", {}).get("wikipedia_attempt", {}).get("status") in {"no_confident_match", "no_candidate_page"} and not args.retry_checked:
            continue
        considered += 1
        if args.limit and considered > args.limit:
            break
        accepted, candidates = collect_for_player(player, args)
        if accepted:
            stats = accepted["stats"]
            player.setdefault("sources", {})["wikipedia"] = {
                **stats,
                "source_match_score": accepted["score"]["score"],
                "source_name_score": accepted["score"]["name_score"],
                "source_club_score": accepted["score"]["club_score"],
                "source_country_score": accepted["score"]["country_score"],
            }
            player["collection_status"] = "wikipedia_basic_stats_collected"
            player["reason"] = "Wikipedia football biography infobox matched; only basic career aggregates available."
            player["player_statistics"] = wikipedia_statistics(stats, accepted["score"])
            collected += 1
        elif candidates:
            player.setdefault("sources", {})["wikipedia_attempt"] = {
                "status": "no_confident_match",
                "checked_at": now_iso(),
                "candidate_count": len(candidates),
            }
            review.append(
                {
                    "player_key": player.get("player_key"),
                    "country": player.get("country"),
                    "name": player.get("name"),
                    "club": player.get("club"),
                    "candidates": [
                        {
                            "score": candidate["score"],
                            "title": candidate["stats"]["title"],
                            "url": candidate["stats"]["url"],
                            "summary": candidate["stats"]["summary"],
                            "current_club": candidate["stats"].get("current_club"),
                        }
                        for candidate in candidates[: args.review_limit]
                    ],
                }
            )
        else:
            player.setdefault("sources", {})["wikipedia_attempt"] = {
                "status": "no_candidate_page",
                "checked_at": now_iso(),
                "candidate_count": 0,
            }

    counts = {}
    stat_sources = {}
    checked_none = 0
    for player in players:
        counts[player.get("collection_status")] = counts.get(player.get("collection_status"), 0) + 1
        source = player.get("player_statistics", {}).get("source")
        stat_sources[source] = stat_sources.get(source, 0) + 1
        if source == "none" and player.get("sources", {}).get("wikipedia_attempt", {}).get("status") in {"no_confident_match", "no_candidate_page"}:
            checked_none += 1

    metadata = data.setdefault("metadata", {})
    metadata["collection_status_counts"] = dict(sorted(counts.items()))
    metadata["wikipedia_enrichment"] = {
        "created_at": now_iso(),
        "last_run_considered_players": considered,
        "last_run_basic_stats_collected": collected,
        "last_run_review_count": len(review),
        "cumulative_basic_stats_collected": stat_sources.get("wikipedia", 0),
        "remaining_without_external_stats": stat_sources.get("none", 0),
        "remaining_wikipedia_checked": checked_none,
        "source": "English Wikipedia football biography infoboxes via MediaWiki API",
        "limitations": [
            "Infobox statistics are basic career aggregates and are manually maintained.",
            "Wikipedia does not reliably provide recent-season minutes or competition splits.",
        ],
    }
    metadata["player_statistics_summary"] = {
        "created_at": now_iso(),
        "player_count": len(players),
        "source_counts": dict(sorted(stat_sources.items())),
        "complete": all("player_statistics" in player for player in players),
    }
    Path(args.output).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.review_output).write_text(
        json.dumps({"metadata": {"created_at": now_iso(), "review_count": len(review)}, "players": review}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata["wikipedia_enrichment"], indent=2))
    print(json.dumps(metadata["player_statistics_summary"], indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--review-output", default=str(DEFAULT_REVIEW))
    parser.add_argument("--aliases", default=str(DEFAULT_ALIASES))
    parser.add_argument("--search-limit", type=int, default=4)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--review-limit", type=int, default=5)
    parser.add_argument("--identity-threshold", type=float, default=0.82)
    parser.add_argument("--high-confidence-threshold", type=float, default=0.92)
    parser.add_argument("--min-name-score", type=float, default=0.72)
    parser.add_argument("--ambiguity-margin", type=float, default=0.04)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--retry-checked", action="store_true")
    args = parser.parse_args()
    args.alias_map = load_name_aliases(args.aliases)
    run(args)


if __name__ == "__main__":
    main()
