"""Left-to-right ordering of a process graph (spec 12 §3.12).

Why: two callers lay a process out by column, the map grounding (spec 20) and the BPMN drawing
(spec 24), and a real process loops ("then we go back to step 2"). Both need the same ranks, and
grounding runs long before any drawing exists, so the ordering lives in the pure domain.
What: `rank_nodes` gives each node its longest-path rank (0 = leftmost) after a depth-first search
has set the back edges (loops) aside, so every node gets a rank whatever the graph.
Must not: know about drawing, BPMN or diagrams; edges to unknown nodes and self-loops are ignored,
never raised. Tests: AC-12.38.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator

_WHITE, _GRAY, _BLACK = 0, 1, 2


def rank_nodes(
    node_ids: Iterable[str], edges: Iterable[tuple[str, str]]
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    """Longest-path rank of every node, and the back edges left out of the ranking.

    The search starts from the nodes nobody flows into, in the given order, then from any node
    not yet visited. Duplicate ids and edges count once.
    """
    ids = list(dict.fromkeys(node_ids))
    known = set(ids)
    unique = list(dict.fromkeys((a, b) for a, b in edges if a in known and b in known and a != b))
    successors: dict[str, list[str]] = {i: [] for i in ids}
    has_incoming: set[str] = set()
    for a, b in unique:
        successors[a].append(b)
        has_incoming.add(b)

    color: dict[str, int] = dict.fromkeys(ids, _WHITE)
    back: set[tuple[str, str]] = set()
    for root in [i for i in ids if i not in has_incoming] + ids:
        if color[root] != _WHITE:
            continue
        color[root] = _GRAY
        stack: list[tuple[str, Iterator[str]]] = [(root, iter(successors[root]))]
        while stack:
            node, remaining = stack[-1]
            nxt = next(remaining, None)
            if nxt is None:
                color[node] = _BLACK
                stack.pop()
            elif color[nxt] == _WHITE:
                color[nxt] = _GRAY
                stack.append((nxt, iter(successors[nxt])))
            elif color[nxt] == _GRAY:
                back.add((node, nxt))

    indegree = dict.fromkeys(ids, 0)
    forward: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in unique:
        if (a, b) not in back:
            forward[a].append(b)
            indegree[b] += 1
    rank = dict.fromkeys(ids, 0)
    queue = deque(i for i in ids if indegree[i] == 0)
    while queue:
        node = queue.popleft()
        for nxt in forward[node]:
            rank[nxt] = max(rank[nxt], rank[node] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return rank, back
