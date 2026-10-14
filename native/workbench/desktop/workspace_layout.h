#ifndef NATIVE_WORKBENCH_WORKSPACE_LAYOUT_H
#define NATIVE_WORKBENCH_WORKSPACE_LAYOUT_H

// Geometry shared by the native workspace and portable layout regression tests.
// Client coordinates are logical (96-DPI) pixels; work-area coordinates are
// physical pixels supplied by Windows. This is not a high-DPI acceptance test.
#include <algorithm>

namespace workspace_layout {
constexpr int minimum_width = 960, minimum_height = 680;
constexpr int preferred_width = 1240, preferred_height = 880;

struct Rect {
  int x, y, width, height;
  int right() const { return x + width; }
  int bottom() const { return y + height; }
};

inline Rect centered_window(Rect work, int preferredWidth, int preferredHeight) {
  const int width = std::min(std::max(1, preferredWidth), std::max(1, work.width));
  const int height = std::min(std::max(1, preferredHeight), std::max(1, work.height));
  return {work.x + (work.width - width) / 2,
          work.y + (work.height - height) / 2, width, height};
}

struct Layout {
  int left, right, center, centerWidth, rightX, rightWidth, bodyHeight, footer;
  Rect toolsMode, workflowMode, samples, queue, results, cancel;
  Rect run, readiness, zoomOut, zoomReset, zoomIn, back;
  Rect saveWorkflow, loadWorkflow, saveSettings, loadSettings;
  Rect remove, undo, reset;
};

inline Layout for_client(int width, int height) {
  // Retain three panes on 1024-pixel displays. A slightly narrower library
  // leaves room for workflow navigation without shrinking the option editor.
  const int left = width < 1100 ? 208 : 232, right = 320;
  const int center = left + 1, centerWidth = std::max(1, width - left - right - 2);
  const int footer = height - 64;
  return {left, right, center, centerWidth, width - right + 16, right - 32,
      std::max(160, height - 174), footer,
      {216, 7, 90, 34}, {314, 7, 110, 34}, {432, 7, 106, 34},
      {546, 7, 132, 34}, {width - 112, 7, 96, 34}, {686, 7, 110, 34},
      {center + 12, footer, 118, 32}, {center + 138, footer, 84, 32},
      {center + centerWidth - 150, footer, 34, 32},
      {center + centerWidth - 110, footer, 62, 32},
      {center + centerWidth - 42, footer, 34, 32},
      {center + 12, footer, 180, 32},
      {center + centerWidth - 248, 59, 126, 32},
      {center + centerWidth - 114, 59, 102, 32},
      {width - right + 12, footer, 146, 32},
      {width - right + 166, footer, 142, 32},
      {width - right + 12, footer, 84, 32},
      {width - right + 104, footer, 72, 32},
      {width - right + 184, footer, 120, 32}};
}
} // namespace workspace_layout
#endif
