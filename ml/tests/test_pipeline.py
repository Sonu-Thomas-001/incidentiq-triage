import numpy as np
import pandas as pd
import pytest

from incidentiq_ml import config as C
from incidentiq_ml import models as M
from incidentiq_ml import validation as V
from incidentiq_ml.experiments import run_classification
from incidentiq_ml.policy import PRIORITY_POLICY, priority_from_impact_urgency
from incidentiq_ml.splits import (
    chronological_split,
    grouped_stratified_split,
    near_duplicate_groups,
)
from incidentiq_ml.synthetic import generate


@pytest.fixture(scope="module")
def syn():
    return generate(600, seed=7)


def test_generator_is_deterministic_and_labelled_synthetic(syn):
    again = generate(600, seed=7)
    pd.testing.assert_frame_equal(syn, again)
    assert syn["is_synthetic"].all() and (syn["provenance"] == C.PROV_SYNTHETIC).all()
    assert not generate(600, seed=8).equals(syn)


def test_priority_is_policy_of_impact_urgency(syn):
    assert (syn.apply(lambda r: priority_from_impact_urgency(r.impact, r.urgency), axis=1) == syn["priority"]).all()
    assert priority_from_impact_urgency(1, 3) is None  # undefined cell is never invented
    assert len(PRIORITY_POLICY) == 8


def test_preprocessing_is_deterministic(syn):
    f1, f2 = M.make_frame(syn, ["service", "impact"]), M.make_frame(syn, ["service", "impact"])
    pd.testing.assert_frame_equal(f1, f2)
    a = M.build_pipeline("combined", "logreg", {"C": 1.0, "ngram": 1}, ["service", "impact"])
    b = M.build_pipeline("combined", "logreg", {"C": 1.0, "ngram": 1}, ["service", "impact"])
    y = syn["category"]
    pa, pb = a.fit(f1, y).predict_proba(f1), b.fit(f1, y).predict_proba(f1)
    np.testing.assert_allclose(pa, pb)


def test_vectoriser_vocabulary_comes_from_training_rows_only(syn):
    X = M.make_frame(syn, [])
    pipe = M.build_pipeline("text", "logreg", {"C": 1.0, "ngram": 1}, [])
    pipe.fit(X.iloc[:50], syn["category"].iloc[:50])
    vocab = set(pipe.named_steps["features"].named_transformers_["word"].vocabulary_)
    held_out_only = {"zzzunseenzzz"}
    assert not (vocab & held_out_only)
    held = X.iloc[50:]["text"].str.lower().str.findall(r"\b\w\w+\b").explode().unique()
    assert set(held) - vocab  # held-out rows contain terms that were NOT learned from them


def test_leakage_guard_rejects_target_and_post_triage_columns():
    with pytest.raises(V.ValidationError):
        V.assert_no_leakage(["text", "resolved_at"], "assignment_group", "t")
    with pytest.raises(V.ValidationError):
        V.assert_no_leakage(["text", "assignment_group"], "assignment_group", "t")
    with pytest.raises(V.ValidationError):
        V.assert_no_leakage(["text", "final_assignment_group"], "assignment_group", "t")
    V.assert_no_leakage(["text", "service", "impact"], "assignment_group", "t")


def test_schema_validation_catches_missing_columns_and_duplicates():
    with pytest.raises(V.ValidationError):
        V.validate_schema(pd.DataFrame({"incident_id": ["a"]}), "tickets")
    with pytest.raises(V.ValidationError):
        V.validate_schema(
            pd.DataFrame(
                {
                    "incident_id": ["a", "a"],
                    "description": ["x", "y"],
                    "category": ["c", "c"],
                }
            ),
            "tickets",
        )


def test_grouped_split_never_straddles_a_group(syn):
    groups = pd.factorize(syn["template_id"])[0]
    sp = grouped_stratified_split(syn["category"], groups)
    sets = [set(groups[i]) for i in (sp.train, sp.val, sp.test)]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])
    allidx = np.concatenate([sp.train, sp.val, sp.test])
    assert len(set(allidx)) == len(allidx) == len(syn)


def test_chronological_split_has_no_time_overlap(syn):
    sp = chronological_split(syn["created_at"])
    t = syn["created_at"]
    assert t.iloc[sp.train].max() <= t.iloc[sp.val].min() and t.iloc[sp.val].max() <= t.iloc[sp.test].min()


def test_near_duplicates_are_grouped():
    s = pd.Series(
        [
            "VPN down at office 12",
            "vpn down at office 99",
            "printer jammed badly",
            "completely different thing",
        ]
    )
    g = near_duplicate_groups(s)
    assert g[0] == g[1] and g[0] != g[2] and g[2] != g[3]


def test_topk_only_with_valid_scores_and_metrics_are_consistent(syn):
    X = M.make_frame(syn, [])
    y = syn["assignment_group"]
    sp = chronological_split(syn["created_at"])
    tr, te = sp.train, sp.test
    maj = M.MajorityBaseline().fit(X.iloc[tr], y.iloc[tr])
    r = M.evaluate(maj, X.iloc[te], y.iloc[te], topk=(1, 3))
    assert r["topk"] == {"1": None, "3": None} and "not computed" in r["topk_note"]
    lr = M.build_pipeline("text", "logreg", {"C": 1.0, "ngram": 1}, []).fit(X.iloc[tr], y.iloc[tr])
    r = M.evaluate(lr, X.iloc[te], y.iloc[te], topk=(1, 3))
    assert r["topk"]["1"] == pytest.approx(r["accuracy"]) and r["topk"]["3"] >= r["topk"]["1"]
    cm = np.array(r["confusion_matrix"]["matrix"])
    assert cm.sum() == r["n"]


def test_ece_perfectly_calibrated_and_overconfident():
    classes = np.array(["a", "b"])
    y = np.array(["a"] * 50 + ["b"] * 50)
    perfect = np.array([[1.0, 0.0]] * 50 + [[0.0, 1.0]] * 50)
    assert M.calibration_metrics(perfect, classes, y)["ece_top_label"] == pytest.approx(0.0)
    wrong = np.array([[0.99, 0.01]] * 100)
    assert M.calibration_metrics(wrong, classes, y)["ece_top_label"] > 0.4


def test_keyword_baseline_learns_from_train_only_and_falls_back_to_majority():
    X = pd.DataFrame({"text": ["vpn tunnel failing"] * 5 + ["printer toner empty"] * 5 + ["misc request"] * 8})
    y = ["net"] * 5 + ["hw"] * 5 + ["gen"] * 8
    kw = M.KeywordRuleClassifier(min_count=2).fit(X, y)
    pred = kw.predict(pd.DataFrame({"text": ["vpn tunnel", "toner is empty", "qwerty asdf"]}))
    assert list(pred) == ["net", "hw", "gen"]  # unknown text -> majority class


def test_category_map_baseline_handles_unseen_category():
    X = pd.DataFrame({"category": ["a", "a", "b", "b", "b"]})
    m = M.CategoryMapBaseline().fit(X, ["t1", "t1", "t2", "t2", "t1"])
    p = m.predict(pd.DataFrame({"category": ["a", "b", "zzz"]}))
    assert list(p[:2]) == ["t1", "t2"] and p[2] in {"t1", "t2"}
    assert m.predict_proba(pd.DataFrame({"category": ["zzz"]})).sum() == pytest.approx(1.0)


def test_test_split_is_untouched_by_tuning(syn):
    """Changing test labels must not change anything selected during tuning/validation."""
    X = M.make_frame(syn, ["service"])
    y = syn["category"].copy()
    sp = chronological_split(syn["created_at"])
    kw = dict(X=X, split=sp, cat_cols={"text": []}, fast=True)
    a = run_classification(name="a", y=y, **kw)
    y2 = y.copy()
    y2.iloc[sp.test] = "Network"
    b = run_classification(name="b", y=y2, **kw)
    assert a["models"]["text/logreg"]["tuning_trials"] == b["models"]["text/logreg"]["tuning_trials"]
    assert a["selected_by_validation"] == b["selected_by_validation"]
    assert a["models"]["text/logreg"]["test"]["accuracy"] != b["models"]["text/logreg"]["test"]["accuracy"]
