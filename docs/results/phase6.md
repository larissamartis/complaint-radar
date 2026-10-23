# Phase 6 results — do complaint patterns warn of CFPB enforcement? (2026-10-23)

**Question:** looking only at a company's complaints over the past 12 months, can we tell whether the CFPB will
take a public enforcement action against it in the next 12 months, better than by simply knowing how big the
company is?

**Answer: no.** Complaint *volume* is a strong signal (big companies get more actions), but the complaint
*patterns* (growth, relief rate, late responses, shifting issues) add nothing on top of it. On the test years
the pattern models did slightly worse than volume alone, and the difference is within noise.

## Data

| Item | Value |
|---|---|
| Enforcement actions | every action on consumerfinance.gov/enforcement/actions, scraped by the `Enforcement study` workflow |
| Matched to a complaint company and used | **262 actions** (one action can sanction several companies) |
| Panel | company × month, companies with ≥ 50 complaints in the previous 12 months |
| Label | an action filed against the company in the **next 12 months** |
| Features (previous 12 months only) | log volume, 3-month growth, relief rate, untimely-response rate, issue-mix shift (Jensen–Shannon), number of issues, top-issue share, months active, credit bureau flag |
| Excluded | company-months with an action in the previous 12 months: complaints often *follow* a public action, which would leak the answer |
| Split | train on months 2015–2018 (labels end Dec 2019); test on months **Jan 2020 – Jul 2024** (labels reach Jul 2025). No label period overlaps. |
| Test set | 22,090 company-months, 506 positive, from **46 sanctioned companies**; base rate 2.3% (1.4%–3.6% by year) |

## Results on 2020–2024 (never seen in training)

| Model | ROC-AUC | PR-AUC | Precision in top 1% | Lift in top 1% |
|---|---|---|---|---|
| **Baseline: complaint volume only** | 0.824 | **0.156** | **29.0%** | **12.6×** |
| Logistic regression, all features | **0.830** | 0.136 | 24.9% | 10.9× |
| LightGBM, all features | 0.648 | 0.042 | 7.7% | 3.4× |

**Gain of the best pattern model over volume (PR-AUC):** −0.018, 95% interval **−0.048 to +0.007**, from 500
bootstrap resamples clustered by company (the pattern model came out ahead in only 10% of them).

**In plain words:** the companies the CFPB acts on are mostly the large ones, and ranking by complaint count
already puts 29% sanctioned company-months in the top 1%, 12.6 times the base rate. Adding complaint patterns
does not move that, and the more flexible LightGBM overfits the few positive companies badly.

The logistic coefficients agree: after volume (+0.61), the pattern features carry small or *negative* weights
(issue shift −0.37, untimely responses −0.21). There is no sign that "complaints getting worse" precedes action.

## Why the result is believable

- **Strict time split** and features built only from the past 12 months.
- **No post-action leakage:** months right after an action are removed, so the model cannot learn from the
  complaint wave a public action causes.
- **Clustered bootstrap:** resampling whole companies, because one company contributes many correlated months.
- **The baseline is not a straw man:** volume is exactly what a skeptic would propose.

## Name matching, and how it was corrected

Matching enforcement names to complaint companies is the hardest part, and errors here silently label the
wrong company as sanctioned. The matcher went through four versions; each was checked by reading every loose
match.

| Run | Matcher | Actions used | Volume PR-AUC | Best pattern PR-AUC |
|---|---|---|---|---|
| 1 | exact + fuzzy only | 128 | 0.057 | 0.060 |
| 2 | + party splitting, brand prefixes, first-word rule | 277 | 0.136 | 0.115 |
| 3 | + every named party labelled, no label overlap, generic words blocked | 283 | 0.153 | 0.137 |
| 4 (final) | + brand rules require the extra words to be institution words; reviewed overrides | 262 | 0.156 | 0.136 |

- **Run 1** missed most large banks ("Regions Bank" vs "REGIONS FINANCIAL CORPORATION").
- **Runs 2–3** found them, but reading the matches showed about 30 wrong links between firms that share only
  a first word: Morgan Drexen → Morgan Stanley, Rocket Homes → Rocket Mortgage, Phoenix Title Loans → Phoenix
  Financial Services.
- **Run 4:** a shared brand word is accepted only if the remaining words describe the kind of institution
  ("SunTrust Mortgage" vs "SunTrust Banks"); otherwise the match goes to review. Renamed and successor companies
  are set by a reviewed override file, each name checked against the CFPB data: Green Tree → Ditech,
  GE Capital Retail Bank → Synchrony, National City → PNC, CitiMortgage → Citibank.

No version showed a reliable gain from patterns (run 1's small edge had an interval spanning zero), which is
evidence that the conclusion is not an artefact of matching.

**Known remaining issues:** 38 actions are flagged for review and 105 have no match. Most of these are small
debt-relief firms or individuals with no complaint history. Two doubtful automatic matches (Asset Recovery
Associates, B&B Pawnbrokers) belong to companies below the 50-complaint threshold, so they never enter the
panel. The full table is in [`enforcement_matches.csv`](enforcement_matches.csv).

## Limits

- **Low power:** 46 sanctioned companies in the test years. A small real effect could be missed; a large one
  would have shown.
- **Enforcement is not only about complaints:** actions come from examinations, whistleblowers and other
  regulators, and the CFPB's activity changes with its leadership (the base rate ranges from 1.4% in 2021 to 3.6% in 2024).
- Only public CFPB actions are counted; state and other federal regulators are not.

Full numbers are in [`enforcement.json`](enforcement.json).
