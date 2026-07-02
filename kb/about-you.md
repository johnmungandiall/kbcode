# About You

- **Name:** John

## Design rules you've stated
- **"Okko model okkola untadhi"** (2026-07-02) — every model/provider behaves
  differently. kbcode must never assume clean behavior from any of them:
  broken/truncated tool-call JSON, strict server-side validation (MiMo),
  hallucinated rewrites (mimo-v2.5-pro), missing streaming fields — all get
  defensive handling + repair, never a crash or a raw error dumped on the user.
