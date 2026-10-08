import argparse
import json
import os
import queue
import random
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from collect_player_performance_data import (
    BROWSER_CANDIDATES,
    CACHE_DIR,
    COMPLETED_STATUSES,
    CONFIG_FILE,
    MANIFEST_FILE,
    OUTPUT_FILE,
    ROOT,
    atomic_write_json,
    derive_scores,
    empty_stats_record,
    extract_sofascore_profile_candidates,
    parse_profile_page,
    polite_sleep,
    score_candidate,
    source_cache_path,
    web_search_urls,
)


EDGE_PROFILE_DIR = ROOT / ".cache" / "edge_cdp_profile"
EDGE_FETCHER_FILE = ROOT / "edge_cdp_fetcher.js"
CODEX_NODE = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"


def now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def detect_browser_path():
    for path in BROWSER_CANDIDATES:
        if path.exists():
            return path
    return None


def detect_node_path():
    if CODEX_NODE.exists():
        return CODEX_NODE
    found = shutil.which("node")
    return Path(found) if found else None


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("WebSocket closed")
        data.extend(chunk)
    return bytes(data)


class CDPWebSocket:
    def __init__(self, ws_url, timeout=60):
        parsed = urllib.parse.urlparse(ws_url)
        self.host = parsed.hostname
        self.port = parsed.port
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.next_id = 1
        self._handshake()

    def _handshake(self):
        key = os.urandom(16)
        import base64

        encoded_key = base64.b64encode(key).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Origin: http://127.0.0.1:{self.port}\r\n"
            f"Sec-WebSocket-Key: {encoded_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            response.extend(self.sock.recv(4096))
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError(response.decode("utf-8", errors="replace"))

    def send_text(self, text):
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126, (length >> 8) & 255, length & 255])
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        masked = bytes(payload[i] ^ mask[i % 4] for i in range(length))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_text(self):
        while True:
            first, second = read_exact(self.sock, 2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = int.from_bytes(read_exact(self.sock, 2), "big")
            elif length == 127:
                length = int.from_bytes(read_exact(self.sock, 8), "big")
            masked = bool(second & 0x80)
            mask = read_exact(self.sock, 4) if masked else b""
            payload = read_exact(self.sock, length) if length else b""
            if masked:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(length))
            if opcode == 1:
                return payload.decode("utf-8", errors="replace")
            if opcode == 8:
                raise ConnectionError("WebSocket closed by browser")
            if opcode == 9:
                self.sock.sendall(b"\x8a\x00")

    def command(self, method, params=None):
        message_id = self.next_id
        self.next_id += 1
        self.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            message = json.loads(self.recv_text())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class EdgeBrowser:
    def __init__(self, browser_path, node_path, port, profile_dir, timeout):
        self.browser_path = Path(browser_path)
        self.node_path = Path(node_path)
        self.port = port
        self.profile_dir = Path(profile_dir)
        self.timeout = timeout
        self.proc = None
        self.stdout_queue = queue.Queue()
        self.stderr_lines = []

    def _reader(self, stream, output_queue=None, output_lines=None):
        for line in iter(stream.readline, ""):
            if output_queue is not None:
                output_queue.put(line)
            if output_lines is not None:
                output_lines.append(line)

    def start(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.node_path),
            str(EDGE_FETCHER_FILE),
            "--browser-path",
            str(self.browser_path),
            "--profile-dir",
            str(self.profile_dir),
            "--port",
            str(self.port),
            "--timeout-ms",
            str(int(self.timeout * 1000)),
        ]
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._reader, args=(self.proc.stdout, self.stdout_queue, None), daemon=True).start()
        threading.Thread(target=self._reader, args=(self.proc.stderr, None, self.stderr_lines), daemon=True).start()
        ready = self._read_message()
        if ready.get("status") != "ready":
            raise RuntimeError(f"Edge helper failed to start: {ready}. {' '.join(self.stderr_lines[-5:])}")

    def _read_message(self):
        try:
            line = self.stdout_queue.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"Edge helper did not respond. {' '.join(self.stderr_lines[-5:])}") from exc
        return json.loads(line)

    def html(self, url, settle_seconds=4):
        self.proc.stdin.write(json.dumps({"url": url, "settleSeconds": settle_seconds}) + "\n")
        self.proc.stdin.flush()
        message = self._read_message()
        if message.get("status") != "ok":
            raise RuntimeError(message.get("error") or "Edge helper failed to fetch page")
        return message["page"]

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"command": "close"}) + "\n")
                self.proc.stdin.flush()
                self._read_message()
            except Exception:
                pass
            try:
                self.proc.terminate()
            except OSError:
                pass


def is_forbidden(page):
    text = f"{page.get('title', '')}\n{page.get('text', '')}".lower()
    return "403 forbidden" in text or "access denied" in text or "request blocked" in text


def browser_cache_path(url):
    return source_cache_path(url + "#edge-cdp", "html")


def load_browser_html(browser, url, args):
    cache_path = browser_cache_path(url)
    if cache_path.exists() and not args.refresh_cache:
        return {
            "url": url,
            "title": "",
            "text": "",
            "html": cache_path.read_text(encoding="utf-8"),
            "from_cache": True,
        }
    page = browser.html(url, settle_seconds=args.settle_seconds)
    cache_path.write_text(page["html"], encoding="utf-8")
    polite_sleep(args.delay, args.jitter)
    return page


def discover_profile(browser, player, args):
    best = None
    best_score = 0.0
    attempts = []
    for search_url in web_search_urls(player):
        page = load_browser_html(browser, search_url, args)
        candidates = extract_sofascore_profile_candidates(page["html"])
        for candidate in candidates:
            current_score = score_candidate(player, candidate)
            if current_score > best_score:
                best = candidate
                best_score = current_score
        attempts.append(
            {
                "url": search_url,
                "status": "forbidden" if is_forbidden(page) else "searched",
                "candidate_count": len(candidates),
            }
        )
        if best_score >= 0.92:
            break
    if best and best_score >= args.identity_threshold:
        best["match_score"] = round(best_score, 3)
        best["discovery_source"] = "edge_web_search"
        return best, attempts
    return None, attempts


def collect_player(browser, player, config, args):
    record = empty_stats_record(player)
    record["collected_at"] = now_iso()
    record["source_attempts"] = {}
    candidate, attempts = discover_profile(browser, player, args)
    record["source_attempts"]["edge_web_search"] = {"status": "matched" if candidate else "not_matched", "attempts": attempts}
    if not candidate:
        record["collection_status"] = "identity_not_matched"
        return record

    record["sources"]["sofascore"] = candidate
    page = load_browser_html(browser, candidate["url"], args)
    record["source_attempts"]["edge_profile_page"] = {
        "status": "forbidden" if is_forbidden(page) else "collected",
        "url": page.get("url"),
        "title": page.get("title"),
    }
    if is_forbidden(page):
        record["collection_status"] = "primary_source_forbidden_browser"
        return record

    profile = parse_profile_page(page["html"], candidate["url"])
    record["profile"].update(profile)
    derive_scores(record, config)
    record["collection_status"] = "profile_collected" if record["profile"] else "identity_matched_stats_unavailable"
    return record


def load_records(output_path):
    path = Path(output_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {record["player_key"]: record for record in data.get("players", []) if record.get("player_key")}


def write_output(path, args, players, records_by_key):
    rows = [records_by_key.get(player["player_key"], empty_stats_record(player)) for player in players]
    counts = {}
    for record in rows:
        counts[record["collection_status"]] = counts.get(record["collection_status"], 0) + 1
    payload = {
        "metadata": {
            "schema_version": 2,
            "created_at": now_iso(),
            "source_manifest": Path(args.manifest).name,
            "config": Path(args.config).name,
            "player_count": len(players),
            "status": "edge_browser_profile_collection",
            "primary_source": "SofaScore public player profile pages via visible Edge browser",
            "browser": str(args.browser_path),
            "node": str(args.node_path),
            "collection_status_counts": dict(sorted(counts.items())),
            "rate_limit_policy": {
                "delay_seconds": args.delay,
                "jitter_seconds": args.jitter,
                "write_every_players": args.write_every,
            },
            "notes": [
                "This collector avoids direct SofaScore JSON endpoints because they return 403 Forbidden.",
                "It opens a normal Edge window with a temporary profile and reads public profile pages.",
                "Profile pages provide lower-resolution evidence than full match-stat endpoints.",
            ],
        },
        "players": rows,
    }
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
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--settle-seconds", type=float, default=4.0)
    parser.add_argument("--identity-threshold", type=float, default=0.74)
    parser.add_argument("--write-every", type=int, default=5)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-complete", action="store_true")
    parser.add_argument("--keep-browser-open", action="store_true")
    args = parser.parse_args()
    args.write_every = max(1, args.write_every)
    args.browser_path = detect_browser_path()
    args.node_path = detect_node_path()
    if not args.browser_path:
        raise SystemExit("Could not find Edge or Chrome.")
    if not args.node_path:
        raise SystemExit("Could not find Node.js. Use Node 22+ or the Codex-bundled Node runtime.")

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    players = manifest["players"]
    worklist = selected_players(players, args.start, args.limit)
    records_by_key = load_records(args.output)
    for player in players:
        records_by_key.setdefault(player["player_key"], empty_stats_record(player))

    browser = EdgeBrowser(args.browser_path, args.node_path, free_port(), EDGE_PROFILE_DIR, args.timeout)
    browser.start()
    try:
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
            records_by_key[player["player_key"]] = collect_player(browser, player, config, args)
            if offset % args.write_every == 0:
                write_output(args.output, args, players, records_by_key)
        write_output(args.output, args, players, records_by_key)
    finally:
        if args.keep_browser_open:
            print("Edge left open because --keep-browser-open was used.")
        else:
            browser.close()
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
