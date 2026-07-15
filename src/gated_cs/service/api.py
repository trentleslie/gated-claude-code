"""Localhost gate-API service.

Gives a sandboxed, network-restricted agent (which can only make approved
localhost connections and cannot reach /var/gate directly) access to the
same dictionary / synthetic samples / script-submission gate used elsewhere
in this repo, over plain HTTP on 127.0.0.1. Standard library only: no new
dependency is introduced by this module.

Endpoints:
  GET  /health              -- no auth
  GET  /dictionary.json     -- auth required
  GET  /dictionary.md       -- auth required
  GET  /synthetic           -- auth required; list of filenames
  GET  /synthetic/<name>    -- auth required; csv content
  POST /submit              -- auth required; body = raw script bytes

Auth: header ``X-Gate-Token`` must equal the contents of GATE_TOKEN_FILE,
compared with hmac.compare_digest.
"""
import hmac
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from gated_cs.gate.run_analysis import run


def _default_config():
    return {
        "data_dir": os.environ.get(
            "GATE_DATA_DIR", "/procedure/data/local_data/ARIVALE_SNAPSHOTS_2025"
        ),
        "dict_dir": os.environ.get("GATE_DICT_DIR", "/var/gate/dict"),
        "audit": os.environ.get("GATE_AUDIT", "/var/gate/audit.jsonl"),
        "queue": os.environ.get("GATE_QUEUE", "/var/gate/queue"),
        "results": os.environ.get("GATE_RESULTS", "/var/gate/results"),
        "token_file": os.environ.get("GATE_TOKEN_FILE", "/var/gate/service.token"),
        "bind": os.environ.get("GATE_BIND", "127.0.0.1"),
        "port": int(os.environ.get("GATE_PORT", "8899")),
    }


class GateAPIHandler(BaseHTTPRequestHandler):
    """Reads per-server config from ``self.server.gate_config`` (not module
    globals) so tests can point independent server instances at tmp dirs."""

    server_version = "GateAPI/1.0"

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test/CLI output quiet; audit.jsonl is the real trail

    # -- helpers ----------------------------------------------------------

    @property
    def _cfg(self):
        return self.server.gate_config

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        supplied = self.headers.get("X-Gate-Token", "")
        return hmac.compare_digest(supplied, self._cfg["token"])

    def _require_auth(self):
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return False
        return True

    # -- GET ----------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._send_json(200, {"ok": True})
            return

        if not self._require_auth():
            return

        cfg = self._cfg

        if path == "/dictionary.json":
            self._serve_file(os.path.join(cfg["dict_dir"], "dictionary.json"), "application/json")
            return

        if path == "/dictionary.md":
            self._serve_file(os.path.join(cfg["dict_dir"], "dictionary.md"), "text/markdown")
            return

        if path == "/synthetic":
            syn_dir = os.path.join(cfg["dict_dir"], "synthetic_samples")
            names = []
            if os.path.isdir(syn_dir):
                names = sorted(
                    n for n in os.listdir(syn_dir) if os.path.isfile(os.path.join(syn_dir, n))
                )
            self._send_json(200, names)
            return

        if path.startswith("/synthetic/"):
            raw_name = unquote(path[len("/synthetic/") :])
            name = os.path.basename(raw_name)  # strips any "/" or ".." traversal components
            syn_dir = os.path.join(cfg["dict_dir"], "synthetic_samples")
            if not name:
                self._send_json(404, {"error": "not found"})
                return
            self._serve_file(os.path.join(syn_dir, name), "text/csv")
            return

        self._send_json(404, {"error": "not found"})

    def _serve_file(self, path, content_type):
        if not os.path.isfile(path):
            self._send_json(404, {"error": "not found"})
            return
        with open(path, "rb") as f:
            self._send_bytes(200, content_type, f.read())

    # -- POST ---------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/submit":
            self._send_json(404, {"error": "not found"})
            return
        if not self._require_auth():
            return

        try:
            self._handle_submit()
        except Exception:
            # never leak a raw traceback or data content in an error response
            self._send_json(500, {"error": "internal error"})

    def _handle_submit(self):
        cfg = self._cfg
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else b""

        scratch_dir = tempfile.mkdtemp(prefix="svc_scratch_")
        script_path = os.path.join(scratch_dir, "script.py")
        with open(script_path, "wb") as f:
            f.write(body)

        out_dir = tempfile.mkdtemp(prefix="svc_out_")

        # force the bwrap sandbox for the child that runs an untrusted, network-submitted
        # script (fail-closed if bwrap is unavailable — see run_analysis.run())
        os.environ["GATED_CS_REQUIRE_SANDBOX"] = "1"

        result = run(
            script_path,
            cfg["data_dir"],
            out_dir,
            cfg["audit"],
            cfg["queue"],
            results_dir=cfg["results"],
        )

        outputs = []
        for p in result.get("outputs") or []:
            try:
                with open(p, "r") as f:
                    content = f.read()
            except OSError:
                continue
            outputs.append({"name": os.path.basename(p), "content": content})

        self._send_json(
            200,
            {"status": result["status"], "message": result["message"], "outputs": outputs},
        )


def make_server(
    bind=None,
    port=None,
    data_dir=None,
    dict_dir=None,
    audit=None,
    queue=None,
    results=None,
    token_file=None,
    token=None,
):
    """Build a configured, bound (not-yet-serving) ThreadingHTTPServer.

    Explicit args override env/defaults, so tests can point a server at tmp dirs
    without mutating process env. If ``token`` is given it is used directly;
    otherwise the token is read (and stripped) from ``token_file``.
    """
    cfg = _default_config()
    overrides = {
        "bind": bind,
        "port": port,
        "data_dir": data_dir,
        "dict_dir": dict_dir,
        "audit": audit,
        "queue": queue,
        "results": results,
        "token_file": token_file,
    }
    for key, val in overrides.items():
        if val is not None:
            cfg[key] = val

    if token is not None:
        cfg["token"] = token
    else:
        with open(cfg["token_file"]) as f:
            cfg["token"] = f.read().strip()

    # untrusted, network-submitted scripts must always run sandboxed
    os.environ["GATED_CS_REQUIRE_SANDBOX"] = "1"

    server = ThreadingHTTPServer((cfg["bind"], cfg["port"]), GateAPIHandler)
    server.gate_config = cfg
    return server


def main():
    server = make_server()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
