import pytest

from incidentiq_ml import servicenow_seed as S
from incidentiq_ml.servicenow_data import ServiceNowPullError


def test_build_is_deterministic_balanced_and_unique():
    a, b = S.build(100), S.build(100)
    assert a == b
    assert {r["category"] for r in a} == set(S.SPEC)
    assert len({r["category"] for r in a[:5]}) == 5
    assert len({(r["short_description"], r["description"]) for r in a}) == 100
    assert all(r["correlation_id"].startswith(S.MARKER) for r in a)
    assert all(r["impact"] in "123" and r["urgency"] in "123" for r in a)


def test_seed_rejects_bad_count_before_any_network_call():
    with pytest.raises(ServiceNowPullError):
        S.seed(count=S.MAX_COUNT + 1)
