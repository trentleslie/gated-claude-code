import http.client
import json
import shutil
import threading

import pytest

from gated_cs.service.api import make_server

requires_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")

TOKEN = "s3cr3t-test-token"


@pytest.fixture
def server(tmp_path):
    dict_dir = tmp_path / "dict"
    syn_dir = dict_dir / "synthetic_samples"
    syn_dir.mkdir(parents=True)
    (dict_dir / "dictionary.json").write_text(json.dumps({"files": ["a.csv"]}))
    (dict_dir / "dictionary.md").write_text("# Dictionary\n\nfile: a.csv\n")
    (syn_dir / "a.csv").write_text("client,val\nc1,1\nc2,2\n")
    (syn_dir / "b.csv").write_text("client,val\nc3,3\n")

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n")  # deliberately un-stripped to exercise .strip()

    srv = make_server(
        bind="127.0.0.1",
        port=0,
        data_dir=str(tmp_path / "data"),
        dict_dir=str(dict_dir),
        audit=str(tmp_path / "audit.jsonl"),
        queue=str(tmp_path / "queue"),
        results=str(tmp_path / "results"),
        token_file=str(token_file),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    thread.join(timeout=5)
    srv.server_close()


def _conn(server):
    return http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)


def _get(server, path, token=None):
    conn = _conn(server)
    headers = {"X-Gate-Token": token} if token is not None else {}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _post(server, path, body_bytes, token=None):
    conn = _conn(server)
    headers = {"X-Gate-Token": token} if token is not None else {}
    conn.request("POST", path, body=body_bytes, headers=headers)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


# -- /health ------------------------------------------------------------


def test_health_no_token_required(server):
    status, body = _get(server, "/health")
    assert status == 200
    assert json.loads(body) == {"ok": True}


# -- auth -----------------------------------------------------------------


def test_dictionary_requires_token(server):
    status, body = _get(server, "/dictionary.json")
    assert status == 401

    status, body = _get(server, "/dictionary.json", token="wrong-token")
    assert status == 401

    status, body = _get(server, "/dictionary.json", token=TOKEN)
    assert status == 200
    assert json.loads(body) == {"files": ["a.csv"]}


def test_dictionary_md(server):
    status, body = _get(server, "/dictionary.md", token=TOKEN)
    assert status == 200
    assert b"Dictionary" in body


# -- synthetic --------------------------------------------------------------


def test_synthetic_listing_and_fetch(server):
    status, body = _get(server, "/synthetic", token=TOKEN)
    assert status == 200
    assert json.loads(body) == ["a.csv", "b.csv"]

    status, body = _get(server, "/synthetic/a.csv", token=TOKEN)
    assert status == 200
    assert body == b"client,val\nc1,1\nc2,2\n"


def test_synthetic_missing_file_404(server):
    status, body = _get(server, "/synthetic/nope.csv", token=TOKEN)
    assert status == 404


def test_synthetic_path_traversal_sanitized(server):
    # basename-stripping means "../../../etc/passwd" collapses to "passwd", which
    # doesn't exist in synthetic_samples/ -> 404, never escapes the directory.
    status, body = _get(server, "/synthetic/..%2F..%2F..%2Fetc%2Fpasswd", token=TOKEN)
    assert status == 404


# -- submit -----------------------------------------------------------------


@requires_bwrap
def test_submit_clean_aggregate_released(server):
    script = (
        "import pandas as pd, os\n"
        "pd.DataFrame({'group': ['a', 'b'], 'count': [80, 60]})"
        ".to_csv(os.path.join(os.environ['OUTPUT_DIR'], 'r.csv'), index=False)\n"
    ).encode()
    status, body = _post(server, "/submit", script, token=TOKEN)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "released"
    assert len(payload["outputs"]) == 1
    assert payload["outputs"][0]["name"].endswith("r.csv")
    assert "group" in payload["outputs"][0]["content"]
    assert "count" in payload["outputs"][0]["content"]


@requires_bwrap
def test_submit_row_dump_queued_with_empty_outputs(server):
    script = (
        "import pandas as pd, os\n"
        "pd.DataFrame({'x': range(100)})"
        ".to_csv(os.path.join(os.environ['OUTPUT_DIR'], 'r.csv'), index=False)\n"
    ).encode()
    status, body = _post(server, "/submit", script, token=TOKEN)
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] == "queued"
    assert payload["outputs"] == []


def test_submit_requires_token(server):
    status, body = _post(server, "/submit", b"x = 1\n")
    assert status == 401


# -- differencing-monitor session boundary (Greptile P1 #3) --------------

def _mk(tmp_path, **kw):
    return make_server(
        bind="127.0.0.1", port=0, token="t",
        data_dir=str(tmp_path / "data"), dict_dir=str(tmp_path / "dict"),
        audit=str(tmp_path / "audit.jsonl"), queue=str(tmp_path / "queue"),
        results=str(tmp_path / "results"), **kw,
    )


def test_make_server_assigns_distinct_session_per_process(tmp_path):
    # each server process is one differencing boundary, so unrelated server runs (a restart,
    # a separate deployment) never share a session that could fuse their activity.
    s1, s2 = _mk(tmp_path), _mk(tmp_path)
    try:
        assert s1.gate_config["session"].startswith("api-")
        assert s1.gate_config["session"] != s2.gate_config["session"]
    finally:
        s1.server_close(); s2.server_close()


def test_make_server_honors_explicit_session(tmp_path):
    s = _mk(tmp_path, session="api-fixed")
    try:
        assert s.gate_config["session"] == "api-fixed"
    finally:
        s.server_close()


@requires_bwrap
def test_submit_stamps_server_session_on_audit(server):
    # end-to-end: a submission's audit record carries the server's per-process session, so
    # the offline monitor can scope this caller's activity without fusing unrelated servers.
    script = (
        "import pandas as pd, os\n"
        "pd.DataFrame({'group': ['a', 'b'], 'count': [80, 60]})"
        ".to_csv(os.path.join(os.environ['OUTPUT_DIR'], 'r.csv'), index=False)\n"
    ).encode()
    status, _ = _post(server, "/submit", script, token=TOKEN)
    assert status == 200
    sess = server.gate_config["session"]
    entries = [json.loads(l) for l in open(server.gate_config["audit"]) if l.strip()]
    art = [e for e in entries if e.get("artifact", "").endswith("r.csv")]
    assert art and all(e.get("session") == sess for e in art)
