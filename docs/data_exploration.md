# Data exploration — 2026-10-21

Sources checked:
- CFPB complaint search API (`consumerfinance.gov/data-research/consumer-complaints/search/api/v1/`).
- Daily bulk CSV (`files.consumerfinance.gov/ccdb/complaints.csv.zip`).
- CFPB FOIA narratives archive (21 `CCDB_Export_*.zip` files).

## 1. Live sources

| Item | Value |
|---|---|
| Complaints in live database | 18,531,443 |
| Bulk CSV | 356 MB zip, last modified 2026-10-20 (updated daily) |
| Bulk CSV columns | 15 — **no narrative**, no "Consumer disputed?" |
| API narrative field | removed (no record returns it); `trends` endpoint no longer responds |
| Volume since 2026-09-01 | 1,027,900 (about 20k/day) |
| Share for TransUnion / Experian / Equifax since 2026-09-01 | about 92% |

CFPB announced on 2026-08-14 that it would stop publishing complaint narratives. Structured data is still
published daily.

## 2. Narratives archive (frozen)

- 21 zips, 1.43 GB; converted to Parquet (823 MB).
- 17,533,918 rows, all complaint IDs unique, 0 unparseable dates. Date range 2011-12-01 to 2026-08-31.
- 3.85M rows with narrative text. Text starts in 2015.

Share with text by year received:

| Year | Complaints | With text | % | Bureau text | Non-bureau text |
|---|---|---|---|---|---|
| 2015 | 168,273 | 54,723 | 32.5 | 9,831 | 44,892 |
| 2018 | 257,131 | 118,393 | 46.0 | 36,081 | 82,312 |
| 2021 | 495,939 | 203,570 | 41.0 | 83,851 | 119,719 |
| 2023 | 1,292,049 | 487,410 | 37.7 | 322,181 | 165,229 |
| 2024 | 2,734,269 | 814,385 | 29.8 | 609,650 | 204,735 |
| 2025 | 5,442,964 | 1,222,050 | 22.5 | 878,132 | 343,918 |
| 2026 | 4,851,531 | 121,394 | 2.5 | 8,998 | 112,396 |

**Publication lag:** text was published weeks to months after the complaint (Oct 2025: 14.7% with text,
Feb 2026: 2.4%, Aug 2026: 0%). Text was therefore never available in time for real-time alerting.

**Templates:**
- 703,032 bureau narratives (30%) are exact copies of a text that appears 50 or more times; the most common one appears 27,496 times.
- For non-bureau companies it is 49,175 (3%).

**Non-bureau unique narratives:** about 1.43M in total (2015–2026). Median 141 words; 90th percentile 433 words.

## 3. Outcome field (non-bureau, 2023+)

| Company response | Share |
|---|---|
| Closed with explanation | 80.0% |
| Closed with non-monetary relief | 13.5% |
| Closed with monetary relief | 4.3% |
| Untimely response | 1.2% |
| In progress | 0.9% |

## 4. Real past spikes (month > 2.5× trailing 6-month median)

| Company | Month | Count vs normal | Top issue | Text says |
|---|---|---|---|---|
| MOHELA | 2022-10 | 355 vs 28 | Dealing with your lender or servicer | Accounts wrongly shown as "TEACH Grant only", payments blocked; servicer-transfer problems |
| MOHELA | 2023-10 | 775 vs 184 | same | Repayment restart |
| PayPal | 2021-03/04 | ~880 vs ~250 | Managing mobile wallet account | Accounts "permanently limited", 180-day holds |
| Chime | 2025-02..04 | ~500 vs ~150 | Managing an account | Mailed checks not delivered; card fraud |
| Block (Cash App) | 2025-01 | 31,616 vs 328 | Other transaction problem | 26,363 texts but only 12,079 unique: near-identical wording, so a likely campaign |
| Wells Fargo | 2023-01 | 5,807 vs 860 | Managing an account | Follows a CFPB action (Dec 2022) |
| Capital One | 2025-01 | 7,682 vs 1,823 | Managing an account | Follows a CFPB lawsuit (Jan 2025) |

Enforcement dates are to be verified against the CFPB enforcement actions list in the enforcement phase.
