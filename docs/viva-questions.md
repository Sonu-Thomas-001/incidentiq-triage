# Viva questions and answers

Short, defensible answers. Numbers come from [model-evaluation.md](model-evaluation.md).

**1. What data did you use and under what license?**
Two public datasets, both CC BY 4.0: Zenodo IT tickets (doi 10.5281/zenodo.7648117, 2,229 tickets, category target) and the UCI incident event log (doi 10.24432/C57S4H, 141,712 events / 24,918 incidents). A seeded synthetic generator supplies demo-only data. Access date 2026-11-21; raw files are not in git, only download commands with hash checks.

**2. Why not just use one dataset?**
None has text, structured fields and team labels together. We separated tasks by what each dataset supports and labelled the combined app output as DEMO because the team model is synthetic.

**3. What is data leakage and how did you prevent it?**
Information at training time that would not exist at prediction time or that reveals the label. We dropped resolution/closure/reassignment-history columns, used only first-event values, blocked target-derived predictors with a guard and tests, fitted all preprocessing inside pipelines on training data only, and split by near-duplicate group (tickets) or time (UCI). A random split gave macro-F1 0.781 vs 0.736 grouped, showing the inflation.

**4. How does TF-IDF work?**
It weights a term by its frequency in a document (we use sublinear tf, 1+log tf) times the inverse document frequency log(N/df), so terms common to all tickets get low weight. The result is a sparse vector; we add character 3-5-grams to tolerate typos and multilingual text.

**5. Why Logistic Regression?**
A linear, regularised, interpretable baseline that outputs class probabilities (softmax), which we can calibrate. Coefficients x TF-IDF values give exact per-prediction contributions.

**6. Why Linear SVM, and what is the catch?**
It maximises the margin and is strong on sparse text. It outputs decision margins, not probabilities, so we never call them probabilities; we use margins only to rank classes (top-K) and calibrate if a probability is needed.

**7. Why macro F1 rather than accuracy?**
Classes are imbalanced (7.4:1 in tickets; one group is 51% of UCI incidents). Accuracy rewards the majority class (majority baseline accuracy 0.25 on tickets, 0.52 on UCI groups), while macro F1 averages per-class F1 equally. We still report weighted F1, precision, recall and per-class results.

**8. What is top-K accuracy and when is it valid?**
The fraction of cases where the true class is among the K highest-scored classes. We report it for Task B models with valid scores; a majority or keyword rule has no ranking, so it is shown as n/a. On UCI the selected model has top-1 0.797 and top-3 0.870.

**9. What is calibration and what did you find?**
Calibration means a predicted 0.8 is correct about 80% of the time. We calibrated with sigmoid (chosen on validation ECE) and measured ECE, Brier score and reliability bins. Test ECE was 0.174 vs 0.104 for the native probabilities, so calibration did not help ECE here; we report that honestly. The model is underconfident, so thresholds are conservative.

**10. Why no SHAP or LIME?**
For a linear model the coefficient x feature value decomposition is exact, so SHAP/LIME would be a slower approximation of the same thing. We added permutation importance for structured columns. We would add SHAP for a non-linear model.

**11. How do you handle class imbalance?**
`class_weight="balanced"`, stratified (grouped) splits, macro-averaged metrics, per-class recall tables, rare-group bucketing in UCI, and baselines that show what imbalance alone achieves.

**12. How are confidence thresholds used?**
Per-task thresholds (`ROUTING_THRESHOLD_*`, default 0.90) apply only to real, calibrated models, and only produce a proposal; an analyst still approves. Routing is disabled by default. For the category model, threshold 0.7 covers 66.1% of test items at 0.990 accuracy, but this is one small test set, not a validated guarantee.

**13. Why is priority not ML?**
We verified priority is a deterministic function of impact x urgency with 0 violations in 141,712 events. A model reaching 1.0 would just rediscover the rule, so we implemented the policy and said so.

**14. What does LangGraph add?**
An explicit, typed, auditable workflow: intake, validation, ML prediction, priority policy, explanation, optional Gemini, routing policy, human review, approval and audit logging, with idempotency keys so replays do not duplicate effects. It orchestrates; it is not the predictor.

**15. What are Gemini's limitations here?**
It can hallucinate and is not evidence of model reasoning. It is opt-in, sends only redacted, size-bounded text, returns structured summary/extraction/missing-info only (no team, priority or confidence), falls back safely without credentials, and is excluded from all evaluations.

**16. How does the ServiceNow integration stay safe?**
Read-only by default; writes need mode `live` (or `mock`), a prior local approval, a preview showing instance host, sys_id and the exact field change, explicit confirmation including the host, and a matching remote `sys_updated_on`. It patches only `assignment_group` and is idempotent. Verified against mocks only.

**17. How do you protect against concurrent edits?**
Optimistic concurrency: each mutation carries `expected_version` and the database update is compare-and-set, returning 409 STALE_VERSION if stale.

**18. What ethical issues arise?**
Misrouting harm, bias across categories or requesters, privacy of ticket text, over-trust in confidence scores or LLM text. Mitigations: human approval, reasons on overrides, audit trail, DEMO/synthetic labelling, no external transmission by default. Future work: fairness analysis and data-protection review.

**19. What would you do with more time?**
A real combined dataset, a real team model, validated thresholds, a live ServiceNow test, retraining from `feedback_labels`, drift monitoring, and a sync UI.

**20. How can I reproduce your results?**
`requirements-lock.txt`, seed 42, `python -m incidentiq_ml all`. We re-ran the full training and every committed metric reproduced exactly (only timing fields differ).
