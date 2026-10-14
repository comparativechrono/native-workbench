"""Deterministic orthogonal routing around padded diagram cards.

Callers supply port escape/entry points outside every obstacle. The Cartesian
visibility grid uses obstacle boundaries, so skip-rank and backwards links go
around cards instead of hiding behind them. An empty route means an endpoint
is obscured (for example overlapping manually positioned cards); there is no
unsafe straight-line fallback.
"""
from __future__ import annotations

from heapq import heappop, heappush

# Large graphs retain all card obstacles; only cosmetic edge separation is bounded.
MAX_COSMETIC_CARDS = 64


def intersects(a, b, box):
    """Whether an axis-aligned segment crosses a rectangle's open interior."""
    left, top, right, bottom = box
    if a[0] == b[0]:
        return left < a[0] < right and max(min(a[1], b[1]), top) < min(max(a[1], b[1]), bottom)
    if a[1] == b[1]:
        return top < a[1] < bottom and max(min(a[0], b[0]), left) < min(max(a[0], b[0]), right)
    raise ValueError("Routing segments must be orthogonal")


def crossing_cost(a, b, occupied):
    penalty = 0
    horizontal = a[1] == b[1]
    for c, d in occupied:
        other_horizontal = c[1] == d[1]
        if horizontal == other_horizontal:
            axis, fixed = (0, 1) if horizontal else (1, 0)
            if a[fixed] == c[fixed]:
                penalty += 100 * max(0, min(max(a[axis], b[axis]), max(c[axis], d[axis])) -
                                  max(min(a[axis], b[axis]), min(c[axis], d[axis])))
        else:
            h1, h2, v1, v2 = (a, b, c, d) if horizontal else (c, d, a, b)
            if min(h1[0], h2[0]) < v1[0] < max(h1[0], h2[0]) and min(v1[1], v2[1]) < h1[1] < max(v1[1], v2[1]):
                penalty += 30
    return penalty


def route(start, end, obstacles, bend_cost=18, occupied=()):
    """Return a shortest Manhattan route with a penalty for unnecessary bends."""
    if len(obstacles) > MAX_COSMETIC_CARDS:
        occupied = ()
    if any(l < p[0] < r and t < p[1] < b for p in (start, end) for l, t, r, b in obstacles):
        return []
    xs = sorted({start[0], end[0], *(v for l, _, r, _ in obstacles for v in (l, r))})
    ys = sorted({start[1], end[1], *(v for _, t, _, b in obstacles for v in (t, b))})
    if occupied:
        # Nearby lanes let independent dependencies remain visually distinct.
        # True fan-out is omitted by callers and may share its common trunk.
        xs = sorted(set(xs) | {p[0] + offset for segment in occupied for p in segment for offset in (-8, 8)})
        ys = sorted(set(ys) | {p[1] + offset for segment in occupied for p in segment for offset in (-8, 8)})
    nx, ny = len(xs), len(ys)
    initial = (xs.index(start[0]), ys.index(start[1]), 0)
    target = (xs.index(end[0]), ys.index(end[1]))
    best = {initial: 0}
    previous = {}
    queue = [(abs(end[0] - start[0]) + abs(end[1] - start[1]), 0, initial)]
    clear = {}
    while queue:
        _, cost, state = heappop(queue)
        if best.get(state) != cost:
            continue
        x, y, direction = state
        if (x, y) == target:
            points = []
            while state is not None:
                points.append((xs[state[0]], ys[state[1]]))
                state = previous.get(state)
            points.reverse()
            return simplify(points)
        for xx, yy, dd in ((x - 1, y, 1), (x + 1, y, 1), (x, y - 1, 2), (x, y + 1, 2)):
            if not (0 <= xx < nx and 0 <= yy < ny):
                continue
            a, b = (xs[x], ys[y]), (xs[xx], ys[yy])
            key = (min(x, xx), min(y, yy), dd)
            if key not in clear:
                clear[key] = not any(intersects(a, b, box) for box in obstacles)
            if not clear[key]:
                continue
            next_cost = cost + abs(a[0] - b[0]) + abs(a[1] - b[1]) + (bend_cost if direction and direction != dd else 0) + crossing_cost(a, b, occupied)
            nxt = (xx, yy, dd)
            if next_cost < best.get(nxt, float('inf')):
                best[nxt] = next_cost
                previous[nxt] = state
                heuristic = abs(b[0] - end[0]) + abs(b[1] - end[1])
                heappush(queue, (next_cost + heuristic, next_cost, nxt))
    return []


def simplify(points):
    result = []
    for p in points:
        if result and p == result[-1]:
            continue
        if len(result) >= 2 and ((result[-2][0] == result[-1][0] == p[0]) or
                                 (result[-2][1] == result[-1][1] == p[1])):
            result[-1] = p
        else:
            result.append(p)
    return result
