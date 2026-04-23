#!/usr/bin/env python3
"""
Netease Music → Spotify Migration Tool - Web UI
Run: python app.py  (then open http://localhost:5050)
"""

from flask import Flask, jsonify, send_from_directory, Response, stream_with_context
import threading
import time
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="static")

NETEASE_FILE = Path("netease_liked.json")
MATCHED_FILE = Path("matched.json")
REVIEW_FILE = Path("review.json")
NOT_FOUND_FILE = Path("not_found.json")

# ── Run state ────────────────────────────────────────────────────────────────

_run_id = 0
_current_run_id = None
_run_logs: dict = {}   # run_id -> [{"type": ..., "text": ...}]
_run_status: dict = {} # run_id -> "running" | "done" | "error"
_lock = threading.Lock()


def _add_log(run_id, text, msg_type="log"):
    with _lock:
        if run_id in _run_logs:
            _run_logs[run_id].append({"type": msg_type, "text": text})


class _PrintCapture:
    """Redirects stdout to the log list during a migration run."""
    def __init__(self, run_id):
        self.run_id = run_id
        self._buf = ""

    def write(self, text):
        # Normalise \r (used by progress prints like end="\r") to \n
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                _add_log(self.run_id, line)

    def flush(self):
        if self._buf.strip():
            _add_log(self.run_id, self._buf)
            self._buf = ""


def _run_migration(run_id, phase):
    old_stdout = sys.stdout
    sys.stdout = _PrintCapture(run_id)
    try:
        import migrate
        import importlib
        importlib.reload(migrate)  # pick up fresh file state

        if phase == "export":
            songs = migrate.phase_export()
            _add_log(run_id, f"Export complete — {len(songs)} songs", "success")

        elif phase == "match":
            if not NETEASE_FILE.exists():
                _add_log(run_id, "Error: Please run the Export step first", "error")
                with _lock:
                    _run_status[run_id] = "error"
                return
            songs = migrate.load_json(NETEASE_FILE)
            matched, review, not_found = migrate.phase_match(songs)
            _add_log(
                run_id,
                f"Matching complete — Matched: {len(matched)}  Review: {len(review)}  Not found: {len(not_found)}",
                "success",
            )

        elif phase == "save":
            if not MATCHED_FILE.exists():
                _add_log(run_id, "Error: Please run the Match step first", "error")
                with _lock:
                    _run_status[run_id] = "error"
                return
            matched = migrate.load_json(MATCHED_FILE)
            migrate.phase_save(matched)
            _add_log(run_id, f"Saved {len(matched)} songs to Spotify", "success")

        elif phase == "all":
            songs = migrate.phase_export()
            matched, review, not_found = migrate.phase_match(songs)
            migrate.phase_save(matched)
            total = len(matched) + len(review) + len(not_found)
            _add_log(
                run_id,
                f"All done! {total} total — Saved: {len(matched)}  Review: {len(review)}  Not found: {len(not_found)}",
                "success",
            )

        with _lock:
            _run_status[run_id] = "done"

    except Exception as e:
        _add_log(run_id, f"Error: {e}", "error")
        with _lock:
            _run_status[run_id] = "error"
    finally:
        sys.stdout = old_stdout


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status")
def status():
    def count(path):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return len(json.load(f))
        return 0

    return jsonify({
        "netease_count":  count(NETEASE_FILE),
        "matched_count":  count(MATCHED_FILE),
        "review_count":   count(REVIEW_FILE),
        "not_found_count": count(NOT_FOUND_FILE),
        "has_netease":    NETEASE_FILE.exists(),
        "has_matched":    MATCHED_FILE.exists(),
        "is_running":     _run_status.get(_current_run_id) == "running",
        "current_run_id": _current_run_id,
    })


@app.route("/api/songs/<category>")
def get_songs(category):
    files = {
        "matched":   MATCHED_FILE,
        "review":    REVIEW_FILE,
        "not_found": NOT_FOUND_FILE,
        "netease":   NETEASE_FILE,
    }
    path = files.get(category)
    if not path or not path.exists():
        return jsonify([])
    with open(path, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/run/<phase>", methods=["POST"])
def run_phase(phase):
    global _run_id, _current_run_id

    if _run_status.get(_current_run_id) == "running":
        return jsonify({"error": "Already running"}), 409

    if phase not in ["export", "match", "save", "all"]:
        return jsonify({"error": "Invalid phase"}), 400

    with _lock:
        _run_id += 1
        rid = _run_id
        _current_run_id = rid
        _run_logs[rid] = []
        _run_status[rid] = "running"

    thread = threading.Thread(target=_run_migration, args=(rid, phase), daemon=True)
    thread.start()

    return jsonify({"run_id": rid})


@app.route("/api/stream/<int:run_id>")
def stream(run_id):
    def generate():
        sent = 0
        while True:
            with _lock:
                batch = list(_run_logs.get(run_id, [])[sent:])
                status = _run_status.get(run_id)

            for msg in batch:
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            sent += len(batch)

            if status != "running":
                # flush any remaining messages then signal done
                with _lock:
                    remaining = list(_run_logs.get(run_id, [])[sent:])
                for msg in remaining:
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'status': status})}\n\n"
                break

            time.sleep(0.15)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    print("Starting Netease → Spotify Migration UI")
    print("Open http://localhost:5050 in your browser")
    app.run(debug=False, port=5050, threaded=True)
