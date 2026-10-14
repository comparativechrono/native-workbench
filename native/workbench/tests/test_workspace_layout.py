"""Compile the native workspace's actual geometry; Windows focus is a GUI gate.

These checks cover 96-DPI client sizes, including the observed 1024 x 728 work
area and the 960 x 680 outer minimum. They do not establish high-DPI acceptance.
"""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('C++17 compiler unavailable; native layout was not executed')
        cls.temporary = tempfile.TemporaryDirectory(prefix='workbench-layout-')
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.executable = folder / 'layout'
        source = folder / 'layout.cpp'
        source.write_text(r'''
#include "workspace_layout.h"
#include <cstdlib>
#include <iostream>
#include <string>
void rect(workspace_layout::Rect r) {
  std::cout << '[' << r.x << ',' << r.y << ',' << r.width << ',' << r.height << ']';
}
int main(int argc, char **argv) {
  if (argc == 6) {
    rect(workspace_layout::centered_window(
        {std::atoi(argv[2]), std::atoi(argv[3]), std::atoi(argv[4]), std::atoi(argv[5])},
        workspace_layout::preferred_width, workspace_layout::preferred_height));
  } else if (argc == 3) {
    const auto g = workspace_layout::for_client(std::atoi(argv[1]), std::atoi(argv[2]));
    std::cout << "{\"minimum\":[" << workspace_layout::minimum_width << ','
      << workspace_layout::minimum_height << "],\"panes\":[" << g.left << ','
      << g.center << ',' << g.centerWidth << ',' << g.right << "],\"controls\":{";
    bool first = true;
    auto put = [&](const char *name, workspace_layout::Rect value) {
      if (!first) std::cout << ',';
      first = false; std::cout << '"' << name << "\":"; rect(value);
    };
    put("toolsMode", g.toolsMode); put("workflowMode", g.workflowMode);
    put("samples", g.samples); put("queue", g.queue); put("results", g.results);
    put("cancel", g.cancel); put("run", g.run); put("readiness", g.readiness);
    put("zoomOut", g.zoomOut); put("zoomReset", g.zoomReset); put("zoomIn", g.zoomIn);
    put("back", g.back); put("saveWorkflow", g.saveWorkflow);
    put("loadWorkflow", g.loadWorkflow); put("saveSettings", g.saveSettings);
    put("loadSettings", g.loadSettings); put("remove", g.remove);
    put("undo", g.undo); put("reset", g.reset);
    std::cout << "}}";
  } else return 2;
}
''', encoding='utf-8')
        subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'desktop'), str(source), '-o', str(cls.executable)],
                       capture_output=True, text=True, check=True)

    def geometry(self, *args):
        result = subprocess.run([str(self.executable), *map(str, args)],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def assert_inside(self, rect, parent):
        x, y, width, height = rect
        px, py, pwidth, pheight = parent
        self.assertGreater(width, 0, rect)
        self.assertGreater(height, 0, rect)
        self.assertGreaterEqual(x, px, rect)
        self.assertGreaterEqual(y, py, rect)
        self.assertLessEqual(x + width, px + pwidth, rect)
        self.assertLessEqual(y + height, py + pheight, rect)

    def assert_row(self, controls, names, parent):
        previous = None
        for name in names:
            rect = controls[name]
            self.assert_inside(rect, parent)
            if previous:
                self.assertGreaterEqual(rect[0] - (previous[0] + previous[2]), 6,
                                        (names, previous, rect))
            previous = rect

    def test_observed_1024_work_area_contains_initial_window(self):
        work = (0, 0, 1024, 728)
        bounds = self.geometry('window', *work)
        self.assert_inside(bounds, work)
        self.assertEqual(bounds, list(work))
        # The former 1040 outer minimum invalidated an otherwise bounded request.
        minimum = self.geometry(1008, 669)['minimum']
        self.assertLessEqual(minimum[0], bounds[2])
        self.assertLessEqual(minimum[1], bounds[3])

    def test_startup_accounts_for_work_area_origin_and_taskbar(self):
        for work in [(0, 40, 1920, 1040), (56, 0, 1864, 1080),
                     (-1920, -200, 1920, 1040), (300, 200, 1024, 728)]:
            with self.subTest(work=work):
                rect = self.geometry('window', *work)
                self.assert_inside(rect, work)
                self.assertLessEqual(abs((rect[0] - work[0]) -
                                         (work[0] + work[2] - rect[0] - rect[2])), 1)
                self.assertLessEqual(abs((rect[1] - work[1]) -
                                         (work[1] + work[3] - rect[1] - rect[3])), 1)

    def test_workflow_navigation_fits_minimum_and_1024_client_sizes(self):
        # Native framing at96DPI: 16 horizontal and59 vertical nonclient pixels.
        # Exact bounds and font rendering still have their own packaged GUI gate.
        for width, height in [(944, 621), (1008, 669), (1099, 669),
                              (1100, 669), (1224, 821), (1584, 981)]:
            with self.subTest(width=width, height=height):
                g = self.geometry(width, height)
                controls = g['controls']
                left, center, center_width, right = g['panes']
                self.assertGreaterEqual(left, 200)
                self.assertGreaterEqual(center_width, 390)
                self.assertGreaterEqual(right, 320)
                self.assertGreater(center, left)
                self.assertEqual(center + center_width + 1, width - right)
                client = (0, 0, width, height)
                self.assert_row(controls, ['toolsMode', 'workflowMode', 'samples',
                                          'queue', 'cancel', 'results'], client)
                self.assert_row(controls, ['run', 'readiness', 'zoomOut',
                                          'zoomReset', 'zoomIn'], (center, 0, center_width, height))
                self.assert_row(controls, ['remove', 'undo', 'reset'],
                                (width - right, 0, right, height))
                self.assert_row(controls, ['saveWorkflow', 'loadWorkflow'],
                                (center, 0, center_width, height))
                self.assert_row(controls, ['back', 'zoomOut', 'zoomReset', 'zoomIn'],
                                (center, 0, center_width, height))

    def test_standalone_settings_and_actions_fit_minimum_client(self):
        for width in (944, 1008, 1224):
            g = self.geometry(width, 621)
            left, center, center_width, right = g['panes']
            self.assertGreater(left, 0)
            self.assert_row(g['controls'], ['saveSettings', 'loadSettings'],
                            (width - right, 0, right, 621))
            self.assert_row(g['controls'], ['run', 'readiness'],
                            (center, 0, center_width, 621))

    def test_compact_library_retains_editor_width_and_gives_canvas_room(self):
        compact = self.geometry(1008, 669)['panes']
        normal = self.geometry(1224, 821)['panes']
        self.assertLess(compact[0], normal[0])
        self.assertEqual(compact[3], normal[3])
        self.assertGreaterEqual(compact[2], 450)


if __name__ == '__main__':
    unittest.main(verbosity=2)
