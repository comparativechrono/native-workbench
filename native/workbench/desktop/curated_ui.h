// Included inside Workspace: explicit, local synthetic training workflows.
  Json curatedCatalogue = object({{"workflows", Json::array()}});

  const Json &curated_selected() const {
    return desktop::selected_record(curatedCatalogue, "workflows", selected_row(curatedView, CURATED_LIST));
  }
  void curated_enabled(bool idle, bool edit) {
    if (!curatedView.window) return;
    EnableWindow(aux(curatedView, CURATED_REFRESH), idle);
    EnableWindow(aux(curatedView, CURATED_LOAD), edit && !analysis_active() &&
        curated_selected().get("available").boolean());
    EnableWindow(aux(curatedView, CURATED_SETUP), idle && !analysis_active() &&
        !setupBusy && !packBusy && !refBusy && !showingHistory);
  }
  template<class Put> void curated_layout(Auxiliary &view, int w, int h, Put put) {
    const int left = std::min(300, w / 3);
    ListView_SetColumnWidth(aux(view, CURATED_LIST), 0, MulDiv(left - 126, view.dpi, 96));
    ListView_SetColumnWidth(aux(view, CURATED_LIST), 1, MulDiv(118, view.dpi, 96));
    put(-1, 18, 12, w - 36, 52);
    put(-2, 18, 72, left, 22);
    put(-3, left + 32, 72, w - left - 50, 22);
    put(CURATED_LIST, 18, 100, left, h - 242);
    put(CURATED_DETAILS, left + 32, 100, w - left - 50, h - 242);
    put(CURATED_NOTICE, 18, h - 132, w - 36, 74);
    put(CURATED_LOAD, 18, h - 44, 164, 32);
    put(CURATED_SETUP, 194, h - 44, 130, 32);
    put(CURATED_REFRESH, 336, h - 44, 106, 32);
    put(CURATED_CLOSE, w - 108, h - 44, 90, 32);
  }
  template<class Label, class Action, class Edit, class List>
  void curated_controls(Auxiliary &view, Label label, Action action, Edit edit, List list) {
    curatedCatalogue = object({{"workflows", Json::array()}});
    label(-1, L"Small synthetic training workflows with known answers. Review the inputs and exact tool requirements, then explicitly load a workflow to edit and run locally.");
    label(-2, L"Training workflows"); label(-3, L"Inputs, expected answers and requirements");
    list(CURATED_LIST);
    aux_columns(view, CURATED_LIST, {{L"Workflow", 194}, {L"Requirements", 116}});
    edit(CURATED_DETAILS, L"Loading the local workflow catalogue...", true);
    SendMessageW(aux(view, CURATED_DETAILS), EM_SETLIMITTEXT, 1024 * 1024, 0);
    edit(CURATED_NOTICE, L"Loading does not run an analysis or download tools or reference data.", true);
    action(CURATED_LOAD, L"Load selected workflow");
    action(CURATED_SETUP, L"Manage tools...");
    action(CURATED_REFRESH, L"Refresh"); action(CURATED_CLOSE, L"Close");
    send("examples/list");
  }
  void curated_selection() {
    if (!curatedView.window || curatedView.rebuilding) return;
    const auto &entry = curated_selected();
    std::wstring details = wt(entry, "details");
    if (details.empty() && !getstr(entry, "id").empty()) {
      details = wt(entry, "name") + L"\n\n" + wt(entry, "description", getstr(entry, "summary"));
      if (entry.get("issues").is_array()) for (const auto &issue : entry.get("issues").array_items())
        details += L"\n\n" + (issue.is_string() ? wide(issue.string()) : wt(issue, "message"));
    }
    aux_text(curatedView, CURATED_DETAILS, lines(details.empty() ? L"Select a training workflow to review its inputs and expected answers." : details));
    std::wstring notice = wt(curatedCatalogue, "notice",
        "These fixtures teach workflow use; their expected answers are not biological quality thresholds.");
    if (!getstr(entry, "id").empty() && !entry.get("available").boolean())
      notice = L"This workflow needs attention before loading. Review the details for missing files or exact tool versions. Use Manage tools for pack installation, then Refresh.\n\n" + notice;
    else if (!getstr(entry, "id").empty())
      notice = L"The pinned workflow is available. Loading replaces the editable workflow after confirmation. Nothing runs or downloads automatically.\n\n" + notice;
    aux_text(curatedView, CURATED_NOTICE, lines(notice));
    auxiliary_enabled();
  }
  void curated_rows(const Json &value) {
    if (!curatedView.window) return;
    if (!value.get("workflows").is_array())
      throw std::runtime_error("The local workflow catalogue returned no workflow list. Refresh the catalogue and check the application files.");
    const auto previous = getstr(curated_selected(), "id");
    curatedCatalogue = value;
    curatedView.rebuilding = true;
    HWND list = aux(curatedView, CURATED_LIST);
    ListView_DeleteAllItems(list);
    int selectedIndex = 0, row = 0;
    for (const auto &entry : value.get("workflows").array_items()) {
      if (getstr(entry, "id") == previous) selectedIndex = row;
      auto label = wt(entry, "name");
      const std::wstring prefix = L"Synthetic training: ";
      if (label.rfind(prefix, 0) == 0) label.erase(0, prefix.size());
      if (!label.empty()) label[0] = static_cast<wchar_t>(std::towupper(label[0]));
      aux_row(list, row++, {label, entry.get("available").boolean() ? L"Available" : L"Needs attention"});
    }
    if (row) ListView_SetItemState(list, selectedIndex, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
    curatedView.rebuilding = false;
    curated_selection();
  }
  void curated_loaded(const Json &value) {
    submittedFields.clear();
    if (showingHistory) canvas_leave_history();
    showingHistory = false; historyRun = Json::object();
    snapshot(value);
    canvas_reset_positions();
    status_text(L"Synthetic training workflow loaded. Review the inputs, expected answers and planned Methods before running.");
    if (curatedView.window) DestroyWindow(curatedView.window);
    SetForegroundWindow(window);
  }
  void curated_command(int id, int notification) {
    if (notification != BN_CLICKED || !ready || closing || activeRequest || !outgoing.empty()) return;
    if (id == CURATED_REFRESH) {
      aux_text(curatedView, CURATED_NOTICE, L"Checking the local catalogue and exact installed tool requirements...");
      send("examples/list");
    } else if (id == CURATED_SETUP && IsWindowEnabled(aux(curatedView, CURATED_SETUP))) {
      requiredPack = Json::object();
      const auto &requirements = curated_selected().get("requirements");
      if (requirements.is_array()) for (const auto &requirement : requirements.array_items())
        if (!requirement.get("available").boolean() && getstr(requirement, "packId") != "builtin") {
          requiredPack = requirement;
          break;
        }
      show_pack_manager();
      if (!getstr(requiredPack, "packId").empty()) {
        SetWindowTextW(packSearch, wt(requiredPack, "packId").c_str());
        SendMessageW(packFilter, CB_SETCURSEL, 0, 0);
        refresh_packs(); pack_notice();
      }
    } else if (id == CURATED_LOAD && IsWindowEnabled(aux(curatedView, CURATED_LOAD))) {
      const auto identity = getstr(curated_selected(), "id");
      if (identity.empty()) return;
      // Tools mode keeps a separate workflow draft that is not in state.graph.
      // Always confirm here so that a hidden draft cannot be overwritten silently.
      if (MessageBoxW(curatedView.window,
              L"Replace the current editable workflow with this synthetic training workflow?\n\nSave your current workflow first if you want to keep it. Existing saved workflows and results remain available.",
              L"Load training workflow", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return;
      aux_text(curatedView, CURATED_NOTICE, L"Loading the reviewed synthetic workflow and its exact tool pins...");
      send("examples/load", object({{"id", identity}}));
    }
    auxiliary_enabled();
  }
