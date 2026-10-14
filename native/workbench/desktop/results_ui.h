// Included inside Workspace: searchable recorded results and evidence summaries.
  Json resultsRecords = object({{"runs", Json::array()}});
  std::string resultsRequested;
  std::set<long long> standaloneResultSummaries;

  void show_result_summary(const std::string &identity) {
    if (identity.empty() || !ready || closing) return;
    const auto request = send("results/summary", object({{"id", identity}}));
    pendingViews.erase(request);
    standaloneResultSummaries.insert(request);
  }

  const Json &results_selected() const {
    return desktop::selected_record(resultsRecords, "runs", selected_row(resultsView, RESULTS_RUNS));
  }
  void results_enabled(bool idle) {
    if (!resultsView.window) return;
    const bool selectedRun = idle && !getstr(results_selected(), "run_id").empty();
    auto enable = [&](int id, bool value) {
      HWND control = aux(resultsView, id);
      // Disabling a focused Win32 button clears keyboard focus. Search starts
      // asynchronously and also reads the selected summary, so move to the
      // always-available query before disabling, not when either reply arrives.
      // Replies must not steal focus back from a different control or window.
      if (!value && control && GetFocus() == control)
        SetFocus(aux(resultsView, RESULTS_QUERY));
      EnableWindow(control, value);
    };
    enable(RESULTS_SEARCH, idle);
    enable(RESULTS_VIEW, selectedRun);
    enable(RESULTS_OPEN, selectedRun && !getstr(results_selected(), "folder").empty());
  }
  template<class Put> void results_layout(Auxiliary &, int w, int h, Put put) {
    const int listHeight = std::max(96, (h - 260) / 3);
    put(-1, 18, 12, w - 36, 40);
    put(-2, 18, 60, 62, 24);
    put(RESULTS_QUERY, 82, 56, w - 218, 32);
    put(RESULTS_SEARCH, w - 124, 56, 106, 32);
    put(RESULTS_RUNS, 18, 100, w - 36, listHeight);
    put(-3, 18, 110 + listHeight, w - 36, 22);
    put(RESULTS_DETAILS, 18, 138 + listHeight, w - 36, std::max(100, h - listHeight - 240));
    put(RESULTS_NOTICE, 18, h - 92, w - 36, 40);
    put(RESULTS_VIEW, 18, h - 44, 154, 32);
    put(RESULTS_OPEN, 184, h - 44, 160, 32);
    put(RESULTS_CLOSE, w - 108, h - 44, 90, 32);
  }
  template<class Label, class Action, class Edit, class List>
  void results_controls(Auxiliary &view, Label label, Action action, Edit edit, List list) {
    resultsRecords = object({{"runs", Json::array()}}); resultsRequested.clear();
    label(-1, L"Find recorded analyses by name, sample, tool or status. Select a result to read recorded measurements, unavailable evidence and any next steps.");
    label(-2, L"Search");
    edit(RESULTS_QUERY, L"", false);
    SendMessageW(aux(view, RESULTS_QUERY), EM_SETLIMITTEXT, 500, 0);
    SendMessageW(aux(view, RESULTS_QUERY), EM_SETCUEBANNER, FALSE,
        reinterpret_cast<LPARAM>(L"Name, sample, tool or status"));
    action(RESULTS_SEARCH, L"Search");
    list(RESULTS_RUNS);
    aux_columns(view, RESULTS_RUNS, {{L"Analysis", 224}, {L"Status", 104}, {L"Sample", 120}, {L"Tools", 230}, {L"Started", 168}});
    label(-3, L"Recorded summary · metrics and their source files");
    edit(RESULTS_DETAILS, L"Loading recorded analyses...", true);
    SendMessageW(aux(view, RESULTS_DETAILS), EM_SETLIMITTEXT, 1024 * 1024, 0);
    label(RESULTS_NOTICE, L"Reading local records. No files are uploaded.");
    action(RESULTS_VIEW, L"View saved workflow");
    action(RESULTS_OPEN, L"Open results folder");
    action(RESULTS_CLOSE, L"Close");
    send("results/search", object({{"query", ""}}));
  }
  void results_selection() {
    if (!resultsView.window || resultsView.rebuilding) return;
    const auto identity = getstr(results_selected(), "run_id");
    if (identity == resultsRequested) { auxiliary_enabled(); return; }
    resultsRequested = identity;
    aux_text(resultsView, RESULTS_DETAILS, identity.empty() ?
        L"No matching result is selected. Search for a recorded analysis or clear the search to show recent runs." :
        L"Reading the selected result and its recorded output evidence...");
    if (!identity.empty()) send("results/summary", object({{"id", identity}}));
    auxiliary_enabled();
  }
  void results_rows(const Json &value) {
    if (!resultsView.window) return;
    if (!value.get("runs").is_array())
      throw std::runtime_error("The local results search returned no run list. Search again and check the application files.");
    const auto previous = getstr(results_selected(), "run_id");
    resultsRecords = value; resultsRequested.clear();
    resultsView.rebuilding = true;
    HWND list = aux(resultsView, RESULTS_RUNS);
    ListView_DeleteAllItems(list);
    int selectedIndex = 0, row = 0;
    for (const auto &entry : value.get("runs").array_items()) {
      if (getstr(entry, "run_id") == previous) selectedIndex = row;
      aux_row(list, row++, {wt(entry, "name", getstr(entry, "run_id")), wt(entry, "status"),
          wt(entry, "sample"), wt(entry, "tools"), wt(entry, "started_at")});
    }
    if (row) ListView_SetItemState(list, selectedIndex, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
    resultsView.rebuilding = false;
    std::wstring notice = std::to_wstring(row) + L" recorded analyses shown. " + wt(value, "note");
    if (value.get("omitted").integer() > 0)
      notice += L" " + std::to_wstring(value.get("omitted").integer()) + L" additional matches omitted; refine the search.";
    aux_text(resultsView, RESULTS_NOTICE, notice);
    if (!row) aux_text(resultsView, RESULTS_DETAILS, L"No matching recorded analyses. Clear the search and press Search to show recent runs.");
    results_selection();
  }
  void results_summary(const Json &value) {
    if (!resultsView.window || getstr(value, "run_id") != resultsRequested) return;
    auto details = wt(value, "summaryText", getstr(value, "details"));
    if (details.empty()) details = L"No readable summary is available for this record. Open the result folder to inspect the saved methods and logs.";
    aux_text(resultsView, RESULTS_DETAILS, lines(details));
    auxiliary_enabled();
  }
  void results_command(int id, int notification) {
    if (notification != BN_CLICKED || !ready || closing || activeRequest || !outgoing.empty()) return;
    if (id == RESULTS_SEARCH) {
      aux_text(resultsView, RESULTS_NOTICE, L"Searching recorded names, samples, tools and execution status...");
      send("results/search", object({{"query", narrow(control_text(aux(resultsView, RESULTS_QUERY)))}}));
    } else if (id == RESULTS_VIEW || id == RESULTS_OPEN) {
      const auto identity = getstr(results_selected(), "run_id");
      if (identity.empty()) return;
      send(id == RESULTS_VIEW ? "run/get" : "open", object({{"run_id", identity}}));
      if (id == RESULTS_VIEW) DestroyWindow(resultsView.window);
    }
    auxiliary_enabled();
  }
