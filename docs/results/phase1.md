# Phase 1 results — foundation (2026-10-21)

## Archive backfill

`complaint-radar backfill-archive` on the 21 official archive zips:

| Metric | Value |
|---|---|
| Files processed | 21 of 21 |
| Rows loaded | 17,533,918 |
| Data contract failures | 0 |
| Runtime | 426 s (laptop, CPU) |
| Rerun | processed 0, skipped 21, 0 rows (idempotent) |
| Lake size (Parquet, zstd) | ~0.8 GB, outside the repo |

## dbt build on the full lake

21 of 21 passed (1 seed, 4 models, 15 data tests, 1 unit test) in about 30 s.

| Model | Rows |
|---|---|
| `stg_complaints` | 17,533,918 |
| `int_narrative_templates` | 246,328 distinct duplicated texts covering 1,501,088 complaints (max copies: 27,496) |
| `fct_complaints_daily` | 2,410,769 |
| `dim_company` | 8,112 companies (3 bureaus with 13.67M complaints; 8,109 others with 3.87M) |

## Engineering notes

- **Narratives with quotes and line breaks** broke DuckDB's parallel CSV reader. The normaliser uses the
  single-threaded reader, and a fixture with a multi-line quoted narrative pins this.
- **The row fingerprint (`row_hash`) is computed on trimmed raw text before type conversion and excludes the
  narrative.** An archive row and the same complaint in today's text-free daily file therefore get the same
  hash, which is what change capture in phase 2 relies on.
- **Old response values** (`Closed`, `Closed with relief`, `Closed without relief`) are allowed by the
  contract. `relief_given` maps `Closed with relief` to true, and `In progress`/NULL to unknown.
- **Unit testing a Parquet-file source:** a dbt unit test on a source defined by an external Parquet location
  needs its input given as SQL with every column spelled out, because dbt cannot look up the columns itself.
