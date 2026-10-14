#ifndef NATIVE_WORKBENCH_LIBRARY_TEXT_LAYOUT_H
#define NATIVE_WORKBENCH_LIBRARY_TEXT_LAYOUT_H

#include <algorithm>
#include <string>
#include <vector>

namespace library_text_layout {

// The caller measures with the same font/DC used to paint. Unlike DrawText's
// DT_CALCRECT word wrapping, an oversized word never widens the text column.
// Preserve UTF-16 surrogate pairs when a long token must continue on a new line.
template <typename Measure>
std::vector<std::wstring> wrap(const std::wstring &text, int width, Measure measure) {
  std::vector<std::wstring> lines;
  std::wstring line, word;
  width = std::max(1, width);
  const auto flush_word = [&]() {
    if (word.empty()) return;
    const auto candidate = line.empty() ? word : line + L" " + word;
    if (measure(candidate) <= width) {
      line = candidate;
    } else {
      if (!line.empty()) { lines.push_back(line); line.clear(); }
      for (size_t i = 0; i < word.size();) {
        size_t count = 1;
        if (word[i] >= 0xd800 && word[i] <= 0xdbff && i + 1 < word.size() &&
            word[i + 1] >= 0xdc00 && word[i + 1] <= 0xdfff) count = 2;
        const auto unit = word.substr(i, count);
        if (!line.empty() && measure(line + unit) > width) {
          lines.push_back(line); line.clear();
        }
        line += unit;
        i += count;
      }
    }
    word.clear();
  };
  for (size_t i = 0; i < text.size(); ++i) {
    const wchar_t c = text[i];
    if (c == L'\r' || c == L'\n') {
      flush_word(); lines.push_back(line); line.clear();
      if (c == L'\r' && i + 1 < text.size() && text[i + 1] == L'\n') ++i;
    } else if (c == L' ' || c == L'\t' || c == L'\v' || c == L'\f') {
      flush_word();
    } else word += c;
  }
  flush_word();
  if (!line.empty() || (!text.empty() && (text.back() == L'\n' || text.back() == L'\r')))
    lines.push_back(line);
  return lines;
}

inline int integral_height(int titleLines, int titleLineHeight,
                           int descriptionLines, int descriptionLineHeight,
                           int padding, int gap, int baseHeight) {
  const int content = 2 * padding + titleLines * titleLineHeight +
      descriptionLines * descriptionLineHeight + (descriptionLines ? gap : 0);
  return std::max(1, (content + baseHeight - 1) / baseHeight);
}

} // namespace library_text_layout
#endif
