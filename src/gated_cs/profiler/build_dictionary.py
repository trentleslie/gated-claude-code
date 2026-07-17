import argparse, glob, json, os
from .profile import profile_file, profile_column
from .synthesize import synthesize
from ..config import DEFAULTS

def build(data_dir, out_dir, thresholds=DEFAULTS, join_keys=("public_client_id",), id_pool_size=50):
    os.makedirs(os.path.join(out_dir, "synthetic_samples"), exist_ok=True)
    files = {}
    paths = sorted(glob.glob(os.path.join(data_dir, "*.csv")) +
                   glob.glob(os.path.join(data_dir, "*.tsv")))
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    for p in paths:
        name = os.path.basename(p)
        prof = profile_file(p, thresholds)
        files[name] = prof
        synth = synthesize(prof, n_rows=100, seed=0, join_keys=join_keys, id_pool=id_pool)
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

def profile_dataframe(df, thresholds=DEFAULTS):
    cols = {name: profile_column(df[name], name=name, thresholds=thresholds) for name in df.columns}
    return {"file_metadata": [], "row_count": int(df.shape[0]), "columns": cols}

def add_layer_to_dictionary(dict_path, out_dir, name, df, thresholds=DEFAULTS,
                            join_keys=("public_client_id",), id_pool_size=50):
    with open(dict_path) as f: d = json.load(f)
    prof = profile_dataframe(df, thresholds); prof["derived"] = True
    d["files"][name] = prof
    with open(dict_path, "w") as f: json.dump(d, f, indent=2)
    with open(os.path.join(os.path.dirname(dict_path), "dictionary.md"), "w") as f:
        f.write(_render_md(d))
    ss = os.path.join(out_dir, "synthetic_samples"); os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    synth = synthesize(prof, n_rows=100, seed=0, join_keys=join_keys, id_pool=id_pool)
    synth.to_csv(os.path.join(ss, name if name.endswith(".csv") else name + ".csv"), index=False)
    return prof

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--out", default="dictionary_out")
    a = ap.parse_args()
    build(a.data_dir, a.out)
    print(f"Wrote dictionary + synthetic samples to {a.out}")

def build_synthetic_from_dictionary(dict_path, out_dir, join_keys=("public_client_id",),
                                    id_pool_size=50, n_rows=100, seed=0):
    with open(dict_path) as f:
        d = json.load(f)
    ss = os.path.join(out_dir, "synthetic_samples")
    os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    for name, prof in d["files"].items():
        synth = synthesize(prof, n_rows=n_rows, seed=seed, join_keys=join_keys, id_pool=id_pool)
        synth.to_csv(os.path.join(ss, name), index=False)
    return len(d["files"])

def synthetic_main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--join-keys", default="public_client_id")
    ap.add_argument("--id-pool-size", type=int, default=50)
    a = ap.parse_args()
    join_keys = tuple(k.strip() for k in a.join_keys.split(",") if k.strip())
    n = build_synthetic_from_dictionary(a.dictionary, a.out, join_keys=join_keys,
                                        id_pool_size=a.id_pool_size)
    print(f"Wrote synthetic samples for {n} files to {os.path.join(a.out, 'synthetic_samples')}")

if __name__ == "__main__":
    main()
