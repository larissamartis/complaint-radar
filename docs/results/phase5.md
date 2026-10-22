# Phase 5 results — escalation triage, scoring API and drift monitoring (2026-10-22)

**Question:** when a complaint arrives, can we tell which ones are likely to end with the company giving the
customer relief (money back or another fix), so a team can look at those first?

## Setup

| Item | Choice |
|---|---|
| Population | non-bureau complaints with a known outcome (in-progress and untimely complaints have no outcome and are excluded) |
| Label | `relief_given` = closed with monetary or non-monetary relief |
| Features | **intake-time fields only**: product, sub-product, issue, sub-issue, company (top 300, others grouped), state, channel, tags, month, weekday. Response fields (timeliness, public response, response date) are excluded because they are only known afterwards. |
| Split | train 2019–2023, calibrate 2024 (isotonic regression), **test 2025** (761,880 complaints, 17.5% got relief) |
| Training | the `Train triage model` GitHub workflow, on the full archive |

## Results on 2025 (never seen in training)

| Model | ROC-AUC | PR-AUC | Precision in top 10% | Lift in top 10% | Brier |
|---|---|---|---|---|---|
| Baseline: historical relief rate of the product × issue | 0.562 | 0.220 | 25.6% | 1.5× | 0.145 |
| Logistic regression on the fields | 0.769 | 0.427 | 45.5% | 2.6× | 0.124 |
| **LightGBM on the fields, calibrated** (serving model) | **0.782** | **0.461** | **53.1%** | **3.0×** | **0.119** |

**In plain words:** if a team reviews the model's top 10% of complaints first, 53% of them end in relief, against
17.5% on average. That is 3× better than random and 2× better than the simple baseline. The model is calibrated:
in the bottom deciles, scores of about 5% match observed relief rates of 3–5%. Full numbers, including
calibration by decile, are in [`triage.json`](triage.json).

### Does the complaint text help? (honest negative result)

On the 2025 complaints that have a narrative (339,854):

| Model | ROC-AUC | PR-AUC | Lift in top 10% |
|---|---|---|---|
| LightGBM, fields only | **0.788** | **0.422** | 3.04× |
| TF-IDF of the narrative + fields | 0.786 | 0.420 | 3.16× |

**The text adds essentially nothing** once company, product and issue are known. Whether a customer gets relief
depends mostly on *who* the company is and *what* the complaint is about, not on how it is written. That is
convenient, because live complaints no longer carry text, and it tells a bank where its triage effort should go.

## Serving

- **Daily scoring:** every complaint appearing in the warehouse for the first time (non-bureau) gets a relief
  probability and a priority (high = top 10% of 2024 scores, medium = next 20%). Results go to BigQuery
  `triage_scores`.
- **API** (FastAPI, Docker):
  - `POST /score` returns the probability, the priority and the top 3 reasons, using LightGBM's built-in SHAP
    values in log-odds;
  - `GET /topics` returns the typical topics for a product × issue;
  - `GET /alerts` returns the latest alerts;
  - `GET /health` reports service and model status.

  CI builds the image, starts it, and calls `/health` and `/score`.

**Caveat on the public feed:** the CFPB publishes a complaint only after the company responds (or after about
15 days), so many complaints are already closed when the pipeline first sees them. Each daily score therefore
stores the complaint's status and age (`already_closed`, `days_since_received`). On public data these scores
are retrospective; inside a bank the same model would score at intake.

## Drift monitoring

Every day the pipeline compares new complaints with the 2024 reference using the **Population Stability Index**:
- product mix;
- score distribution.

Readings: < 0.10 stable, 0.10–0.25 moderate, > 0.25 significant (investigate or retrain). Results go to
BigQuery `drift_metrics`; days with fewer than 200 scored complaints are marked `insufficient_data`.

## Independent review fixes

The review found no critical issues and confirmed there is no leakage: no post-response features, and every
encoder and threshold is fitted on training data only.

| Finding | Fix |
|---|---|
| A scoring failure stopped the rest of the daily run, and those complaints were never scored | Scoring is isolated: a failure is logged in the run message and alerting continues |
| "First appearance" is not intake on the public feed | Status and age are stored with each score, and the caveat is documented |
| The Docker check never called `/score` | It now does whenever the model is packaged |
| The training job loaded every narrative into memory | Narratives are kept only for the text sample and the test rows |
| Two different priority rules (API vs daily) | One shared rule; "unknown" when no reference exists |
| A complaint with no company was dropped by the bureau filter | Treated as non-bureau |
| `reasons()` units unclear | Documented as log-odds |
| Docker reinstalled every dependency on each code change | Dependencies are installed in their own cached layer |
