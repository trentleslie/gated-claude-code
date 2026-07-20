# Gated-analyst skills

Source of truth for the skills deployed to `cs-gated`'s `~/.claude/skills/` on the gated box.
Edit here, then deploy: `provision/bin/deploy-skills` (rsync over ssh; env `GCS_BOX`, `GCS_KEY`).

- `apply-to-arivale/` — transfer a frontier paper's method to Arivale + route validation.
- `tre-runpack/` — emit human-run validation packs for non-exportable TREs (UKB-RAP, All of Us).
- `replicate/`, `validate/`, `method-kd-biological-age/` — backfilled from the box (captured verbatim).
