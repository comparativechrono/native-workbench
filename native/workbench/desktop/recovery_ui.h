// Included inside Workspace: native recovery, resource and portable-project forms.
  Json resourceGraph = Json::object(), resourcePolicy = Json::object(),
       restartSummary = Json::object(), projectSummary = Json::object();
  std::vector<Json> resourceNodes;
  std::string restartRun, restartToken, projectToken;
  bool resourcePending = false, restartPending = false, projectPending = false, resourceError = false;

  bool recovery_method(const std::string &method) const {
    return method.rfind("resources/", 0) == 0 || method.rfind("restart/", 0) == 0 || method.rfind("project/", 0) == 0;
  }
  Auxiliary &auxiliary_view(int kind) {
    if (kind == SHOW_SAMPLES) return samplesView;
    if (kind == SHOW_QUEUE) return queueView;
    if (kind == SHOW_RESOURCES) return resourcesView;
    if (kind == SHOW_RESTART) return restartView;
    if (kind == SHOW_PROJECTS) return projectsView;
    return indexesView;
  }
  Auxiliary &auxiliary_method(const std::string &method) {
    if (method.rfind("sample/", 0) == 0) return samplesView;
    if (method.rfind("queue/", 0) == 0) return queueView;
    if (method.rfind("resources/", 0) == 0) return resourcesView;
    if (method.rfind("restart/", 0) == 0) return restartView;
    if (method.rfind("project/", 0) == 0) return projectsView;
    return indexesView;
  }
  int recovery_notice(const Auxiliary &view) const {
    return view.kind == SHOW_RESOURCES ? RESOURCE_NOTICE : view.kind == SHOW_RESTART ? RESTART_NOTICE : PROJECT_NOTICE;
  }
  int selected_row(const Auxiliary &view, int id) const {
    return aux(view, id) ? ListView_GetNextItem(aux(view, id), -1, LVNI_SELECTED) : -1;
  }
  long long positive_number(HWND control, const char *label) const {
    const auto value = narrow(control_text(control));
    if (value.empty() || value.size() > 6 || value.find_first_not_of("0123456789") != std::string::npos)
      throw std::runtime_error(std::string(label) + " must be a positive whole number.");
    const auto parsed = std::stoll(value);
    if (!parsed) throw std::runtime_error(std::string(label) + " must be a positive whole number.");
    return parsed;
  }
  void recovery_enabled(bool idle, bool) {
    const bool mutate = idle && !setupBusy && !setupActionPending && !packBusy && !packActionPending && !refBusy && !refActionPending;
    if (resourcesView.window) {
      for (int id : {RESOURCE_CPU, RESOURCE_PARALLEL, RESOURCE_TEMP, RESOURCE_BROWSE, RESOURCE_LIST, RESOURCE_APPLY})
        EnableWindow(aux(resourcesView, id), idle && !resourcePending);
      EnableWindow(aux(resourcesView, RESOURCE_APPLY), mutate && !resourcePending && !resourceError);
      for (int id : {RESOURCE_RESERVATION, RESOURCE_ASSIGN})
        EnableWindow(aux(resourcesView, id), idle && !resourcePending && selected_row(resourcesView, RESOURCE_LIST) >= 0);
    }
    if (restartView.window) {
      for (int id : {RESTART_REVIEW, RESTART_OUTPUT, RESTART_BROWSE})
        EnableWindow(aux(restartView, id), idle && !restartPending);
      EnableWindow(aux(restartView, RESTART_QUEUE), idle && !restartPending && !queuePreparing && !restartToken.empty());
    }
    if (projectsView.window) {
      aux_text(projectsView, PROJECT_EXPORT, showingHistory ? L"Export result..." : L"Export workflow...");
      for (int id : {PROJECT_ARCHIVE, PROJECT_BROWSE, PROJECT_INSPECT, PROJECT_OUTPUT, PROJECT_OUTPUT_BROWSE,
                     PROJECT_INCLUDE_DATA, PROJECT_EXPORT, PROJECT_OPEN})
        EnableWindow(aux(projectsView, id), idle && !projectPending);
      EnableWindow(aux(projectsView, PROJECT_OPEN), mutate && !projectPending && !analysis_active());
      const int row = selected_row(projectsView, PROJECT_LIST);
      for (int id : {PROJECT_PATH, PROJECT_MAP_BROWSE, PROJECT_MAP})
        EnableWindow(aux(projectsView, id), idle && !projectPending && row >= 0 && !projectToken.empty());
      EnableWindow(aux(projectsView, PROJECT_IMPORT), mutate && !projectPending && !projectToken.empty() &&
          projectSummary.get("ready").boolean() && !analysis_active());
    }
  }
  template<class Put> void recovery_layout(Auxiliary &view, int w, int h, Put put) {
    put(-1, 18, 12, w - 36, 58);
    if (view.kind == SHOW_RESOURCES) {
      put(-2, 18, 82, 170, 24); put(RESOURCE_CPU, 192, 78, 100, 30);
      put(-3, 330, 82, 180, 24); put(RESOURCE_PARALLEL, 514, 78, 100, 30);
      put(-4, 18, 122, w - 36, 22);
      put(RESOURCE_LIST, 18, 150, w - 36, std::max(70, h - 376));
      put(-5, 18, h - 214, 280, 24); put(RESOURCE_RESERVATION, 308, h - 220, 92, 30);
      put(RESOURCE_ASSIGN, 412, h - 220, 170, 30);
      put(-6, 18, h - 176, w - 36, 22);
      put(RESOURCE_TEMP, 18, h - 150, w - 168, 30); put(RESOURCE_BROWSE, w - 138, h - 150, 120, 30);
      put(RESOURCE_NOTICE, 18, h - 110, w - 36, 58);
      put(RESOURCE_APPLY, 18, h - 42, 200, 30); put(RESOURCE_CLOSE, w - 108, h - 42, 90, 30);
    } else if (view.kind == SHOW_RESTART) {
      put(RESTART_LIST, 18, 78, w - 36, std::max(84, h - 328));
      put(RESTART_DETAILS, 18, h - 240, w - 36, 92);
      put(RESTART_NOTICE, 18, h - 138, w - 36, 46);
      put(RESTART_OUTPUT, 18, h - 82, w - 190, 30); put(RESTART_BROWSE, w - 160, h - 82, 142, 30);
      put(RESTART_REVIEW, 18, h - 42, 154, 30); put(RESTART_QUEUE, 184, h - 42, 236, 30);
      put(RESTART_CLOSE, w - 108, h - 42, 90, 30);
    } else {
      put(PROJECT_ARCHIVE, 18, 76, w - 254, 30); put(PROJECT_BROWSE, w - 224, 76, 96, 30);
      put(PROJECT_INSPECT, w - 116, 76, 98, 30);
      put(PROJECT_LIST, 18, 116, w - 36, std::max(72, h - 398));
      put(PROJECT_PATH, 18, h - 272, w - 272, 30); put(PROJECT_MAP_BROWSE, w - 242, h - 272, 98, 30);
      put(PROJECT_MAP, w - 132, h - 272, 114, 30);
      put(PROJECT_DETAILS, 18, h - 232, w - 36, 78);
      put(PROJECT_NOTICE, 18, h - 144, w - 36, 40);
      put(PROJECT_OUTPUT, 18, h - 94, w - 206, 30); put(PROJECT_OUTPUT_BROWSE, w - 176, h - 94, 158, 30);
      put(PROJECT_INCLUDE_DATA, 18, h - 48, 196, 30); put(PROJECT_EXPORT, 226, h - 48, 150, 30);
      put(PROJECT_IMPORT, 388, h - 48, 160, 30); put(PROJECT_OPEN, 560, h - 48, 136, 30);
      put(PROJECT_CLOSE, w - 108, h - 48, 90, 30);
    }
  }
  template<class Label, class Action, class Edit, class List>
  void recovery_controls(Auxiliary &view, Label label, Action action, Edit edit, List list) {
    if (view.kind == SHOW_RESOURCES) {
      label(-1, L"Controls how many steps can run together. Match CPU reservations to each tool's thread setting. This does not limit CPU use inside a tool. Unknown steps run alone.");
      label(-2, L"Total CPU budget"); edit(RESOURCE_CPU, L"1", false);
      label(-3, L"Maximum parallel steps"); edit(RESOURCE_PARALLEL, L"1", false);
      label(-4, L"Reservations for the current workflow copy (blank means unknown)");
      list(RESOURCE_LIST); aux_columns(view, RESOURCE_LIST, {{L"Step", 340}, {L"CPU reservation", 190}, {L"Tool", 310}});
      label(-5, L"Selected step's CPU reservation"); edit(RESOURCE_RESERVATION, L"", false); action(RESOURCE_ASSIGN, L"Set reservation");
      label(-6, L"Temporary folder (blank uses the system default)"); edit(RESOURCE_TEMP, L"", false); action(RESOURCE_BROWSE, L"Browse...");
      edit(RESOURCE_NOTICE, L"Loading resource policy...", true); action(RESOURCE_APPLY, L"Save for future analyses"); action(RESOURCE_CLOSE, L"Close");
      resourceGraph = Json::object(); resourceNodes.clear(); resourcePolicy = Json::object(); resourceError = false;
      resourcePending = true; send("resources/get");
    } else if (view.kind == SHOW_RESTART) {
      label(-1, L"Restart checks completed products and their dependencies. Verified products may be copied into a new result; remaining steps run again. The original result is preserved.");
      list(RESTART_LIST); aux_columns(view, RESTART_LIST, {{L"Step", 270}, {L"Decision", 150}, {L"Reason", 450}});
      edit(RESTART_DETAILS, L"Reviewing the recorded analysis...", true);
      edit(RESTART_NOTICE, L"Checking identities and output hashes. Nothing is queued or running yet.", true);
      edit(RESTART_OUTPUT, control_text(output), false); action(RESTART_BROWSE, L"Output folder...");
      action(RESTART_REVIEW, L"Review again"); action(RESTART_QUEUE, L"Queue reviewed restart"); action(RESTART_CLOSE, L"Close");
      restartRun = showingHistory ? getstr(historyRun, "run_id") : runId;
      restartToken.clear(); restartSummary = Json::object(); restartPending = true;
      send("restart/review", object({{"run_id", restartRun}}));
    } else {
      label(-1, L"Export a portable workflow with exact requirements and optional input files. Inspect an archive before importing; map external files explicitly. Missing packs are never substituted.");
      edit(PROJECT_ARCHIVE, L"", false); action(PROJECT_BROWSE, L"Browse..."); action(PROJECT_INSPECT, L"Inspect");
      list(PROJECT_LIST); aux_columns(view, PROJECT_LIST, {{L"Required input", 300}, {L"Status", 180}, {L"File", 390}});
      edit(PROJECT_PATH, L"", false); action(PROJECT_MAP_BROWSE, L"Choose file..."); action(PROJECT_MAP, L"Map selected");
      edit(PROJECT_DETAILS, showingHistory ? L"Export source: the displayed recorded analysis, with its frozen workflow and sample metadata. Choose an archive above to inspect an import." : L"Export source: the current editable workflow. Choose an archive above to inspect its input and exact pack requirements.", true);
      edit(PROJECT_NOTICE, L"Import creates a new local project and opens its workflow as an editable draft. Nothing runs automatically.", true);
      edit(PROJECT_OUTPUT, L"", false); action(PROJECT_OUTPUT_BROWSE, L"New project folder...");
      aux_make(view, PROJECT_INCLUDE_DATA, L"BUTTON", L"Include input data", WS_TABSTOP | BS_AUTOCHECKBOX);
      action(PROJECT_EXPORT, showingHistory ? L"Export result..." : L"Export workflow..."); action(PROJECT_IMPORT, L"Import as new draft"); action(PROJECT_OPEN, L"Open project..."); action(PROJECT_CLOSE, L"Close");
      projectPending = false; projectToken.clear(); projectSummary = Json::object();
    }
  }
  void resource_rows() {
    int i = 0;
    for (const auto &node : resourceNodes) {
      const auto identity = getstr(node, "id");
      const auto cpus = resourcePolicy.get("stepCpus").get(identity);
      aux_row(aux(resourcesView, RESOURCE_LIST), i++, {wt(node, "name", identity), cpus.is_number() ? wide(cpus.dump()) : L"Unknown · runs alone", wt(node, "toolId", getstr(node, "tool"))});
    }
  }
  void recovery_selection(Auxiliary &view) {
    if (view.rebuilding) return;
    if (view.kind == SHOW_RESOURCES) {
      const int row = selected_row(view, RESOURCE_LIST);
      if (row >= 0 && static_cast<size_t>(row) < resourceNodes.size()) {
        const auto value = resourcePolicy.get("stepCpus").get(getstr(resourceNodes[row], "id"));
        aux_text(view, RESOURCE_RESERVATION, value.is_number() ? wide(value.dump()) : L"");
      }
    } else if (view.kind == SHOW_RESTART) {
      const int row = selected_row(view, RESTART_LIST);
      const auto &nodes = restartSummary.get("nodes").array_items();
      if (row >= 0 && static_cast<size_t>(row) < nodes.size())
        aux_text(view, RESTART_DETAILS, wt(nodes[row], "label", getstr(nodes[row], "id")) + L"\r\n" + wt(nodes[row], "reason"));
    } else {
      const int row = selected_row(view, PROJECT_LIST);
      const auto &entries = projectSummary.get("dependencies").array_items();
      if (row >= 0 && static_cast<size_t>(row) < entries.size()) {
        const auto &entry = entries[row];
        aux_text(view, PROJECT_DETAILS, project_requirements(projectSummary) + L"\r\n" + wt(entry, "label", getstr(entry, "filename", getstr(entry, "id"))) + L"\r\n" + wt(entry, "message") +
            L"\r\nSHA-256: " + wt(entry, "sha256") + L"\r\nBytes: " + wt(entry, "bytes"));
        aux_text(view, PROJECT_PATH, wt(entry, "resolved_path"));
      }
    }
    auxiliary_enabled();
  }
  std::wstring project_requirements(const Json &value) const {
    std::wstring result;
    if (value.get("packs").is_array()) for (const auto &pack : value.get("packs").array_items())
      result += L"Pack " + wt(pack.get("pin"), "packId") + L" " + wt(pack.get("pin"), "packVersion") + L": " + wt(pack, "status") + L" " + wt(pack, "message") + L"\r\n";
    if (value.get("warnings").is_array()) for (const auto &warning : value.get("warnings").array_items())
      result += wide(text(warning, getstr(warning, "message"))) + L"\r\n";
    return result;
  }
  void project_rows(const Json &value) {
    projectSummary = value; projectToken = getstr(value, "token");
    projectsView.rebuilding = true;
    ListView_DeleteAllItems(aux(projectsView, PROJECT_LIST));
    int i = 0;
    if (value.get("dependencies").is_array()) for (const auto &entry : value.get("dependencies").array_items())
      aux_row(aux(projectsView, PROJECT_LIST), i++, {wt(entry, "label", getstr(entry, "id")), wt(entry, "status"), wt(entry, "filename")});
    projectsView.rebuilding = false;
    aux_text(projectsView, PROJECT_DETAILS, project_requirements(value));
    aux_text(projectsView, PROJECT_NOTICE, value.get("ready").boolean() ?
        L"Required files and exact pack pins are available. Choose a new project folder, then import as a draft." :
        L"This project is not ready to import. Review the pack requirements and map missing files. No tool versions are substituted.");
  }
  std::wstring project_save_path() {
    IFileSaveDialog *dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileSaveDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog))))
      throw std::runtime_error("Windows could not create the project save dialog.");
    struct Release { IFileSaveDialog *p; ~Release() { p->Release(); } } release{dialog};
    FILEOPENDIALOGOPTIONS flags{}; dialog->GetOptions(&flags);
    dialog->SetOptions(flags | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR | FOS_OVERWRITEPROMPT);
    dialog->SetTitle(L"Save a new portable project archive"); dialog->SetDefaultExtension(L"nwproject.zip");
    dialog->SetFileName(L"native-workbench-project.nwproject.zip");
    const COMDLG_FILTERSPEC filter[] = {{L"Portable project archive", L"*.nwproject.zip"}};
    dialog->SetFileTypes(1, filter);
    const auto result = dialog->Show(projectsView.window);
    if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) return {};
    if (FAILED(result)) throw std::runtime_error("Windows could not select the project destination.");
    IShellItem *item = nullptr; if (FAILED(dialog->GetResult(&item))) throw std::runtime_error("Windows did not return a project destination.");
    PWSTR path = nullptr; const auto hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path); item->Release();
    if (FAILED(hr)) throw std::runtime_error("The project destination is not a local filesystem path.");
    std::wstring value(path); CoTaskMemFree(path); return value;
  }
  void recovery_command(Auxiliary &view, int id, int notification) {
    if (view.kind == SHOW_PROJECTS && id == PROJECT_ARCHIVE && notification == EN_CHANGE) {
      projectToken.clear(); projectSummary = Json::object(); view.rebuilding = true;
      ListView_DeleteAllItems(aux(view, PROJECT_LIST)); view.rebuilding = false;
      aux_text(view, PROJECT_NOTICE, L"Inspect this archive before mapping files or importing."); auxiliary_enabled(); return;
    }
    if (!ready || closing || activeRequest || !outgoing.empty()) return;
    if (view.kind == SHOW_RESOURCES && !resourcePending) {
      if (id == RESOURCE_BROWSE) {
        const auto path = pick(view.window, true, false, L"", L"Choose temporary storage", control_text(aux(view, RESOURCE_TEMP)));
        if (!path.empty()) aux_text(view, RESOURCE_TEMP, path);
      } else if (id == RESOURCE_ASSIGN) {
        const int row = selected_row(view, RESOURCE_LIST);
        if (row < 0 || static_cast<size_t>(row) >= resourceNodes.size()) return;
        const auto key = getstr(resourceNodes[row], "id");
        if (control_text(aux(view, RESOURCE_RESERVATION)).empty()) resourcePolicy["stepCpus"].object_items().erase(key);
        else resourcePolicy["stepCpus"][key] = positive_number(aux(view, RESOURCE_RESERVATION), "CPU reservation");
        resource_rows(); aux_text(view, RESOURCE_NOTICE, L"Reservation changed locally. Save for future analyses to apply this reviewed policy.");
      } else if (id == RESOURCE_APPLY) {
        resourcePolicy["cpuBudget"] = positive_number(aux(view, RESOURCE_CPU), "CPU budget");
        resourcePolicy["maxParallel"] = positive_number(aux(view, RESOURCE_PARALLEL), "Maximum parallel steps");
        resourcePolicy["temporaryFolder"] = narrow(control_text(aux(view, RESOURCE_TEMP)));
        resourcePending = true; send("resources/set", object({{"graph", resourceGraph}, {"policy", resourcePolicy}}));
      }
    } else if (view.kind == SHOW_RESTART && !restartPending) {
      if (id == RESTART_BROWSE) {
        const auto path = pick(view.window, true, false, L"", L"Choose the parent folder for restarted results", control_text(aux(view, RESTART_OUTPUT)));
        if (!path.empty()) aux_text(view, RESTART_OUTPUT, path);
      } else if (id == RESTART_REVIEW) {
        restartToken.clear(); restartPending = true;
        aux_text(view, RESTART_NOTICE, L"Rechecking completed products and their dependencies. Nothing is queued or running yet.");
        send("restart/review", object({{"run_id", restartRun}}));
      } else if (id == RESTART_QUEUE && !restartToken.empty()) {
        const auto token = restartToken; restartToken.clear(); restartPending = true;
        aux_text(view, RESTART_NOTICE, L"Freezing a new result from the reviewed restart. Start it explicitly in Analysis queue.");
        send("restart/queue", object({{"token", token}, {"output_folder", narrow(control_text(aux(view, RESTART_OUTPUT)))}}));
      }
    } else if (view.kind == SHOW_PROJECTS && !projectPending) {
      if (id == PROJECT_BROWSE) {
        const auto path = pick(view.window, false, false, L"Portable project archives|*.nwproject.zip|ZIP archives|*.zip|All files|*.*", L"Choose a portable project archive");
        if (!path.empty()) aux_text(view, PROJECT_ARCHIVE, path);
      } else if (id == PROJECT_INSPECT) {
        projectToken.clear(); projectPending = true;
        aux_text(view, PROJECT_NOTICE, L"Checking archive integrity, required files and exact pack versions...");
        send("project/inspect", object({{"path", narrow(control_text(aux(view, PROJECT_ARCHIVE)))}}));
      } else if (id == PROJECT_MAP_BROWSE) {
        const auto path = pick(view.window, false, false, L"All files|*.*", L"Choose the exact required input file", control_text(inputFolder));
        if (!path.empty()) aux_text(view, PROJECT_PATH, path);
      } else if (id == PROJECT_MAP && !projectToken.empty()) {
        const int row = selected_row(view, PROJECT_LIST);
        const auto &entries = projectSummary.get("dependencies").array_items();
        if (row < 0 || static_cast<size_t>(row) >= entries.size()) return;
        projectPending = true;
        aux_text(view, PROJECT_NOTICE, L"Verifying the selected file against the required checksum...");
        send("project/resolve", object({{"token", projectToken}, {"mappings", object({{getstr(entries[row], "id"), narrow(control_text(aux(view, PROJECT_PATH)))}})}}));
      } else if (id == PROJECT_OUTPUT_BROWSE) {
        const auto parent = pick(view.window, true, false, L"", L"Choose a parent for the new project folder", control_text(output));
        if (!parent.empty()) aux_text(view, PROJECT_OUTPUT, parent + L"\\Native Workbench project");
      } else if (id == PROJECT_OPEN) {
        const auto folder = pick(view.window, true, false, L"", L"Open an imported Native Workbench project", control_text(output));
        if (!folder.empty() && MessageBoxW(view.window, L"Open this project as the editable draft? Save your current draft first if you want to keep it. Nothing will run automatically.",
            L"Open portable project", MB_OKCANCEL | MB_ICONQUESTION) == IDOK) {
          projectPending = true;
          aux_text(view, PROJECT_NOTICE, L"Verifying the project files before opening its draft...");
          send("project/open", object({{"folder", narrow(folder)}}));
        }
      } else if (id == PROJECT_EXPORT) {
        commit_all(); projectPending = true;
        aux_text(view, PROJECT_NOTICE, L"Preparing an export review. No archive has been written yet.");
        Json request = object({{"include_data", SendMessageW(aux(view, PROJECT_INCLUDE_DATA), BM_GETCHECK, 0, 0) == BST_CHECKED}});
        if (showingHistory) request["run_id"] = getstr(historyRun, "run_id");
        send("project/export-preview", request);
      } else if (id == PROJECT_IMPORT && !projectToken.empty() && projectSummary.get("ready").boolean()) {
        if (MessageBoxW(view.window, L"Import this project into a new folder and replace the current editable draft? Save your draft first if you want to keep it. Nothing will run automatically.",
            L"Import portable project", MB_OKCANCEL | MB_ICONQUESTION) != IDOK) return;
        projectPending = true;
        aux_text(view, PROJECT_NOTICE, L"Importing the verified project. Closing this window does not cancel the import.");
        send("project/import", object({{"token", projectToken}, {"destination_folder", narrow(control_text(aux(view, PROJECT_OUTPUT)))}}));
      }
    }
    auxiliary_enabled();
  }
  void recovery_error(const std::string &method, const std::wstring &error) {
    Auxiliary &view = auxiliary_method(method);
    if (method.rfind("restart/", 0) == 0) restartToken.clear();
    if (method == "project/inspect" || method == "project/resolve" || method == "project/import") projectToken.clear();
    aux_text(view, recovery_notice(view), error);
    MessageBoxW(view.window ? view.window : window, error.c_str(), L"Native Workbench", MB_OK | MB_ICONERROR);
  }
  void recovery_response(const std::string &method, const Json &result) {
    if (method.rfind("resources/", 0) == 0) {
      if (method == "resources/get") {
        resourceGraph = state.get("graph"); resourceNodes.clear();
        for (const auto &node : resourceGraph.get("nodes").array_items()) resourceNodes.push_back(node);
      }
      resourcePolicy = result.get("policy"); resourceError = !getstr(result, "error").empty();
      aux_text(resourcesView, RESOURCE_CPU, wt(resourcePolicy, "cpuBudget", "1"));
      aux_text(resourcesView, RESOURCE_PARALLEL, wt(resourcePolicy, "maxParallel", "1"));
      aux_text(resourcesView, RESOURCE_TEMP, wt(resourcePolicy, "temporaryFolder"));
      resource_rows();
      aux_text(resourcesView, RESOURCE_NOTICE, resourceError ? wt(result, "error") :
          (method == "resources/set" ? L"Saved. " : L"") + wt(result, "notice") + L" Logical CPUs: " + wt(result, "logical_cpus") +
          L"\r\nReservations apply only to this exact workflow copy. Edits require another review. Already queued plans are unchanged.");
    } else if (method == "restart/review") {
      restartSummary = result; restartToken = getstr(result, "token");
      ListView_DeleteAllItems(aux(restartView, RESTART_LIST)); int i = 0;
      if (result.get("nodes").is_array()) for (const auto &node : result.get("nodes").array_items())
        aux_row(aux(restartView, RESTART_LIST), i++, {wt(node, "label", getstr(node, "id")), wt(node, "action"), wt(node, "reason")});
      aux_text(restartView, RESTART_DETAILS, L"Source analysis: " + wide(restartRun) + L"\r\nVerified reuse: " + wt(result, "reuse_count") + L"; run again: " + wt(result, "rerun_count") + L"\r\n" + wt(result, "notice"));
      aux_text(restartView, RESTART_NOTICE, L"Review each step's decision. Queue creates a new result and rechecks identities before reuse; it does not start execution.");
    } else if (method == "restart/queue") {
      restartToken.clear(); queue_response(result); show_auxiliary(SHOW_QUEUE);
      aux_text(restartView, RESTART_NOTICE, L"Restart queued as a new result. Use Start queued in Analysis queue when ready.");
    } else if (method == "project/inspect" || method == "project/resolve") project_rows(result);
    else if (method == "project/export-preview") {
      Modal review_; review_.owner = projectsView.window; review_.font = projectsView.font;
      review_.mode = 2; review_.title = L"Review portable project export";
      review_.message = L"Review the exact requirements and included data before choosing a new archive path. Nothing is uploaded.";
      review_.value = L"Project: " + wt(result, "name") + L"\r\nSource: " + wt(result, "source") +
          L"\r\nIncluded input data: " + wt(result, "includedBytes", "0") + L" bytes\r\n" + project_requirements(result);
      if (result.get("sampleMetadataIncluded").boolean())
        review_.value += L"\r\nSample metadata: " + wide(result.get("sample_metadata").dump()) + L"\r\n" + wt(result, "metadata_notice");
      if (result.get("dependencies").is_array()) for (const auto &entry : result.get("dependencies").array_items())
        review_.value += L"\r\n" + wt(entry, "label", getstr(entry, "id")) + L": " + wt(entry, "filename") + L" · " +
            (entry.get("included").boolean() ? L"included" : L"external requirement") + L"\r\nSHA-256: " + wt(entry, "sha256");
      review_.confirm = L"Choose path...";
      if (review_.show()) {
        const auto path = project_save_path();
        if (!path.empty()) {
          projectPending = true;
          aux_text(projectsView, PROJECT_NOTICE, L"Writing the reviewed archive. Closing this window does not cancel the export.");
          send("project/export", object({{"token", getstr(result, "token")}, {"destination", narrow(path)}}));
        }
      }
    } else if (method == "project/export") {
      aux_text(projectsView, PROJECT_NOTICE, L"Project archive saved: " + wt(result, "path"));
      aux_text(projectsView, PROJECT_DETAILS, L"Archive SHA-256: " + wt(result, "sha256") + L"\r\nBytes: " + wt(result, "bytes"));
    } else if (method == "project/import" || method == "project/open") {
      if (result.contains("model")) {
        showingHistory = false; historyRun = Json::object(); snapshot(result.get("model")); canvas_reset_positions();
      }
      projectToken.clear();
      aux_text(projectsView, PROJECT_NOTICE, result.get("model_loaded").boolean(true) ?
          L"Project opened locally as an editable draft. No analysis was started." : wt(result, "notice"));
      aux_text(projectsView, PROJECT_DETAILS, L"Project folder: " + wt(result, "folder"));
    }
  }
