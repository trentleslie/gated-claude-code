import argparse, os, shutil
from .audit import AuditLog

def list_pending(queue_dir):
    if not os.path.isdir(queue_dir):
        return []
    return sorted(n for n in os.listdir(queue_dir)
                  if os.path.isfile(os.path.join(queue_dir, n)))

def approve(name, queue_dir, results_dir, audit_path):
    os.makedirs(results_dir, exist_ok=True)
    dest = os.path.join(results_dir, name)
    shutil.move(os.path.join(queue_dir, name), dest)
    AuditLog(audit_path).record({"artifact": name, "verdict": "review:approve"})
    return dest

def reject(name, queue_dir, audit_path):
    os.remove(os.path.join(queue_dir, name))
    AuditLog(audit_path).record({"artifact": name, "verdict": "review:reject"})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "approve", "reject"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--queue", default="/var/gate/queue")
    ap.add_argument("--results", default="/home/cs-gated/results")
    ap.add_argument("--audit", default="/var/gate/audit.jsonl")
    a = ap.parse_args()
    if a.cmd == "list":
        for n in list_pending(a.queue):
            print(n)
    elif a.cmd == "approve":
        print("approved:", approve(a.name, a.queue, a.results, a.audit))
    else:
        reject(a.name, a.queue, a.audit); print("rejected:", a.name)

if __name__ == "__main__":
    main()
