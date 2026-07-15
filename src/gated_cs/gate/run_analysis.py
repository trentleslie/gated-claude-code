import argparse, hashlib, os, shutil, subprocess, sys
import pandas as pd
from .sdc import check_table
from .scrub import scrub
from .audit import AuditLog
from ..config import DEFAULTS

def _hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]

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
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".csv"):
            continue
        p = os.path.join(out_dir, name)
        try:
            v = check_table(pd.read_csv(p), thresholds)
        except Exception:
            v = None
        if v and v.status in ("allow", "suppress"):
            if v.safe_df is not None:
                v.safe_df.to_csv(p, index=False)
            released.append(p); verdict = v.status
        else:
            dest = os.path.join(queue_dir, name); shutil.move(p, dest)
            queued.append(dest); verdict = "block" if v else "unclassifiable"
        audit.record({"script_hash": sh, "artifact": name, "verdict": verdict,
                      "reason": (v.reason if v else "unreadable output")})
    status = "queued" if queued else ("released" if released else "error")
    return {"status": status, "outputs": released, "message": f"{len(released)} released, {len(queued)} queued"}

def main():
    ap = argparse.ArgumentParser()
    for arg in ("script", "--data-dir", "--out-dir", "--audit", "--queue"):
        ap.add_argument(arg)
    a = ap.parse_args()
    r = run(a.script, a.data_dir, a.out_dir, a.audit, a.queue)
    print(r["message"]); sys.exit(0 if r["status"] != "error" else 1)

if __name__ == "__main__":
    main()
