# ML methodology

Reproduce everything with `python -m incidentiq_ml all` from `ml/` (see the README). Seed 42 throughout. A second full training run on this repository reproduced every committed metric exactly; only wall-clock `fit_s` fields differed.

## Tasks

| Task | Data | Target | Split | Models |
|---|---|---|---|---|
| A: category | Zenodo tickets (REAL), text only | `category` (7) | stratified **grouped** 1,242 / 380 / 607 | majority, keyword rules, TF-IDF + LogReg, TF-IDF + LinearSVC |
| B: assignment group | UCI log (REAL), structured fields only | first-event group (44 classes after bucketing) | **chronological** 70/15/15 by `created_at` | majority, category-to-group map, LogReg and LinearSVC over five feature sets |
| C: priority | UCI log (REAL) | `priority` | chronological | majority, impact x urgency policy, decision tree |
| Demo | synthetic generator | category, team | stratified grouped | same families plus text / structured / combined ablation |

## Pipeline

1. **Validation** (`validation.py`): schema, missing values, exact and near-duplicate text, class balance, text length. Output in `docs/report/results/validation_*.json`.
2. **EDA** (`eda.py`): class distribution, text length, volume over time, Cramer's V associations, figures in `docs/report/figures/`.
3. **Leakage control**: post-triage columns dropped; a guard rejects target-derived predictors.
4. **Splitting**: tickets are highly templated (745 exact duplicate texts), so near-duplicate clusters are kept in one partition (grouped, stratified). UCI is time dependent, so it uses a chronological split. A diagnostic with a fixed LogReg configuration gives macro-F1 0.736 on the grouped split versus 0.781 on a naive random split, i.e. random splitting would overstate performance.
5. **Features**: all preprocessing lives inside scikit-learn `Pipeline` / `ColumnTransformer` and is fitted on training data only.
   - Text: word TF-IDF (sublinear TF, 1 or 1-2 grams) with an optional character 3-5 gram TF-IDF (`min_df=2`).
   - Structured: `OneHotEncoder(handle_unknown="ignore")`, so unseen categories at inference are tolerated.
6. **Models**: `LogisticRegression` and `LinearSVC`, both `class_weight="balanced"`.
7. **Tuning**: C, word n-gram range and char n-grams on/off, on the validation split only. Finalists are refit on train + validation and evaluated once on the test split. The winner is chosen by validation macro-F1. Test numbers are also printed for every ablation cell, but they never drive selection.
8. **Metrics**: macro F1 (primary, because classes are imbalanced), weighted F1, macro precision/recall, accuracy, per-class precision/recall/F1, confusion matrices. Top-1/top-3 for Task B only for models that have valid scores; SVM margins rank classes but are never reported as probabilities; majority and keyword baselines have no top-K. High-priority recall for Task C.
9. **Calibration** (confidence routing): sigmoid or isotonic via cross-validated `CalibratedClassifierCV` (grouped CV), chosen by validation ECE. ECE, Brier score and reliability bins are stored in the results JSON.
10. **Artifacts**: joblib bundle per model plus `manifest.json` with library versions, configuration, class mapping, metrics, dataset fingerprint, split, SHA-256 and model version.

## Ablation

- Synthetic (DEMO): text-only, structured-only, combined.
- UCI (REAL, Task B): category only; category + subcategory + symptom; context (location, contact type); impact + urgency; all. Results are in [model-evaluation.md](model-evaluation.md).
- Tickets have text only, so no text/structured ablation is possible there.

## Explainability

- **Per-prediction**: linear coefficient x TF-IDF value from an uncalibrated linear model with the same configuration (exact for a linear model). Served to the UI as "influential features".
- **Global**: top coefficients per class; permutation importance (10 repeats) over structured column groups.
- **SHAP/LIME**: deliberately not added. For linear models the coefficients are the model's own decomposition, so a surrogate adds approximation error without new information. Revisit if a non-linear model is introduced.
- Gemini text, when enabled, is labelled `LLM` and is never presented as model reasoning.

## Confidence and routing

Confidence is shown only when it is a calibrated probability. Routing is disabled by default (`ROUTING_ENABLED=false`); when enabled, a task passes only if the model is real (not demo), calibrated, and above its configurable threshold, and even then the result is a proposal that an analyst must approve (`auto_assign` is always false). The coverage/accuracy trade-off table in [model-evaluation.md](model-evaluation.md) is the evidence available for choosing thresholds; thresholds themselves are not validated on operational data.

## Model loading safety

`ml_service` loads a joblib bundle only if the file is inside `MODEL_DIR`, its SHA-256 matches the manifest, and the recorded scikit-learn/numpy/scipy/pandas versions match the running environment; otherwise it refuses and triage reports `NOT_READY`. joblib files execute code on load, so only load artifacts you trained yourself.

## Commands

```bash
cd ml
python -m incidentiq_ml download   # fetch public datasets (hash-checked)
python -m incidentiq_ml prepare    # build parquet files
python -m incidentiq_ml validate   # validation reports
python -m incidentiq_ml eda        # figures
python -m incidentiq_ml train      # about 6 minutes on a laptop; writes artifacts + results JSON
python -m incidentiq_ml all        # all of the above
python -m incidentiq_ml.report_tables   # regenerate docs/report/evaluation_tables.md
python -m pytest                   # 14 ML tests
```

(Set `PYTHONPATH=src` or `pip install -e .` equivalent; the setup scripts do this.) `--fast` uses a tiny grid for smoke tests only; do not report its numbers.
