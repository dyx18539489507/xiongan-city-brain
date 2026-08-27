# Formal 2026 experiment campaign

This directory contains the reproducible formal evaluation campaign. Raw run
directories are append-only. Processing scripts read `raw/` and write only to
`processed/`, `tables/`, `figures/`, or `metadata/`.

Main commands (from the repository root):

```powershell
.\.venv\Scripts\python.exe experiments\formal_2026\scripts\run_formal_benchmark.py --suite pilot
.\.venv\Scripts\python.exe experiments\formal_2026\scripts\process_results.py
```

No report conclusion may be written from a planned or failed row. Only a raw
directory with `status.json` equal to `completed` and a matching SHA-256
manifest is eligible for processing.

