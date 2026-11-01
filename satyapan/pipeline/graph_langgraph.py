"""Optional: the same nodes wired into LangGraph (pip install -r requirements-optional.txt).

Honest note: with deterministic nodes, LangGraph adds little over pipeline.graph.run.
It becomes worth it when an LLM planner chooses tools, when urlscan results must
resume a paused investigation (checkpointing), or when a human reviewer must
approve a verdict (interrupts). tests/test_graph.py checks both runners agree.
"""
from __future__ import annotations

from satyapan.pipeline.graph import LINEAR, TAIL, Context, route_after_rank, traced


def build(ctx: Context):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(dict)
    for name in LINEAR + ["resolve_conflict"] + TAIL:
        g.add_node(name, traced(name, ctx))
    g.add_edge(START, LINEAR[0])
    for a, b in zip(LINEAR, LINEAR[1:]):
        g.add_edge(a, b)
    g.add_conditional_edges(LINEAR[-1], route_after_rank, {"resolve_conflict": "resolve_conflict", "decide": "decide"})
    g.add_edge("resolve_conflict", "decide")
    for a, b in zip(TAIL, TAIL[1:]):
        g.add_edge(a, b)
    g.add_edge(TAIL[-1], END)
    return g.compile()
