"""Local web GUI (Flask) for the Sidon pipeline. Run with `python -m speech_enhancer gui`."""

from __future__ import annotations

import subprocess
import threading
import webbrowser
from dataclasses import asdict
from pathlib import Path

import numpy as np
from flask import Flask, abort, jsonify, request, send_file

from .workspace import Workspace

STATIC = Path(__file__).resolve().parent / "static"


def _osascript_choose(kind: str) -> list[str]:
    """Native macOS open dialog (files or folder); returns POSIX paths, [] if cancelled."""
    if kind == "folder":
        script = 'POSIX path of (choose folder with prompt "Choose a folder")'
    else:
        script = (
            'set fs to choose file with prompt "Choose audio files" of type {"public.audio"} with multiple selections allowed\n'
            'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nreturn out'
        )
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return [line for line in res.stdout.splitlines() if line.strip()] if res.returncode == 0 else []


def create_app(ws: Workspace | None = None) -> Flask:
    ws = ws or Workspace()
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")

    def entry_or_404(fid: str):
        try:
            return ws.get(fid)
        except KeyError:
            abort(404)

    @app.get("/")
    def index():
        return send_file(STATIC / "index.html")

    @app.get("/api/state")
    def state():
        with ws.lock:
            files = [e.summary() for e in ws.files.values()]
        return jsonify(files=files, model=ws.model_status, queue=ws.jobs.qsize(), settings=asdict(ws.settings))

    @app.put("/api/settings")
    def put_settings():
        for k, v in (request.json or {}).items():
            if hasattr(ws.settings, k):
                setattr(ws.settings, k, type(getattr(ws.settings, k))(v))
        return jsonify(asdict(ws.settings))

    @app.post("/api/pick")
    def pick():
        kind = (request.json or {}).get("kind", "files")
        paths = _osascript_choose("folder" if kind in ("folder", "output") else "files")
        if kind == "output":
            if paths:
                ws.settings.output_dir = paths[0]
            return jsonify(paths=paths)
        return jsonify(added=ws.add_paths(paths))

    @app.post("/api/files")
    def add_files():
        return jsonify(added=ws.add_paths(request.json.get("paths", [])))

    @app.get("/api/files/<fid>")
    def file_details(fid):
        entry_or_404(fid)
        return jsonify(ws.details(fid))

    @app.delete("/api/files/<fid>")
    def remove_file(fid):
        ws.remove(fid)
        return jsonify(ok=True)

    @app.get("/api/files/<fid>/peaks/<which>")
    def peaks(fid, which):
        entry_or_404(fid)
        p = ws.cache_dir(fid) / f"peaks_{which}.npy"
        if which not in ("original", "enhanced") or not p.exists():
            abort(404)
        return jsonify(np.load(p).astype(np.float32).round(3).tolist())

    @app.get("/api/files/<fid>/audio/<which>")
    def audio(fid, which):
        e = entry_or_404(fid)
        if which == "original":
            path = ws.cache_dir(fid) / "original.wav"
        elif which == "enhanced" and e.output_path:
            path = Path(e.output_path)
        elif which.startswith("preview-") and int(which[8:]) in e.previews:
            path = Path(e.previews[int(which[8:])])
        else:
            abort(404)
        return send_file(path, mimetype="audio/wav", conditional=True, max_age=0)

    @app.put("/api/files/<fid>/segmentation")
    def put_segmentation(fid):
        entry_or_404(fid)
        body = request.json or {}
        ws.set_segmentation(fid, cuts=body.get("cuts"), speech=body.get("speech"))
        return jsonify(ws.details(fid))

    @app.post("/api/files/<fid>/reset-speech")
    def reset_speech(fid):
        entry_or_404(fid)
        ws.reset_speech(fid)
        return jsonify(ws.details(fid))

    @app.post("/api/files/<fid>/resegment")
    def resegment(fid):
        entry_or_404(fid)
        ws.resegment(fid)
        return jsonify(ws.details(fid))

    @app.post("/api/files/<fid>/preview/<int:k>")
    def preview(fid, k):
        entry_or_404(fid)
        ws.enqueue("preview", fid, k)
        return jsonify(ok=True)

    @app.post("/api/files/<fid>/enhance")
    def enhance(fid):
        e = entry_or_404(fid)
        if e.status not in ("enhancing", "queued", "analyzing"):
            ws.enqueue("enhance", fid)
        return jsonify(ok=True)

    @app.post("/api/files/<fid>/cancel")
    def cancel(fid):
        entry_or_404(fid)
        ws.cancel(fid)
        return jsonify(ok=True)

    @app.post("/api/files/<fid>/reveal")
    def reveal(fid):
        e = entry_or_404(fid)
        target = e.output_path or e.path
        subprocess.run(["open", "-R", target], check=False)
        return jsonify(ok=True)

    return app


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, files: list[str] | None = None) -> None:
    ws = Workspace()
    if files:
        ws.add_paths(files)
    app = create_app(ws)
    url = f"http://{host}:{port}/"
    print(f"Stentor GUI -> {url}  (Ctrl+C to quit)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, threaded=True, use_reloader=False)
