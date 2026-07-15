import random, pandas as pd

def synthesize(file_profile, n_rows=100, seed=0, join_keys=(), id_pool=None):
    rng = random.Random(seed)
    jk = set(join_keys)
    data = {}
    for name, col in file_profile["columns"].items():
        if name in jk and id_pool:
            data[name] = [rng.choice(id_pool) for _ in range(n_rows)]
        elif col.get("sensitive"):
            data[name] = ["<suppressed>"] * n_rows
        elif "histogram" in col and col["histogram"]:
            bins = col["histogram"]
            weights = [b["count"] for b in bins]
            chosen = rng.choices(bins, weights=weights, k=n_rows)
            vals = [rng.uniform(b["lo"], b["hi"]) for b in chosen]
            is_int = "int" in str(col.get("dtype", "")).lower()
            data[name] = [int(round(v)) for v in vals] if is_int else vals
        elif col.get("categories"):
            data[name] = [rng.choice(col["categories"]) for _ in range(n_rows)]
        else:
            data[name] = ["<suppressed>"] * n_rows
    return pd.DataFrame(data)
