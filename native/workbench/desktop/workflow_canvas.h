// Included inside Workspace. Native workflow presentation and pointer gestures
// live here; the desktop model remains the authority for every connection.
struct CanvasPort {
  POINT point{}; // World coordinates, before scrolling, zoom and DPI scaling.
  std::string node, port, ref, label, type;
  bool output = false;
};
struct CanvasCard {
  RECT box{};
  std::string id, title, subtitle;
  bool source = false, unavailable = false;
  std::vector<CanvasPort> inputs, outputs;
};
std::map<std::string, POINT> canvasPositions;
std::vector<CanvasCard> canvasCards;
std::vector<CanvasPort> canvasPorts;
struct CanvasConnection {
  CanvasPort source, target;
  std::vector<dag_routing::Point> points;
};
std::vector<CanvasConnection> canvasConnections;
std::string canvasRouteKey;
bool canvasBlockedRoutes = false;
std::string canvasDragNode, canvasDragRef;
std::string canvasHoverNode;
Json canvasTargets = Json::object();
POINT canvasDragStart{}, canvasNodeStart{}, canvasPointer{};
POINT canvasPanStart{}, canvasPanScroll{}, canvasGesturePoint{};
POINT canvasWorkspaceScroll{LONG_MIN, LONG_MIN};
bool canvasNodeMoved = false, canvasPanning = false, canvasHoverDelete = false;
int canvasZoom = 100, canvasWorkspaceZoom = 100, canvasGestureZoom = 100;
double canvasPreciseZoom = 100.0;
int canvasWheelVertical = 0, canvasWheelHorizontal = 0;
ULONGLONG canvasGestureDistance = 0;

int canvas_px(int value) const { return MulDiv(value, dpi * canvasZoom, 9600); }
int canvas_units(int value) const { return MulDiv(value, 9600, dpi * canvasZoom); }
int canvas_zoom_percent() const { return canvasZoom; }
void canvas_zoom_label() {
  if (zoomReset)
    SetWindowTextW(zoomReset, (std::to_wstring(canvasZoom) + L"%").c_str());
}
SIZE canvas_viewport() const {
  RECT r{};
  GetClientRect(dag, &r);
  return {std::max(1, canvas_units(r.right)), std::max(1, canvas_units(r.bottom))};
}

POINT canvas_world(POINT p) const {
  return {canvas_units(p.x) + dagX, canvas_units(p.y) + dagY};
}
bool canvas_editable() const {
  return ready && !setupBusy && !setupActionPending && !packBusy && !packActionPending && !refBusy &&
         !refActionPending && !showingHistory && !closing && workflowMode;
}
bool canvas_positioned(const std::string &id) const {
  return !showingHistory && canvasPositions.count(id);
}
void canvas_configure_gestures() {
  GESTURECONFIG config[] = {{GID_ZOOM, GC_ZOOM, 0},
                           {GID_PAN, GC_PAN | GC_PAN_WITH_SINGLE_FINGER_HORIZONTALLY |
                                       GC_PAN_WITH_SINGLE_FINGER_VERTICALLY, GC_PAN_WITH_INERTIA}};
  SetGestureConfig(dag, 0, 2, config, sizeof(GESTURECONFIG));
}
void canvas_navigation_bounds() {
  const auto view = canvas_viewport();
  dagWidth = view.cx;
  dagHeight = view.cy;
  for (const auto &item : canvasCards) {
    dagWidth = std::max(dagWidth, static_cast<int>(item.box.right) + static_cast<int>(view.cx));
    dagHeight = std::max(dagHeight, static_cast<int>(item.box.bottom) + static_cast<int>(view.cy));
  }
  // A viewport of margin permits grabbing an initially top-left graph in either
  // direction without forcing users to find the scrollbars first.
  dagX = std::clamp(dagX, -static_cast<int>(view.cx), std::max(0, dagWidth - static_cast<int>(view.cx)));
  dagY = std::clamp(dagY, -static_cast<int>(view.cy), std::max(0, dagHeight - static_cast<int>(view.cy)));
  for (int bar : {SB_HORZ, SB_VERT}) {
    const int page = static_cast<int>(bar == SB_HORZ ? view.cx : view.cy);
    SCROLLINFO si{sizeof(si), SIF_RANGE | SIF_PAGE | SIF_POS};
    si.nMin = -page;
    si.nMax = (bar == SB_HORZ ? dagWidth : dagHeight) - 1;
    si.nPage = page;
    si.nPos = bar == SB_HORZ ? dagX : dagY;
    SetScrollInfo(dag, bar, &si, TRUE);
  }
}
void canvas_scroll(int bar, int action, int delta = 0) {
  const auto view = canvas_viewport();
  const int page = static_cast<int>(bar == SB_HORZ ? view.cx : view.cy);
  const int line = std::max(1, MulDiv(32, 100, canvasZoom));
  int &value = bar == SB_HORZ ? dagX : dagY;
  SCROLLINFO si{sizeof(si), SIF_TRACKPOS};
  GetScrollInfo(dag, bar, &si);
  if (delta)
    value += MulDiv(delta, 100, canvasZoom);
  else
    switch (action) {
    case SB_LINEUP: value -= line; break;
    case SB_LINEDOWN: value += line; break;
    case SB_PAGEUP: value -= page; break;
    case SB_PAGEDOWN: value += page; break;
    case SB_THUMBTRACK:
    case SB_THUMBPOSITION: value = si.nTrackPos; break;
    case SB_TOP: value = -page; break;
    case SB_BOTTOM: value = bar == SB_HORZ ? dagWidth : dagHeight; break;
    default: break;
    }
  canvas_navigation_bounds();
  InvalidateRect(dag, nullptr, FALSE);
}
void canvas_zoom_at(double requested, POINT screen) {
  // Precision touchpads can send wheel deltas much smaller than WHEEL_DELTA.
  // Retain their fractional progress even when no whole percent is drawn yet.
  // Explicit reset/button/gesture requests replace this accumulator as well.
  canvasPreciseZoom = std::clamp(requested, 25.0, 200.0);
  const int percent = static_cast<int>(canvasPreciseZoom + .5);
  if (percent == canvasZoom)
    return;
  // A pointer anchor makes pinch and wheel zoom keep the same part of the
  // graph beneath the user's hand; toolbar zoom anchors the viewport centre.
  const auto anchor = canvas_world(screen);
  canvas_cancel_drag();
  canvasZoom = percent;
  canvas_zoom_label();
  dagX = anchor.x - canvas_units(screen.x);
  dagY = anchor.y - canvas_units(screen.y);
  canvas_navigation_bounds();
  InvalidateRect(dag, nullptr, FALSE);
  status_text(L"Workflow zoom: " + std::to_wstring(canvasZoom) + L"%. Drag empty canvas to pan; Ctrl+wheel or pinch to zoom.");
}
void canvas_zoom_by(double factor) {
  RECT r{};
  GetClientRect(dag, &r);
  canvas_zoom_at(static_cast<int>(canvasZoom * factor + .5), {r.right / 2, r.bottom / 2});
}
void canvas_zoom_reset() {
  RECT r{};
  GetClientRect(dag, &r);
  canvas_zoom_at(100, {r.right / 2, r.bottom / 2});
}
void canvas_mouse_wheel(WPARAM w, LPARAM l, bool horizontal = false) {
  const int delta = GET_WHEEL_DELTA_WPARAM(w);
  if (!horizontal && (GET_KEYSTATE_WPARAM(w) & MK_CONTROL)) {
    POINT pointer{GET_X_LPARAM(l), GET_Y_LPARAM(l)};
    ScreenToClient(dag, &pointer);
    const double factor = 1.0 + std::min(480, std::abs(delta)) / 120.0 * .15;
    canvas_zoom_at(canvasPreciseZoom * (delta < 0 ? 1.0 / factor : factor), pointer);
  } else {
    const bool across = horizontal || (GET_KEYSTATE_WPARAM(w) & MK_SHIFT);
    int &remainder = across ? canvasWheelHorizontal : canvasWheelVertical;
    remainder += (horizontal ? delta : -delta) * 48;
    const int movement = remainder / WHEEL_DELTA;
    remainder %= WHEEL_DELTA;
    if (movement)
      canvas_scroll(across ? SB_HORZ : SB_VERT, 0, movement);
  }
}
bool canvas_gesture(LPARAM l) {
  GESTUREINFO gesture{sizeof(GESTUREINFO)};
  if (!GetGestureInfo(reinterpret_cast<HGESTUREINFO>(l), &gesture))
    return false;
  if (gesture.dwID != GID_ZOOM && gesture.dwID != GID_PAN)
    return false; // DefWindowProc owns unhandled gesture handles.
  POINT point{gesture.ptsLocation.x, gesture.ptsLocation.y};
  ScreenToClient(dag, &point);
  if (gesture.dwFlags & GF_BEGIN)
    canvas_cancel_drag();
  if (gesture.dwID == GID_ZOOM) {
    if ((gesture.dwFlags & GF_BEGIN) || !canvasGestureDistance) {
      canvasGestureDistance = gesture.ullArguments;
      canvasGestureZoom = canvasZoom;
    } else if (canvasGestureDistance) {
      const auto percent = static_cast<int>(std::clamp(
          canvasGestureZoom * static_cast<double>(gesture.ullArguments) / canvasGestureDistance, 25.0, 200.0) + .5);
      canvas_zoom_at(percent, point);
    }
    if (gesture.dwFlags & GF_END)
      canvasGestureDistance = 0;
  } else {
    if (!(gesture.dwFlags & GF_BEGIN)) {
      dagX -= canvas_units(point.x - canvasGesturePoint.x);
      dagY -= canvas_units(point.y - canvasGesturePoint.y);
      canvas_navigation_bounds();
      InvalidateRect(dag, nullptr, FALSE);
    }
    canvasGesturePoint = point;
  }
  CloseGestureInfoHandle(reinterpret_cast<HGESTUREINFO>(l));
  return true;
}
RECT canvas_delete_rect(const CanvasCard &card) const {
  return {card.box.right - 30, card.box.top + 6, card.box.right - 5, card.box.top + 33};
}
bool canvas_delete(const CanvasCard &card) {
  if (!canvas_editable() || activeRequest || !outgoing.empty())
    return false;
  const auto id = card.id;
  const bool source = card.source;
  canvas_cancel_drag();
  canvasHoverNode.clear();
  canvasHoverDelete = false;
  commit_all();
  model(source ? "remove_source" : "remove_step",
        object({{source ? "sourceId" : "nodeId", id}}));
  return true;
}
bool canvas_key_down(WPARAM key) {
  if (key == VK_ADD || key == VK_OEM_PLUS) { canvas_zoom_by(1.2); return true; }
  if (key == VK_SUBTRACT || key == VK_OEM_MINUS) { canvas_zoom_by(1.0 / 1.2); return true; }
  if (key == '0' || key == VK_NUMPAD0) { canvas_zoom_reset(); return true; }
  if (key == VK_DELETE)
    for (const auto &card : canvasCards)
      if (card.id == selected)
        return canvas_delete(card);
  return false;
}
void canvas_mouse_leave() {
  if (!canvasHoverNode.empty()) {
    canvasHoverNode.clear();
    canvasHoverDelete = false;
    InvalidateRect(dag, nullptr, FALSE);
  }
}
const Json &canvas_input(const std::string &node,
                         const std::string &port) const {
  static const Json missing;
  if (!state.get("nodes").is_array())
    return missing;
  for (const auto &item : state.get("nodes").array_items())
    if (getstr(item, "id") == node && item.get("inputs").is_array())
      for (const auto &input : item.get("inputs").array_items())
        if (getstr(input, "id") == port)
          return input;
  return missing;
}
bool canvas_connected(const Json &input, const std::string &ref) const {
  if (!input.get("refs").is_array())
    return false;
  for (const auto &item : input.get("refs").array_items())
    if (getstr(item, "ref") == ref)
      return true;
  return false;
}
bool canvas_accepts(const CanvasPort &target,
                    const std::string &ref) const {
  if (target.output || ref.empty())
    return false;
  // The bounded host query applies the model's semantic state, cycle and
  // capacity checks. Never substitute extension or type-only inference.
  if (getstr(canvasTargets, "ref") != ref || !canvasTargets.get("targets").is_array())
    return false;
  for (const auto &choice : canvasTargets.get("targets").array_items())
    if (getstr(choice, "nodeId") == target.node &&
        getstr(choice, "portId") == target.port)
      return true;
  return false;
}
void canvas_set_targets(const Json &result) {
  if (getstr(result, "ref") != canvasDragRef || canvasDragRef.empty())
    return;
  canvasTargets = result;
  InvalidateRect(dag, nullptr, FALSE);
}
const CanvasPort *canvas_port_at(POINT screen) const {
  const auto p = canvas_world(screen);
  const int radius = std::max(6, MulDiv(12, 100, canvasZoom));
  for (auto it = canvasPorts.rbegin(); it != canvasPorts.rend(); ++it) {
    const long long dx = static_cast<long long>(p.x) - it->point.x,
                    dy = static_cast<long long>(p.y) - it->point.y;
    if (dx * dx + dy * dy <= static_cast<long long>(radius) * radius)
      return &*it;
  }
  return nullptr;
}
void canvas_cancel_drag() {
  if (canvasDragNode.empty() && canvasDragRef.empty() && !canvasPanning)
    return;
  // Escape and capture loss cancel the visual move as well as a pending link.
  if (!canvasDragNode.empty() && canvasNodeMoved)
    canvasPositions[canvasDragNode] = canvasNodeStart;
  if (canvasPanning) {
    dagX = canvasPanScroll.x;
    dagY = canvasPanScroll.y;
  }
  canvasDragNode.clear();
  canvasDragRef.clear();
  canvasTargets = Json::object();
  canvasNodeMoved = false;
  canvasPanning = false;
  if (GetCapture() == dag)
    ReleaseCapture();
  InvalidateRect(dag, nullptr, FALSE);
}
void canvas_reset_positions() {
  canvas_cancel_drag();
  canvasPositions.clear();
  canvasCards.clear();
  canvasPorts.clear();
  canvasHoverNode.clear();
  canvasHoverDelete = false;
  canvasZoom = 100;
  canvasPreciseZoom = canvasZoom;
  canvas_zoom_label();
  dagX = dagY = 0;
  canvasWorkspaceScroll = {LONG_MIN, LONG_MIN};
  InvalidateRect(dag, nullptr, FALSE);
}
void canvas_enter_history() {
  canvas_cancel_drag();
  if (canvasWorkspaceScroll.x == LONG_MIN) {
    canvasWorkspaceScroll = {dagX, dagY};
    canvasWorkspaceZoom = canvasZoom;
  }
  dagX = dagY = 0;
  canvasZoom = 100;
  canvasPreciseZoom = canvasZoom;
  canvas_zoom_label();
}
void canvas_leave_history() {
  if (canvasWorkspaceScroll.x != LONG_MIN) {
    dagX = static_cast<int>(canvasWorkspaceScroll.x);
    dagY = static_cast<int>(canvasWorkspaceScroll.y);
    canvasZoom = canvasWorkspaceZoom;
  }
  canvasPreciseZoom = canvasZoom;
  canvas_zoom_label();
  canvasWorkspaceScroll = {LONG_MIN, LONG_MIN};
  InvalidateRect(dag, nullptr, FALSE);
}
void canvas_place_new_node(const std::string &id, POINT screen) {
  auto p = canvas_world(screen);
  // Match the pointer to the card header, leaving sockets inside the canvas.
  p.x = std::max<LONG>(24, p.x - 120);
  p.y = std::max<LONG>(24, p.y - 20);
  canvasPositions[id] = p;
  InvalidateRect(dag, nullptr, FALSE);
}
bool canvas_mouse_down(POINT screen) {
  SetFocus(dag);
  canvas_cancel_drag();
  canvasPointer = canvas_world(screen);
  const auto p = canvasPointer;
  // Navigation stays available while a run/host request is active, but card
  // selection, connection and deletion continue to use the editing guard.
  const bool editable = canvas_editable() && !activeRequest && outgoing.empty();
  if (editable)
    for (auto it = canvasCards.rbegin(); it != canvasCards.rend(); ++it) {
      const RECT close = canvas_delete_rect(*it);
      if (PtInRect(&close, p))
        return canvas_delete(*it);
    }
  if (const auto *hit = canvas_port_at(screen)) {
    if (!editable)
      return false;
    const auto port = *hit;
    if (port.output) {
      commit_all();
      canvasDragRef = port.ref;
      canvasTargets = Json::object();
      send("workspace/connection-targets", object({{"ref", canvasDragRef}}));
      SetCapture(dag);
      status_text(L"Drag to a highlighted input socket. Compatible inputs are green.");
      InvalidateRect(dag, nullptr, FALSE);
    } else {
      generalVisible = false;
      layout();
      commit_all();
      model("select", object({{"nodeId", port.node}}));
      status_text(L"Drag an output socket onto this input, or choose its source in Tool options.");
    }
    return true;
  }
  for (auto it = canvasCards.rbegin(); it != canvasCards.rend(); ++it)
    if (PtInRect(&it->box, p)) {
      if (!editable)
        return false;
      const auto id = it->id;
      canvasDragNode = id;
      canvasDragStart = p;
      canvasNodeStart = {it->box.left, it->box.top};
      canvasNodeMoved = false;
      SetCapture(dag);
      generalVisible = false;
      layout();
      commit_all();
      if (id != selected)
        model("select", object({{"nodeId", id}}));
      return true;
    }
  canvasPanning = true;
  canvasPanStart = screen;
  canvasPanScroll = {dagX, dagY};
  SetCapture(dag);
  SetCursor(LoadCursorW(nullptr, IDC_SIZEALL));
  return true;
}
bool canvas_mouse_move(POINT screen) {
  canvasPointer = canvas_world(screen);
  if (canvasPanning) {
    dagX = canvasPanScroll.x - canvas_units(screen.x - canvasPanStart.x);
    dagY = canvasPanScroll.y - canvas_units(screen.y - canvasPanStart.y);
    canvas_navigation_bounds();
    InvalidateRect(dag, nullptr, FALSE);
    SetCursor(LoadCursorW(nullptr, IDC_SIZEALL));
    return true;
  }
  if (!canvasDragNode.empty()) {
    const LONG dx = canvasPointer.x - canvasDragStart.x,
               dy = canvasPointer.y - canvasDragStart.y;
    if (dx > 3 || dx < -3 || dy > 3 || dy < -3)
      canvasNodeMoved = true;
    if (canvasNodeMoved) {
      canvasPositions[canvasDragNode] = {
          std::max<LONG>(24, canvasNodeStart.x + dx),
          std::max<LONG>(24, canvasNodeStart.y + dy)};
      InvalidateRect(dag, nullptr, FALSE);
    }
    SetCursor(LoadCursorW(nullptr, IDC_SIZEALL));
    return true;
  }
  if (!canvasDragRef.empty()) {
    const auto *target = canvas_port_at(screen);
    SetCursor(LoadCursorW(nullptr, target && !canvas_accepts(*target, canvasDragRef)
                                      ? IDC_NO : IDC_CROSS));
    InvalidateRect(dag, nullptr, FALSE);
    return true;
  }
  std::string hover;
  bool overDelete = false;
  if (canvas_editable())
    for (auto it = canvasCards.rbegin(); it != canvasCards.rend(); ++it)
      if (PtInRect(&it->box, canvasPointer) && canvasPointer.y < it->box.top + 44) {
        hover = it->id;
        const RECT close = canvas_delete_rect(*it);
        overDelete = PtInRect(&close, canvasPointer);
        break;
      }
  if (hover != canvasHoverNode || overDelete != canvasHoverDelete) {
    canvasHoverNode = hover;
    canvasHoverDelete = overDelete;
    InvalidateRect(dag, nullptr, FALSE);
  }
  TRACKMOUSEEVENT tracking{sizeof(tracking), TME_LEAVE, dag, 0};
  TrackMouseEvent(&tracking);
  if (overDelete) {
    SetCursor(LoadCursorW(nullptr, IDC_HAND));
    return true;
  }
  if (const auto *port = canvas_port_at(screen)) {
    SetCursor(LoadCursorW(nullptr, port->output ? IDC_CROSS : IDC_HAND));
    return true;
  }
  return false;
}
bool canvas_mouse_up(POINT screen) {
  if (canvasPanning) {
    canvasPanning = false;
    if (GetCapture() == dag)
      ReleaseCapture();
    InvalidateRect(dag, nullptr, FALSE);
    return true;
  }
  if (canvasDragNode.empty() && canvasDragRef.empty())
    return false;
  const auto ref = canvasDragRef;
  const auto *at = canvas_port_at(screen);
  const auto target = at ? *at : CanvasPort{};
  const bool hasTarget = at && !at->output;
  const bool previewReady = getstr(canvasTargets, "ref") == ref &&
                            canvasTargets.get("targets").is_array();
  const bool accepted = hasTarget && canvas_accepts(target, ref);
  // Clear before releasing capture: WM_CAPTURECHANGED is synchronous.
  canvasDragNode.clear();
  canvasDragRef.clear();
  canvasTargets = Json::object();
  canvasNodeMoved = false;
  if (GetCapture() == dag)
    ReleaseCapture();
  InvalidateRect(dag, nullptr, FALSE);
  if (ref.empty())
    return true;
  if (!canvas_editable())
    return true;
  if (!hasTarget) {
    status_text(L"Connection cancelled. Drop onto a highlighted input socket to connect tools.");
    return true;
  }
  if (previewReady && !accepted) {
    status_text(L"These ports cannot connect: check the input type, required state, available slots and workflow direction.");
    return true;
  }
  const auto &input = canvas_input(target.node, target.port);
  if (!input.get("refs").is_array())
    return true;
  if (canvas_connected(input, ref)) {
    status_text(L"This output is already connected to that input.");
    return true;
  }
  Json refs = Json::array();
  if (input.get("max").integer(1) > 1)
    for (const auto &item : input.get("refs").array_items())
      refs.array_items().push_back(item.get("ref"));
  refs.array_items().push_back(ref);
  model("connect", object({{"nodeId", target.node}, {"portId", target.port},
                            {"refs", std::move(refs)}}));
  return true;
}
std::vector<dag_routing::Rect> canvas_obstacles() const {
  std::vector<dag_routing::Rect> result;
  for (const auto &card : canvasCards)
    result.push_back({static_cast<int>(card.box.left) - 12, static_cast<int>(card.box.top) - 12,
                      static_cast<int>(card.box.right) + 12, static_cast<int>(card.box.bottom) + 12});
  return result;
}
std::vector<dag_routing::Point> canvas_route(const CanvasPort &source, POINT endpoint,
                                           const std::string &targetNode,
                                           const std::vector<dag_routing::Segment> &occupied = {}) const {
  const dag_routing::Point start{static_cast<int>(source.point.x), static_cast<int>(source.point.y)},
                          end{static_cast<int>(endpoint.x), static_cast<int>(endpoint.y)};
  int sourceIndex = -1, targetIndex = -1;
  for (size_t i = 0; i < canvasCards.size(); ++i) {
    if (canvasCards[i].id == source.node)
      sourceIndex = static_cast<int>(i);
    if (canvasCards[i].id == targetNode)
      targetIndex = static_cast<int>(i);
  }
  return dag_routing::route_ports(start, end, canvas_obstacles(), sourceIndex, targetIndex, occupied);
}
void canvas_route_connections() {
  // Painting, panning, hovering and zooming reuse world-coordinate routes.
  // Recompute only when cards, ports or actual graph connections change.
  std::ostringstream key;
  for (const auto &card : canvasCards)
    key << card.id << ':' << card.box.left << ',' << card.box.top << ','
        << card.box.right << ',' << card.box.bottom << ';';
  for (const auto &port : canvasPorts)
    key << port.node << ':' << port.port << ':' << port.ref << ':'
        << port.point.x << ',' << port.point.y << ';';
  std::vector<CanvasConnection> connections;
  for (const auto &target : canvasPorts) {
    if (target.output)
      continue;
    for (const auto &node : graph().get("nodes").array_items()) {
      if (getstr(node, "id") != target.node || !node.get("inputs").get(target.port).is_array())
        continue;
      for (const auto &ref : node.get("inputs").get(target.port).array_items())
        for (const auto &source : canvasPorts)
          if (source.output && source.ref == text(ref)) {
            key << source.ref << '>' << target.node << ':' << target.port << ';';
            connections.push_back({source, target, {}});
          }
    }
  }
  if (key.str() == canvasRouteKey)
    return;
  canvasRouteKey = key.str();
  canvasBlockedRoutes = false;
  for (size_t i = 0; i < connections.size(); ++i) {
    auto &connection = connections[i];
    std::vector<dag_routing::Segment> occupied;
    for (size_t j = 0; canvasCards.size() <= dag_routing::max_cosmetic_cards && j < i; ++j)
      if (connections[j].source.ref != connection.source.ref)
        for (size_t k = 1; k < connections[j].points.size(); ++k)
          occupied.emplace_back(connections[j].points[k - 1], connections[j].points[k]);
    connection.points = canvas_route(connection.source, connection.target.point, connection.target.node, occupied);
    canvasBlockedRoutes = canvasBlockedRoutes || connection.points.empty();
  }
  canvasConnections = std::move(connections);
}
void canvas_layout() {
  canvasCards.clear();
  canvasPorts.clear();
  hits.clear();
  const auto rank = ranks();
  std::map<int, int> nextY;
  std::set<std::string> activeIds;
  auto card = [&](const Json &node, bool source) {
    CanvasCard item;
    item.id = getstr(node, "id");
    item.source = source;
    activeIds.insert(item.id);
    item.title = display_id(item.id) + " · " +
                 (source ? getstr(node, "label", "Local input") : node_name(node));
    const auto &metadata = tool(node);
    item.unavailable = !source && metadata.is_null();
    item.subtitle = source ? "Local input · " + getstr(node, "type")
                           : getstr(metadata, "packId") + " " + getstr(metadata, "packVersion");
    if (!source && metadata.get("id").is_null()) {
      item.unavailable = true;
      item.subtitle = "Exact tool version unavailable";
    }
    if (source) {
      CanvasPort port;
      port.node = item.id;
      port.ref = item.id;
      port.label = "Files";
      port.type = getstr(node, "type");
      port.output = true;
      item.outputs.push_back(port);
    } else {
      if (metadata.get("ports").is_array())
        for (const auto &input : metadata.get("ports").array_items()) {
          CanvasPort port;
          port.node = item.id;
          port.port = getstr(input, "id");
          port.label = getstr(input, "label", port.port);
          port.type = getstr(input, "type");
          item.inputs.push_back(port);
        }
      if (metadata.get("outputs").is_array())
        for (const auto &output : metadata.get("outputs").array_items()) {
          CanvasPort port;
          port.node = item.id;
          port.port = getstr(output, "id");
          port.ref = item.id + "::" + port.port;
          port.label = getstr(output, "label", port.port);
          port.type = getstr(output, "type");
          port.output = true;
          item.outputs.push_back(port);
        }
    }
    const int level = source ? 0 : rank.at(item.id);
    const int h = 64 + static_cast<int>(item.inputs.size() + item.outputs.size()) * 34 +
                  (!item.inputs.empty() && !item.outputs.empty() ? 8 : 0);
    int x = 32 + level * 310, y = nextY.count(level) ? nextY[level] : 32;
    if (canvas_positioned(item.id)) {
      const auto &position = canvasPositions.at(item.id);
      x = static_cast<int>(position.x);
      y = static_cast<int>(position.y);
    }
    nextY[level] = std::max(nextY[level], y + h + 36);
    item.box = {x, y, x + 242, y + h};
    int row = y + 65;
    for (auto &port : item.inputs) {
      port.point = {x, row};
      row += 34;
    }
    if (!item.inputs.empty() && !item.outputs.empty())
      row += 8;
    for (auto &port : item.outputs) {
      port.point = {x + 242, row};
      row += 34;
    }
    canvasCards.push_back(std::move(item));
  };
  for (const auto &source : graph().get("sources").array_items())
    card(source, true);
  for (const auto &node : graph().get("nodes").array_items())
    card(node, false);
  // Automatically placed inputs must not cover a tool dropped near the left
  // edge. Move only automatic cards; a user's positions stay at their pointer.
  for (size_t i = 0; i < canvasCards.size(); ++i) {
    auto &item = canvasCards[i];
    if (canvas_positioned(item.id))
      continue;
    for (size_t retry = 0; retry < canvasCards.size(); ++retry) {
      LONG shift = 0;
      for (size_t j = 0; j < canvasCards.size(); ++j) {
        if (j == i || (j > i && !canvas_positioned(canvasCards[j].id)))
          continue;
        const auto &other = canvasCards[j].box;
        const auto &box = item.box;
        if (box.left < other.right + 18 && box.right + 18 > other.left &&
            box.top < other.bottom + 18 && box.bottom + 18 > other.top)
          shift = std::max(shift, other.bottom + 36 - box.top);
      }
      if (!shift)
        break;
      item.box.top += shift;
      item.box.bottom += shift;
      for (auto &port : item.inputs)
        port.point.y += shift;
      for (auto &port : item.outputs)
        port.point.y += shift;
    }
  }
  for (const auto &item : canvasCards) {
    canvasPorts.insert(canvasPorts.end(), item.inputs.begin(), item.inputs.end());
    canvasPorts.insert(canvasPorts.end(), item.outputs.begin(), item.outputs.end());
  }
  // A removed node must not leave a position for a later, unrelated graph.
  if (!showingHistory) {
    for (auto it = canvasPositions.begin(); it != canvasPositions.end();)
      if (!activeIds.count(it->first))
        it = canvasPositions.erase(it);
      else
        ++it;
  }
  canvas_route_connections();
  canvas_navigation_bounds();
  for (const auto &item : canvasCards) {
    const auto &box = item.box;
    hits.push_back({{canvas_px(box.left - dagX), canvas_px(box.top - dagY),
                     canvas_px(box.right - dagX), canvas_px(box.bottom - dagY)},
                    item.id, item.source});
  }
}
void paint_dag() {
  PAINTSTRUCT ps{};
  HDC dc = BeginPaint(dag, &ps);
  struct End {
    HWND h;
    PAINTSTRUCT *ps;
    ~End() { EndPaint(h, ps); }
  } end{dag, &ps};
  RECT client{};
  GetClientRect(dag, &client);
  HDC mem = CreateCompatibleDC(dc);
  HBITMAP bitmap = CreateCompatibleBitmap(dc, std::max<LONG>(1, client.right),
                                          std::max<LONG>(1, client.bottom));
  HGDIOBJ old = SelectObject(mem, bitmap);
  HBRUSH gridBackground = CreateSolidBrush(RGB(246, 248, 251));
  FillRect(mem, &client, gridBackground);
  DeleteObject(gridBackground);
  canvas_layout();
  const auto view = canvas_viewport();
  const int vw = static_cast<int>(view.cx), vh = static_cast<int>(view.cy);
  {
    Gdiplus::Graphics g(mem);
    g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
    const float scale = dpi / 96.f * canvasZoom / 100.f;
    g.ScaleTransform(scale, scale);
    g.TranslateTransform(static_cast<float>(-dagX), static_cast<float>(-dagY));
    Gdiplus::SolidBrush grid(Gdiplus::Color(255, 215, 224, 234));
    for (int y = dagY / 20 * 20; y <= dagY + vh; y += 20)
      for (int x = dagX / 20 * 20; x <= dagX + vw; x += 20)
        g.FillEllipse(&grid, static_cast<float>(x), static_cast<float>(y), 1.5f, 1.5f);
    auto connection = [&](const std::vector<dag_routing::Point> &points,
                          Gdiplus::Color color, float weight, bool pending, bool arrow) {
      if (points.size() < 2)
        return;
      Gdiplus::Pen pen(color, weight);
      pen.SetLineJoin(Gdiplus::LineJoinRound);
      if (pending)
        pen.SetDashStyle(Gdiplus::DashStyleDash);
      std::vector<Gdiplus::PointF> path;
      for (const auto point : points)
        path.emplace_back(static_cast<float>(point.x), static_cast<float>(point.y));
      // A background halo makes an unavoidable crossing read as two edges,
      // rather than an accidental merge. Shared fan-out still has one trunk.
      Gdiplus::Pen halo(Gdiplus::Color(255, 246, 248, 251), weight + 4.f);
      halo.SetLineJoin(Gdiplus::LineJoinRound);
      if (pending)
        halo.SetDashStyle(Gdiplus::DashStyleDash);
      g.DrawLines(&halo, path.data(), static_cast<INT>(path.size()));
      g.DrawLines(&pen, path.data(), static_cast<INT>(path.size()));
      if (arrow) {
        const auto &end = path.back();
        // The socket is drawn later. Put the arrow just outside its left rim.
        const Gdiplus::PointF head[] = {{end.X - 7.f, end.Y},
                                      {end.X - 15.f, end.Y - 4.f},
                                      {end.X - 15.f, end.Y + 4.f}};
        Gdiplus::SolidBrush fill(color);
        g.FillPolygon(&fill, head, 3);
      }
    };
    for (const auto &edge : canvasConnections) {
      const bool active = edge.source.node == selected || edge.target.node == selected ||
                          edge.source.ref == canvasDragRef;
      connection(edge.points,
                 active ? Gdiplus::Color(255, 45, 106, 166) : Gdiplus::Color(255, 123, 145, 170),
                 active ? 2.4f : 1.7f, false, true);
    }
    if (!canvasDragRef.empty())
      for (const auto &source : canvasPorts)
        if (source.output && source.ref == canvasDragRef) {
          POINT endpoint = canvasPointer;
          bool compatible = false;
          std::string targetNode;
          for (const auto &target : canvasPorts) {
            const long long dx = static_cast<long long>(canvasPointer.x) - target.point.x,
                            dy = static_cast<long long>(canvasPointer.y) - target.point.y;
            const int radius = std::max(6, MulDiv(12, 100, canvasZoom));
            if (!target.output && dx * dx + dy * dy <= static_cast<long long>(radius) * radius) {
              endpoint = target.point;
              targetNode = target.node;
              compatible = canvas_accepts(target, canvasDragRef);
              break;
            }
          }
          connection(canvas_route(source, endpoint, targetNode),
                     compatible ? Gdiplus::Color(255, 33, 135, 94) : Gdiplus::Color(255, 45, 106, 166),
                     2.5f, true, !targetNode.empty());
          break;
        }
    for (const auto &item : canvasCards) {
      const auto &box = item.box;
      const bool active = item.id == selected;
      rounded(g, static_cast<float>(box.left + 2), static_cast<float>(box.top + 3),
              static_cast<float>(box.right - box.left), static_cast<float>(box.bottom - box.top),
              5, RGB(230, 235, 241), RGB(230, 235, 241));
      rounded(g, static_cast<float>(box.left), static_cast<float>(box.top),
              static_cast<float>(box.right - box.left), static_cast<float>(box.bottom - box.top),
              5, PAPER, active ? RGB(33, 102, 172) : RGB(188, 203, 219));
      Gdiplus::SolidBrush header(item.unavailable ? Gdiplus::Color(255, 137, 84, 59)
                                    : item.source ? Gdiplus::Color(255, 87, 111, 138)
                                                  : Gdiplus::Color(255, 43, 90, 139));
      g.FillRectangle(&header, static_cast<float>(box.left + 1), static_cast<float>(box.top + 1),
                      static_cast<float>(box.right - box.left - 2), 43.f);
      if (item.id == canvasHoverNode && canvas_editable()) {
        const auto close = canvas_delete_rect(item);
        if (canvasHoverDelete)
          rounded(g, static_cast<float>(close.left), static_cast<float>(close.top),
                  static_cast<float>(close.right - close.left), static_cast<float>(close.bottom - close.top),
                  3, RGB(169, 54, 57), RGB(169, 54, 57));
        Gdiplus::Pen cross(Gdiplus::Color(255, 255, 255, 255), 1.8f);
        const float cx = (close.left + close.right) / 2.f,
                    cy = (close.top + close.bottom) / 2.f;
        g.DrawLine(&cross, cx - 4.f, cy - 4.f, cx + 4.f, cy + 4.f);
        g.DrawLine(&cross, cx + 4.f, cy - 4.f, cx - 4.f, cy + 4.f);
      }
      if (!item.inputs.empty() && !item.outputs.empty()) {
        Gdiplus::Pen separator(Gdiplus::Color(255, 224, 231, 239), 1.f);
        const float y = item.outputs.front().point.y - 23.f;
        g.DrawLine(&separator, box.left + 12.f, y, box.right - 12.f, y);
      }
    }
    for (const auto &port : canvasPorts) {
      const bool candidate = !canvasDragRef.empty() && !port.output;
      const bool accepted = candidate && canvas_accepts(port, canvasDragRef);
      const bool active = port.ref == canvasDragRef || port.node == selected;
      Gdiplus::Color color = accepted ? Gdiplus::Color(255, 32, 136, 92)
                              : candidate ? Gdiplus::Color(255, 177, 186, 197)
                              : active ? Gdiplus::Color(255, 40, 101, 166)
                                       : Gdiplus::Color(255, 86, 112, 145);
      if (accepted) {
        Gdiplus::SolidBrush halo(Gdiplus::Color(55, 32, 136, 92));
        g.FillEllipse(&halo, port.point.x - 11.f, port.point.y - 11.f, 22.f, 22.f);
      }
      Gdiplus::Pen border(color, 2.f);
      Gdiplus::SolidBrush fill(port.output || accepted ? color : Gdiplus::Color(255, 255, 255, 255));
      g.FillEllipse(&fill, port.point.x - 5.f, port.point.y - 5.f, 10.f, 10.f);
      g.DrawEllipse(&border, port.point.x - 5.f, port.point.y - 5.f, 10.f, 10.f);
    }
  }
  SetBkMode(mem, TRANSPARENT);
  // GDI text uses the same zoom as the GDI+ card geometry. Scaling only the
  // boxes leaves clipped, overlapping labels at non-default zoom levels.
  auto scaledFont = [&](HFONT face) {
    LOGFONTW descriptor{};
    if (!GetObjectW(face, sizeof(descriptor), &descriptor))
      return static_cast<HFONT>(nullptr);
    descriptor.lfHeight = MulDiv(descriptor.lfHeight, canvasZoom, 100);
    return CreateFontIndirectW(&descriptor);
  };
  HFONT zoomFont = scaledFont(font), zoomBold = scaledFont(bold), zoomSmall = scaledFont(small);
  const auto oldFont = SelectObject(mem, zoomFont ? zoomFont : font);
  auto label = [&](const std::wstring &value, RECT r, HFONT face, COLORREF color, UINT flags) {
    RECT screen{canvas_px(r.left - dagX), canvas_px(r.top - dagY), canvas_px(r.right - dagX), canvas_px(r.bottom - dagY)};
    SelectObject(mem, face);
    SetTextColor(mem, color);
    DrawTextW(mem, value.c_str(), -1, &screen, flags | DT_NOPREFIX | DT_SINGLELINE | DT_END_ELLIPSIS);
  };
  for (const auto &item : canvasCards) {
    const auto &box = item.box;
    label(wide(item.title), {box.left + 12, box.top + 5, box.right - 34, box.top + 25}, zoomBold ? zoomBold : bold, PAPER, DT_LEFT | DT_VCENTER);
    label(wide(item.subtitle), {box.left + 12, box.top + 25, box.right - 34, box.top + 42}, zoomSmall ? zoomSmall : small, RGB(223, 235, 247), DT_LEFT | DT_VCENTER);
    auto portLabel = [&](const CanvasPort &port) {
      const UINT align = port.output ? DT_RIGHT : DT_LEFT;
      label(wide(port.label), {box.left + 14, port.point.y - 14, box.right - 14, port.point.y + 3}, zoomFont ? zoomFont : font, INK, align | DT_VCENTER);
      label(wide(port.type), {box.left + 14, port.point.y + 3, box.right - 14, port.point.y + 18}, zoomSmall ? zoomSmall : small, MUTED, align | DT_VCENTER);
    };
    for (const auto &port : item.inputs)
      portLabel(port);
    for (const auto &port : item.outputs)
      portLabel(port);
  }
  if (canvasCards.empty()) {
    SelectObject(mem, bold);
    SetTextColor(mem, INK);
    RECT title{px(32), px(40), client.right - px(32), px(75)};
    DrawTextW(mem, L"Build your workflow", -1, &title, DT_LEFT | DT_WORDBREAK | DT_NOPREFIX);
    SelectObject(mem, font);
    SetTextColor(mem, MUTED);
    RECT help{px(32), px(88), client.right - px(32), client.bottom - px(24)};
    DrawTextW(mem, L"Add named workflow inputs for your files and reference, then drag tools from the Tool shed onto this canvas.\n\nConnect input or tool-output sockets to compatible tool inputs. Select a card to edit its options on the right.\n\nDrag empty canvas to pan. Use the zoom buttons, Ctrl+wheel or a trackpad pinch to zoom.", -1, &help, DT_LEFT | DT_WORDBREAK | DT_NOPREFIX);
  }
  if (canvasBlockedRoutes && !canvasCards.empty()) {
    // Obscured sockets cannot have a truthful visible route. Explain the small
    // remaining manual-layout action instead of silently drawing under a card.
    RECT notice{px(10), client.bottom - px(40), client.right - px(10), client.bottom - px(10)};
    HBRUSH background = CreateSolidBrush(RGB(255, 245, 221));
    FillRect(mem, &notice, background);
    DeleteObject(background);
    SelectObject(mem, small);
    SetTextColor(mem, RGB(115, 75, 24));
    notice.left += px(8);
    DrawTextW(mem, L"Move overlapping cards apart to show every connection.", -1,
              &notice, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX);
  }
  BitBlt(dc, 0, 0, client.right, client.bottom, mem, 0, 0, SRCCOPY);
  SelectObject(mem, oldFont);
  for (HFONT face : {zoomFont, zoomBold, zoomSmall})
    if (face)
      DeleteObject(face);
  SelectObject(mem, old);
  DeleteObject(bitmap);
  DeleteDC(mem);
}
