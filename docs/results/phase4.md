# Phase 4 results — text: campaigns, topics and summaries (2026-10-22)

Live complaints no longer carry text (CFPB stopped publishing narratives on 2026-08-14), so everything here is
learned from the frozen narratives archive and attached to live alerts through product × issue.

## 1. Template and campaign amplification

Method:
- A near-duplicate detector written from scratch in NumPy: MinHash signatures over word 3-grams, with
  locality-sensitive hashing (25 bands × 4 rows).
- Two texts count as near-duplicates at an estimated Jaccard similarity of 0.6 or more; exact copies are
  collapsed first.
- An incident is **template-amplified** when at least 30% of its narratives belong to a near-duplicate cluster
  of 5 or more texts.

It processes about 24,000 narratives in roughly 6 seconds on a laptop CPU.

| Incident | Near-duplicate share | Before the incident | Reading |
|---|---|---|---|
| Block (Cash App), Jan 2025 | **94%** | 0% | coordinated campaign (right after a CFPB order) |
| Navy Federal, overdraft, Nov 2024 – Jan 2025 | **76%** | 0% | campaign (right after a CFPB order) |
| Capital One, Jan 2025 | 43% | 0% | partly template-driven (right after a CFPB lawsuit) |
| PayPal, account limitations, Feb – Apr 2021 | 47% | 0% | real grievance, amplified: 204 people filed the same paragraph |
| MOHELA, servicing, Oct 2022 | **0%** | — | organic (real servicing failure) |
| Wells Fargo, overdraft, Jan 2023 | **0%** | — | organic |

Across **136 non-bureau incidents** with enough text (2016 – May 2026), **27 (20%) were template-amplified**,
and **21 of those 27 happened in 2024–2026**. Template- and campaign-driven complaint volume is rising, and an
early-warning system that treats every spike as a product failure would increasingly raise false alarms.
Details: [`campaigns.json`](campaigns.json).

Live data has no text, so live alerts get a structured proxy instead. When the same product + issue spikes at
5 or more companies in the same week, the alerts are labelled a **cross-company wave**. The first live week
(5 Oct 2026) had this pattern: "Incorrect information on your report" rose at about 15 lenders at once.

## 2. Topic discovery

| Step | Detail |
|---|---|
| Corpus | 1,053,433 unique non-bureau narratives, 2019–2025 (exact copies collapsed) |
| Sample | 40,019 narratives, stratified by product × year |
| Embeddings | `all-MiniLM-L6-v2` (384 dimensions), CPU, first 128 tokens |
| Topics | BERTopic (UMAP + HDBSCAN, outliers reassigned) → **61 topics** |
| Names | 59 named by a local `qwen2.5:1.5b` model from keywords + example complaints; 2 fell back to keywords |
| Full corpus | a TF-IDF + logistic-regression classifier distils the topics to all 1.05M narratives |

**Why distil?** Embedding 1M+ texts on a laptop CPU would take over a day. The whole build, run on a GitHub
runner, took 18 minutes.

**Does the text add information?** On held-out sample documents, using a grouped split so near-duplicate
templates never sit on both sides:

| Predicting a complaint's topic | Accuracy | Macro F1 |
|---|---|---|
| **Text classifier (distilled)** | **71.3%** | **0.69** |
| Baseline: most common topic for its product × issue | 28.1% | 0.13 |

The narrative carries far more than the structured fields. That is why losing narratives in August 2026 matters,
and why live alerts show the typical topics and example complaints for their product × issue from the archive.

Largest topics (complaints in corpus): banking fraud complaints (100k), mortgage billing and payment issues
(69k), vehicle repossession disputes (64k), fraudulent account theft (63k), credit collection issues (56k),
student-loan forgiveness / servicers (40k), Zelle dispute handling (14k), healthcare billing (14k).
Full list: [`topics.json`](topics.json).

**Known weakness:** some topics are named after a company ("Chase account issues", "Capital One account
issues") because customers write the company name in their narrative. Masking company names before
embedding would give purely issue-based topics; this is a planned improvement.

## 3. Alert summaries

Each new alert gets:
- its **pattern** (single company / cross-company wave);
- the **typical topics** for its product × issue, with shares;
- a **2–3 sentence summary**.

The summary comes from a local `qwen2.5:1.5b` model (Ollama, CPU, free) and is accepted only if:
- every number in it appears in the alert's facts (not the dates, not the example complaints);
- it uses no unchecked ratio words ("doubled", "hundreds", …);
- it fits in 3 sentences.

Otherwise, or if the model is unavailable or slow, a deterministic template summary is used. Each alert records
which method produced its summary.

Example complaints are fenced as untrusted data in the prompt, and instruction-like text is removed: complaint
narratives are written by the public. The daily GitHub job installs a pinned Ollama version and summarises at
most 10 alerts per run with a 60-second timeout per call. If the model step fails, the pipeline still runs.

Example (MOHELA, week of 10 Oct 2022, real complaints as context):

> The number of complaints about MOHELA's handling of student loans has risen sharply this week, with 104
> complaints received, compared to the usual expected number of 7. This is a 14.9x increase, indicating a
> significant rise in customer dissatisfaction. Customers are reporting issues with account management,
> including being locked out of their MOHELA account …

## Independent review fixes

A fresh reviewer found 2 critical and 6 important issues; each was fixed with a test that failed first.

| Finding | Fix |
|---|---|
| The existing BigQuery alerts table could not accept the new columns, so the next load would fail | Missing columns are added automatically (a metadata change, allowed in the sandbox) |
| CI could not import scikit-learn (it was only in the optional text group) | Moved to the main dependencies |
| Waves counted only today's new alerts | Waves are counted over every alert in the week |
| The number guard accepted date digits and numbers from example complaints | Only the alert's numeric facts are allowed; ratio words are rejected |
| Complaint text went into the prompt unfenced | Fenced as untrusted data; instruction-like text removed |
| The installer was unpinned; worst-case model time was too long | Ollama version pinned; 60-second timeout |
| Distillation accuracy could be inflated by templates split across train and test | Grouped split by near-duplicate cluster |
| Topic lookup missing for null issues; LSH less sensitive than intended | Key normalised; 25 × 4 bands |
