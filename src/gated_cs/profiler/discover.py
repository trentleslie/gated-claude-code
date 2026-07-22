import os
from dataclasses import dataclass

CHECKPOINT_DIR = ".ipynb_checkpoints"
_STAGES = ("raw", "processed")
_CODEBOOK_STEMS = ("questions", "response_options")

@dataclass
class DiscoveredFile:
    path: str
    relpath: str
    source: str
    stage: str
    role: str

def _classify_role(stage: str, filename: str) -> str:
    if stage == "raw":
        low = filename.lower()
        for stem in _CODEBOOK_STEMS:
            if stem in low:
                return "codebook"
    return "data"

def discover_files(data_dir: str, exts=(".csv", ".tsv")) -> list:
    out = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if d != CHECKPOINT_DIR]  # prune, don't descend
        for fn in sorted(files):
            if not fn.lower().endswith(tuple(exts)):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, data_dir)
            parts = rel.split(os.sep)
            source = parts[0] if len(parts) > 1 else ""
            stage = next((p for p in parts if p in _STAGES), "")
            out.append(DiscoveredFile(full, rel, source, stage, _classify_role(stage, fn)))
    return sorted(out, key=lambda f: f.relpath)
