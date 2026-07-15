import argparse, glob, json, os
from .profile import profile_file
from .synthesize import synthesize
from ..config import DEFAULTS

def build(data_dir, out_dir, thresholds=DEFAULTS):
    os.makedirs(os.path.join(out_dir, "synthetic_samples"), exist_ok=True)
    files = {}
    paths = sorted(glob.glob(os.path.join(data_dir, "*.csv")) +
                   glob.glob(os.path.join(data_dir, "*.tsv")))
    for p in paths:
        name = os.path.basename(p)
        prof = profile_file(p, thresholds)
        files[name] = prof
        synth = synthesize(prof, n_rows=100, seed=0)
        synth.to_csv(os.path.join(out_dir, "synthetic_samples", name), index=False)
    dictionary = {"data_dir": data_dir, "files": files}
    with open(os.path.join(out_dir, "dictionary.json"), "w") as f:
        json.dump(dictionary, f, indent=2)
    with open(os.path.join(out_dir, "dictionary.md"), "w") as f:
        f.write(_render_md(dictionary))
    return dictionary

def _render_md(d):
    out = ["# Data Dictionary\n"]
    for name, prof in d["files"].items():
        out.append(f"\n## {name}  ({prof['row_count']} rows)\n")
        for meta in prof["file_metadata"]:
            out.append(f"> {meta}\n")
        out.append("\n| column | dtype | %missing | cardinality | sensitive | description |\n")
        out.append("|---|---|---|---|---|---|\n")
        for cname, c in prof["columns"].items():
            out.append(f"| {cname} | {c['dtype']} | {c['pct_missing']} | "
                       f"{c['cardinality']} | {c.get('sensitive', False)} | "
                       f"{c.get('description','')} |\n")
    return "".join(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--out", default="dictionary_out")
    a = ap.parse_args()
    build(a.data_dir, a.out)
    print(f"Wrote dictionary + synthetic samples to {a.out}")

if __name__ == "__main__":
    main()
