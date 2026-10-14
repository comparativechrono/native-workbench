"""Execute the native library's wrapping helper; actual fonts are a Windows gate."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LibraryTextLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('C++17 compiler unavailable; wrapping was not executed')
        cls.temporary = tempfile.TemporaryDirectory(prefix='workbench-library-')
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.executable = folder / 'layout'
        source = folder / 'layout.cpp'
        source.write_text(r'''
#include "library_text_layout.h"
#include <cstdlib>
#include <iostream>
#include <sstream>
int measured(const std::wstring &text) {
  int width = 0;
  for (size_t i = 0; i < text.size(); ++i) {
    const auto c = text[i];
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.size() &&
        text[i + 1] >= 0xdc00 && text[i + 1] <= 0xdfff) { width += 12; ++i; }
    else width += c == L'W' ? 12 : c == L'i' ? 3 : 6;
  }
  return width;
}
int main(int argc, char **argv) {
  if (argc == 9 && std::string(argv[1]) == "height") {
    std::cout << library_text_layout::integral_height(
        std::atoi(argv[2]), std::atoi(argv[3]), std::atoi(argv[4]),
        std::atoi(argv[5]), std::atoi(argv[6]), std::atoi(argv[7]), std::atoi(argv[8]));
  } else if (argc == 4) {
    std::istringstream encoded(argv[3]); std::string unit; std::wstring text;
    while (std::getline(encoded, unit, ',')) text += static_cast<wchar_t>(std::stoul(unit, nullptr, 16));
    const auto lines = library_text_layout::wrap(text, std::atoi(argv[2]), measured);
    std::cout << '[';
    for (size_t i = 0; i < lines.size(); ++i) {
      if (i) std::cout << ',';
      std::cout << '[';
      for (size_t j = 0; j < lines[i].size(); ++j) {
        if (j) std::cout << ',';
        std::cout << static_cast<unsigned>(lines[i][j]);
      }
      std::cout << ']';
    }
    std::cout << ']';
  } else return 2;
}
''', encoding='utf-8')
        subprocess.run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'desktop'), str(source), '-o', str(cls.executable)],
                       capture_output=True, text=True, check=True)

    def run_layout(self, *args):
        result = subprocess.run([str(self.executable), *map(str, args)],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def wrap(self, text, width):
        lines = self.run_layout('wrap', width, ','.join(f'{ord(c):x}' for c in text))
        return [''.join(map(chr, line)) for line in lines]

    def test_words_wrap_without_ellipsis_or_lost_suffix(self):
        self.assertEqual(self.wrap('SAMtools Coordinate sort', 80),
                         ['SAMtools', 'Coordinate', 'sort'])

    def test_long_unbroken_description_is_entirely_reachable(self):
        text = 'a' * 2048
        lines = self.wrap(text, 78)
        self.assertEqual(''.join(lines), text)
        self.assertTrue(all(len(line) <= 13 for line in lines))
        self.assertEqual(len(lines), 158)

    def test_surrogate_pair_never_splits_between_rows(self):
        pair = '\ud83e\uddec'
        self.assertEqual(self.wrap('A' + pair + 'B' + pair, 12), ['A', pair, 'B', pair])

    def test_explicit_paragraphs_and_spacing_are_preserved_readably(self):
        self.assertEqual(self.wrap('alpha  beta\r\n\n gamma\t delta', 100),
                         ['alpha beta', '', 'gamma delta'])
        self.assertEqual(self.wrap('alpha\n', 100), ['alpha', ''])

    def test_actual_measured_advances_choose_breaks(self):
        self.assertEqual(self.wrap('WWiiii', 24), ['WW', 'iiii'])
        self.assertEqual(self.wrap('iiii WWW', 30), ['iiii', 'WW', 'W'])

    def test_narrowing_reflows_both_short_and_long_tokens(self):
        text = 'Sequence identification abcdefghijklmnopqrstuvwxyz'
        wide, narrow = self.wrap(text, 150), self.wrap(text, 72)
        self.assertGreater(len(narrow), len(wide))
        self.assertEqual(''.join(narrow).replace(' ', ''), text.replace(' ', ''))
        self.assertTrue(all(sum(3 if c == 'i' else 6 for c in line) <= 72 for line in narrow))

    def test_empty_description_adds_no_line_or_gap(self):
        self.assertEqual(self.wrap('', 100), [])
        self.assertEqual(self.run_layout('height', 1, 17, 0, 17, 6, 3, 30), 1)

    def test_integral_rows_cover_all_text_padding_and_font_scales(self):
        for title_lines, description_lines in [(2, 5), (12, 158), (3, 0)]:
            for line_height, padding, gap, base in [(17, 6, 3, 30), (26, 9, 5, 45), (34, 12, 6, 60)]:
                with self.subTest(title_lines=title_lines, description_lines=description_lines,
                                  line_height=line_height):
                    integral = self.run_layout('height', title_lines, line_height,
                                               description_lines, line_height, padding, gap, base)
                    content = (title_lines + description_lines) * line_height + 2 * padding
                    content += gap if description_lines else 0
                    self.assertGreaterEqual(integral * base, content)
                    self.assertLess((integral - 1) * base, content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
