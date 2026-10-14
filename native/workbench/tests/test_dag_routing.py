"""Actual native/SVG route geometry; no Windows GUI pass is implied.

The C++ test compiles the same header included by the desktop application and
compares it to the Python implementation over fixed and generated obstacles.
"""
from __future__ import annotations

from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workspace'))
from dag_routing import intersects, route

FIXTURES = [
    # A skip-rank dependency previously went straight through the middle card.
    ((260, 80), (630, 80), [(0, 0, 244, 170), (320, 0, 564, 170), (646, 0, 890, 170)]),
    # A manually moved consumer is left of its producer; exit right, enter left.
    ((620, 100), (10, 100), [(360, 20, 604, 180), (26, 20, 270, 180)]),
    # Fan-out/fan-in routes share ports but avoid every intervening branch card.
    ((260, 80), (630, 340), [(0, 0, 244, 170), (320, 0, 564, 170), (320, 220, 564, 390), (646, 250, 890, 420)]),
    ((260, 300), (630, 80), [(0, 220, 244, 390), (320, 0, 564, 170), (320, 220, 564, 390), (646, 0, 890, 170)]),
    # Vertical saved-result routing bypasses a card spanning the middle rank.
    ((160, 110), (160, 430), [(30, 10, 290, 100), (30, 180, 290, 270), (30, 440, 290, 530)]),
    # The only straight corridor runs precisely along padded obstacle borders.
    ((10, 110), (500, 110), [(100, 0, 210, 110), (210, 110, 320, 220)]),
    # An obscured port must not produce an unsafe straight-line fallback.
    ((150, 60), (500, 60), [(100, 20, 260, 160)]),
    ((10, 10), (10, 10), []),
]


def assert_clear(test, points, boxes):
    for a, b in zip(points, points[1:]):
        test.assertTrue(a[0] == b[0] or a[1] == b[1], (a, b))
        for box in boxes:
            test.assertFalse(intersects(a, b, box), (a, b, box, points))


class RouteGeometryTests(unittest.TestCase):
    def test_skip_rank_detours_instead_of_crossing_card(self):
        start, end, boxes = FIXTURES[0]
        self.assertTrue(intersects(start, end, boxes[1]))  # reproduces old straight centreline
        points = route(start, end, boxes)
        self.assertGreater(len(points), 2)
        self.assertEqual((points[0], points[-1]), (start, end))
        assert_clear(self, points, boxes)

    def test_backwards_manual_positions(self):
        start, end, boxes = FIXTURES[1]
        points = route(start, end, boxes)
        self.assertEqual((points[0], points[-1]), (start, end))
        self.assertTrue(any(p[1] <= 20 or p[1] >= 180 for p in points))
        assert_clear(self, points, boxes)

    def test_fan_out_fan_in_and_vertical_saved_graph(self):
        for start, end, boxes in FIXTURES[2:5]:
            with self.subTest(start=start, end=end):
                points = route(start, end, boxes)
                self.assertEqual((points[0], points[-1]), (start, end))
                assert_clear(self, points, boxes)

    def test_tight_corridor_and_obscured_endpoint(self):
        start, end, boxes = FIXTURES[5]
        points = route(start, end, boxes)
        self.assertEqual(points, [start, end])
        assert_clear(self, points, boxes)
        self.assertEqual(route(*FIXTURES[6]), [])
        self.assertEqual(route(*FIXTURES[7]), [(10, 10)])

    def test_independent_edges_use_distinct_corridors(self):
        occupied = [((250, 20), (250, 200)), ((100, 160), (350, 160))]
        points = route((250, 0), (450, 220), [], occupied=occupied)
        self.assertEqual((points[0], points[-1]), ((250, 0), (450, 220)))
        for a, b in zip(points, points[1:]):
            for c, d in occupied:
                if a[0] == b[0] == c[0] == d[0]:
                    self.assertLessEqual(min(max(a[1], b[1]), max(c[1], d[1])),
                                         max(min(a[1], b[1]), min(c[1], d[1])))
                if a[1] == b[1] == c[1] == d[1]:
                    self.assertLessEqual(min(max(a[0], b[0]), max(c[0], d[0])),
                                         max(min(a[0], b[0]), min(c[0], d[0])))

    def test_large_graph_bounds_cosmetics_but_keeps_card_obstacles(self):
        start, end, boxes = FIXTURES[0]
        boxes = boxes + [(1000 + index * 50, 500, 1020 + index * 50, 530) for index in range(62)]
        self.assertEqual(len(boxes), 65)
        occupied = [((260, 80), (630, 80)), ((260, 0), (630, 0))]
        points = route(start, end, boxes, occupied=occupied)
        self.assertEqual(points, route(start, end, boxes))
        self.assertGreater(len(points), 2)
        assert_clear(self, points, boxes)

    def test_translation_preserves_routes(self):
        for start, end, boxes in FIXTURES[:6]:
            points = route(start, end, boxes)
            dx, dy = -701, 529
            translated = route((start[0] + dx, start[1] + dy), (end[0] + dx, end[1] + dy),
                               [(l + dx, t + dy, r + dx, b + dy) for l, t, r, b in boxes])
            self.assertEqual(translated, [(x + dx, y + dy) for x, y in points])

    def test_native_header_matches_python_and_avoids_obstacles(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('A native C++17 compiler is unavailable; Windows GUI remains a separate gate')
        randomizer = random.Random(783)
        fixtures = list(FIXTURES)
        for _ in range(24):
            boxes = [(col * 290 + 50, row * 150 + 30, col * 290 + 270, row * 150 + 140)
                     for col in range(5) for row in range(4) if randomizer.random() < .6]
            fixtures.append(((10, randomizer.randrange(0, 600)), (1550, randomizer.randrange(0, 600)), boxes))
        fixtures.append((FIXTURES[0][0], FIXTURES[0][1], FIXTURES[0][2] +
                         [(1000 + i * 50, 500, 1020 + i * 50, 530) for i in range(62)]))
        code = r'''
#include "dag_routing.h"
#include <iostream>
int main() {
  int mode, sx, sy, tx, ty, count, source, target;
  while (std::cin >> mode >> sx >> sy >> tx >> ty >> count >> source >> target) {
    std::vector<dag_routing::Rect> boxes;
    for (int i = 0; i < count; ++i) {
      dag_routing::Rect r{};
      std::cin >> r.left >> r.top >> r.right >> r.bottom;
      boxes.push_back(r);
    }
    const std::vector<dag_routing::Segment> occupied{{{15, 15}, {480, 15}}, {{480, 15}, {480, 280}}};
    const auto points = mode ? dag_routing::route_ports({sx, sy}, {tx, ty}, boxes, source, target, occupied)
                             : dag_routing::route({sx, sy}, {tx, ty}, boxes, 18, occupied);
    std::cout << points.size();
    for (auto p : points) std::cout << ' ' << p.x << ' ' << p.y;
    std::cout << '\n';
  }
}
'''
        port_fixtures = [
            ((274, 105), (652, 105), [(20, 20, 286, 186), (330, 20, 596, 186), (640, 20, 906, 186)], 0, 2),
            ((624, 105), (32, 105), [(370, 20, 636, 186), (20, 20, 286, 186)], 0, 1),
            # Another card covers the source's short socket lead.
            ((274, 105), (652, 105), [(20, 20, 286, 186), (278, 80, 544, 246), (640, 20, 906, 186)], 0, 2),
        ]
        with tempfile.TemporaryDirectory(prefix='workbench-dag-') as directory:
            folder = Path(directory)
            (folder / 'routing.cpp').write_text(code)
            subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'desktop'), str(folder / 'routing.cpp'), '-o', str(folder / 'routing')],
                           check=True, capture_output=True, text=True)
            data = '\n'.join(' '.join(map(str, [0, *a, *b, len(boxes), -1, -1, *(v for box in boxes for v in box)]))
                             for a, b, boxes in fixtures)
            data += '\n' + '\n'.join(' '.join(map(str, [1, *a, *b, len(boxes), source, target, *(v for box in boxes for v in box)]))
                                    for a, b, boxes, source, target in port_fixtures)
            result = subprocess.run([str(folder / 'routing')], input=data, capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), len(fixtures) + len(port_fixtures))
        for fixture, line in zip(fixtures, result.stdout.splitlines()):
            numbers = list(map(int, line.split()))
            native = list(zip(numbers[1::2], numbers[2::2]))
            self.assertEqual(len(native), numbers[0])
            self.assertEqual(native, route(*fixture, occupied=[((15, 15), (480, 15)), ((480, 15), (480, 280))]), fixture)
            assert_clear(self, native, fixture[2])
        for fixture, line in zip(port_fixtures, result.stdout.splitlines()[len(fixtures):]):
            start, end, boxes, source, target = fixture
            numbers = list(map(int, line.split()))
            points = list(zip(numbers[1::2], numbers[2::2]))
            if fixture is port_fixtures[-1]:
                self.assertEqual(points, [])
                continue
            self.assertEqual((points[0], points[-1]), (start, end))
            self.assertGreater(points[1][0], start[0])
            self.assertLess(points[-2][0], end[0])
            assert_clear(self, points, [(l + 12, t + 12, r - 12, b - 12) for l, t, r, b in boxes])
            for identity, box in enumerate(boxes):
                for index, (a, b) in enumerate(zip(points, points[1:])):
                    if identity == source and index == 0:
                        continue
                    if identity == target and index == len(points) - 2:
                        continue
                    self.assertFalse(intersects(a, b, box), (fixture, points, box))


class SavedDiagramTests(unittest.TestCase):
    @staticmethod
    def diagram(graph):
        from engine import Engine
        subject = Engine.__new__(Engine)
        subject._tool = lambda node: {'name': node.get('label', node['id'])}
        return subject.diagram({'graph': graph})

    def verify(self, graph):
        svg = self.diagram(graph)
        document = ET.fromstring(svg)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        boxes = {}
        for group in document.findall('s:g', ns):
            rect = group.find('s:rect', ns)
            x, y = float(rect.attrib['x']), float(rect.attrib['y'])
            boxes[group.attrib['data-node']] = (x - 10, y - 10, x + 250, y + 86)
        paths = [path for path in document.findall('s:path', ns) if path.attrib.get('class') == 'dependency']
        expected = sum(len(refs) for n in graph['nodes'] for refs in n.get('inputs', {}).values())
        self.assertEqual(len(paths), expected)
        for edge in paths:
            points = [tuple(map(float, xy.split(','))) for xy in re.findall(r'[ML]([\d.-]+,[\d.-]+)', edge.attrib['d'])]
            self.assertGreaterEqual(len(points), 2)
            self.assertEqual(edge.attrib['marker-end'], 'url(#arrow)')
            for identity, box in boxes.items():
                # First/last segments escape their own padding at named ports.
                for index, (a, b) in enumerate(zip(points, points[1:])):
                    if identity == edge.attrib['data-source'] and index == 0:
                        continue
                    if identity == edge.attrib['data-target'] and index == len(points) - 2:
                        continue
                    self.assertFalse(intersects(a, b, box), (identity, edge.attrib, a, b))
        self.assertEqual(svg, self.diagram(graph))
        return svg

    def test_saved_skip_rank_fan_out_merge_and_distinct_ports(self):
        graph = {'sources': [{'id': 'input-1', 'label': 'Reference & reads'}], 'nodes': [
            {'id': 'step-1', 'label': 'Align', 'inputs': {'reference': ['input-1']}},
            {'id': 'step-2', 'label': 'Sort branch A', 'inputs': {'sam': ['step-1::sam']}},
            {'id': 'step-3', 'label': 'Sort branch B', 'inputs': {'sam': ['step-1::sam']}},
            {'id': 'step-4', 'label': 'Merge and compare', 'inputs': {'bam': ['step-2::bam', 'step-3::bam'], 'reference': ['input-1']}},
        ]}
        svg = self.verify(graph)
        self.assertIn('Reference &amp; reads', svg)
        self.assertNotIn(' C', svg)

    def test_empty_and_single_tool_graphs(self):
        self.verify({'sources': [], 'nodes': []})
        self.verify({'sources': [], 'nodes': [{'id': 'step-1', 'inputs': {}}]})

    def test_saved_graph_large_branching_fixture(self):
        graph = {'sources': [{'id': 'input-1'}], 'nodes': []}
        for index in range(30):
            graph['nodes'].append({'id': f'step-{index + 1}', 'inputs': {
                'file': ['input-1'] if index == 0 else [f'step-{index}::file'],
                'reference': ['input-1'],
            }})
        self.verify(graph)


if __name__ == '__main__':
    unittest.main(verbosity=2)
