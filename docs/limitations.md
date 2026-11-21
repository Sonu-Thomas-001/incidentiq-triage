# Limitations

Honest scope statement for the DA377 submission. Nothing here should be read as an operational performance claim.

## Data

1. **No unified real dataset.** Public data offers either text with a category (Zenodo tickets) or structured fields with groups (UCI log), never text + structure + team together. The end-to-end triage therefore pairs a real category model with a **synthetic** team model, and responses are labelled `DEMO`.
2. **Zenodo tickets** are small (2,229), templated (745 exact duplicate texts) and multilingual. The test split has no EOL examples; per-class scores for small classes are noisy. Category definitions are the source's.
3. **UCI log** has no free text, anonymised groups/categories (so groups do not map to the app's teams), one organisation, and a target (first-event group) that equals the final group only 57.7% of the time. Rare groups are bucketed and 906 incidents with unknown first group are dropped.
4. **Synthetic data** has labels defined by the generator with injected noise; high scores and ablation outcomes reflect the generator, not reality.
5. **Priority** has no independent labels; it is the impact x urgency policy. Its 1.0 scores are by construction.

## Modelling

6. Differences of a few macro-F1 points on 607 test rows are within noise. LinearSVC beat the validation-selected LogReg on the Zenodo test split; we kept the pre-registered selection rule.
7. Calibration did not improve test ECE for the deployed category model (0.174 calibrated vs 0.104 native). The model is underconfident, so thresholds are conservative. Thresholds are configuration, not validated guarantees; at 0.9 the category model covers about 1% of test items.
8. Near-duplicate grouping reduces but may not eliminate template leakage.
9. No SHAP/LIME (deliberate; exact linear contributions are provided). No non-linear or transformer models were evaluated.
10. No human-in-the-loop study, latency/load testing, drift monitoring or retraining loop (feedback labels are recorded but unused).

## Application

11. LangGraph orchestration is real but lightweight; routing is disabled by default and only ever proposes.
12. **Gemini** is optional, unverified against a live key in this project, and not part of any evaluation. It can hallucinate; output is labelled `LLM` and never feeds routing or confidence. Redaction is pattern-based and cannot catch all personal data. The default model alias (`gemini-flash-latest`) is a configuration value that must be checked against Google's current model list.
13. **ServiceNow** was tested only against mocks, not a live instance. Basic auth is used for a developer instance.
14. Auth is local (scrypt hashes, JWT bearer). There is no login rate limiting, refresh tokens, password change or user-admin API. SQLite only. The JWT lives in sessionStorage, which is exposed to any XSS.
15. "Request review" in the UI is run-triage; the backend has no separate action. The incident Explorer has no team column or category filter; assignment-per-day trends are unavailable.
16. The ServiceNow sync preview/approve flow exists in the API and client but has no UI.
17. Docker files are untested (Docker was unavailable); the lock file was built on Python 3.13.7 only.
18. The frontend main bundle is about 594 kB (Recharts is split out, zod and the router are not).

## Ethics

Automated routing can misdirect work or disadvantage categories of requesters if models are wrong or biased. The design keeps a human approver in the loop, stores overrides with reasons, never auto-assigns, discloses synthetic/DEMO output, and avoids sending data to external services by default. Real deployments would need a data-protection review, fairness analysis per team/category, and monitoring.
