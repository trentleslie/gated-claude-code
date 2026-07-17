# docs/examples/impute-metabolomics.py
# Run via: submit-derivation impute-metabolomics.py --layer metabolomics_imputed
#
# Derives a per-person imputed-metabolite layer. Fits inside the sandbox on real data; the
# imputed matrix is persisted to $LAYER_DIR (stays in the store, never released), and only
# fit-quality AGGREGATES go to $OUTPUT_DIR (which the gate checks and releases).
#
# NOTE: IterativeImputer over all ~1350 metabolites exceeds the gate's 120s child timeout.
# Cap to the best-detected N_FEATURES to stay under it; raise N or swap the imputer once you
# know the runtime on real data.
import os
import numpy as np
import pandas as pd
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer

DATA_DIR, LAYER_DIR, OUTPUT_DIR = os.environ["DATA_DIR"], os.environ["LAYER_DIR"], os.environ["OUTPUT_DIR"]
KEY = "public_client_id"
N_FEATURES = 40          # feature cap so IterativeImputer stays under the 120s timeout

df = pd.read_csv(os.path.join(DATA_DIR, "metabolomics_corrected.tsv"),
                 sep="\t", skiprows=13, low_memory=False)

# One row per person: a derived layer is per-person, but the raw table has repeat draws.
# Keep each client's earliest draw.
draw = "days_since_first_draw"
df = df.sort_values(draw).drop_duplicates(KEY, keep="first") if draw in df.columns \
    else df.drop_duplicates(KEY, keep="first")

# The best-detected numeric metabolite columns (fewest missing) — bounds the runtime.
numeric = [c for c in df.columns if c != KEY and df[c].dtype.kind in "fi"]
feats = sorted(numeric, key=lambda c: df[c].isna().mean())[:N_FEATURES]
X = df[feats].to_numpy(dtype=float)

# Mask-and-predict cross-validation. Baseline is EACH FEATURE'S OWN MEAN: a single global mean
# across metabolites of differing scales inflates R2 (don't use np.nanmean(X)).
rng = np.random.default_rng(0)
mask = (~np.isnan(X)) & (rng.random(X.shape) < 0.1)
Xtr = X.copy(); Xtr[mask] = np.nan
pred = IterativeImputer(random_state=0, max_iter=5, sample_posterior=False).fit_transform(Xtr)
col_mean = np.nanmean(Xtr, axis=0)
ss_res = np.nansum((X - pred)[mask] ** 2)
ss_tot = np.nansum((X - col_mean[None, :])[mask] ** 2)
cv_r2 = float(1 - ss_res / ss_tot) if ss_tot else float("nan")
per = []
for j in range(X.shape[1]):
    mj = mask[:, j]
    if mj.sum() >= 5:
        sr = np.nansum((X[mj, j] - pred[mj, j]) ** 2)
        st = np.nansum((X[mj, j] - col_mean[j]) ** 2)
        if st:
            per.append(1 - sr / st)
r2_med = float(np.median(per)) if per else float("nan")

# Persist the full imputed per-person matrix to the store (NOT released; keyed by public_client_id).
full = IterativeImputer(random_state=0, max_iter=5).fit_transform(X)
out = pd.DataFrame(full, columns=feats); out.insert(0, KEY, df[KEY].to_numpy())
out.to_csv(os.path.join(LAYER_DIR, "data.tsv.gz"), sep="\t", index=False, compression="gzip")

# Release ONLY aggregates — the fit quality, never per-person values.
pd.DataFrame({"metric": ["cv_r2_pooled", "cv_r2_per_feature_median",
                         "n_features", "n_persons", "pct_missing_before"],
              "value": [round(cv_r2, 4), round(r2_med, 4), len(feats), len(df),
                        round(float(np.isnan(X).mean() * 100), 2)]}
             ).to_csv(os.path.join(OUTPUT_DIR, "metabolomics_imputed__quality.csv"), index=False)
