"""Tests for left-to-right node ranking of a process graph (spec 12 §3.12).

Why: the map grounding (spec 20) and the BPMN drawing (spec 24) both lay nodes out by rank, and
a process with a loop ("then we go back to step 2") must still give every node a column.
What: linear flows, loops, pure cycles, isolated nodes, unknown endpoints, self-loops and
duplicates. Implements AC-12.38.
"""

from app.services.process_discovery.domain.node_order import rank_nodes


def test_a_linear_flow_ranks_left_to_right():
    """AC-12.38."""
    rank, back = rank_nodes(["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("c", "d")])
    assert rank == {"a": 0, "b": 1, "c": 2, "d": 3}
    assert back == set()


def test_a_loop_yields_one_back_edge_and_ranks_every_node():
    """AC-12.38."""
    rank, back = rank_nodes(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "b")])
    assert back == {("c", "b")}
    assert rank == {"a": 0, "b": 1, "c": 2}


def test_longest_path_wins():
    """§3.12: longest-path rank, so a shortcut does not pull a node left."""
    rank, _ = rank_nodes(["a", "b", "c"], [("a", "b"), ("b", "c"), ("a", "c")])
    assert rank["c"] == 2


def test_a_pure_cycle_and_isolated_nodes_get_ranks():
    """AC-12.38."""
    rank, back = rank_nodes(["a", "b", "x"], [("a", "b"), ("b", "a")])
    assert set(rank) == {"a", "b", "x"}
    assert len(back) == 1
    assert rank["x"] == 0


def test_unknown_nodes_self_loops_and_duplicates_are_ignored():
    """AC-12.38."""
    rank, back = rank_nodes(["a", "b", "a"], [("a", "b"), ("a", "b"), ("b", "zzz"), ("q", "a"), ("b", "b")])
    assert rank == {"a": 0, "b": 1}
    assert back == set()
