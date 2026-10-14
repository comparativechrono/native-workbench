#ifndef NATIVE_WORKBENCH_DAG_ROUTING_H
#define NATIVE_WORKBENCH_DAG_ROUTING_H
// Win32-independent geometry, also compiled by tests/test_dag_routing.py.
#include <algorithm>
#include <array>
#include <cstdlib>
#include <limits>
#include <map>
#include <queue>
#include <tuple>
#include <vector>

namespace dag_routing {
constexpr size_t max_cosmetic_cards = 64;
struct Point {
  int x = 0, y = 0;
  bool operator==(const Point &other) const { return x == other.x && y == other.y; }
};
struct Rect { int left, top, right, bottom; };
inline bool intersects(Point a, Point b, Rect r) {
  if (a.x == b.x)
    return r.left < a.x && a.x < r.right &&
           std::max(std::min(a.y, b.y), r.top) < std::min(std::max(a.y, b.y), r.bottom);
  return r.top < a.y && a.y < r.bottom &&
         std::max(std::min(a.x, b.x), r.left) < std::min(std::max(a.x, b.x), r.right);
}
inline std::vector<Point> simplify(const std::vector<Point> &points) {
  std::vector<Point> result;
  for (auto p : points) {
    if (!result.empty() && result.back() == p)
      continue;
    if (result.size() >= 2 &&
        ((result[result.size() - 2].x == result.back().x && result.back().x == p.x) ||
         (result[result.size() - 2].y == result.back().y && result.back().y == p.y)))
      result.back() = p;
    else
      result.push_back(p);
  }
  return result;
}
using Segment = std::pair<Point, Point>;
inline int crossing_cost(Point a, Point b, const std::vector<Segment> &occupied) {
  int penalty = 0;
  const bool horizontal = a.y == b.y;
  for (const auto &[c, d] : occupied) {
    const bool otherHorizontal = c.y == d.y;
    if (horizontal == otherHorizontal) {
      if (horizontal && a.y == c.y)
        penalty += 100 * std::max(0, std::min(std::max(a.x, b.x), std::max(c.x, d.x)) -
                                   std::max(std::min(a.x, b.x), std::min(c.x, d.x)));
      else if (!horizontal && a.x == c.x)
        penalty += 100 * std::max(0, std::min(std::max(a.y, b.y), std::max(c.y, d.y)) -
                                   std::max(std::min(a.y, b.y), std::min(c.y, d.y)));
    } else {
      const Point h1 = horizontal ? a : c, h2 = horizontal ? b : d,
                  v1 = horizontal ? c : a, v2 = horizontal ? d : b;
      if (std::min(h1.x, h2.x) < v1.x && v1.x < std::max(h1.x, h2.x) &&
          std::min(v1.y, v2.y) < h1.y && h1.y < std::max(v1.y, v2.y))
        penalty += 30;
    }
  }
  return penalty;
}
inline std::vector<Point> route(Point start, Point end, const std::vector<Rect> &obstacles,
                                int bendCost = 18, const std::vector<Segment> &requestedOccupied = {}) {
  // All node obstacles remain active. Bound only cosmetic lane/crossing work.
  const std::vector<Segment> empty;
  const auto &occupied = obstacles.size() <= max_cosmetic_cards ? requestedOccupied : empty;
  std::vector<int> xs{start.x, end.x}, ys{start.y, end.y};
  for (const auto r : obstacles) {
    for (auto p : {start, end})
      if (r.left < p.x && p.x < r.right && r.top < p.y && p.y < r.bottom)
        return {};
    xs.insert(xs.end(), {r.left, r.right});
    ys.insert(ys.end(), {r.top, r.bottom});
  }
  for (const auto &[a, b] : occupied)
    for (const auto p : {a, b}) {
      xs.insert(xs.end(), {p.x - 8, p.x + 8});
      ys.insert(ys.end(), {p.y - 8, p.y + 8});
    }
  for (auto *values : {&xs, &ys}) {
    std::sort(values->begin(), values->end());
    values->erase(std::unique(values->begin(), values->end()), values->end());
  }
  using State = std::tuple<int, int, int>;
  using Entry = std::tuple<int, int, State>;
  auto index = [](const std::vector<int> &values, int value) {
    return static_cast<int>(std::lower_bound(values.begin(), values.end(), value) - values.begin());
  };
  const State initial{index(xs, start.x), index(ys, start.y), 0};
  const int tx = index(xs, end.x), ty = index(ys, end.y);
  std::map<State, int> best{{initial, 0}};
  std::map<State, State> previous;
  std::map<State, bool> clear;
  std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> queue;
  queue.emplace(std::abs(end.x - start.x) + std::abs(end.y - start.y), 0, initial);
  while (!queue.empty()) {
    const auto [estimate, cost, state] = queue.top();
    (void)estimate;
    queue.pop();
    if (best.at(state) != cost)
      continue;
    const auto [x, y, direction] = state;
    if (x == tx && y == ty) {
      std::vector<Point> points;
      auto walk = state;
      for (;;) {
        points.push_back({xs[std::get<0>(walk)], ys[std::get<1>(walk)]});
        auto prior = previous.find(walk);
        if (prior == previous.end())
          break;
        walk = prior->second;
      }
      std::reverse(points.begin(), points.end());
      return simplify(points);
    }
    const std::array<State, 4> next{{{x - 1, y, 1}, {x + 1, y, 1},
                                    {x, y - 1, 2}, {x, y + 1, 2}}};
    for (const auto &[xx, yy, dd] : next) {
      if (xx < 0 || yy < 0 || xx >= static_cast<int>(xs.size()) || yy >= static_cast<int>(ys.size()))
        continue;
      const Point a{xs[x], ys[y]}, b{xs[xx], ys[yy]};
      const State key{std::min(x, xx), std::min(y, yy), dd};
      auto visible = clear.find(key);
      if (visible == clear.end()) {
        const bool free = std::none_of(obstacles.begin(), obstacles.end(),
                                     [&](Rect r) { return intersects(a, b, r); });
        visible = clear.emplace(key, free).first;
      }
      if (!visible->second)
        continue;
      const int nextCost = cost + std::abs(a.x - b.x) + std::abs(a.y - b.y) +
                           (direction && direction != dd ? bendCost : 0) + crossing_cost(a, b, occupied);
      const State nxt{xx, yy, dd};
      const auto old = best.find(nxt);
      if (old == best.end() || nextCost < old->second) {
        best[nxt] = nextCost;
        previous[nxt] = state;
        queue.emplace(nextCost + std::abs(b.x - end.x) + std::abs(b.y - end.y), nextCost, nxt);
      }
    }
  }
  return {}; // Obscured endpoint: never draw a fallback through another card.
}
// Horizontal native sockets: callers identify the cards allowed to contain
// each short endpoint lead. This is separate from the obstacle-free main path.
inline std::vector<Point> route_ports(Point start, Point end, const std::vector<Rect> &obstacles,
                                     int sourceIndex, int targetIndex = -1, const std::vector<Segment> &occupied = {}) {
  const Point escape{start.x + 16, start.y}, entry{end.x - (targetIndex < 0 ? 0 : 16), end.y};
  for (size_t i = 0; i < obstacles.size(); ++i)
    if ((static_cast<int>(i) != sourceIndex && intersects(start, escape, obstacles[i])) ||
        (static_cast<int>(i) != targetIndex && intersects(entry, end, obstacles[i])))
      return {};
  auto points = route(escape, entry, obstacles, 18, occupied);
  if (points.empty())
    return {};
  points.insert(points.begin(), start);
  points.push_back(end);
  return simplify(points);
}
} // namespace dag_routing
#endif
