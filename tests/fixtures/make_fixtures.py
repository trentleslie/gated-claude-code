import csv, pathlib, random
HERE = pathlib.Path(__file__).parent

def _write(path, rows, delimiter=","):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerows(rows)

def main():
    random.seed(42)
    # simple.csv: # metadata rows, then header, then numeric+categorical data
    lines = [
        "# source: arivale_snapshot_2018\n",
        "# age: age in years\n",
        "# sex: biological sex (M/F)\n",
        "age,sex\n",
    ] + [f"{random.randint(30,70)},{random.choice(['M','F'])}\n" for _ in range(100)]
    (HERE / "simple.csv").write_text("".join(lines))
    # tabbed.tsv: tab-delimited, same shape
    tsv = ["# glucose: fasting glucose mg/dL\nglucose\tsite\n"] + \
          [f"{random.randint(70,140)}\t{random.choice(['A','B','C'])}\n" for _ in range(100)]
    (HERE / "tabbed.tsv").write_text("".join(tsv))
    # with_ids.csv: a direct identifier column + a tiny subgroup
    rows = [["public_id", "email", "cohort"]]
    for i in range(100):
        cohort = "rare" if i < 3 else random.choice(["big1", "big2"])
        rows.append([f"P{i:04d}", f"user{i}@example.com", cohort])
    _write(HERE / "with_ids.csv", rows)

if __name__ == "__main__":
    main()
