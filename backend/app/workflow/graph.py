"""Graph wiring.

triage:   intake -> validate_input -> ml_prediction -> priority_policy -> explanation_retrieval
          -> gemini_assist -> routing_policy -> human_review -> audit_log
approval: approval_gate -> approved_assignment -> audit_log
Both paths short-circuit to END when the request is an idempotent replay.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.workflow import nodes
from app.workflow.state import WorkflowState


def _entry_router(state: WorkflowState) -> str:
    return "approval_gate" if state.get("action") == "approve" else "intake"


def _after_gate(state: WorkflowState) -> str:
    return "end" if state.get("reused") else "continue"


@lru_cache(maxsize=1)
def build_graph():
    g = StateGraph(WorkflowState)
    g.add_node("intake", nodes.intake)
    g.add_node("validate_input", nodes.validate_input)
    # Only transient file-system errors are retried; model faults degrade to NOT_READY inside the node.
    g.add_node(
        "ml_prediction",
        nodes.ml_prediction,
        retry_policy=RetryPolicy(
            max_attempts=3, initial_interval=0.1, backoff_factor=2.0, retry_on=OSError
        ),
    )
    g.add_node("priority_policy", nodes.priority_policy)
    g.add_node("explanation_retrieval", nodes.explanation_retrieval)
    g.add_node("gemini_assist", nodes.gemini_assist)
    g.add_node("routing_policy", nodes.routing)
    g.add_node("human_review", nodes.human_review)
    g.add_node("approval_gate", nodes.approval_gate)
    g.add_node("approved_assignment", nodes.approved_assignment)
    g.add_node("audit_log", nodes.audit_log)

    g.add_conditional_edges(
        START, _entry_router, {"intake": "intake", "approval_gate": "approval_gate"}
    )
    g.add_conditional_edges("intake", _after_gate, {"end": END, "continue": "validate_input"})
    g.add_edge("validate_input", "ml_prediction")
    g.add_edge("ml_prediction", "priority_policy")
    g.add_edge("priority_policy", "explanation_retrieval")
    g.add_edge("explanation_retrieval", "gemini_assist")
    g.add_edge("gemini_assist", "routing_policy")
    g.add_edge("routing_policy", "human_review")
    g.add_edge("human_review", "audit_log")
    g.add_conditional_edges(
        "approval_gate", _after_gate, {"end": END, "continue": "approved_assignment"}
    )
    g.add_edge("approved_assignment", "audit_log")
    g.add_edge("audit_log", END)
    return g.compile()


def mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()
