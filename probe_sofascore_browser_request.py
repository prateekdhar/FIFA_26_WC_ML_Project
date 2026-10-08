import argparse
import gzip
import json
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CURL_FILE = ROOT / ".cache" / "sofascore_browser_request.curl"
DEFAULT_OUTPUT = ROOT / ".cache" / "sofascore_browser_probe_result.json"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


VALUE_OPTIONS = {
    "-A",
    "--user-agent",
    "-b",
    "--cookie",
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-ascii",
    "-e",
    "--referer",
    "-H",
    "--header",
    "-I",
    "--head",
    "-X",
    "--request",
    "--url",
}
BODY_OPTIONS = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii"}
SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "x-rapidapi-key"}
DROP_REPLAY_HEADERS = {"host", "content-length"}
DROP_ENCODING_HEADERS = {"accept-encoding"}


def normalize_curl_text(text):
    text = text.replace("^\r\n", " ").replace("^\n", " ")
    text = text.replace("`r`n", " ").replace("`\r\n", " ").replace("`\n", " ")
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    return " ".join(line.strip() for line in text.strip().splitlines() if line.strip())


def parse_header(value):
    if ":" not in value:
        raise ValueError(f"Invalid header in cURL command: {value!r}")
    key, header_value = value.split(":", 1)
    return key.strip(), header_value.strip()


def set_header(headers, key, value):
    for existing_key in list(headers):
        if existing_key.lower() == key.lower():
            del headers[existing_key]
    headers[key] = value


def has_header(headers, key):
    return any(existing_key.lower() == key.lower() for existing_key in headers)


def parse_curl_command(text):
    normalized = normalize_curl_text(text)
    if not normalized:
        raise ValueError("The cURL input is empty.")
    if normalized.lower().startswith("invoke-webrequest") or normalized.lower().startswith("iwr "):
        raise ValueError("Please copy the browser request as cURL, preferably 'Copy as cURL (bash)'.")

    try:
        tokens = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise ValueError(f"Could not parse cURL input: {exc}") from exc

    if not tokens or not Path(tokens[0]).name.lower().startswith("curl"):
        raise ValueError("The input must start with a curl command copied from the browser.")

    request = {"method": "GET", "url": None, "headers": {}, "body": None}
    index = 1
    while index < len(tokens):
        token = tokens[index]

        if token in {"--compressed", "--location", "-L", "--globoff", "--http1.1", "--http2"}:
            index += 1
            continue

        option = token
        value = None
        if "=" in token and token.split("=", 1)[0] in VALUE_OPTIONS:
            option, value = token.split("=", 1)
        elif token in VALUE_OPTIONS:
            if token == "-I" or token == "--head":
                request["method"] = "HEAD"
                index += 1
                continue
            if index + 1 >= len(tokens):
                raise ValueError(f"Missing value after {token}.")
            value = tokens[index + 1]
            index += 2
        else:
            if token.startswith("-"):
                index += 1
                continue
            if request["url"] is None:
                request["url"] = token
            index += 1
            continue

        if option in {"-H", "--header"}:
            key, header_value = parse_header(value)
            set_header(request["headers"], key, header_value)
        elif option in {"-A", "--user-agent"}:
            set_header(request["headers"], "User-Agent", value)
        elif option in {"-b", "--cookie"}:
            existing_key = next((key for key in request["headers"] if key.lower() == "cookie"), None)
            existing = request["headers"].get(existing_key) if existing_key else None
            set_header(request["headers"], "Cookie", f"{existing}; {value}" if existing else value)
        elif option in {"-e", "--referer"}:
            set_header(request["headers"], "Referer", value)
        elif option in {"-X", "--request"}:
            request["method"] = value.upper()
        elif option == "--url":
            request["url"] = value
        elif option in BODY_OPTIONS:
            request["body"] = value.encode("utf-8")
            if request["method"] == "GET":
                request["method"] = "POST"

    if not request["url"]:
        raise ValueError("Could not find a URL in the cURL command.")
    return request


def request_origin(url):
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "https://www.sofascore.com"
    return f"{parsed.scheme}://{parsed.netloc}"


def build_probe_urls(base_request, args):
    urls = []
    if args.url:
        urls.extend(args.url)
    if args.path:
        origin = request_origin(base_request["url"])
        for path in args.path:
            urls.append(urllib.parse.urljoin(origin, path))
    if args.player_id:
        origin = request_origin(base_request["url"])
        urls.append(f"{origin}/api/v1/player/{args.player_id}")
        urls.append(f"{origin}/api/v1/player/{args.player_id}/events/last/0")
    if not urls:
        urls.append(base_request["url"])
    return dedupe_preserve_order(urls)


def dedupe_preserve_order(items):
    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def replay_headers(base_headers, keep_encoding):
    headers = {}
    drop = set(DROP_REPLAY_HEADERS)
    if not keep_encoding:
        drop |= DROP_ENCODING_HEADERS
    for key, value in base_headers.items():
        if key.lower() not in drop:
            headers[key] = value
    if not has_header(headers, "User-Agent"):
        headers["User-Agent"] = DEFAULT_USER_AGENT
    if not has_header(headers, "Accept"):
        headers["Accept"] = "application/json,text/plain,*/*"
    if not has_header(headers, "Referer"):
        headers["Referer"] = "https://www.sofascore.com/"
    return headers


def redact_headers(headers):
    redacted = {}
    for key, value in sorted(headers.items(), key=lambda item: item[0].lower()):
        if key.lower() in SENSITIVE_HEADERS:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def decode_body(raw, headers):
    encoding = ""
    for key, value in headers.items():
        if key.lower() == "content-encoding":
            encoding = value.lower()
            break
    if "gzip" in encoding:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def fetch_probe(url, base_request, args):
    headers = replay_headers(base_request["headers"], args.keep_encoding)
    body = base_request["body"] if base_request["method"] not in {"GET", "HEAD"} else None
    method = base_request["method"] if body else "GET"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as response:
            raw = response.read()
            response_headers = dict(response.headers.items())
            text = decode_body(raw, response_headers)
            return build_result(url, response.status, response.reason, response_headers, text, started)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        response_headers = dict(exc.headers.items())
        text = decode_body(raw, response_headers) if raw else ""
        return build_result(url, exc.code, exc.reason, response_headers, text, started)
    except urllib.error.URLError as exc:
        return {
            "url": url,
            "ok": False,
            "status_code": None,
            "reason": str(exc.reason),
            "elapsed_seconds": round(time.time() - started, 3),
            "json": None,
            "body_preview": None,
        }


def summarize_json(data):
    if isinstance(data, dict):
        summary = {"type": "object", "keys": sorted(data.keys())[:30]}
        for key in ["player", "events", "statistics", "seasons", "tournaments"]:
            value = data.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                summary[f"{key}_keys"] = sorted(value.keys())[:20]
        return summary
    if isinstance(data, list):
        summary = {"type": "array", "count": len(data)}
        if data and isinstance(data[0], dict):
            summary["first_item_keys"] = sorted(data[0].keys())[:20]
        return summary
    return {"type": type(data).__name__}


def build_result(url, status_code, reason, headers, text, started):
    parsed_json = None
    json_summary = None
    try:
        parsed_json = json.loads(text)
        json_summary = summarize_json(parsed_json)
    except json.JSONDecodeError:
        pass
    return {
        "url": url,
        "ok": 200 <= int(status_code) < 300,
        "status_code": int(status_code),
        "reason": reason,
        "elapsed_seconds": round(time.time() - started, 3),
        "content_type": next((value for key, value in headers.items() if key.lower() == "content-type"), None),
        "json_summary": json_summary,
        "json": parsed_json,
        "body_preview": None if parsed_json is not None else text[:800],
    }


def read_curl(args):
    if args.curl:
        return args.curl
    curl_file = Path(args.curl_file)
    if not curl_file.exists():
        raise FileNotFoundError(
            f"Could not find {curl_file}. Copy a SofaScore browser request as cURL into that file, "
            "or pass --curl."
        )
    return curl_file.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Replay a SofaScore browser-copied cURL request as a small 403/JSON access probe."
    )
    parser.add_argument("--curl-file", default=str(DEFAULT_CURL_FILE))
    parser.add_argument("--curl", default=None, help="Single-line cURL command. Prefer --curl-file for cookies.")
    parser.add_argument("--url", action="append", help="Full URL to probe. Can be repeated.")
    parser.add_argument("--path", action="append", help="Path on the copied request origin to probe. Can be repeated.")
    parser.add_argument("--player-id", type=int, help="Probe /api/v1/player/{id} and recent events for this player.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--keep-encoding", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Parse the request and print planned probes only.")
    args = parser.parse_args()

    try:
        base_request = parse_curl_command(read_curl(args))
    except Exception as exc:
        raise SystemExit(f"Could not prepare browser request probe: {exc}") from exc

    probe_urls = build_probe_urls(base_request, args)
    request_summary = {
        "source_url": base_request["url"],
        "method": base_request["method"],
        "headers": redact_headers(replay_headers(base_request["headers"], args.keep_encoding)),
        "probe_urls": probe_urls,
    }

    if args.dry_run:
        print(json.dumps({"request": request_summary}, indent=2, ensure_ascii=False))
        return

    results = [fetch_probe(url, base_request, args) for url in probe_urls]
    payload = {
        "metadata": {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "purpose": "SofaScore browser-request replay probe",
            "note": "Browser cookies/authorization headers are redacted and are not written to this result file.",
        },
        "request": request_summary,
        "probes": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for result in results:
        status = result["status_code"] if result["status_code"] is not None else "no response"
        print(f"{status} {result['url']}")
        if result["json_summary"]:
            print(f"  JSON: {result['json_summary']}")
        elif result["body_preview"]:
            print(f"  Body: {result['body_preview'][:180].replace(chr(10), ' ')}")
    print(f"wrote {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
