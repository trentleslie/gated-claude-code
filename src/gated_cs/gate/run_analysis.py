import argparse, hashlib, os, shutil, subprocess, sys, uuid
import pandas as pd
from .sdc import check_table
from .scrub import scrub
from .audit import AuditLog
from ..config import DEFAULTS

def _hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]

def _iter_artifacts(out_dir):
    # every regular file the script left anywhere under out_dir, as (fullpath, relname)
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            full = os.path.join(root, name)
            yield full, os.path.relpath(full, out_dir)

def _sandbox_available():
    return shutil.which("bwrap") is not None and os.environ.get("GATED_CS_NO_SANDBOX") != "1"

def _interpreter_binds():
    # The interpreter running us may live outside /usr,/bin,/lib,/lib64,/etc — e.g. a
    # project venv (uv/.venv) whose python is a symlink into a uv-managed base install
    # under ~/.local/share/uv. Without these, the sandboxed child can't import stdlib
    # or any installed package (pandas, etc.) even though it's the *same* interpreter
    # the gate itself is running under. Bind each real, non-system prefix read-only.
    already = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")
    binds, seen = [], set()
    for candidate in (sys.prefix, sys.base_prefix, os.path.dirname(os.path.realpath(sys.executable))):
        real = os.path.realpath(candidate)
        # path-boundary-aware: real=="/usr" or real under "/usr/" should be skipped, but
        # real=="/usrlocal" must NOT false-match "/usr" via a naive startswith().
        if real in seen or any(real == c or real.startswith(c + os.sep) for c in already) \
                or not os.path.exists(real):
            continue
        seen.add(real)
        binds += ["--ro-bind", real, real]
    return binds

def _child_command(script_path, data_dir, out_dir):
    py = sys.executable
    if not _sandbox_available():
        return [py, script_path]
    return [
        "bwrap",
        "--unshare-net", "--unshare-pid", "--new-session", "--die-with-parent", "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/sbin", "/sbin",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/etc", "/etc",
        *_interpreter_binds(),
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        # bind these AFTER --tmpfs /tmp: in dev/test data_dir/out_dir/script_path can be
        # nested under /tmp, and bwrap applies mounts in order, so a later specific bind
        # must win over the earlier tmpfs to stay visible in the sandbox.
        "--ro-bind-try", data_dir, data_dir,   # real data: READ-ONLY (tolerate absence — not
                                                # every run touches DATA_DIR, e.g. in tests)
        "--ro-bind", script_path, script_path, # the submitted script: readable in sandbox
        "--bind", out_dir, out_dir,            # ONLY writable path
        "--setenv", "OUTPUT_DIR", out_dir,
        "--setenv", "DATA_DIR", data_dir,
        "--setenv", "PATH", os.environ.get("PATH", "/usr/bin:/bin"),
        "--setenv", "HOME", "/tmp",
        py, script_path,
    ]

def _quarantine(full, rel, queue_dir, sh):
    # unique flat destination so no two quarantined artifacts (across runs OR within a
    # run via path-flattening) can overwrite each other; queue_dir stays flat for review.
    safe_name = rel.replace(os.sep, "_")
    dest = os.path.join(queue_dir, f"{sh}_{uuid.uuid4().hex[:8]}_{safe_name}")
    shutil.move(full, dest)
    return dest

def _deliver(df_or_path, rel, results_dir, sh):
    # write a RELEASED artifact into the shared results dir with a unique, flat name
    # so cs-gated (which cannot see cs-exec-private out_dir) can retrieve it.
    safe_name = rel.replace(os.sep, "_")
    dest = os.path.join(results_dir, f"{sh}_{uuid.uuid4().hex[:8]}_{safe_name}")
    if isinstance(df_or_path, str):
        shutil.copy(df_or_path, dest)
    else:
        df_or_path.to_csv(dest, index=False)   # already-gated (masked) frame
    return dest

def run(script_path, data_dir, out_dir, audit_path, queue_dir, results_dir=None, thresholds=DEFAULTS):
    os.makedirs(out_dir, exist_ok=True); os.makedirs(queue_dir, exist_ok=True)
    if results_dir is not None:
        os.makedirs(results_dir, exist_ok=True)
    audit = AuditLog(audit_path)
    # env for launching bwrap itself / the no-sandbox fallback; the sandboxed child's env
    # is set entirely by --clearenv + --setenv in _child_command
    env = {"OUTPUT_DIR": out_dir, "DATA_DIR": data_dir,
           "PATH": os.environ.get("PATH", ""), "HOME": out_dir}
    sh = _hash(script_path)
    if os.environ.get("GATED_CS_REQUIRE_SANDBOX") == "1" and not _sandbox_available():
        audit.record({"script_hash": sh, "verdict": "error",
                      "reason": "sandbox required but bubblewrap unavailable"})
        return {"status": "error", "outputs": [], "message": "sandbox required but unavailable"}
    cmd = _child_command(script_path, data_dir, out_dir)
    try:
        proc = subprocess.run(cmd, env=env, cwd=out_dir,
                              capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        audit.record({"script_hash": sh, "verdict": "error", "reason": "timeout"})
        return {"status": "error", "outputs": [], "message": "timeout"}
    if proc.returncode != 0:
        audit.record({"script_hash": sh, "verdict": "error", "reason": scrub(proc.stderr)})
        return {"status": "error", "outputs": [], "message": scrub(proc.stderr)}
    released, queued = [], []
    for full, rel in sorted(_iter_artifacts(out_dir), key=lambda t: t[1]):
        if rel.endswith(".csv"):
            try:
                v = check_table(pd.read_csv(full), thresholds)
            except Exception:
                v = None
            if v and v.status in ("allow", "suppress"):
                if v.safe_df is not None:
                    dest_out = _deliver(v.safe_df, rel, results_dir, sh) if results_dir else full
                    if not results_dir:
                        v.safe_df.to_csv(full, index=False)
                else:
                    dest_out = _deliver(full, rel, results_dir, sh) if results_dir else full
                released.append(dest_out)
                verdict, reason = v.status, v.reason
            else:
                dest = _quarantine(full, rel, queue_dir, sh)
                queued.append(dest)
                verdict = "block" if v else "unclassifiable"
                reason = v.reason if v else "unreadable output"
        else:
            # non-CSV artifact cannot be gate-checked -> quarantine (fail-closed)
            dest = _quarantine(full, rel, queue_dir, sh)
            queued.append(dest)
            verdict, reason = "unclassifiable", "non-csv artifact quarantined"
        record = {"script_hash": sh, "artifact": rel, "verdict": verdict, "reason": reason}
        if verdict in ("block", "unclassifiable"):
            record["quarantined_to"] = dest
        elif verdict in ("allow", "suppress") and results_dir:
            record["delivered_to"] = dest_out
        audit.record(record)

    # always record a run-level entry so no successful run is trace-less
    audit.record({"script_hash": sh, "verdict": "run",
                  "released": len(released), "queued": len(queued)})
    status = "queued" if queued else "released"
    return {"status": status, "outputs": released,
            "message": f"{len(released)} released, {len(queued)} queued"}

def main():
    ap = argparse.ArgumentParser()
    for arg in ("script", "--data-dir", "--out-dir", "--audit", "--queue"):
        ap.add_argument(arg)
    ap.add_argument("--results", default=None)
    a = ap.parse_args()
    r = run(a.script, a.data_dir, a.out_dir, a.audit, a.queue, results_dir=a.results)
    print(r["message"]); sys.exit(0 if r["status"] != "error" else 1)

if __name__ == "__main__":
    main()
