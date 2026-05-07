#!/usr/bin/env python3
"""
swagger2py web UI — Flask backend

Usage:
    pip install flask pyyaml
    python app.py
    # open http://localhost:5000
"""

from __future__ import annotations

import io
import json
import os
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from swagger2py import (
    detect_version,
    generate,
    _normalise_swagger2,
    _spec_summary as _print_summary,
)

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

app = Flask(__name__, static_folder="static")

STATIC_DIR = Path(__file__).parent / "static"


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_upload(file_storage) -> dict:
    """Read an uploaded FileStorage object into a spec dict."""
    raw = file_storage.read()
    name = (file_storage.filename or "").lower()
    if name.endswith((".yaml", ".yml")):
        if not _HAS_YAML:
            raise ValueError("PyYAML is not installed — cannot parse YAML files.")
        return _yaml.safe_load(raw)
    return json.loads(raw)


def _spec_info(spec: dict) -> dict:
    """Return a JSON-serialisable summary of the spec."""
    import copy
    s = copy.deepcopy(spec)
    version = detect_version(s)
    if version == "swagger2":
        s = _normalise_swagger2(s)

    info = s.get("info", {})
    paths = s.get("paths", {})
    ops = sum(
        1 for pi in paths.values() if isinstance(pi, dict)
        for m in ("get", "post", "put", "patch", "delete", "head", "options", "trace")
        if m in pi
    )
    schemas = len(s.get("components", {}).get("schemas", {}))
    sec = list(s.get("components", {}).get("securitySchemes", {}).keys())
    servers = [sv.get("url", "") for sv in s.get("servers", []) if isinstance(sv, dict)]
    webhooks = len(s.get("webhooks", {}))
    channels = len(s.get("channels", {}))

    return {
        "format": version,
        "title": info.get("title", ""),
        "version": info.get("version", ""),
        "description": (info.get("description") or "")[:200],
        "paths": len(paths),
        "operations": ops,
        "schemas": schemas,
        "security": sec,
        "servers": servers,
        "webhooks": webhooks,
        "channels": channels,
    }


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/info", methods=["POST"])
def api_info():
    """Return spec summary without generating code."""
    if "spec" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    try:
        spec = _parse_upload(request.files["spec"])
        return jsonify(_spec_info(spec))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 422


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Generate Python client and return code + metadata."""
    if "spec" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    use_async = request.form.get("async", "false").lower() == "true"
    validate  = request.form.get("validate", "true").lower() == "true"
    base_url  = request.form.get("base_url", "").strip() or None

    try:
        import copy
        spec = _parse_upload(request.files["spec"])
        info = _spec_info(spec)

        # Patch in custom base_url before generation
        if base_url:
            spec = copy.deepcopy(spec)
            spec.setdefault("servers", [])
            if spec["servers"]:
                spec["servers"][0]["url"] = base_url
            else:
                spec["servers"] = [{"url": base_url}]

        code = generate(spec, use_async=use_async, validate=validate)

        # Derive suggested filename
        from swagger2py import _safe_name
        title = spec.get("info", {}).get("title", "client")
        filename = _safe_name(title.replace(" ", "_")) + ".py"

        return jsonify({
            "code": code,
            "filename": filename,
            "lines": len(code.splitlines()),
            "bytes": len(code.encode()),
            "info": info,
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 422


if __name__ == "__main__":
    STATIC_DIR.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    print(f"swagger2py UI running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
