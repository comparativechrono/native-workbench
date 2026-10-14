// Included inside Workspace. The editor owns a draft until Use table succeeds.
  Auxiliary sampleEditorView;
  Json sampleEditorTable = Json::object();
  std::set<std::string> sampleEditorFileColumns;
  std::string sampleEditorIntent, sampleEditorSavePath, sampleEditorSourcePath, sampleLoadedPath;
  std::wstring sampleEditorRetentionNotice;
  bool sampleEditorPending = false, sampleEditorDirty = false;
  int sampleEditorRow = -1, sampleEditorColumn = 0;
  unsigned sampleEditorParentGeneration = 0;

  bool sample_editor_method(const std::string &method) const {
    return method == "sample/edit" || method == "sample/apply" ||
           method == "sample/save" || method == "sample/example";
  }
  std::string sample_editor_column() const {
    const auto &columns = sampleEditorTable.get("columns").array_items();
    return sampleEditorColumn >= 0 && static_cast<size_t>(sampleEditorColumn) < columns.size()
        ? text(columns[sampleEditorColumn]) : "";
  }
  void sample_editor_changed() {
    sampleEditorDirty = true; sampleEditorSourcePath.clear();
    sample_invalidate();
    aux_text(sampleEditorView, SAMPLE_EDITOR_NOTICE,
        L"Draft changes stay here until Use table. Mark file columns explicitly; other columns are kept as text. Save as never overwrites an existing file." +
        (sampleEditorRetentionNotice.empty() ? L"" : L"\r\n" + sampleEditorRetentionNotice));
  }
  void sample_editor_enabled(bool idle) {
    if (!sampleEditorView.window) return;
    const bool available = idle && !sampleEditorPending;
    const bool loaded = sampleEditorTable.get("columns").is_array();
    const bool cell = loaded && sampleEditorRow >= 0 &&
        static_cast<size_t>(sampleEditorRow) < sampleEditorTable.get("rows").array_items().size();
    for (int id : {SAMPLE_EDITOR_GRID, SAMPLE_EDITOR_COLUMN, SAMPLE_EDITOR_BASE_BROWSE,
                  SAMPLE_EDITOR_ADD_ROW, SAMPLE_EDITOR_ADD_COLUMN, SAMPLE_EDITOR_SAVE, SAMPLE_EDITOR_USE})
      enable_control(aux(sampleEditorView, id), available && loaded);
    for (int id : {SAMPLE_EDITOR_VALUE, SAMPLE_EDITOR_REMOVE_ROW})
      enable_control(aux(sampleEditorView, id), available && cell);
    for (int id : {SAMPLE_EDITOR_RENAME_COLUMN, SAMPLE_EDITOR_REMOVE_COLUMN, SAMPLE_EDITOR_FILE_COLUMN})
      enable_control(aux(sampleEditorView, id), available && loaded && sample_editor_column() != "sample_id");
    enable_control(aux(sampleEditorView, SAMPLE_EDITOR_FILE), available && cell &&
        sampleEditorFileColumns.count(sample_editor_column()) != 0);
    enable_control(aux(sampleEditorView, SAMPLE_EDITOR_CANCEL), !sampleEditorPending);
  }
  void sample_editor_selection() {
    if (!sampleEditorView.window || sampleEditorView.rebuilding) return;
    sampleEditorView.rebuilding = true;
    const auto key = sample_editor_column();
    const auto &rows = sampleEditorTable.get("rows").array_items();
    const bool cell = sampleEditorRow >= 0 && static_cast<size_t>(sampleEditorRow) < rows.size();
    aux_text(sampleEditorView, -4, cell ? L"Row " + std::to_wstring(sampleEditorRow + 1) + L" · " + wide(key) : L"Select a row to edit a cell");
    aux_text(sampleEditorView, SAMPLE_EDITOR_VALUE, cell ? wt(rows[sampleEditorRow], key.c_str()) : L"");
    SendMessageW(aux(sampleEditorView, SAMPLE_EDITOR_COLUMN), CB_SETCURSEL, sampleEditorColumn, 0);
    SendMessageW(aux(sampleEditorView, SAMPLE_EDITOR_FILE_COLUMN), BM_SETCHECK,
        sampleEditorFileColumns.count(key) ? BST_CHECKED : BST_UNCHECKED, 0);
    sampleEditorView.rebuilding = false;
    sample_editor_enabled(ready && !closing && ui_request_idle());
  }
  void sample_editor_rows() {
    if (!sampleEditorView.window) return;
    auto &view = sampleEditorView;
    view.rebuilding = true;
    HWND list = aux(view, SAMPLE_EDITOR_GRID), combo = aux(view, SAMPLE_EDITOR_COLUMN);
    SendMessageW(list, WM_SETREDRAW, FALSE, 0);
    ListView_DeleteAllItems(list);
    SendMessageW(combo, CB_RESETCONTENT, 0, 0);
    std::vector<std::pair<std::wstring, int>> columns;
    for (const auto &column : sampleEditorTable.get("columns").array_items()) {
      const auto name_ = wide(text(column));
      columns.emplace_back(name_, 190);
      SendMessageW(combo, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(name_.c_str()));
    }
    aux_columns(view, SAMPLE_EDITOR_GRID, columns);
    const auto &rows = sampleEditorTable.get("rows").array_items();
    for (size_t row = 0; row < rows.size(); ++row) {
      std::vector<std::wstring> values;
      for (const auto &column : sampleEditorTable.get("columns").array_items())
        values.push_back(wt(rows[row], text(column).c_str()));
      if (!values.empty()) aux_row(list, static_cast<int>(row), values);
    }
    sampleEditorRow = rows.empty() ? -1 : std::clamp(sampleEditorRow, 0, static_cast<int>(rows.size()) - 1);
    sampleEditorColumn = columns.empty() ? 0 : std::clamp(sampleEditorColumn, 0, static_cast<int>(columns.size()) - 1);
    if (sampleEditorRow >= 0) {
      ListView_SetItemState(list, sampleEditorRow, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
      ListView_EnsureVisible(list, sampleEditorRow, FALSE);
    }
    SendMessageW(list, WM_SETREDRAW, TRUE, 0);
    RedrawWindow(list, nullptr, nullptr, RDW_INVALIDATE | RDW_FRAME);
    aux_text(view, SAMPLE_EDITOR_BASE, wt(sampleEditorTable, "baseDirectory"));
    aux_text(view, -3, std::to_wstring(rows.size()) + L" rows · " + std::to_wstring(columns.size()) + L" columns · all rows are editable (maximum 1,000 rows / 64 columns / 1 MiB)");
    view.rebuilding = false;
    sample_editor_selection();
  }
  template<class Put> void sample_editor_layout(int w, int h, Put put) {
    put(-1, 18, 12, w - 36, 38);
    put(-2, 18, 58, 152, 26);
    put(SAMPLE_EDITOR_BASE, 174, 54, w - 318, 30);
    put(SAMPLE_EDITOR_BASE_BROWSE, w - 134, 54, 116, 30);
    put(-3, 18, 96, w - 36, 22);
    put(SAMPLE_EDITOR_GRID, 18, 122, w - 36, std::max(94, h - 400));
    put(SAMPLE_EDITOR_ADD_ROW, 18, h - 268, 92, 30);
    put(SAMPLE_EDITOR_REMOVE_ROW, 120, h - 268, 112, 30);
    put(SAMPLE_EDITOR_ADD_COLUMN, 252, h - 268, 110, 30);
    put(SAMPLE_EDITOR_RENAME_COLUMN, 372, h - 268, 130, 30);
    put(SAMPLE_EDITOR_REMOVE_COLUMN, 512, h - 268, 130, 30);
    put(SAMPLE_EDITOR_COLUMN, 18, h - 226, 250, 240);
    put(SAMPLE_EDITOR_FILE_COLUMN, 282, h - 226, w - 300, 30);
    put(-4, 18, h - 188, w - 36, 24);
    put(SAMPLE_EDITOR_VALUE, 18, h - 160, w - 172, 56);
    put(SAMPLE_EDITOR_FILE, w - 144, h - 160, 126, 32);
    put(SAMPLE_EDITOR_NOTICE, 18, h - 94, w - 36, 44);
    put(SAMPLE_EDITOR_SAVE, 18, h - 42, 132, 30);
    put(SAMPLE_EDITOR_USE, 162, h - 42, 132, 30);
    put(SAMPLE_EDITOR_CANCEL, w - 108, h - 42, 90, 30);
  }
  template<class Label, class Action, class Edit, class List>
  void sample_editor_controls(Auxiliary &view, Label label, Action action, Edit edit, List list) {
    label(-1, L"Create or edit a sample table. Select a row and column, then edit its cell below. Use table keeps your explicit workflow mappings; preview again before queueing.");
    label(-2, L"Relative path base");
    edit(SAMPLE_EDITOR_BASE, L"", false);
    SendMessageW(aux(view, SAMPLE_EDITOR_BASE), EM_SETREADONLY, TRUE, 0);
    action(SAMPLE_EDITOR_BASE_BROWSE, L"Choose folder...");
    label(-3, L"Reading the complete table..."); list(SAMPLE_EDITOR_GRID);
    action(SAMPLE_EDITOR_ADD_ROW, L"Add row"); action(SAMPLE_EDITOR_REMOVE_ROW, L"Remove row");
    action(SAMPLE_EDITOR_ADD_COLUMN, L"Add column"); action(SAMPLE_EDITOR_RENAME_COLUMN, L"Rename column");
    action(SAMPLE_EDITOR_REMOVE_COLUMN, L"Remove column");
    aux_make(view, SAMPLE_EDITOR_COLUMN, L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL);
    aux_make(view, SAMPLE_EDITOR_FILE_COLUMN, L"BUTTON", L"Contains file paths (preserved when saving elsewhere)", WS_TABSTOP | BS_AUTOCHECKBOX);
    label(-4, L"Select a row to edit a cell");
    aux_make(view, SAMPLE_EDITOR_VALUE, L"EDIT", L"", WS_TABSTOP | ES_MULTILINE | ES_WANTRETURN | ES_AUTOVSCROLL | WS_VSCROLL, WS_EX_CLIENTEDGE);
    SendMessageW(aux(view, SAMPLE_EDITOR_VALUE), EM_SETLIMITTEXT, 4096, 0);
    action(SAMPLE_EDITOR_FILE, L"Choose file...");
    edit(SAMPLE_EDITOR_NOTICE, L"Each sample needs a unique sample_id. No replicate rows or sample design are inferred. Save as creates a new CSV or TSV file.", true);
    action(SAMPLE_EDITOR_SAVE, L"Save as..."); action(SAMPLE_EDITOR_USE, L"Use table"); action(SAMPLE_EDITOR_CANCEL, L"Cancel");
  }
  void show_sample_editor(int action) {
    if (sampleEditorView.window) { SetForegroundWindow(sampleEditorView.window); return; }
    sampleEditorTable = Json::object(); sampleEditorFileColumns.clear();
    sampleEditorPending = false; sampleEditorDirty = false; sampleEditorIntent.clear(); sampleEditorRetentionNotice.clear();
    sampleEditorSavePath.clear(); sampleEditorSourcePath = action == SAMPLE_EDIT ? sampleLoadedPath : ""; sampleEditorRow = 0; sampleEditorColumn = 0;
    sampleEditorParentGeneration = samplesView.generation;
    show_auxiliary(SHOW_SAMPLE_EDITOR);
    if (action == SAMPLE_NEW) {
      Json columns = Json::array(), row = Json::object();
      for (const char *key : {"sample_id", "read1", "read2", "reference"}) { columns.array_items().push_back(key); row[key] = ""; }
      sampleEditorTable = object({{"columns", columns}, {"rows", Json::Array{row}}, {"delimiter", ","},
          {"baseDirectory", control_text(inputFolder).empty() ? Json(nullptr) : Json(narrow(control_text(inputFolder)))}});
      sampleEditorFileColumns = {"read1", "read2", "reference"};
      sample_editor_rows(); SetFocus(aux(sampleEditorView, SAMPLE_EDITOR_GRID));
    } else {
      sampleEditorPending = true;
      Json params = action == SAMPLE_EXAMPLE ? Json::object() : object({{"table_token", getstr(sampleTable, "table_token")}});
      if (action == SAMPLE_EXAMPLE && !getstr(sampleTable, "table_token").empty()) params["retain_token"] = getstr(sampleTable, "table_token");
      send(action == SAMPLE_EXAMPLE ? "sample/example" : "sample/edit", params);
    }
    auxiliary_enabled();
  }
  bool sample_editor_close() {
    if (!sampleEditorView.window) return true;
    if (sampleEditorPending) {
      MessageBoxW(sampleEditorView.window, L"Wait for the sample table operation to finish before closing.",
          L"Sample table operation", MB_OK | MB_ICONINFORMATION);
      return false;
    }
    if (sampleEditorDirty && MessageBoxW(sampleEditorView.window,
        sampleEditorRetentionNotice.empty() ? L"Discard these draft changes? The table already loaded in Samples will stay unchanged." :
        L"Discard these draft changes? The previous selection is no longer cached. You will need to import the previous table again.",
        L"Discard sample table changes", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return false;
    DestroyWindow(sampleEditorView.window);
    if (!sampleEditorRetentionNotice.empty()) aux_text(samplesView, SAMPLE_NOTICE, sampleEditorRetentionNotice);
    auxiliary_enabled();
    return true;
  }
  std::wstring sample_editor_save_path() {
    IFileSaveDialog *dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileSaveDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog))))
      throw std::runtime_error("Windows could not create the sample table save dialog.");
    struct Release { IFileSaveDialog *p; ~Release() { p->Release(); } } release{dialog};
    FILEOPENDIALOGOPTIONS options{}; dialog->GetOptions(&options);
    dialog->SetOptions(options | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR);
    dialog->SetTitle(L"Save a new sample table");
    COMDLG_FILTERSPEC filters[] = {{L"CSV sample table", L"*.csv"}, {L"TSV sample table", L"*.tsv"}};
    dialog->SetFileTypes(2, filters); dialog->SetDefaultExtension(L"csv"); dialog->SetFileName(L"samples.csv");
    IShellItem *folder = nullptr;
    const auto base = wt(sampleEditorTable, "baseDirectory");
    if (!base.empty() && SUCCEEDED(SHCreateItemFromParsingName(base.c_str(), nullptr, IID_PPV_ARGS(&folder)))) {
      dialog->SetFolder(folder); folder->Release();
    }
    const HRESULT shown = dialog->Show(sampleEditorView.window);
    if (shown == HRESULT_FROM_WIN32(ERROR_CANCELLED)) return {};
    if (FAILED(shown)) throw std::runtime_error("Windows could not save the sample table selection.");
    IShellItem *item = nullptr;
    if (FAILED(dialog->GetResult(&item))) throw std::runtime_error("Windows did not return a sample table filename.");
    PWSTR path = nullptr; const HRESULT got = item->GetDisplayName(SIGDN_FILESYSPATH, &path); item->Release();
    if (FAILED(got)) throw std::runtime_error("Windows did not return a filesystem path.");
    std::wstring result(path); CoTaskMemFree(path); return result;
  }
  void sample_editor_command(int id, int notification) {
    auto &view = sampleEditorView;
    if (view.rebuilding || sampleEditorPending) return;
    if (id == SAMPLE_EDITOR_CANCEL || id == IDCANCEL) { sample_editor_close(); return; }
    if (id == SAMPLE_EDITOR_COLUMN && notification == CBN_SELCHANGE) {
      sampleEditorColumn = static_cast<int>(SendMessageW(aux(view, id), CB_GETCURSEL, 0, 0));
      sample_editor_selection(); return;
    }
    const auto key = sample_editor_column();
    if (id == SAMPLE_EDITOR_VALUE && notification == EN_CHANGE) {
      auto &rows = sampleEditorTable["rows"].array_items();
      if (sampleEditorRow < 0 || static_cast<size_t>(sampleEditorRow) >= rows.size() || key.empty()) return;
      const auto value = control_text(aux(view, id));
      if (getstr(rows[sampleEditorRow], key.c_str()) == narrow(value)) return;
      rows[sampleEditorRow][key] = narrow(value);
      ListView_SetItemText(aux(view, SAMPLE_EDITOR_GRID), sampleEditorRow, sampleEditorColumn, const_cast<wchar_t *>(value.c_str()));
      sample_editor_changed(); return;
    }
    if (notification != BN_CLICKED || !ready || closing || !ui_request_idle()) return;
    auto &columns = sampleEditorTable["columns"].array_items();
    auto &rows = sampleEditorTable["rows"].array_items();
    if (id == SAMPLE_EDITOR_FILE_COLUMN) {
      if (key == "sample_id") return;
      if (SendMessageW(aux(view, id), BM_GETCHECK, 0, 0) == BST_CHECKED) sampleEditorFileColumns.insert(key);
      else sampleEditorFileColumns.erase(key);
      sample_editor_changed(); sample_editor_selection();
    } else if (id == SAMPLE_EDITOR_FILE) {
      if (!sampleEditorFileColumns.count(key)) return;
      const auto path = pick(view.window, false, false, L"All files|*.*", L"Choose a file for this sample cell", wt(sampleEditorTable, "baseDirectory"));
      if (!path.empty()) SetWindowTextW(aux(view, SAMPLE_EDITOR_VALUE), path.c_str());
    } else if (id == SAMPLE_EDITOR_BASE_BROWSE) {
      const auto path = pick(view.window, true, false, L"", L"Choose the explicit base folder for relative paths", wt(sampleEditorTable, "baseDirectory"));
      if (path.empty() || path == wt(sampleEditorTable, "baseDirectory")) return;
      if (!wt(sampleEditorTable, "baseDirectory").empty() && MessageBoxW(view.window,
          L"Changing this folder changes what relative file paths refer to. Cell text will stay unchanged. Use this folder?",
          L"Change relative-path base", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return;
      sampleEditorTable["baseDirectory"] = narrow(path); sample_editor_changed();
      aux_text(view, SAMPLE_EDITOR_BASE, path);
    } else if (id == SAMPLE_EDITOR_ADD_ROW) {
      if (rows.size() >= 1000) throw std::runtime_error("The table editor supports at most 1,000 rows. No rows have been removed.");
      Json row = Json::object(); for (const auto &column : columns) row[text(column)] = "";
      rows.push_back(row); sampleEditorRow = static_cast<int>(rows.size()) - 1;
      sample_editor_changed(); sample_editor_rows();
    } else if (id == SAMPLE_EDITOR_REMOVE_ROW) {
      if (sampleEditorRow < 0 || static_cast<size_t>(sampleEditorRow) >= rows.size()) return;
      if (MessageBoxW(view.window, L"Remove the selected row from this draft?", L"Remove sample row",
          MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return;
      rows.erase(rows.begin() + sampleEditorRow); sample_editor_changed(); sample_editor_rows();
    } else if (id == SAMPLE_EDITOR_ADD_COLUMN || id == SAMPLE_EDITOR_RENAME_COLUMN) {
      if (id == SAMPLE_EDITOR_RENAME_COLUMN && key == "sample_id") return;
      if (id == SAMPLE_EDITOR_ADD_COLUMN && columns.size() >= 64) throw std::runtime_error("The table editor supports at most 64 columns.");
      Modal dialog; dialog.owner = view.window; dialog.font = view.font; dialog.mode = 1;
      dialog.title = id == SAMPLE_EDITOR_ADD_COLUMN ? L"Add column" : L"Rename column";
      dialog.message = L"Unique name: start with a letter; use letters, digits, _ . or -.";
      dialog.confirm = L"Apply"; dialog.value = id == SAMPLE_EDITOR_ADD_COLUMN ? L"" : wide(key);
      if (!dialog.show()) return;
      const auto next = narrow(dialog.value);
      const auto letter = [](char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); };
      if (next.empty() || next.size() > 64 || !letter(next.front()) ||
          !std::all_of(next.begin(), next.end(), [&](char c) { return letter(c) || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-'; }))
        throw std::runtime_error("Use at most 64 characters: start with a letter, then letters, digits, underscores, dots or hyphens.");
      if (id == SAMPLE_EDITOR_RENAME_COLUMN && next == key) return;
      for (const auto &column : columns) if (lower(wide(text(column))) == lower(wide(next))) throw std::runtime_error("That column name is already present.");
      if (id == SAMPLE_EDITOR_ADD_COLUMN) {
        columns.push_back(next); for (auto &row : rows) row[next] = "";
        sampleEditorColumn = static_cast<int>(columns.size()) - 1;
      } else {
        columns[sampleEditorColumn] = next;
        for (auto &row : rows) { row[next] = row.get(key); row.object_items().erase(key); }
        if (sampleEditorFileColumns.erase(key)) sampleEditorFileColumns.insert(next);
      }
      sample_editor_changed(); sample_editor_rows();
    } else if (id == SAMPLE_EDITOR_REMOVE_COLUMN) {
      if (key.empty() || key == "sample_id") return;
      if (MessageBoxW(view.window, (L"Remove column '" + wide(key) + L"' and all its cell values from this draft?").c_str(),
          L"Remove sample column", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return;
      columns.erase(columns.begin() + sampleEditorColumn); for (auto &row : rows) row.object_items().erase(key);
      sampleEditorFileColumns.erase(key); sample_editor_changed(); sample_editor_rows();
    } else if (id == SAMPLE_EDITOR_SAVE || id == SAMPLE_EDITOR_USE) {
      if (id == SAMPLE_EDITOR_SAVE) {
        const auto path = sample_editor_save_path(); if (path.empty()) return;
        sampleEditorSavePath = narrow(path);
      }
      Json fileColumns = Json::array(); for (const auto &column : sampleEditorFileColumns) fileColumns.array_items().push_back(column);
      Json draft = object({{"columns", sampleEditorTable.get("columns")}, {"rows", sampleEditorTable.get("rows")},
          {"baseDirectory", sampleEditorTable.get("baseDirectory")}, {"delimiter", getstr(sampleEditorTable, "delimiter", ",")}, {"fileColumns", fileColumns}});
      if (draft.dump().size() > 1024 * 1024) throw std::runtime_error("This table exceeds the 1 MiB editor limit. No rows were truncated or saved. Reduce the table size or cancel to keep the original table.");
      sampleEditorIntent = id == SAMPLE_EDITOR_SAVE ? "save" : "use";
      sampleEditorPending = true;
      aux_text(view, SAMPLE_EDITOR_NOTICE, L"Validating the complete table. Nothing is queued or running...");
      Json request = object({{"table", draft}});
      if (!getstr(sampleTable, "table_token").empty()) request["retain_token"] = getstr(sampleTable, "table_token");
      send("sample/apply", request);
    }
    auxiliary_enabled();
  }
  void sample_editor_response(const std::string &method, const Json &response_) {
    sampleEditorPending = false;
    if (!response_.get("ok").boolean()) {
      const auto error = wt(response_, "error", "The sample table could not be read or saved.");
      aux_text(sampleEditorView, SAMPLE_EDITOR_NOTICE, error);
      MessageBoxW(sampleEditorView.window, error.c_str(), L"Sample table", MB_OK | MB_ICONERROR);
      auxiliary_enabled(); return;
    }
    const auto &result = response_.get("result");
    if (result.contains("retainedSelectionAvailable") && !result.get("retainedSelectionAvailable").boolean()) {
      sampleEditorRetentionNotice = wt(result, "retentionNotice",
          "The previous sample-table selection is no longer cached. Use this complete draft, or import the previous table again if you cancel.");
      // The complete draft is still usable. Do not offer preview/edit against a
      // missing original token if the user later cancels this editor.
      sampleTable["table_token"] = "";
      sample_invalidate();
      aux_text(sampleEditorView, SAMPLE_EDITOR_NOTICE, sampleEditorRetentionNotice);
      aux_text(samplesView, SAMPLE_NOTICE, sampleEditorRetentionNotice);
    }
    if (method == "sample/example" || method == "sample/save") {
      sampleEditorPending = true;
      if (method == "sample/save") { sampleEditorIntent = "saved"; sampleEditorSourcePath = getstr(result, "path"); }
      send("sample/edit", object({{"table_token", getstr(result, "table_token")}}));
    } else if (method == "sample/edit") {
      sampleEditorTable = result; sampleEditorFileColumns.clear();
      for (const auto &column : result.get("fileColumns").array_items()) sampleEditorFileColumns.insert(text(column));
      sampleEditorDirty = false; sample_editor_rows();
      aux_text(sampleEditorView, SAMPLE_EDITOR_NOTICE, !getstr(result, "exampleNotice").empty() ? wt(result, "exampleNotice") : sampleEditorIntent == "saved" ?
          L"Saved as a new table. File columns now contain absolute paths; other cells are unchanged. Use table to apply it to Samples." :
          L"Complete table loaded. Each row is one sample; map read 1 and read 2 separately after Use table. No replicate groups are inferred.");
      if (!sampleEditorRetentionNotice.empty()) aux_text(sampleEditorView, SAMPLE_EDITOR_NOTICE,
          control_text(aux(sampleEditorView, SAMPLE_EDITOR_NOTICE)) + L"\r\n" + sampleEditorRetentionNotice);
      if (GetForegroundWindow() == sampleEditorView.window) SetFocus(aux(sampleEditorView, SAMPLE_EDITOR_GRID));
    } else if (method == "sample/apply" && sampleEditorIntent == "save") {
      Json fileColumns = Json::array(); for (const auto &column : sampleEditorFileColumns) fileColumns.array_items().push_back(column);
      sampleEditorPending = true;
      Json request = object({{"table_token", getstr(result, "table_token")}, {"path", sampleEditorSavePath}, {"file_columns", fileColumns}});
      if (!getstr(sampleTable, "table_token").empty()) request["retain_token"] = getstr(sampleTable, "table_token");
      send("sample/save", request);
    } else if (method == "sample/apply" && sampleEditorIntent == "use") {
      if (samplesView.window && samplesView.generation == sampleEditorParentGeneration) {
        sampleTable = result; sampleLoadedPath = sampleEditorSourcePath;
        samplesView.rebuilding = true;
        aux_text(samplesView, SAMPLE_PATH, wide(sampleEditorSourcePath));
        samplesView.rebuilding = false;
        sample_table_rows();
        if (!sampleEditorRetentionNotice.empty()) aux_text(samplesView, SAMPLE_NOTICE,
            L"The previous cached selection expired. This edited table is now loaded. Check the mappings and preview the analyses again.");
      }
      sampleEditorDirty = false;
      DestroyWindow(sampleEditorView.window);
      if (samplesView.window) SetFocus(aux(samplesView, SAMPLE_TARGETS));
    }
    auxiliary_enabled();
  }
