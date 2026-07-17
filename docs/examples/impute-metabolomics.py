# docs/examples/impute-metabolomics.py — run via: submit-derivation impute-metabolomics.py --layer metabolomics_imputed
import os, numpy as np, pandas as pd
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer

DATA_DIR, LAYER_DIR, OUTPUT_DIR = os.environ["DATA_DIR"], os.environ["LAYER_DIR"], os.environ["OUTPUT_DIR"]
df = pd.read_csv(os.path.join(DATA_DIR, "metabolomics_corrected.tsv"), sep="\t", skiprows=13, low_memory=False)
key = "public_client_id"; feats = [c for c in df.columns if df[c].dtype.kind in "fi" and c != key]
X = df[feats].to_numpy(dtype=float)

# mask-and-predict CV quality (mask observed cells, impute, score) — released aggregate
rng = np.random.default_rng(0); mask = (~np.isnan(X)) & (rng.random(X.shape) < 0.1)
Xtr = X.copy(); Xtr[mask] = np.nan
imp = IterativeImputer(random_state=0, max_iter=10, sample_posterior=False).fit(Xtr)
pred = imp.transform(Xtr)
ss_res = np.nansum((X[mask] - pred[mask])**2); ss_tot = np.nansum((X[mask] - np.nanmean(X))**2)
cv_r2 = float(1 - ss_res/ss_tot) if ss_tot else float("nan")

full = IterativeImputer(random_state=0, max_iter=10).fit_transform(X)      # persist full imputed matrix
out = pd.DataFrame(full, columns=feats); out.insert(0, key, df[key].values)
out.to_csv(os.path.join(LAYER_DIR, "data.tsv.gz"), sep="\t", index=False, compression="gzip")

pd.DataFrame({"metric": ["cv_r2", "n_features", "n_rows", "pct_missing_before"],
              "value": [round(cv_r2,4), len(feats), len(df), round(float(np.isnan(X).mean()*100),2)]}
             ).to_csv(os.path.join(OUTPUT_DIR, "metabolomics_imputed__quality.csv"), index=False)
