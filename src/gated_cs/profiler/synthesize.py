import random, re, pandas as pd

_DATE_NAME = re.compile(r"date|time|_at$|timestamp", re.I)

def synthesize(file_profile, n_rows=100, seed=0, join_keys=(), id_pool=None):
    rng = random.Random(seed)
    jk = set(join_keys)
    data = {}
    for name, col in file_profile["columns"].items():
        dtype = str(col.get("dtype", ""))
        if name in jk and id_pool:
            data[name] = [rng.choice(id_pool) for _ in range(n_rows)]
        elif "histogram" in col and col["histogram"]:
            bins = col["histogram"]
            weights = [b["count"] for b in bins]
            chosen = rng.choices(bins, weights=weights, k=n_rows)
            vals = [rng.uniform(b["lo"], b["hi"]) for b in chosen]
            is_int = "int" in dtype.lower()
            data[name] = [int(round(v)) for v in vals] if is_int else vals
        elif col.get("categories"):
            data[name] = [rng.choice(col["categories"]) for _ in range(n_rows)]
        elif "int" in dtype or "float" in dtype:
            vals = [rng.uniform(0, 100) for _ in range(n_rows)]
            data[name] = [int(round(v)) for v in vals] if "int" in dtype else [round(v, 3) for v in vals]
        elif _DATE_NAME.search(name):
            data[name] = ["20%02d-%02d-%02d" % (rng.randint(15, 20), rng.randint(1, 12), rng.randint(1, 28))
                          for _ in range(n_rows)]
        else:
            tag = re.sub(r"[^A-Za-z0-9]", "", name)[:8] or "col"
            data[name] = ["FAKE_%s_%04d" % (tag, rng.randint(0, 9999)) for _ in range(n_rows)]
    return pd.DataFrame(data)
