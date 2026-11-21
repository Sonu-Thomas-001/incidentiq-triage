# Video recording plan (about 10 minutes)

**Status: no video has been recorded or uploaded.** This is a plan only. The IITG Video Submission Guide and official IITG title slide were not available locally; before recording, check this plan against the guide and use the official title slide as slide 1 and as the YouTube thumbnail.

Requirements to honour: student's face visible throughout (camera overlay on screen share), official title slide first, about 10 minutes.

## Timeline

| Time | Segment | Content |
|---|---|---|
| 0:00-0:30 | Title slide | Official IITG slide; name, roll number, project title |
| 0:30-1:30 | Problem | Manual triage cost; recommendation is not a decision; need for explainability and approval |
| 1:30-3:00 | Dataset | Zenodo tickets (2,229; CC BY 4.0), UCI log (141,712 events); synthetic generator labelled DEMO; leakage exclusions; grouped/chronological splits |
| 3:00-4:00 | Code tour | `ml/src/incidentiq_ml`, `backend/app` (routes, workflow, integrations), `frontend/src` |
| 4:00-5:30 | ML experiments | Baselines vs TF-IDF LogReg/SVM; Task A 0.067/0.548/0.800/0.849 macro-F1; Task B top-1 0.797, top-3 0.870; priority as policy; ablation; calibration (ECE 0.174 vs 0.104, disclosed) |
| 5:30-8:00 | Live demo | Follow [demo-guide.md](../demo-guide.md): reporter creates, analyst triages (ML / policy / Gemini panels, warnings), approve or override, engineer accepts, audit timeline |
| 8:00-8:45 | Metrics and explainability | Analytics page, confusion matrix, feature contributions |
| 8:45-9:30 | Limitations | Synthetic team model, small templated data, ServiceNow mock-only, calibration result, no operational claims |
| 9:30-10:00 | Future scope and close | Real combined data, validated thresholds, live ServiceNow test, fairness, sync UI |

## Pre-recording checklist

- Run `scripts/dev.ps1`, confirm login works, reset to a fresh seed if needed.
- Close notifications; browser at 100% zoom; terminal font large.
- Have `docs/model-evaluation.md` open for exact numbers; read only measured values.
- Rehearse once; keep the demo to the 10-step walkthrough.
- After recording: upload, set the thumbnail to the official title slide, and verify the face is visible throughout.
