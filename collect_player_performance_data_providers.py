import argparse
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from collect_player_performance_data import (
    CACHE_DIR,
    CONFIG_FILE,
    MANIFEST_FILE,
    empty_stats_record,
    name_score,
    norm,
    strip_club_country,
)


ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "player_performance_data_providers.json"
PROVIDER_CACHE_DIR = CACHE_DIR / "providers"
SCHEMA_VERSION = 3


COMPLETED_STATUSES = {
    "stats_collected_provider",
    "identity_matched_stats_unavailable_provider",
}


PROVIDER_ENV = {
    "sportmonks": ["SPORTMONKS_API_TOKEN", "SPORTMONKS_TOKEN"],
    "api_football": ["APIFOOTBALL_API_KEY", "API_FOOTBALL_KEY", "API_SPORTS_KEY", "APISPORTS_KEY"],
    "footystats": ["FOOTYSTATS_API_KEY", "FOOTYSTATS_KEY"],
}


SENSITIVE_QUERY_KEYS = {"api_token", "key"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def token_for(provider):
    for env_name in PROVIDER_ENV[provider]:
        value = os.environ.get(env_name)
        if value:
            return env_name, value
    return None, None


def redact_url(url):
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [
        (key, "REDACTED" if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in query
    ]
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(safe_query))
    )


def cache_path(url, provider):
    PROVIDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", redact_url(url))[:150]
    return PROVIDER_CACHE_DIR / f"{provider}_{safe}.json"


def request_json(url, provider, args, headers=None):
    path = cache_path(url, provider)
    if path.exists() and not args.refresh_cache:
        return {
            "status": "ok",
            "url": redact_url(url),
            "data": json.loads(path.read_text(encoding="utf-8")),
            "from_cache": True,
            "error": None,
        }

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FIFA26WCResearch/0.4",
            "Accept": "application/json,text/plain,*/*",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {
            "status": f"http_{exc.code}",
            "url": redact_url(url),
            "data": None,
            "from_cache": False,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "status": "unreachable",
            "url": redact_url(url),
            "data": None,
            "from_cache": False,
            "error": str(exc),
        }

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "status": "invalid_json",
            "url": redact_url(url),
            "data": None,
            "from_cache": False,
            "error": str(exc),
        }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.delay or args.jitter:
        time.sleep(args.delay + random.uniform(0, args.jitter))
    return {"status": "ok", "url": redact_url(url), "data": data, "from_cache": False, "error": None}


def list_from_response(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ["data", "response", "players"]:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def deep_get(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def flatten_scalars(data, prefix=""):
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, value in data.items():
        next_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten_scalars(value, next_key))
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[next_key] = value
    return out


def candidate_name(candidate, provider):
    if provider == "api_football":
        player = candidate.get("player") if isinstance(candidate.get("player"), dict) else candidate
        return player.get("name") or " ".join(
            part for part in [player.get("firstname"), player.get("lastname")] if part
        )
    if provider == "footystats":
        return candidate.get("full_name") or candidate.get("known_as")
    return (
        candidate.get("display_name")
        or candidate.get("name")
        or candidate.get("common_name")
        or " ".join(part for part in [candidate.get("firstname"), candidate.get("lastname")] if part)
    )


def candidate_country(candidate, provider):
    if provider == "api_football":
        player = candidate.get("player") if isinstance(candidate.get("player"), dict) else candidate
        return player.get("nationality") or player.get("birth", {}).get("country")
    if provider == "footystats":
        return candidate.get("nationality")
    country = candidate.get("country") or candidate.get("nationality")
    if isinstance(country, dict):
        return country.get("name") or country.get("official_name")
    return country


def candidate_team(candidate, provider):
    if provider == "api_football":
        stats = candidate.get("statistics") or []
        if stats and isinstance(stats[0], dict):
            return deep_get(stats[0], "team", "name")
        return None
    if provider == "footystats":
        return candidate.get("club") or candidate.get("club_team") or candidate.get("team")
    teams = candidate.get("teams")
    if isinstance(teams, list) and teams:
        team = teams[0]
        if isinstance(team, dict):
            return team.get("name") or deep_get(team, "team", "name")
    return None


def score_candidate(player, candidate, provider):
    score = name_score(player["name"], candidate_name(candidate, provider) or "")
    player_country = norm(player.get("country"))
    source_country = norm(candidate_country(candidate, provider))
    if player_country and source_country:
        if player_country == source_country:
            score += 0.08
        elif player_country in source_country or source_country in player_country:
            score += 0.04
    player_club = norm(strip_club_country(player.get("club")))
    source_team = norm(candidate_team(candidate, provider))
    if player_club and source_team and (player_club in source_team or source_team in player_club):
        score += 0.06
    return min(score, 1.0)


def best_match(player, candidates, provider, threshold):
    best = None
    best_score = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        score = score_candidate(player, candidate, provider)
        if score > best_score:
            best = candidate
            best_score = score
    if best and best_score >= threshold:
        return best, round(best_score, 3)
    return None, round(best_score, 3)


def sportmonks_search(player, token, args):
    query = urllib.parse.quote(player["name"])
    include = urllib.parse.quote("statistics;teams;position;detailedPosition;nationality")
    url = f"https://api.sportmonks.com/v3/football/players/search/{query}?api_token={token}&include={include}"
    result = request_json(url, "sportmonks", args)
    if result["status"] != "ok":
        return result, []
    return result, list_from_response(result["data"])


def sportmonks_player_details(player_id, token, args):
    include = urllib.parse.quote("statistics;teams;position;detailedPosition;nationality")
    url = f"https://api.sportmonks.com/v3/football/players/{player_id}?api_token={token}&include={include}"
    return request_json(url, "sportmonks", args)


def api_football_search(player, token, args):
    headers = {"x-apisports-key": token}
    query = urllib.parse.quote(player["name"])
    urls = [
        f"https://v3.football.api-sports.io/players/profiles?search={query}",
        f"https://v3.football.api-sports.io/players?search={query}&season={args.api_football_season}",
    ]
    attempts = []
    candidates = []
    for url in urls:
        result = request_json(url, "api_football", args, headers=headers)
        attempts.append(result)
        if result["status"] == "ok":
            candidates.extend(list_from_response(result["data"]))
        if candidates:
            break
    return attempts, candidates


def footystats_league_players(season_id, token, args):
    include = "&include=stats" if args.footystats_include_stats else ""
    url = f"https://api.football-data-api.com/league-players?key={token}&season_id={season_id}{include}&page=1"
    result = request_json(url, "footystats", args)
    if result["status"] != "ok":
        return result, []
    return result, list_from_response(result["data"])


def footystats_player_stats(player_id, token, args):
    url = f"https://api.football-data-api.com/player-stats?key={token}&player_id={player_id}"
    return request_json(url, "footystats", args)


def normalize_api_football(candidate):
    player = candidate.get("player") if isinstance(candidate.get("player"), dict) else candidate
    rows = []
    for stat in candidate.get("statistics") or []:
        if not isinstance(stat, dict):
            continue
        rows.append(
            {
                "source": "api_football",
                "context": {
                    "team": deep_get(stat, "team", "name"),
                    "league": deep_get(stat, "league", "name"),
                    "season": deep_get(stat, "league", "season"),
                    "country": deep_get(stat, "league", "country"),
                },
                "statistics": {
                    "appearances": deep_get(stat, "games", "appearences") or deep_get(stat, "games", "appearances"),
                    "starts": deep_get(stat, "games", "lineups"),
                    "minutes": deep_get(stat, "games", "minutes"),
                    "average_rating": deep_get(stat, "games", "rating"),
                    "goals": deep_get(stat, "goals", "total"),
                    "assists": deep_get(stat, "goals", "assists"),
                    "shots": deep_get(stat, "shots", "total"),
                    "shots_on_target": deep_get(stat, "shots", "on"),
                    "key_passes": deep_get(stat, "passes", "key"),
                    "tackles": deep_get(stat, "tackles", "total"),
                    "interceptions": deep_get(stat, "tackles", "interceptions"),
                    "duels_total": deep_get(stat, "duels", "total"),
                    "duels_won": deep_get(stat, "duels", "won"),
                    "successful_dribbles": deep_get(stat, "dribbles", "success"),
                    "yellow_cards": deep_get(stat, "cards", "yellow"),
                    "red_cards": deep_get(stat, "cards", "red"),
                    "penalties_scored": deep_get(stat, "penalty", "scored"),
                    "penalties_missed": deep_get(stat, "penalty", "missed"),
                    "raw": flatten_scalars(stat),
                },
            }
        )
    return {
        "identity": {
            "id": player.get("id"),
            "name": player.get("name"),
            "firstname": player.get("firstname"),
            "lastname": player.get("lastname"),
            "nationality": player.get("nationality"),
            "photo": player.get("photo"),
        },
        "aggregates": rows,
    }


def normalize_footystats_row(row):
    stats = {
        "appearances": row.get("appearances_overall"),
        "starts": row.get("games_started") or row.get("detailed", {}).get("games_started"),
        "minutes": row.get("minutes_played_overall"),
        "average_rating": row.get("average_rating_overall") or row.get("detailed", {}).get("average_rating_overall"),
        "goals": row.get("goals_overall"),
        "assists": row.get("assists_overall"),
        "goals_per_90": row.get("goals_per_90_overall"),
        "assists_per_90": row.get("assists_per_90_overall"),
        "goal_contributions_per_90": row.get("goals_involved_per_90_overall"),
        "shots": row.get("detailed", {}).get("shots_total_overall"),
        "shots_on_target": row.get("detailed", {}).get("shots_on_target_total_overall"),
        "shots_per_90": row.get("detailed", {}).get("shots_per_90_overall"),
        "xg_total": row.get("detailed", {}).get("xg_total_overall"),
        "xa_total": row.get("detailed", {}).get("xa_total_overall"),
        "tackles": row.get("detailed", {}).get("tackles_total_overall"),
        "interceptions": row.get("detailed", {}).get("interceptions_total_overall"),
        "clearances": row.get("detailed", {}).get("clearances_total_overall"),
        "duels_total": row.get("detailed", {}).get("duels_total_overall"),
        "duels_won": row.get("detailed", {}).get("duels_won_total_overall"),
        "saves": row.get("detailed", {}).get("saves_total_overall"),
        "yellow_cards": row.get("yellow_cards_overall"),
        "red_cards": row.get("red_cards_overall"),
        "raw": flatten_scalars(row),
    }
    return {
        "identity": {
            "id": row.get("id"),
            "name": row.get("full_name") or row.get("known_as"),
            "nationality": row.get("nationality"),
            "position": row.get("position"),
            "url": row.get("url"),
        },
        "aggregate": {
            "source": "footystats",
            "context": {
                "competition_id": row.get("competition_id"),
                "league": row.get("league"),
                "league_type": row.get("league_type"),
                "season": row.get("season"),
                "club_team_id": row.get("club_team_id"),
            },
            "statistics": stats,
        },
    }


def normalize_sportmonks(candidate):
    identity = {
        "id": candidate.get("id"),
        "name": candidate_name(candidate, "sportmonks"),
        "country": candidate_country(candidate, "sportmonks"),
        "team": candidate_team(candidate, "sportmonks"),
    }
    statistics = candidate.get("statistics")
    aggregates = []
    if isinstance(statistics, list):
        for row in statistics:
            if isinstance(row, dict):
                aggregates.append(
                    {
                        "source": "sportmonks",
                        "context": {
                            "season_id": row.get("season_id"),
                            "team_id": row.get("team_id"),
                            "league_id": row.get("league_id"),
                        },
                        "statistics": {"raw": flatten_scalars(row)},
                    }
                )
    return {"identity": identity, "aggregates": aggregates}


def collect_sportmonks(player, args):
    env_name, token = token_for("sportmonks")
    attempt = {"provider": "sportmonks", "credential_env": env_name, "status": "missing_key" if not token else "pending"}
    if not token:
        return None, attempt
    search, candidates = sportmonks_search(player, token, args)
    attempt.update({"status": search["status"], "url": search["url"], "error": search["error"]})
    if search["status"] != "ok":
        return None, attempt
    match, score = best_match(player, candidates, "sportmonks", args.identity_threshold)
    attempt.update({"candidate_count": len(candidates), "best_score": score})
    if not match:
        attempt["status"] = "not_matched"
        return None, attempt
    details = sportmonks_player_details(match.get("id"), token, args) if match.get("id") else search
    payload = list_from_response(details["data"])[0] if isinstance(details.get("data"), dict) and isinstance(details["data"].get("data"), list) and details["data"]["data"] else details.get("data", {}).get("data", match)
    normalized = normalize_sportmonks(payload if isinstance(payload, dict) else match)
    normalized["identity"]["match_score"] = score
    attempt["status"] = "matched"
    return normalized, attempt


def collect_api_football(player, args):
    env_name, token = token_for("api_football")
    attempt = {"provider": "api_football", "credential_env": env_name, "status": "missing_key" if not token else "pending"}
    if not token:
        return None, attempt
    attempts, candidates = api_football_search(player, token, args)
    attempt["requests"] = [{"status": item["status"], "url": item["url"], "error": item["error"]} for item in attempts]
    if not candidates and attempts:
        attempt["status"] = attempts[-1]["status"]
        return None, attempt
    match, score = best_match(player, candidates, "api_football", args.identity_threshold)
    attempt.update({"candidate_count": len(candidates), "best_score": score})
    if not match:
        attempt["status"] = "not_matched"
        return None, attempt
    normalized = normalize_api_football(match)
    normalized["identity"]["match_score"] = score
    attempt["status"] = "matched"
    return normalized, attempt


def collect_footystats(player, args):
    env_name, token = token_for("footystats")
    if args.footystats_example and not token:
        env_name, token = "example", "example"
    attempt = {"provider": "footystats", "credential_env": env_name, "status": "missing_key" if not token else "pending"}
    if not token:
        return None, attempt
    if not args.footystats_season_id:
        attempt["status"] = "missing_season_ids"
        return None, attempt
    all_rows = []
    requests = []
    for season_id in args.footystats_season_id:
        result, rows = footystats_league_players(season_id, token, args)
        requests.append({"status": result["status"], "url": result["url"], "error": result["error"], "rows": len(rows)})
        all_rows.extend(rows)
    attempt["requests"] = requests
    if not all_rows:
        attempt["status"] = requests[-1]["status"] if requests else "no_rows"
        return None, attempt
    match, score = best_match(player, all_rows, "footystats", args.identity_threshold)
    attempt.update({"candidate_count": len(all_rows), "best_score": score})
    if not match:
        attempt["status"] = "not_matched"
        return None, attempt
    normalized = normalize_footystats_row(match)
    player_id = normalized["identity"].get("id")
    if player_id:
        stats_response = footystats_player_stats(player_id, token, args)
        if stats_response["status"] == "ok":
            rows = list_from_response(stats_response["data"])
            aggregates = [normalize_footystats_row(row)["aggregate"] for row in rows if isinstance(row, dict)]
        else:
            aggregates = [normalized["aggregate"]]
            attempt["player_stats_request"] = {
                "status": stats_response["status"],
                "url": stats_response["url"],
                "error": stats_response["error"],
            }
    else:
        aggregates = [normalized["aggregate"]]
    normalized["aggregates"] = aggregates
    normalized["identity"]["match_score"] = score
    attempt["status"] = "matched"
    return normalized, attempt


def derive_from_aggregates(record):
    ratings = []
    for aggregate in record.get("season_aggregates", []):
        stats = aggregate.get("statistics") or {}
        value = stats.get("average_rating")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        if value:
            ratings.append(value)
    if ratings:
        recent = sum(ratings) / len(ratings)
        record["derived"]["recent_form_score"] = round(recent, 3)
        record["derived"]["performance_adjustment"] = round((recent - 6.8) * 4.0, 3)
        record["derived"]["rating_evidence_matches"] = len(ratings)
        record["derived"]["confidence"] = "season_aggregate"


def collect_player(player, args):
    record = empty_stats_record(player)
    record["collected_at"] = now_iso()
    record["source_attempts"] = {}
    record["provider_order"] = args.providers

    all_missing = True
    saw_unreachable = False
    saw_forbidden = False

    collectors = {
        "sportmonks": collect_sportmonks,
        "api_football": collect_api_football,
        "footystats": collect_footystats,
    }
    for provider in args.providers:
        normalized, attempt = collectors[provider](player, args)
        record["source_attempts"][provider] = attempt
        if attempt["status"] != "missing_key":
            all_missing = False
        if attempt["status"] == "unreachable":
            saw_unreachable = True
        if attempt["status"] in {"http_401", "http_403"}:
            saw_forbidden = True
        if normalized:
            record["sources"][provider] = normalized["identity"]
            record["season_aggregates"].extend(normalized.get("aggregates") or [])
            if record["season_aggregates"]:
                record["collection_status"] = "stats_collected_provider"
            else:
                record["collection_status"] = "identity_matched_stats_unavailable_provider"
            derive_from_aggregates(record)
            return record

    if all_missing:
        record["collection_status"] = "provider_missing_credentials"
    elif saw_forbidden:
        record["collection_status"] = "provider_auth_failed"
    elif saw_unreachable:
        record["collection_status"] = "provider_source_unreachable"
    else:
        record["collection_status"] = "identity_not_matched_provider"
    return record


def load_existing(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {row["player_key"]: row for row in data.get("players", []) if row.get("player_key")}


def write_output(path, args, players, records):
    rows = [records.get(player["player_key"], empty_stats_record(player)) for player in players]
    counts = {}
    for row in rows:
        counts[row["collection_status"]] = counts.get(row["collection_status"], 0) + 1
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "source_manifest": Path(args.manifest).name,
        "player_count": len(players),
        "status": "provider_collection",
        "providers": args.providers,
        "credential_presence": {
            provider: bool(token_for(provider)[1])
            for provider in ["sportmonks", "api_football", "footystats"]
        },
        "collection_status_counts": dict(sorted(counts.items())),
        "notes": [
            "Provider API keys are read from environment variables and are never written to output or cache filenames.",
            "API-Football player statistics are team/season/league contextual, so season defaults to the configured API_FOOTBALL season.",
            "FootyStats requires one or more season IDs for League Players lookup before player-stats can be fetched.",
        ],
    }
    Path(path).write_text(json.dumps({"metadata": metadata, "players": rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def selected_players(players, start, limit):
    end = None if limit is None else start + limit
    return players[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_FILE))
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    parser.add_argument("--providers", default="sportmonks,api_football,footystats")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--jitter", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--identity-threshold", type=float, default=0.74)
    parser.add_argument("--write-every", type=int, default=5)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-complete", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--api-football-season", type=int, default=2025)
    parser.add_argument("--footystats-season-id", action="append", default=[])
    parser.add_argument("--footystats-include-stats", action="store_true", default=True)
    parser.add_argument("--footystats-example", action="store_true")
    args = parser.parse_args()
    args.providers = [provider.strip() for provider in args.providers.split(",") if provider.strip()]
    invalid = [provider for provider in args.providers if provider not in PROVIDER_ENV]
    if invalid:
        raise SystemExit(f"Unknown providers: {', '.join(invalid)}")
    args.write_every = max(1, args.write_every)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    players = manifest["players"]
    worklist = selected_players(players, args.start, args.limit)
    records = {} if args.no_resume else load_existing(args.output)
    for player in players:
        records.setdefault(player["player_key"], empty_stats_record(player))

    write_output(args.output, args, players, records)
    for offset, player in enumerate(worklist, start=1):
        absolute_index = args.start + offset
        existing = records.get(player["player_key"])
        if (
            existing
            and existing.get("collection_status") in COMPLETED_STATUSES
            and not args.refresh_complete
            and not args.refresh_cache
        ):
            print(f"[{absolute_index}/{len(players)}] {player['country']} - {player['name']} (already collected)")
            continue
        print(f"[{absolute_index}/{len(players)}] {player['country']} - {player['name']}")
        records[player["player_key"]] = collect_player(player, args)
        if offset % args.write_every == 0:
            write_output(args.output, args, players, records)
    write_output(args.output, args, players, records)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
