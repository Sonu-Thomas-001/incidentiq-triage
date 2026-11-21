# Dataset card

All figures below are read from `docs/report/results/validation_*.json` and the manifests. Raw data is never committed; `python -m incidentiq_ml download` fetches it and verifies pinned SHA-256 hashes. Access date for both downloads: 2026-11-21.

## 1. Zenodo IT-support tickets (REAL) - Task A, category

| | |
|---|---|
| Source | https://doi.org/10.5281/zenodo.7648117 |
| License | CC BY 4.0 (attribution required) |
| Records | 2,229 tickets (train and test files from the source concatenated, then re-split by us) |
| Fields | ticket text, `category` (7 classes), author/split flag |
| Target provenance | `category` as recorded in the source data; not relabelled by us |
| Classes | Support general 762, Fileservice 684, Software 222, O365 219, Active Directory 133, Computer-Services 106, EOL 103 (max:min = 7.4) |
| Text length | mean 231 characters, median 141, max 1,908 |
| Duplicates | 745 exact and 784 normalised duplicate texts (templated tickets); handled by grouped splitting |
| Languages | multilingual, highly templated |

Field registry (observed / derived / synthetic / absent): `incident_id` observed, `description` observed, `category` observed, `short_description` **derived** (first sentence of the text); `priority`, `assignment_group`, `created_at`, `service`, `impact`, `urgency` **absent**. Absent fields are not back-filled.

## 2. UCI incident event log (REAL) - Task B (assignment group) and Task C (priority)

| | |
|---|---|
| Source | https://doi.org/10.24432/C57S4H |
| License | CC BY 4.0 |
| Records | 141,712 events covering 24,918 incidents |
| Fields used | `created_at`, `category`, `subcategory`, `u_symptom`, `contact_type`, `location`, `impact`, `urgency`, `priority`, first-event `assignment_group` |
| Text | none (the log is anonymised and has no free text) |
| Target (B) | assignment group of the first event (69 anonymised groups, e.g. "Group 70"; rare groups bucketed to `OTHER (rare)`; 906 incidents with unknown first group dropped) |
| Target (C) | recorded `priority`, which is a deterministic function of impact x urgency (0 violations in 141,712 events) |
| Missingness | `u_symptom` 23.0%, `final_assignment_group` 8.7%, first `assignment_group` 3.6% |
| Imbalance | one group holds 12,790 incidents (about 51%); five singleton classes before bucketing |

Because groups and categories are anonymised, UCI group labels do **not** correspond to this app's demo teams.

## 3. Synthetic generator (DEMO only)

`ml/src/incidentiq_ml/synthetic.py` produces seeded synthetic incidents (3,000 rows for the committed run) with category, team, priority, service, impact and urgency, plus injected label noise. Labels are defined by the generator, so ablation outcomes mirror its design. It exists only to demonstrate the pipeline and to give the app a five-team demo model. Results from it must never be cited as real accuracy. Seeded demo users and incidents in the database are separately labelled `is_synthetic = true` with `[SYNTHETIC]` titles.

## 4. Leakage exclusions

Resolution notes, closure fields, final reassignment history and other post-triage columns are dropped (`config.UCI_LEAKAGE_COLUMNS`). Only opening-time (first-event) values are used. A guard rejects any predictor equal to or derived from the target, and unit tests cover it (`ml/tests/test_pipeline.py`). In UCI, first-event group equals the final group for only 57.7% of incidents, so the Task B target is the group at opening, not the eventual resolver.

## 5. Known limitations of the data

- No single public dataset provides text, structured fields and team labels together. The end-to-end app therefore combines a real category model with a synthetic team model and labels triage responses `DEMO`.
- Tickets are small, templated and multilingual; one class (EOL) has no test examples after the grouped split.
- UCI is a single organisation's log with anonymised fields; generalisation to other settings is unknown.
- Priority has no independent labels; it is the impact x urgency policy.
- ServiceNow sample records from a personal developer instance were not used for training or evaluation.

## 6. Ethics and privacy

Both public datasets are released for reuse under CC BY 4.0 and contain no confidential enterprise data used by us. Attribution: cite the two DOIs above. Do not commit raw data (the `.gitignore` excludes `ml/data/raw` and `ml/data/processed`).
