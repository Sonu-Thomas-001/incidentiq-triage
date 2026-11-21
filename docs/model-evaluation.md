# Model evaluation

Every number here is copied from executed experiments (`docs/report/results/*.json`, rendered in full in [report/evaluation_tables.md](report/evaluation_tables.md)). Test scores come from a single held-out evaluation after validation-only tuning; the winner is picked on validation macro-F1. **Part I is real public data; Part II is synthetic and says nothing about real accuracy.** None of this is an operational performance claim.

## Part I - real public data

### Task A: ticket category (Zenodo, 7 classes, text only)

Grouped split, 1,242 / 380 / 607. Selected on validation: TF-IDF + LogReg (val macro-F1 0.836 vs 0.820 for LinearSVC).

| Model | Val macro-F1 | Test macro-F1 | Test weighted-F1 | Macro precision | Macro recall | Accuracy |
|---|---|---|---|---|---|---|
| majority baseline | 0.096 | 0.067 | 0.100 | 0.042 | 0.167 | 0.250 |
| keyword-rule baseline | 0.537 | 0.548 | 0.830 | 0.655 | 0.534 | 0.848 |
| TF-IDF + LogReg (selected) | 0.836 | 0.800 | 0.890 | 0.777 | 0.843 | 0.888 |
| TF-IDF + LinearSVC | 0.820 | 0.849 | 0.920 | 0.864 | 0.838 | 0.921 |

Observations (not over-interpreted): LinearSVC scored higher on the test set than the validation-selected LogReg. With 607 test rows and rare classes, a difference of a few points is within noise, and we kept the validation-based choice rather than re-selecting on test. LogReg is deployed because it provides probabilities that can be calibrated. The test set has no EOL examples, so macro scores average six classes.

Per-class test results for deployed LogReg:

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Active Directory | 0.611 | 0.846 | 0.710 | 26 |
| Computer-Services | 0.818 | 0.857 | 0.837 | 21 |
| Fileservice | 0.988 | 1.000 | 0.994 | 321 |
| O365 | 0.593 | 0.814 | 0.686 | 43 |
| Software | 0.712 | 0.841 | 0.771 | 44 |
| Support general | 0.938 | 0.697 | 0.800 | 152 |

Figures: `report/figures/tickets_category_confusion.png`, `tickets_category_per_class_recall.png`, `tickets_class_dist.png`, `tickets_text_length.png`.

### Task B: first-event assignment group (UCI log, 44 classes, structured fields)

Chronological split, 16,808 / 3,602 / 3,602. Selected on validation: `structured_all` + LinearSVC.

| Model | Test macro-F1 | Test weighted-F1 | Top-1 | Top-3 |
|---|---|---|---|---|
| majority baseline | 0.016 | 0.359 | n/a | n/a |
| category -> group map | 0.174 | 0.535 | 0.643 | 0.762 |
| category + subcategory + symptom / LogReg | 0.518 | 0.740 | 0.682 | 0.797 |
| category + subcategory + symptom / LinearSVC | 0.533 | 0.773 | 0.735 | 0.811 |
| all fields / LogReg | 0.605 | 0.768 | 0.737 | 0.860 |
| all fields / LinearSVC (selected) | 0.650 | 0.820 | 0.797 | 0.870 |

Ablation (test macro-F1, LinearSVC): category only 0.189; context only (location, contact type) 0.069; impact + urgency only 0.017 (no better than majority); category + subcategory + symptom 0.533; all 0.650. Most of the signal is in the subcategory and symptom fields. Top-3 values are computed from LogReg probabilities and LinearSVC margins used only for ranking. Groups are anonymised, so these results do not transfer to the app's demo teams.

### Task C: priority (UCI log)

Priority is a deterministic function of impact x urgency (0 violations in 141,712 events), so it is implemented as a documented policy, not claimed as ML.

| Method | Test macro-F1 | High-priority recall |
|---|---|---|
| majority baseline | 0.244 | 0.000 |
| impact x urgency policy | 1.000 | 1.000 |
| decision tree on impact, urgency | 1.000 | 1.000 |

The perfect scores are by construction of the label. They are not evidence of learned skill.

### Calibration and confidence routing (deployed category model)

Calibration method chosen on validation ECE: sigmoid (validation ECE 0.220 vs 0.238 for isotonic). Test ECE after calibration is 0.174 and Brier score 0.198; the model is underconfident. Native LogReg probabilities had a **lower** test ECE (0.104), so calibration did not improve ECE on the test set. We report this rather than hide it.

| Confidence threshold | Coverage | Accuracy on covered |
|---|---|---|
| 0.5 | 0.873 | 0.947 |
| 0.6 | 0.774 | 0.983 |
| 0.7 | 0.661 | 0.990 |
| 0.8 | 0.560 | 0.997 |
| 0.9 | 0.012 | 1.000 |

A threshold of 0.9 would cover about 1% of tickets, so the default `ROUTING_THRESHOLD_*=0.90` effectively routes nothing for this model, which is the intended conservative default. Figure: `tickets_category_reliability.png`.

## Part II - synthetic demo (labels defined by the generator)

| Experiment | Selected on validation | Test macro-F1 of selected |
|---|---|---|
| synthetic category (6 classes) | text / LinearSVC | 0.925 |
| synthetic team (5 classes) | structured / LogReg | 0.821 |

The deployed demo team model is text / LogReg (test macro-F1 0.783, top-1 0.768, top-3 1.000); a category -> team map scored higher (macro-F1 0.894), as expected from how the generator ties teams to categories. Ablation differences mirror the generator's design. See the full tables in `report/evaluation_tables.md`.

## Backend and frontend verification (executed)

| Check | Result |
|---|---|
| Backend pytest | 116 passed |
| ML pytest | 14 passed |
| Frontend Vitest | 28 passed |
| Frontend Playwright E2E (real backend) | 4 passed (+1 optional screenshot spec) |
| ruff / black / ESLint / `tsc` / Vite build | clean |
| Alembic upgrade, downgrade base, upgrade, `alembic check` | clean, no model drift |
| Full ML retraining | all committed metrics reproduced exactly |
