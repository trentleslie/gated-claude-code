import argparse, hashlib, os, shutil, subprocess, sys
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

def run(script_path, data_dir, out_dir, audit_path, queue_dir, thresholds=DEFAULTS):
    os.makedirs(out_dir, exist_ok=True); os.makedirs(queue_dir, exist_ok=True)
    audit = AuditLog(audit_path)
    env = {"OUTPUT_DIR": out_dir, "DATA_DIR": data_dir,
           "PATH": os.environ.get("PATH", ""), "HOME": out_dir}
    sh = _hash(script_path)
    try:
        proc = subprocess.run([sys.executable, script_path], env=env, cwd=out_dir,
                              capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        audit.record({"script_hash": sh, "verdict": "error", "reason": "timeout"})
        return {"status": "error", "outputs": [], "message": "timeout"}
    if proc.returncode != 0:
        audit.record({"script_hash": sh, "verdict": "error", "reason": scrub(proc.stderr)})
        return {"status": "error", "outputs": [], "message": scrub(proc.stderr)}
    released, queued = [], []
    for full, rel in sorted(_iter_artifacts(out_dir), key=lambda t: t[1]):
        safe_name = rel.replace(os.sep, "_")
        if rel.endswith(".csv"):
            try:
                v = check_table(pd.read_csv(full), thresholds)
            except Exception:
                v = None
            if v and v.status in ("allow", "suppress"):
                if v.safe_df is not None:
                    v.safe_df.to_csv(full, index=False)
                released.append(full)
                verdict, reason = v.status, v.reason
            else:
                dest = os.path.join(queue_dir, f"{sh}_{safe_name}")
                shutil.move(full, dest)
                queued.append(dest)
                verdict = "block" if v else "unclassifiable"
                reason = v.reason if v else "unreadable output"
        else:
            # non-CSV artifact cannot be gate-checked -> quarantine (fail-closed)
            dest = os.path.join(queue_dir, f"{sh}_{safe_name}")
            shutil.move(full, dest)
            queued.append(dest)
            verdict, reason = "unclassifiable", "non-csv artifact quarantined"
        audit.record({"script_hash": sh, "artifact": rel, "verdict": verdict, "reason": reason})

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
    a = ap.parse_args()
    r = run(a.script, a.data_dir, a.out_dir, a.audit, a.queue)
    print(r["message"]); sys.exit(0 if r["status"] != "error" else 1)

if __name__ == "__main__":
    main()
