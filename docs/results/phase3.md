# Phase 3 results — emerging-issue detection backtest (2026-10-21)

**Question:** if Complaint Radar had been running in the past, how early would it have flagged real complaint
spikes, and how often would it have raised false alarms?

## Setup

| Item | Choice |
|---|---|
| Series | weekly counts per segment × company × product × issue (1,556 series that ever reach 10/week) |
| Baseline | previous 8 weeks only (no peeking at the scored week) |
| Alert gate | detector score ≥ threshold **and** ≥ 20 complaints **and** ≥ 1.5× expected |
| Incident (ground truth) | a month with ≥ 50 complaints and ≥ 3× the median of the previous 6 months (that median ≥ 10); consecutive months merged; peak = busiest week |
| Catch / lead time | alert in the same series 0–8 weeks before the peak; lead = days from first alert to peak |
| False alarm | alert with no incident peak from 4 weeks before to 10 weeks after it |
| Split | thresholds tuned on 2016–2021 (≤ 2 false alarms per 100 series-months), results on **2022 – Jul 2026** |

Full numbers are in [`backtest.json`](backtest.json) (`complaint-radar backtest` regenerates them).

## Results — test period, non-bureau companies (261 incidents)

| Detector | Threshold | Incidents caught | Caught ≥ 7 days early | Median lead | False alarms / 100 series-months | Precision |
|---|---|---|---|---|---|---|
| **Volume rule** (baseline: this week ÷ 8-week mean) | 1.75 | **92%** | **64%** | 21 days | 3.2 | 28% |
| Robust z-score | 2.5 | 90% | 62% | 21 days | 3.9 | 23% |
| Negative-binomial surprise | 2.0 | 83% | 55% | 21 days | 2.8 | 19% |

**At an equal false-alarm budget** (best recall on the test period within each budget):

| Detector | ≤ 0.5 | ≤ 1.0 | ≤ 2.0 |
|---|---|---|---|
| Volume rule | **69%** | **86%** | **90%** |
| Robust z-score | 52% | 74% | 83% |
| Negative-binomial surprise | 44% | 52% | 72% |

Credit bureaus (100 test incidents, reported separately): volume rule 62% caught / 2.2 false alarms per 100;
robust z 57% / 2.3; negative binomial 42% / 1.3. Bureau spikes are harder to anticipate: they are larger, more
abrupt and often template-driven.

## Honest reading

1. **The simple baseline was not beaten.** The statistical detectors catch fewer incidents at every noise level.
   Production therefore uses the volume rule (threshold 1.75).
2. **Part of this is how incidents are defined.** "3× the recent median" is itself a ratio, so a ratio detector
   is favoured. The statistical detectors would matter for very large series, where a 40% rise is highly
   significant but never reaches 3×; this definition does not count those as incidents. A business-defined
   incident list (for example, confirmed outages) would be a fairer judge.
3. **A median lead of about 3 weeks, but a quarter of incidents are caught only in the peak week.** These are
   sudden explosions with no ramp-up, so no detector can warn early.
4. **Precision is low (about 1 in 4 alerts precedes an incident).** For a triage queue this is workable (a few
   alerts a week to review), but it is why Phase 4 adds summaries and campaign labels, so each alert is quick
   to dismiss or escalate.

## Named incidents (volume rule; all three detectors gave the same lead)

| Incident | Peak week | Complaints in incident | Normal month | Alert before peak |
|---|---|---|---|---|
| MOHELA: dealing with servicer (TEACH-grant / transfer problems) | 2022-10-17 | 349 | 15 | **35 days** |
| PayPal: mobile wallet account limited / 180-day holds | 2021-03-22 | 683 | 33 | **56 days** |
| Wells Fargo: problems caused by low funds (overdraft) | 2023-01-16 | 882 | 13.5 | **28 days** |
| Navy Federal: problems caused by low funds | 2025-01-13 | 7,024 | 13.5 | 0 days (overnight explosion) |
| Block (Cash App): other transaction problem | 2025-01-13 | 28,008 | 16.5 | 0 days (overnight explosion) |
| Chime: managing an account (2025) | — | — | — | not an incident under the definition (growth spread across issues) |

The Navy Federal and Block waves went from normal to thousands in a week, and both came right after CFPB
actions against those companies. The Block wave's narratives are about 50% exact duplicates. These are the
cases the Phase 4 campaign detector labels as "possible campaign / news-driven" rather than an organic
product failure.

## Limits

- CFPB's product and issue taxonomy changed (2017, 2022). Renamed issues start new series with no history,
  so they cannot alert until 8 weeks of baseline exist.
- Incidents are defined statistically, not confirmed as real business problems. Some "incidents" are news- or
  campaign-driven waves.
