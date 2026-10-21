# Phase 3 results — emerging-issue detection backtest (2026-10-21)

**Question:** if Complaint Radar had been running in the past, how early would it have flagged real complaint
spikes, and how often would it have raised false alarms?

## Setup

| Item | Choice |
|---|---|
| Series | weekly counts per segment × company × product × issue (1,556 series that ever reach 10/week) |
| Baseline | previous 8 weeks only (no peeking at the scored week) |
| Alert gate | detector score ≥ threshold **and** ≥ 20 complaints **and** ≥ 1.5× expected |
| Incident (ground truth) | a month with ≥ 50 complaints and ≥ 3× the median of the previous 6 months (that median ≥ 10); **consecutive incident months in a series are merged into one incident**; peak = busiest week |
| Catch / lead time | alert in the same series 0–8 weeks before the peak; lead = days from first alert to peak |
| False alarm | alert with no incident peak from 4 weeks before to 10 weeks after it |
| Split | thresholds tuned on 2016–2021 (≤ 2 false alarms per 100 series-months), results on **2022 – May 2026** (later weeks were still being published when the archive froze) |

Full numbers are in [`backtest.json`](backtest.json) (`complaint-radar backtest` regenerates them).

## Results — test period, non-bureau companies (161 incidents)

| Detector | Threshold | Caught (≤ 8 wks before peak) | Caught ≥ 14 days early | Median lead | False alarms / 100 series-months | Precision |
|---|---|---|---|---|---|---|
| **Volume rule** (baseline: this week ÷ 8-week mean) | 1.75 | **90%** | **45%** | 14 days | 3.3 | 28% |
| Robust z-score | 2.5 | 87% | 44% | 14 days | 4.0 | 23% |
| Negative-binomial surprise | 2.0 | 83% | 40% | 7 days | 2.9 | 19% |

Best recall within each false-alarm budget on the test period. **The thresholds here are picked on the test period itself, so this table compares how well each detector ranks weeks; it is not a production estimate:**

| Detector | ≤ 0.5 | ≤ 1.0 | ≤ 2.0 |
|---|---|---|---|
| Volume rule | **65%** | **75%** | **87%** |
| Robust z-score | 49% | 63% | 80% |
| Negative-binomial surprise | 47% | 55% | 73% |

**Credit bureaus** (39 test incidents): volume rule (threshold 3.0) caught 49% with 1.8 false alarms per 100;
**robust z-score caught 54% with 2.2**, and did better at an equal budget too (31% vs 18% at ≤ 1).

## The publication delay: why live warnings arrive later than the backtest suggests

The backtest scores each week using the *final* archive. Live data is different. On 2026-10-21, for non-bureau
companies, only **28%** of last week's complaints and **69%** of the week before were published. Recent weeks
fill in over 2–3 weeks as companies respond. Speed also varies by product: after one week about 51% of
debt-collection complaints are visible, but about 7% of mortgage complaints.

The live detector therefore uses a **nowcast**:
- the baseline comes only from mature weeks (3 or more weeks old);
- each recent week's completeness is estimated per segment and product;
- a week is scored only once it is at least half published, against "baseline × completeness".

For most non-bureau products, a week first passes that bar at about 2 weeks old. Debt collection and the
credit bureaus are faster.

What that means for the headline numbers:
- **The fair live comparison is "caught ≥ 14 days early": 45% of non-bureau incidents.** Roughly half of real
  incidents would still be flagged before their peak once the publication delay is accounted for.
- The other half are either sudden (no ramp-up) or only visible after they have peaked.
- Products whose recent weeks stay below 50% completeness for two weeks (mortgage, at current speeds)
  effectively get a 3-week delay.
- **The nowcast itself is not yet backtested.** That would need historical "as published on that day"
  snapshots, which nobody kept. The pipeline now stores a daily vintage (`snapshot_vintages`) so it can be
  replayed and calibrated. Note that the BigQuery sandbox's 60-day partition expiry limits this history
  unless vintages are also exported.

## Honest reading

1. **For non-bureau companies the simple baseline was not beaten.** It catches as many or more incidents than
   the statistical detectors at every noise level. Production uses the volume rule.
2. **For credit bureaus the robust z-score was better**, but production still uses the volume rule (threshold
   3.0) because the live nowcast currently implements the ratio score only. Moving bureaus to the robust z-score
   is a documented follow-up.
3. **The incident definition favours ratio detectors.** "3× the recent median" is itself a ratio; statistical
   detectors would matter for very large series where a 40% rise is significant but never reaches 3×.
4. **Precision is low (about 1 in 4 alerts precedes an incident).** For a review queue this is workable (a few
   alerts a week), and it is why Phase 4 adds summaries and campaign labels so each alert can be dismissed or
   escalated quickly.

## Named incidents (volume rule; backtest lead, before publication delay)

| Incident | Peak week | Complaints in incident | Normal month | Alert before peak |
|---|---|---|---|---|
| MOHELA: dealing with servicer (TEACH-grant / transfer problems) | 2022-10-17 | 349 | 15 | **35 days** |
| PayPal: mobile wallet account limited / 180-day holds | 2021-04-26 | 683+ (Mar–Apr wave) | 33 | **56 days** |
| Wells Fargo: problems caused by low funds (overdraft) | 2023-01-16 | 882 | 13.5 | **28 days** |
| Navy Federal: problems caused by low funds | 2025-01-13 | 7,024 | 13.5 | 0 days (overnight explosion) |
| Block (Cash App): other transaction problem | 2025-01-13 | 28,008 | 16.5 | 0 days (overnight explosion) |
| Chime: managing an account (2025) | — | — | — | not an incident under the definition (growth spread across issues) |

The Navy Federal and Block waves went from normal to thousands in a week, both right after CFPB actions against
those companies. Block's narratives are about 50% exact duplicates. These are the cases the Phase 4 campaign
detector labels as "possible campaign / news-driven" rather than an organic product failure.

## Correction log

An independent review found that the first version of this backtest never merged consecutive incident months.
A pandas comparison between a time difference and a `DateOffset` is always true, so every incident month
became its own incident. That inflated the results (261 incidents, 92% caught, 21-day median lead). The numbers
above are after the fix, which is pinned by `test_consecutive_spike_months_merge_into_one_incident`.

## Limits

- CFPB's product and issue taxonomy changed (2017, 2022). Renamed issues start new series with no history,
  so they cannot alert until 8 weeks of baseline exist.
- Incidents are defined statistically, not confirmed as real business problems. Some are news- or
  campaign-driven waves.
