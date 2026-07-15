import random, pandas as pd

def synthesize(file_profile, n_rows=100, seed=0):
    rng = random.Random(seed)
    data = {}
    for name, col in file_profile["columns"].items():
        if col.get("sensitive"):
            data[name] = ["<suppressed>"] * n_rows
        elif "histogram" in col and col["histogram"]:
            bins = col["histogram"]
            weights = [b["count"] for b in bins]
            data[name] = [round(rng.uniform(b["lo"], b["hi"]))
                          for b in rng.choices(bins, weights=weights, k=n_rows)]
        elif col.get("categories"):
            data[name] = [rng.choice(col["categories"]) for _ in range(n_rows)]
        else:
            data[name] = ["<suppressed>"] * n_rows
    return pd.DataFrame(data)
