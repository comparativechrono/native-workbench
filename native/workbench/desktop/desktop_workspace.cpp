#include "desktop_ipc.h"
#include "record_list.h"
#include "workspace_layout.h"
#include "library_text_layout.h"
#include "resource.h"
#include "dag_routing.h"
#include "workbench.h"
#include <algorithm>
#include <commctrl.h>
#include <climits>
#include <cstdlib>
#include <cwctype>
#include <deque>
#include <gdiplus.h>
#include <iomanip>
#include <map>
#include <memory>
#include <objidl.h>
#include <set>
#include <shellapi.h>
#include <shobjidl.h>
#include <sstream>
#include <uxtheme.h>
#include <vssym32.h>
#include <windowsx.h>

namespace {
using desktop::Json;
constexpr UINT HOST_MESSAGE = WM_APP + 35;
constexpr COLORREF BACK = RGB(246, 247, 248), PAPER = RGB(255, 255, 255),
                   INK = RGB(32, 44, 62), MUTED = RGB(98, 112, 132),
                   BORDER = RGB(198, 206, 214), ACCENT = RGB(43, 88, 122),
                   NAVY = RGB(44, 49, 67);
enum {
  NAME = 101,
  SEARCH,
  TASKS = 104,
  ADD,
  STEPS,
  REMOVE,
  UNDO,
  UP,
  DOWN,
  OUTPUT,
  BROWSE_OUTPUT,
  RUN,
  CANCEL,
  REVIEW,
  BACK_WORKSPACE,
  DAG,
  FORM,
  STATUS,
  FILE_NEW = 301,
  FILE_EXAMPLE,
  FILE_SAVE_PIPELINE,
  FILE_SAVE_PRESET,
  FILE_LOAD,
  FILE_HISTORY,
  FILE_IMPORT,
  FILE_CHECK,
  FILE_EXIT,
  VIEW_LOG,
  VIEW_METHODS,
  OPEN_RESULTS,
  CLEAR_FILTER = 401,
  MANAGE_TOOLS,
  MANAGE_REFERENCES,
  MODE_TOOLS = 410,
  MODE_WORKFLOW,
  GENERAL_SETTINGS,
  INPUT_FOLDER,
  BROWSE_INPUT,
  SAVE_CURRENT,
  LOAD_CURRENT,
  RESULTS_LIST,
  RESET_LAYOUT,
  ADD_INPUT,
  ZOOM_OUT,
  ZOOM_IN,
  ZOOM_RESET,
  REVIEW_DIAGNOSTICS,
  SHOW_SAMPLES,
  SHOW_QUEUE,
  SHOW_INDEXES,
  SHOW_RESOURCES, SHOW_RESTART, SHOW_PROJECTS,
  LIBRARY_VIEWPORT = 430,
  PACK_SEARCH = 501,
  PACK_FILTER,
  PACK_LIST,
  PACK_DETAILS,
  PACK_INSTALL,
  PACK_IMPORT_ZIP,
  PACK_IMPORT_FOLDER,
  PACK_SOURCE,
  PACK_REFRESH,
  PACK_CANCEL,
  PACK_PROGRESS,
  PACK_NOTICE,
  PACK_CLOSE,
  REF_TAB = 601,
  REF_RELEASE,
  REF_QUERY,
  REF_SEARCH,
  REF_SPECIES,
  REF_DISCOVER,
  REF_FILES,
  REF_DETAILS,
  REF_DESTINATION,
  REF_BROWSE,
  REF_DOWNLOAD,
  REF_LOCAL,
  REF_TARGET,
  REF_USE,
  REF_OPEN,
  REF_CANCEL,
  REF_PROGRESS,
  REF_NOTICE,
  REF_CLOSE,
  REF_PROVIDER, REF_PENDING, REF_RESUME, REF_DISCARD, REF_PAUSE,
  REF_IMPORT_PREVIEW, REF_RELOCATE, REF_REVIEW,
  REF_IMPORT_PATH = 660, REF_IMPORT_BROWSE = 665, REF_IMPORT_METADATA = 670,
  TOOL_SETUP = 701,
  SETUP_FULL,
  SETUP_STARTER,
  SETUP_CUSTOM,
  SETUP_LIST,
  SETUP_TOTAL,
  SETUP_NOTICE,
  SETUP_PROGRESS,
  SETUP_REFRESH,
  SETUP_INSTALL,
  SETUP_RETRY,
  SETUP_CANCEL,
  SETUP_CLOSE,
  PACK_SETUP,
  SAMPLE_PATH = 801,
  SAMPLE_BROWSE, SAMPLE_LOAD, SAMPLE_TARGETS, SAMPLE_COLUMN, SAMPLE_SHARED,
  SAMPLE_PREVIEW, SAMPLE_ROWS, SAMPLE_NOTICE, SAMPLE_OUTPUT, SAMPLE_OUTPUT_BROWSE,
  SAMPLE_QUEUE, SAMPLE_CLOSE,
  SAMPLE_MODE, SAMPLE_NEW, SAMPLE_EDIT, SAMPLE_EXAMPLE,
  QUEUE_LIST = 901,
  QUEUE_DETAILS, QUEUE_ADD, QUEUE_START, QUEUE_PAUSE, QUEUE_CANCEL,
  QUEUE_RESULTS, QUEUE_NOTICE, QUEUE_CLOSE,
  INDEX_LIST = 1001,
  INDEX_DETAILS, INDEX_REFRESH, INDEX_VERIFY, INDEX_NOTICE, INDEX_CLOSE,
  RESOURCE_CPU = 1101, RESOURCE_PARALLEL, RESOURCE_TEMP, RESOURCE_BROWSE,
  RESOURCE_LIST, RESOURCE_RESERVATION, RESOURCE_ASSIGN, RESOURCE_NOTICE, RESOURCE_APPLY, RESOURCE_CLOSE,
  RESTART_LIST = 1201, RESTART_DETAILS, RESTART_OUTPUT, RESTART_BROWSE, RESTART_REVIEW, RESTART_QUEUE, RESTART_NOTICE, RESTART_CLOSE,
  PROJECT_ARCHIVE = 1301, PROJECT_BROWSE, PROJECT_INSPECT, PROJECT_LIST, PROJECT_PATH, PROJECT_MAP_BROWSE,
  PROJECT_MAP, PROJECT_DETAILS, PROJECT_OUTPUT, PROJECT_OUTPUT_BROWSE, PROJECT_INCLUDE_DATA, PROJECT_EXPORT,
  PROJECT_IMPORT, PROJECT_NOTICE, PROJECT_CLOSE, PROJECT_OPEN,
  CURATED_LIST = 1401, CURATED_DETAILS, CURATED_LOAD, CURATED_SETUP,
  CURATED_REFRESH, CURATED_NOTICE, CURATED_CLOSE,
  SHOW_CURATED = 1430, SHOW_RESULTS, VIEW_RESULT_SUMMARY,
  RESULTS_QUERY = 1501, RESULTS_SEARCH, RESULTS_RUNS, RESULTS_DETAILS,
  RESULTS_VIEW, RESULTS_OPEN, RESULTS_NOTICE, RESULTS_CLOSE,
  SHOW_SAMPLE_EDITOR = 1590,
  SAMPLE_EDITOR_GRID = 1601, SAMPLE_EDITOR_COLUMN, SAMPLE_EDITOR_VALUE, SAMPLE_EDITOR_FILE,
  SAMPLE_EDITOR_FILE_COLUMN, SAMPLE_EDITOR_BASE, SAMPLE_EDITOR_BASE_BROWSE,
  SAMPLE_EDITOR_ADD_ROW, SAMPLE_EDITOR_REMOVE_ROW, SAMPLE_EDITOR_ADD_COLUMN,
  SAMPLE_EDITOR_RENAME_COLUMN, SAMPLE_EDITOR_REMOVE_COLUMN, SAMPLE_EDITOR_SAVE,
  SAMPLE_EDITOR_USE, SAMPLE_EDITOR_CANCEL, SAMPLE_EDITOR_NOTICE,
  FIELD_BASE = 2000
};
std::wstring wide(const std::string &s) { return bw::utf16(s); }
std::string narrow(const std::wstring &s) { return bw::utf8(s); }
std::string text(const Json &j, const std::string &fallback = {}) {
  if (j.is_string())
    return j.string();
  if (j.is_bool() || j.is_number())
    return j.dump();
  return fallback;
}
std::string getstr(const Json &j, const char *key,
                   const std::string &fallback = {}) {
  return text(j.get(key), fallback);
}
std::wstring wt(const Json &j, const char *key,
                const std::string &fallback = {}) {
  return wide(getstr(j, key, fallback));
}
std::wstring control_text(HWND h) {
  const int n = GetWindowTextLengthW(h);
  std::wstring out(static_cast<size_t>(n) + 1, L'\0');
  int got = GetWindowTextW(h, out.data(), n + 1);
  out.resize(std::max(0, got));
  return out;
}
std::wstring lower(std::wstring s) {
  for (auto &c : s)
    c = static_cast<wchar_t>(std::towlower(c));
  return s;
}
std::string display_id(const std::string &id) {
  auto p = id.find('-');
  return (id.rfind("step-", 0) == 0 ? "S" : "I") +
         (p == id.npos ? id : id.substr(p + 1));
}
std::wstring quote(const std::wstring &arg) {
  std::wstring out = L"\"";
  size_t n = 0;
  for (wchar_t c : arg) {
    if (c == L'\\') {
      ++n;
      continue;
    }
    out.append(c == L'"' ? n * 2 + 1 : n, L'\\');
    out += c;
    n = 0;
  }
  out.append(n * 2, L'\\');
  return out + L'"';
}
Json object(std::initializer_list<std::pair<const std::string, Json>> values) {
  return Json(Json::Object(values));
}
std::wstring lines(std::wstring s) {
  std::wstring r;
  for (wchar_t c : s) {
    if (c == L'\n')
      r += L'\r';
    if (c != L'\r')
      r += c;
  }
  return r;
}
void rounded(Gdiplus::Graphics &g, float x, float y, float w, float h,
             float radius, COLORREF fill, COLORREF stroke = BORDER) {
  if (w <= 0 || h <= 0)
    return;
  Gdiplus::GraphicsPath p;
  float d = std::min({radius * 2, w, h});
  p.AddArc(x, y, d, d, 180, 90);
  p.AddArc(x + w - d, y, d, d, 270, 90);
  p.AddArc(x + w - d, y + h - d, d, d, 0, 90);
  p.AddArc(x, y + h - d, d, d, 90, 90);
  p.CloseFigure();
  Gdiplus::SolidBrush b(
      Gdiplus::Color(255, GetRValue(fill), GetGValue(fill), GetBValue(fill)));
  g.FillPath(&b, &p);
  Gdiplus::Pen pen(Gdiplus::Color(255, GetRValue(stroke), GetGValue(stroke),
                                  GetBValue(stroke)));
  g.DrawPath(&pen, &p);
}
std::wstring pick(HWND owner, bool folder, bool multiple,
                  const std::wstring &filter, const std::wstring &title,
                  const std::wstring &initialFolder = {}) {
  IFileOpenDialog *raw = nullptr;
  HRESULT hr = CoCreateInstance(CLSID_FileOpenDialog, nullptr,
                                CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&raw));
  if (FAILED(hr))
    throw std::runtime_error("Windows could not create the file picker.");
  struct Release {
    IFileOpenDialog *p;
    ~Release() { p->Release(); }
  } release{raw};
  FILEOPENDIALOGOPTIONS flags{};
  raw->GetOptions(&flags);
  hr = raw->SetOptions(flags | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST |
                       FOS_NOCHANGEDIR |
                       (folder ? FOS_PICKFOLDERS : FOS_FILEMUSTEXIST) |
                       (multiple ? FOS_ALLOWMULTISELECT : 0));
  if (FAILED(hr))
    throw std::runtime_error("Windows could not configure the file picker.");
  raw->SetTitle(title.c_str());
  if (!initialFolder.empty()) {
    IShellItem *start = nullptr;
    if (SUCCEEDED(SHCreateItemFromParsingName(initialFolder.c_str(), nullptr,
                                             IID_PPV_ARGS(&start)))) {
      raw->SetFolder(start);
      start->Release();
    }
  }
  std::vector<std::wstring> parts;
  std::vector<COMDLG_FILTERSPEC> specs;
  if (!folder && !filter.empty()) {
    size_t pos = 0;
    for (;;) {
      auto end = filter.find(L'|', pos);
      parts.push_back(
          filter.substr(pos, end == filter.npos ? filter.npos : end - pos));
      if (end == filter.npos)
        break;
      pos = end + 1;
    }
    if (parts.size() % 2 == 0)
      for (size_t i = 0; i < parts.size(); i += 2)
        specs.push_back({parts[i].c_str(), parts[i + 1].c_str()});
    if (!specs.empty())
      raw->SetFileTypes(static_cast<UINT>(specs.size()), specs.data());
  }
  hr = raw->Show(owner);
  if (hr == HRESULT_FROM_WIN32(ERROR_CANCELLED))
    return {};
  if (FAILED(hr))
    throw std::runtime_error("The file picker failed.");
  IShellItemArray *items = nullptr;
  hr = raw->GetResults(&items);
  if (FAILED(hr))
    throw std::runtime_error("Could not read selected paths.");
  struct RI {
    IShellItemArray *p;
    ~RI() { p->Release(); }
  } ri{items};
  DWORD count = 0;
  items->GetCount(&count);
  std::wstring out;
  for (DWORD i = 0; i < count; ++i) {
    IShellItem *item = nullptr;
    if (FAILED(items->GetItemAt(i, &item)))
      continue;
    PWSTR p = nullptr;
    hr = item->GetDisplayName(SIGDN_FILESYSPATH, &p);
    item->Release();
    if (FAILED(hr))
      continue;
    if (!out.empty())
      out += L'\n';
    out += p;
    CoTaskMemFree(p);
  }
  return out;
}
void clipboard(HWND owner, const std::wstring &value) {
  if (!OpenClipboard(owner))
    return;
  EmptyClipboard();
  const size_t bytes = (value.size() + 1) * sizeof(wchar_t);
  HGLOBAL mem = GlobalAlloc(GMEM_MOVEABLE, bytes);
  if (mem) {
    void *p = GlobalLock(mem);
    if (p) {
      memcpy(p, value.c_str(), bytes);
      GlobalUnlock(mem);
      if (!SetClipboardData(CF_UNICODETEXT, mem))
        GlobalFree(mem);
    } else
      GlobalFree(mem);
  }
  CloseClipboard();
}

struct Modal {
  HWND owner{}, window{}, body{}, ok{};
  HFONT font{};
  int mode = 0;
  bool multiple = false, accepted = false;
  std::wstring title, message, value, confirm = L"OK";
  std::vector<std::wstring> labels;
  std::vector<int> selected;
  UINT dpi = 96;
  int px(int n) const { return MulDiv(n, static_cast<int>(dpi), 96); }
  static LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *s = reinterpret_cast<Modal *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      s = static_cast<Modal *>(
          reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      s->window = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(s));
    }
    if (!s)
      return DefWindowProcW(h, m, w, l);
    if (m == WM_COMMAND) {
      if (LOWORD(w) == IDOK) {
        s->accepted = true;
        if (s->mode == 1)
          s->value = control_text(s->body);
        if (s->mode == 0) {
          s->selected.clear();
          if (s->multiple) {
            int n =
                static_cast<int>(SendMessageW(s->body, LB_GETSELCOUNT, 0, 0));
            if (n > 0) {
              s->selected.resize(static_cast<size_t>(n));
              SendMessageW(s->body, LB_GETSELITEMS, n,
                           reinterpret_cast<LPARAM>(s->selected.data()));
            }
          } else {
            int n = static_cast<int>(SendMessageW(s->body, LB_GETCURSEL, 0, 0));
            if (n >= 0)
              s->selected.push_back(n);
          }
        }
        DestroyWindow(h);
        return 0;
      }
      if (LOWORD(w) == IDCANCEL) {
        DestroyWindow(h);
        return 0;
      }
      if (LOWORD(w) == 103) {
        clipboard(h, control_text(s->body));
        return 0;
      }
      if (HIWORD(w) == LBN_DBLCLK && !s->multiple) {
        SendMessageW(h, WM_COMMAND, IDOK, 0);
        return 0;
      }
    }
    if (m == WM_SIZE) {
      RECT r{};
      GetClientRect(h, &r);
      MoveWindow(s->body, s->px(18), s->px(48),
                 std::max<int>(1, r.right - s->px(36)),
                 std::max<int>(s->px(30), r.bottom - s->px(110)), TRUE);
      MoveWindow(s->ok, r.right - s->px(250), r.bottom - s->px(48), s->px(130),
                 s->px(32), TRUE);
      MoveWindow(GetDlgItem(h, IDCANCEL), r.right - s->px(108),
                 r.bottom - s->px(48), s->px(90), s->px(32), TRUE);
      if (s->mode == 2)
        MoveWindow(GetDlgItem(h, 103), s->px(18), r.bottom - s->px(48),
                   s->px(130), s->px(32), TRUE);
      return 0;
    }
    if (m == WM_CLOSE) {
      DestroyWindow(h);
      return 0;
    }
    return DefWindowProcW(h, m, w, l);
  }
  bool show() {
    HINSTANCE inst = GetModuleHandleW(nullptr);
    WNDCLASSEXW wc{sizeof(wc)};
    wc.lpfnWndProc = proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    wc.lpszClassName = L"WorkbenchNativeModal051";
    RegisterClassExW(&wc);
    dpi = GetDpiForWindow(owner);
    RECT r{};
    GetWindowRect(owner, &r);
    const int width = px(mode == 1 ? 560 : 720),
              height = px(mode == 1 ? 225 : 530);
    window = CreateWindowExW(
        WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, wc.lpszClassName,
        title.c_str(), WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME,
        r.left + std::max<LONG>(0, (r.right - r.left - width) / 2),
        r.top + std::max<LONG>(0, (r.bottom - r.top - height) / 2), width,
        height, owner, nullptr, inst, this);
    if (!window)
      return false;
    auto control = [&](const wchar_t *klass, const wchar_t *content,
                       DWORD style, int id) {
      HWND h = CreateWindowExW(
          0, klass, content, WS_CHILD | WS_VISIBLE | style, 0, 0, 1, 1, window,
          reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), inst, nullptr);
      SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(font), FALSE);
      return h;
    };
    HWND label = control(L"STATIC", message.c_str(), 0, 104);
    MoveWindow(label, px(18), px(15), width - px(44), px(30), FALSE);
    if (mode == 0) {
      body = control(L"LISTBOX", L"",
                     WS_TABSTOP | WS_VSCROLL | WS_HSCROLL | LBS_NOTIFY |
                         (multiple ? LBS_EXTENDEDSEL : 0) | WS_BORDER,
                     105);
      for (auto &item : labels)
        SendMessageW(body, LB_ADDSTRING, 0,
                     reinterpret_cast<LPARAM>(item.c_str()));
      for (int n : selected)
        SendMessageW(body, multiple ? LB_SETSEL : LB_SETCURSEL,
                     multiple ? TRUE : n, multiple ? n : 0);
    } else {
      body = control(L"EDIT", lines(value).c_str(),
                     WS_TABSTOP | WS_BORDER |
                         (mode == 2 ? ES_MULTILINE | ES_READONLY |
                                          ES_AUTOVSCROLL | WS_VSCROLL
                                    : ES_AUTOHSCROLL),
                     105);
      if (mode == 2) {
        SendMessageW(body, EM_SETLIMITTEXT, 8 * 1024 * 1024, 0);
        SetWindowTextW(body, lines(value).c_str());
      }
    }
    ok = control(L"BUTTON", confirm.c_str(), WS_TABSTOP | BS_DEFPUSHBUTTON,
                 IDOK);
    control(L"BUTTON", mode == 2 ? L"Close" : L"Cancel", WS_TABSTOP, IDCANCEL);
    if (mode == 2)
      control(L"BUTTON", L"Copy text", WS_TABSTOP, 103);
    SendMessageW(window, WM_SIZE, 0, 0);
    EnableWindow(owner, FALSE);
    ShowWindow(window, SW_SHOW);
    SetFocus(body);
    MSG msg{};
    while (IsWindow(window) && GetMessageW(&msg, nullptr, 0, 0) > 0) {
      if (!IsDialogMessageW(window, &msg)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
      }
    }
    EnableWindow(owner, TRUE);
    SetForegroundWindow(owner);
    return accepted;
  }
};

class Workspace {
  struct Field {
    HWND h{}, button{};
    std::string kind, key, node, source, port;
    Json schema;
    std::wstring initial;
    int y = 0, height = 34;
  };
  struct Hit {
    RECT box;
    std::string id;
    bool source = false;
  };
  HINSTANCE instance{};
  HICON appIcon{}, appSmallIcon{};
  ATOM appWindowClass{}, appSurfaceClass{}, appLibraryViewportClass{};
  HWND window{}, name{}, search{}, tasks{}, add{}, clearFilter{},
      steps{}, remove{}, undo{}, up{}, down{}, output{}, browse{}, run{},
      cancel{}, review{}, back{}, dag{}, form{}, status{}, manageTools{},
      packWindow{}, packSearch{}, packFilter{}, packList{}, packDetails{},
      packInstall{}, packImportZip{}, packImportFolder{}, packSource{},
      packRefresh{}, packCancel{}, packProgress{}, packNotice{}, packClose{},
      manageReferences{}, refWindow{}, refTab{}, refIntro{}, refReleaseLabel{},
      refRelease{}, refQuery{}, refSearch{}, refSpecies{}, refDiscover{},
      refFiles{}, refDetails{}, refDestinationLabel{}, refDestination{},
      refBrowse{}, refDownload{}, refLocal{}, refTargetLabel{}, refTarget{},
      refUse{}, refOpen{}, refCancel{}, refProgress{}, refNotice{}, refClose{},
      refProviderLabel{}, refProvider{}, refPending{}, refResume{}, refDiscard{},
      refPause{}, refImportPreview{}, refRelocate{}, refReviewButton{};
  std::vector<HWND> refImportPaths, refImportBrowse, refImportLabels,
      refImportMetadata, refImportMetadataLabels;
  HWND modeTools{}, modeWorkflow{}, generalSettings{}, inputFolder{}, browseInput{},
      saveCurrent{}, loadCurrent{}, resultsList{}, resetLayout{}, toolsHeading{},
      centerHeading{}, rightHeading{}, nameLabel{}, inputLabel{}, inputHelp{},
      outputLabel{}, outputHelp{}, referenceHelp{}, generalPanel{};
  HWND addInput{}, zoomOut{}, zoomIn{}, zoomReset{}, libraryViewport{};
  HWND samplesButton{}, queueButton{};
  struct Auxiliary {
    Workspace *app = nullptr;
    int kind = 0;
    HWND window{};
    UINT dpi = 96;
    HFONT font{};
    std::map<int, HWND> controls;
    bool rebuilding = false;
    unsigned generation = 0;
  } samplesView, queueView, indexesView, resourcesView, restartView, projectsView,
    curatedView, resultsView;
  Json sampleGraph = Json::object(), sampleTable = Json::object(),
       sampleTargets = Json::array(), sampleTargetSchema = Json::object(), samplePreview = Json::object(),
       queueState = Json::object(), indexState = Json::object();
  std::vector<std::string> sampleColumns;
  std::map<size_t, std::string> sampleMappings;
  std::set<std::string> sampleSharedSources;
  std::map<std::string, Json> verifiedIndexes;
  std::string queueRendered, sampleToken;
  bool samplePending = false, queuePending = false, queuePollPending = false,
       queuePollFailed = false, indexPending = false, queuePreparing = false, queueRunning = false;
  ULONGLONG lastQueuePoll = 0;
  HWND setupWindow{}, setupIntro{}, setupFull{}, setupStarter{}, setupCustom{},
      setupHelp{}, setupList{}, setupTotal{}, setupNotice{}, setupProgress{},
      setupRefresh{}, setupInstall{}, setupRetry{}, setupCancel{}, setupClose{}, packSetup{};
  int generalScroll = 0;
  int generalWheelRemainder = 0, formWheelRemainder = 0;
  HFONT font{}, bold{}, small{}, libraryBold{};
  HFONT refFont{};
  HBRUSH paper{}, background{};
  desktop::HostProcess host;
  Json state = Json::object(), catalog = object({{"tools", Json::object()}}),
       runState = Json::object(), historyRun = Json::object(),
       packState = object({{"packs", Json::array()}, {"sources", Json::array()},
                           {"errors", Json::array()}}),
       packOperation = Json::object(),
       refState = object({{"providers", Json::array()}, {"pending", Json::array()},
                          {"releases", Json::array()}, {"species", Json::array()},
                          {"local", Json::array()}, {"discovery", nullptr}}),
       refOperation = Json::object(), refTargets = Json::array(), refReview = Json::object();
  Json setupState = object({{"rows", Json::array()}, {"operation", Json::object()}});
  std::map<long long, std::string> pending;
  std::map<long long, unsigned> pendingViews;
  std::map<long long, std::string> pendingIndexVerifications;
  std::set<long long> concurrentRequests;
  long long nextRequest = 1, activeRequest = 0;
  std::deque<Json> outgoing;
  std::string submittedFields;
  ULONGLONG closeStarted = 0;
  bool rebuilding = false, ready = false, busy = false, closing = false,
       reviewThenRun = false, showingHistory = false, autoCheck = false;
  bool workflowMode = false, generalVisible = false, pendingCanvasDrop = false;
  POINT canvasDropPoint{};
  std::set<std::string> canvasDropExisting;
  bool packBusy = false, packActionPending = false, packPollPending = false,
       packRebuilding = false, packReloadAfterOperation = false,
       packListAfterOperation = false, packPollFailed = false;
  bool refBusy = false, refActionPending = false, refPollPending = false,
       refRebuilding = false, refPollFailed = false, refReviewOpen = false;
  bool setupBusy = false, setupActionPending = false, setupPollPending = false,
       setupRebuilding = false, setupPollFailed = false, setupWelcomeChecked = false,
       setupSelectionLoaded = false;
  std::string setupProfile = "full";
  Json setupRenderedRows = Json::array();
  std::set<std::string> setupChosen;
  UINT setupDpi = 96;
  UINT dpi = 96;
  UINT packDpi = 96;
  UINT refDpi = 96;
  int width = 1000, height = 700, formScroll = 0, formExtent = 0, dagX = 0,
      dagY = 0, dagWidth = 1, dagHeight = 1;
  std::vector<Field> fields;
  std::vector<HWND> formControls;
  std::map<int, size_t> fieldIds;
  struct LibraryRow {
    std::wstring category, label, description, accessible;
    std::string toolId;
    std::vector<std::wstring> titleLines, descriptionLines;
    int titleLineHeight = 0, descriptionLineHeight = 0, height = 30;
    std::string key() const {
      return toolId.empty() ? "category:" + narrow(category) : "tool:" + toolId;
    }
    bool operator==(const LibraryRow &other) const {
      return category == other.category && label == other.label &&
          description == other.description && toolId == other.toolId;
    }
  };
  struct LibraryView { std::string selected, first; int offset = 0; };
  std::vector<LibraryRow> libraryRows;
  std::map<std::string, HTREEITEM> libraryItems;
  std::map<std::wstring, bool> libraryExpanded;
  std::map<bool, LibraryView> libraryViews;
  bool libraryFiltered = false, libraryWorkflow = false, libraryRendered = false;
  std::wstring libraryQuery;
  std::string librarySource, libraryInspectorTool;
  int libraryLayoutWidth = -1;
  bool libraryHighContrast = false;
  struct LibraryPosition { HTREEITEM item; int top, height; };
  std::vector<LibraryPosition> libraryVisible;
  int libraryScroll = 0, libraryExtent = 0, libraryLargestRow = 0,
      libraryWheelRemainder = 0;
  bool libraryPlacing = false, libraryExpanding = false;
  int libraryPlacedWidth = -1, libraryPlacedHeight = -1, libraryPlacedScroll = -1;
  unsigned libraryGeometry = 0, libraryPlacedGeometry = ~0u;
  std::vector<std::string> stepIds;
  std::vector<size_t> packRows;
  std::vector<std::pair<size_t, size_t>> refLocalRows;
  std::vector<Hit> hits;
  std::string selected, runId, dragTool;
  Json requiredPack = Json::object();
  std::wstring root, logs;
  ULONGLONG lastPoll = 0;
  ULONGLONG lastPackPoll = 0;
  ULONGLONG lastRefPoll = 0;
  std::vector<std::string> refPendingIds;
  std::set<std::string> refInvalidReviewTokens;
  ULONGLONG lastSetupPoll = 0;
  bool pollPending = false;
  int px(int n) const { return MulDiv(n, static_cast<int>(dpi), 96); }
  HWND make(const wchar_t *klass, const std::wstring &title, DWORD style,
            int id, HWND parent = nullptr, DWORD ex = 0) {
    HWND h = CreateWindowExW(ex, klass, title.c_str(),
                             WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | style, 0,
                             0, 1, 1, parent ? parent : window,
                             reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)),
                             instance, nullptr);
    if (!h) {
      const DWORD error = GetLastError();
      throw std::runtime_error("Could not create Windows interface control " + narrow(klass) +
          " (ID " + std::to_string(id) + ", error " + std::to_string(error) + "): " +
          narrow(bw::windows_error(error)));
    }
    SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(font), FALSE);
    if (lstrcmpiW(klass, L"BUTTON") == 0 && (style & BS_TYPEMASK) == BS_OWNERDRAW)
      SetWindowSubclass(h, owner_button_proc, 1, 0);
    return h;
  }
  static LRESULT CALLBACK owner_button_proc(HWND h, UINT message_, WPARAM w, LPARAM l,
                                            UINT_PTR, DWORD_PTR) {
    // WM_DRAWITEM paints the complete background and label into one buffer.
    // A separate default erase exposes a blank frame during hover/focus changes.
    if (message_ == WM_ERASEBKGND) return 1;
    if (message_ == WM_NCDESTROY) RemoveWindowSubclass(h, owner_button_proc, 1);
    return DefSubclassProc(h, message_, w, l);
  }
  HWND button(const wchar_t *s, int id, HWND p = nullptr) {
    return make(L"BUTTON", s, WS_TABSTOP | BS_PUSHBUTTON, id, p);
  }
  static void enable_control(HWND h, bool value) {
    if (h && (IsWindowEnabled(h) != FALSE) != value) EnableWindow(h, value);
  }
  static void show_control(HWND h, bool value) {
    // Check this window's own style, not an ancestor's visibility during setup.
    if (h && ((GetWindowLongPtrW(h, GWL_STYLE) & WS_VISIBLE) != 0) != value)
      ShowWindow(h, value ? SW_SHOW : SW_HIDE);
  }
  static void label_control(HWND h, const std::wstring &value) {
    if (h && control_text(h) != value) SetWindowTextW(h, value.c_str());
  }
  void place(HWND h, int x, int y, int w, int hgt, bool repaint = true) {
    RECT previous{};
    GetWindowRect(h, &previous);
    MapWindowPoints(nullptr, GetParent(h), reinterpret_cast<POINT *>(&previous), 2);
    const int cx = px(x), cy = px(y), cw = px(std::max(1, w)), ch = px(std::max(1, hgt));
    if (previous.left != cx || previous.top != cy ||
        previous.right - previous.left != cw || previous.bottom - previous.top != ch) {
      if (repaint)
        MoveWindow(h, cx, cy, cw, ch, TRUE);
      else
        SetWindowPos(h, nullptr, cx, cy, cw, ch,
                     SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS);
    }
  }
  struct PanelPlacement { HWND h; int x, y, w, height; };
  void place_panel(HWND panel, const std::vector<PanelPlacement> &items, bool repaint = true) {
    constexpr UINT flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS;
    HDWP batch = BeginDeferWindowPos(static_cast<int>(items.size()));
    for (const auto &p : items) {
      if (!batch) break;
      batch = DeferWindowPos(batch, p.h, nullptr, px(p.x), px(p.y),
                             px(std::max(1, p.w)), px(std::max(1, p.height)), flags);
    }
    const bool placed = batch && EndDeferWindowPos(batch);
    if (!placed)
      for (const auto &p : items)
        SetWindowPos(p.h, nullptr, px(p.x), px(p.y), px(std::max(1, p.w)),
                     px(std::max(1, p.height)), flags);
    // Moving partially clipped child controls must not copy their previous
    // pixels. The form and general panel use WS_EX_COMPOSITED so this complete
    // descendant repaint is presented together, without exposing each label's
    // erase/draw cycle. Queue painting so a burst of scroll messages can share
    // one frame. Do not hold a panel DC beyond its paint operation.
    if (repaint)
      RedrawWindow(panel, nullptr, nullptr,
                   RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN);
  }
  static LRESULT CALLBACK field_proc(HWND h, UINT message_, WPARAM w, LPARAM l,
                                     UINT_PTR, DWORD_PTR context) {
    auto *app = reinterpret_cast<Workspace *>(context);
    if (GetParent(h) == app->generalPanel) {
      if (message_ == WM_SETFOCUS) {
        const int previous = app->generalScroll;
        RECT r{}, client{};
        GetWindowRect(h, &r); MapWindowPoints(nullptr, app->generalPanel, reinterpret_cast<POINT *>(&r), 2);
        GetClientRect(app->generalPanel, &client);
        if (r.top < 0) app->generalScroll += MulDiv(r.top - app->px(8), 96, app->dpi);
        else if (r.bottom > client.bottom)
          app->generalScroll += MulDiv(r.bottom - client.bottom + app->px(8), 96, app->dpi);
        if (app->generalScroll != previous) app->layout_general();
      }
      if (message_ == WM_MOUSEWHEEL) {
        app->panel_mouse_wheel(app->generalPanel, w);
        return 0;
      }
      return DefSubclassProc(h, message_, w, l);
    }
    if (message_ == WM_SETFOCUS) {
      auto found = app->fieldIds.find(GetDlgCtrlID(h));
      if (found != app->fieldIds.end() && found->second < app->fields.size()) {
        const int previous = app->formScroll;
        const auto &field = app->fields[found->second];
        RECT client{};
        GetClientRect(app->form, &client);
        int visible = MulDiv(client.bottom, 96, app->dpi);
        if (field.y < app->formScroll)
          app->formScroll = field.y;
        else if (field.y + field.height > app->formScroll + visible)
          app->formScroll = field.y + field.height - visible;
        if (app->formScroll != previous) app->layout_fields();
      }
    }
    if (message_ == WM_MOUSEWHEEL &&
        !SendMessageW(h, CB_GETDROPPEDSTATE, 0, 0)) {
      app->panel_mouse_wheel(app->form, w);
      return 0;
    }
    if (message_ == WM_NCDESTROY)
      RemoveWindowSubclass(h, field_proc, 1);
    return DefSubclassProc(h, message_, w, l);
  }
  void fonts() {
    for (HFONT f : {font, bold, small, libraryBold})
      if (f)
        DeleteObject(f);
    auto create = [&](int size, int weight) {
      return CreateFontW(-px(size), 0, 0, 0, weight, FALSE, FALSE, FALSE,
                         DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                         CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH,
                         L"Segoe UI");
    };
    font = create(14, FW_NORMAL);
    bold = create(14, FW_SEMIBOLD);
    small = create(12, FW_NORMAL);
    libraryBold = create(14, FW_BOLD);
    libraryLayoutWidth = -1;
    if (window)
      EnumChildWindows(
          window,
          [](HWND h, LPARAM l) -> BOOL {
            SendMessageW(h, WM_SETFONT, static_cast<WPARAM>(l), TRUE);
            return TRUE;
          },
          reinterpret_cast<LPARAM>(font));
  }
  void close_host_window() {
    host.stop();
    MSG msg{};
    while (PeekMessageW(&msg, window, HOST_MESSAGE, HOST_MESSAGE, PM_REMOVE))
      delete reinterpret_cast<std::string *>(msg.lParam);
    DestroyWindow(window);
  }
  void message(const std::wstring &value) {
    MessageBoxW(window, value.c_str(), L"Native Workbench",
                MB_OK | MB_ICONERROR);
  }
  void status_text(const std::wstring &value) {
    label_control(status, value);
  }
  void pump() {
    if (activeRequest || outgoing.empty())
      return;
    Json request = std::move(outgoing.front());
    outgoing.pop_front();
    activeRequest = request.get("id").integer();
    host.send(request);
    enabled();
  }
  bool slow_request_pending() const {
    const auto found = pending.find(activeRequest);
    if (found == pending.end()) return false;
    const auto &method = found->second;
    return method == "review" || method == "diagnostics/save" ||
           method.rfind("sample/", 0) == 0 || method.rfind("index/", 0) == 0 ||
           method == "queue/add" || method == "queue/add-batch" ||
           method.rfind("restart/", 0) == 0 || method.rfind("project/", 0) == 0 ||
           method == "resources/set" || method == "results/summary";
  }
  bool cancellation_pending() const {
    for (const auto &request : pending)
      if (request.second == "cancel" || request.second == "queue/cancel") return true;
    return false;
  }
  bool ui_request_idle() const {
    // Queue polling updates activity widgets, not the editable graph. It must
    // not disable focused controls every two seconds. Queued actions still
    // block editing immediately and execute through the existing FIFO pump.
    if (!outgoing.empty()) return false;
    if (!activeRequest) return true;
    const auto found = pending.find(activeRequest);
    return found != pending.end() && found->second == "queue/status";
  }
  bool analysis_active() const { return busy || queuePreparing || queueRunning; }
  long long send(const std::string &method, Json params = Json::object()) {
    long long id = nextRequest++;
    pending[id] = method;
    if (sample_editor_method(method)) pendingViews[id] = sampleEditorView.generation;
    else if (method.rfind("sample/", 0) == 0) pendingViews[id] = samplesView.generation;
    else if (method.rfind("index/", 0) == 0) pendingViews[id] = indexesView.generation;
    else if (method.rfind("resources/", 0) == 0) pendingViews[id] = resourcesView.generation;
    else if (method.rfind("restart/", 0) == 0) pendingViews[id] = restartView.generation;
    else if (method.rfind("project/", 0) == 0) pendingViews[id] = projectsView.generation;
    else if (method.rfind("examples/", 0) == 0) pendingViews[id] = curatedView.generation;
    else if (method.rfind("results/", 0) == 0) pendingViews[id] = resultsView.generation;
    if (method == "index/verify") pendingIndexVerifications[id] = getstr(params, "key");
    Json request = object({{"id", id}, {"method", method}, {"params", std::move(params)}});
    // Keep model mutations ordered. Only bounded monitoring, cancellation and
    // shutdown can pass a slow read/hash operation; replies retain exact IDs.
    if (slow_request_pending() && (method == "status" || method == "queue/status" ||
        method == "cancel" || method == "queue/cancel" || method == "queue/pause" || method == "shutdown")) {
      concurrentRequests.insert(id);
      host.send(request);
      enabled();
      return id;
    }
    outgoing.push_back(std::move(request));
    if (activeRequest) enabled();
    else pump();
    return id;
  }
  void model(const std::string &action, Json payload = Json::object()) {
    if (!ready || packBusy || packActionPending || refBusy ||
        refActionPending || setupBusy || setupActionPending || showingHistory)
      return;
    send("model",
         object({{"action", action}, {"payload", std::move(payload)}}));
  }
  HWND aux(const Auxiliary &view, int id) const {
    const auto found = view.controls.find(id);
    return found == view.controls.end() ? nullptr : found->second;
  }
  HWND aux_make(Auxiliary &view, int id, const wchar_t *klass,
                const std::wstring &label, DWORD style, DWORD ex = 0) {
    HWND h = make(klass, label, style, id, view.window, ex);
    view.controls[id] = h;
    SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(view.font), FALSE);
    return h;
  }
  void aux_text(Auxiliary &view, int id, const std::wstring &value) {
    HWND h = aux(view, id);
    if (h && control_text(h) != value) SetWindowTextW(h, value.c_str());
  }
  void aux_columns(Auxiliary &view, int id,
                   const std::vector<std::pair<std::wstring, int>> &columns) {
    HWND list = aux(view, id);
    while (ListView_DeleteColumn(list, 0)) {}
    int index = 0;
    for (const auto &entry : columns) {
      LVCOLUMNW column{};
      column.mask = LVCF_TEXT | LVCF_WIDTH;
      column.pszText = const_cast<wchar_t *>(entry.first.c_str());
      column.cx = MulDiv(entry.second, view.dpi, 96);
      ListView_InsertColumn(list, index++, &column);
    }
  }
  void aux_row(HWND list, int index, const std::vector<std::wstring> &values) {
    if (index >= ListView_GetItemCount(list)) {
      LVITEMW item{};
      item.mask = LVIF_TEXT;
      item.iItem = index;
      item.pszText = const_cast<wchar_t *>(values.front().c_str());
      ListView_InsertItem(list, &item);
    }
    for (size_t column = 0; column < values.size(); ++column) {
      wchar_t previous[8192]{};
      ListView_GetItemText(list, index, static_cast<int>(column), previous, 8192);
      if (values[column] != previous)
        ListView_SetItemText(list, index, static_cast<int>(column),
                            const_cast<wchar_t *>(values[column].c_str()));
    }
  }
  const Json &queue_selected() const {
    static const Json empty = Json::object();
    if (!queueView.window) return empty;
    const int row = ListView_GetNextItem(aux(queueView, QUEUE_LIST), -1, LVNI_SELECTED);
    const auto &jobs = queueState.get("jobs").array_items();
    return row >= 0 && static_cast<size_t>(row) < jobs.size() ? jobs[row] : empty;
  }
  const Json &index_selected() const {
    static const Json empty = Json::object();
    if (!indexesView.window) return empty;
    const int row = ListView_GetNextItem(aux(indexesView, INDEX_LIST), -1, LVNI_SELECTED);
    const auto &entries = indexState.get("entries").array_items();
    return row >= 0 && static_cast<size_t>(row) < entries.size() ? entries[row] : empty;
  }
  void auxiliary_enabled() {
    const bool idle = ready && !closing && !activeRequest && outgoing.empty();
    const bool responsive = ready && !closing && (idle || slow_request_pending());
    const bool edit = idle && !setupBusy && !setupActionPending && !packBusy &&
                      !packActionPending && !refBusy && !refActionPending && !showingHistory;
    recovery_enabled(idle, edit);
    curated_enabled(idle, edit);
    results_enabled(ready && !closing && ui_request_idle());
    sample_editor_enabled(ready && !closing && ui_request_idle());
    if (samplesView.window) {
      const bool sampleIdle = ready && !closing && ui_request_idle() && !samplePending && !sampleEditorView.window;
      for (int id : {SAMPLE_PATH, SAMPLE_BROWSE, SAMPLE_LOAD, SAMPLE_TARGETS, SAMPLE_MODE,
                     SAMPLE_OUTPUT, SAMPLE_OUTPUT_BROWSE, SAMPLE_NEW, SAMPLE_EXAMPLE})
        enable_control(aux(samplesView, id), sampleIdle);
      enable_control(aux(samplesView, SAMPLE_EDIT), sampleIdle && !getstr(sampleTable, "table_token").empty());
      const int target = ListView_GetNextItem(aux(samplesView, SAMPLE_TARGETS), -1, LVNI_SELECTED);
      const Json &mappedTarget = target >= 0 && static_cast<size_t>(target) < sampleTargets.array_items().size()
          ? sampleTargets.array_items()[target] : Json();
      const auto mappedType = getstr(mappedTarget, "sourceType"), mappedSource = getstr(mappedTarget, "sourceId");
      const bool canShare = !mappedSource.empty() && mappedType != "pair" && mappedType != "reads" &&
          mappedType != "sam" && mappedType != "bam" && mappedType != "sam-rna" && mappedType != "bam-rna" &&
          mappedType != "vcf" && mappedType != "vcf-pass" && mappedType != "bcf" && mappedType != "bcf-likelihoods";
      enable_control(aux(samplesView, SAMPLE_SHARED), sampleIdle && canShare && !mappedTarget.get("shared").boolean() &&
          !sampleMappings.count(static_cast<size_t>(std::max(0, target))));
      enable_control(aux(samplesView, SAMPLE_COLUMN), sampleIdle && target >= 0 && !sampleColumns.empty());
      enable_control(aux(samplesView, SAMPLE_PREVIEW), sampleIdle && !getstr(sampleTable, "table_token").empty() && !sampleTargets.array_items().empty());
      enable_control(aux(samplesView, SAMPLE_QUEUE), sampleIdle && edit && !queuePending && !sampleToken.empty() && samplePreview.get("valid").boolean());
    }
    if (queueView.window) {
      const auto &job = queue_selected();
      const auto status_ = getstr(job, "status");
      bool waiting = false;
      for (const auto &item : queueState.get("jobs").array_items())
        waiting = waiting || getstr(item, "status") == "queued";
      EnableWindow(aux(queueView, QUEUE_ADD), edit && !queuePending && !queuePreparing && !graph().get("nodes").array_items().empty());
      EnableWindow(aux(queueView, QUEUE_START), idle && !setupBusy && !setupActionPending && !packBusy &&
          !packActionPending && !refBusy && !refActionPending && !busy && !queueRunning && !queuePending && !queuePreparing && waiting);
      EnableWindow(aux(queueView, QUEUE_PAUSE), responsive && !queuePending && !queueState.get("scheduled").array_items().empty());
      EnableWindow(aux(queueView, QUEUE_CANCEL), responsive && !queuePending && !cancellation_pending() &&
                   (status_ == "queued" || status_ == "running" || status_ == "preparing"));
      EnableWindow(aux(queueView, QUEUE_RESULTS), idle && !getstr(job, "started_at").empty() && !getstr(job, "run_id").empty() && !getstr(job, "folder").empty());
    }
    if (indexesView.window) {
      EnableWindow(aux(indexesView, INDEX_REFRESH), idle && !indexPending);
      EnableWindow(aux(indexesView, INDEX_VERIFY), idle && !indexPending && !getstr(index_selected(), "key").empty());
    }
  }
  void sample_invalidate() {
    const bool hadPreview = samplePreview.contains("mode");
    sampleToken.clear();
    samplePreview = Json::object();
    if (hadPreview && aux(samplesView, SAMPLE_ROWS)) {
      ListView_DeleteAllItems(aux(samplesView, SAMPLE_ROWS));
      aux_text(samplesView, SAMPLE_NOTICE, L"The mappings changed. Preview the analyses again before queueing.");
    }
    aux_text(samplesView, SAMPLE_QUEUE, L"Queue reviewed analyses");
    auxiliary_enabled();
  }
  void sample_selection() {
    if (!samplesView.window || samplesView.rebuilding) return;
    const int row = ListView_GetNextItem(aux(samplesView, SAMPLE_TARGETS), -1, LVNI_SELECTED);
    samplesView.rebuilding = true;
    int choice = 0;
    if (row >= 0) {
      const auto mapping = sampleMappings.find(static_cast<size_t>(row));
      if (mapping != sampleMappings.end())
        for (size_t i = 0; i < sampleColumns.size(); ++i)
          if (sampleColumns[i] == mapping->second) choice = static_cast<int>(i) + 1;
    }
    SendMessageW(aux(samplesView, SAMPLE_COLUMN), CB_SETCURSEL, choice, 0);
    const Json &target = row >= 0 && static_cast<size_t>(row) < sampleTargets.array_items().size()
                            ? sampleTargets.array_items()[row] : Json();
    const auto type = getstr(target, "sourceType"), source = getstr(target, "sourceId");
    const bool eligible = !source.empty() && type != "pair" && type != "reads" &&
        type != "sam" && type != "bam" && type != "sam-rna" && type != "bam-rna" &&
        type != "vcf" && type != "vcf-pass" && type != "bcf" && type != "bcf-likelihoods";
    const bool shared = !choice && (target.get("shared").boolean() || sampleSharedSources.count(source));
    SendMessageW(aux(samplesView, SAMPLE_SHARED), BM_SETCHECK, shared ? BST_CHECKED : BST_UNCHECKED, 0);
    EnableWindow(aux(samplesView, SAMPLE_SHARED), eligible && !choice && !target.get("shared").boolean() && !samplePending);
    aux_text(samplesView, -4, row < 0 ? L"Select a workflow input or option to map its column." :
        L"Current value: " + wt(target, "value", "(empty)") + (shared ? L"\r\nShared resource; no sample pooling." : L""));
    samplesView.rebuilding = false;
    auxiliary_enabled();
  }
  void sample_mapping_rows() {
    if (!samplesView.window) return;
    HWND list = aux(samplesView, SAMPLE_TARGETS);
    samplesView.rebuilding = true;
    for (size_t i = 0; i < sampleTargets.array_items().size(); ++i) {
      const auto &target = sampleTargets.array_items()[i];
      const bool parameter = target.contains("nodeId");
      const auto mapping = sampleMappings.find(i);
      const bool shared = target.get("shared").boolean() || sampleSharedSources.count(getstr(target, "sourceId"));
      aux_row(list, static_cast<int>(i), {
          (parameter ? wt(target, "nodeId") + L" · " : L"") + wt(target, "label"),
          mapping == sampleMappings.end() ? (shared ? L"Shared workflow value" : L"Keep workflow value") : wide(mapping->second)});
    }
    while (ListView_GetItemCount(list) > static_cast<int>(sampleTargets.array_items().size()))
      ListView_DeleteItem(list, ListView_GetItemCount(list) - 1);
    samplesView.rebuilding = false;
    sample_selection();
  }
  void sample_table_rows() {
    if (!samplesView.window) return;
    sample_invalidate();
    sampleColumns.clear();
    HWND combo = aux(samplesView, SAMPLE_COLUMN), list = aux(samplesView, SAMPLE_ROWS);
    SendMessageW(combo, CB_RESETCONTENT, 0, 0);
    SendMessageW(combo, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"Keep workflow value"));
    std::vector<std::pair<std::wstring, int>> columns;
    for (const auto &column : sampleTable.get("columns").array_items()) {
      sampleColumns.push_back(text(column));
      const auto label = wide(text(column));
      SendMessageW(combo, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str()));
      columns.emplace_back(label, 180);
    }
    ListView_DeleteAllItems(list);
    aux_columns(samplesView, SAMPLE_ROWS, columns);
    const auto &rows = sampleTable.get("rows").array_items();
    for (size_t i = 0; i < std::min<size_t>(100, rows.size()); ++i) {
      std::vector<std::wstring> values;
      for (const auto &column : sampleColumns) values.push_back(wt(rows[i], column.c_str()));
      aux_row(list, static_cast<int>(i), values);
    }
    for (auto it = sampleMappings.begin(); it != sampleMappings.end();) {
      if (std::find(sampleColumns.begin(), sampleColumns.end(), it->second) == sampleColumns.end()) it = sampleMappings.erase(it);
      else ++it;
    }
    // Sample-identity options are declared by packs, never inferred from labels.
    for (size_t i = 0; i < sampleTargets.array_items().size(); ++i)
      if (sampleTargets.array_items()[i].get("binding").boolean()) sampleMappings[i] = "sample_id";
    aux_text(samplesView, SAMPLE_NOTICE, L"Loaded " + std::to_wstring(sampleTable.get("rowCount").integer(static_cast<long long>(rows.size()))) +
        L" samples. Showing the first " + std::to_wstring(std::min<size_t>(100, rows.size())) +
        L" rows; Edit table opens all rows within the editor limits. Map input columns, then preview.\r\nRelative-path base: " + wt(sampleTable, "baseDirectory", "the loaded table folder") + L". Workspace copy fixed when Samples opened.");
    if (sampleGraph.get("nodes").array_items().empty())
      aux_text(samplesView, SAMPLE_NOTICE, L"The table is loaded. Save it with Edit table → Save as. Select a tool or workflow, then reopen Samples to map its inputs and preview analyses.");
    sample_mapping_rows();
  }
  void sample_preview_rows(const Json &value) {
    samplePreview = value;
    sampleToken = value.get("valid").boolean() ? getstr(value, "token") : "";
    if (!samplesView.window) return;
    HWND list = aux(samplesView, SAMPLE_ROWS);
    ListView_DeleteAllItems(list);
    aux_columns(samplesView, SAMPLE_ROWS, {{L"Sample", 180}, {L"Preview", 120}, {L"Detail", 440}});
    int row = 0;
    for (const auto &sample : value.get("samples").array_items()) {
      std::wstring issues;
      for (const auto &issue : value.get("errors").array_items())
        if (getstr(issue, "sampleId") == getstr(sample, "sampleId")) issues += wt(issue, "message") + L" ";
      if (issues.empty()) issues = std::to_wstring(sample.get("nodeCount").integer()) + L" workflow steps";
      aux_row(list, row++, {wt(sample, "sampleId"), sample.get("valid").boolean() ? L"Valid" : L"Needs attention", issues});
    }
    std::wstring notice = wt(value, "notice") + L"\r\n";
    for (const auto &error : value.get("errors").array_items())
      notice += wt(error, "sampleId") + L" " + wt(error, "message") + L"\r\n";
    for (const auto &warning : value.get("warnings").array_items())
      notice += warning.is_string() ? wide(warning.string()) + L"\r\n" : wt(warning, "message") + L"\r\n";
    for (const char *key : {"errors_omitted", "warnings_omitted"})
      if (value.get(key).integer() > 0) notice += std::to_wstring(value.get(key).integer()) + L" additional " +
          (std::string(key) == "errors_omitted" ? L"errors" : L"warnings") + L" omitted; narrow the table to inspect them.\r\n";
    if (!sampleToken.empty()) notice += L"Review the rows and output folder. Queueing freezes each analysis; Start queued begins execution.";
    aux_text(samplesView, SAMPLE_NOTICE, lines(notice));
    aux_text(samplesView, SAMPLE_QUEUE, getstr(value, "mode") == "combined" ? L"Queue one combined report" :
        L"Queue " + std::to_wstring(value.get("sampleCount").integer()) + L" independent analyses");
    auxiliary_enabled();
  }
  void queue_send(const std::string &method, Json request = Json::object()) {
    if (method == "queue/status") queuePollPending = true;
    else queuePending = true;
    send(method, std::move(request));
  }
  void queue_selection() {
    if (!queueView.window || queueView.rebuilding) return;
    const auto &job = queue_selected();
    std::wstring details = getstr(job, "job_id").empty() ? L"Select an analysis to inspect its frozen identity and results." :
        L"Analysis: " + wt(job, "name") + L"\r\nSample: " + wt(job, "sample_id") +
        L"\r\nStatus: " + wt(job, "status") + L" — " + wt(job, "message") +
        L"\r\nResult folder: " + wt(job, "folder") + L"\r\nFrozen plan SHA-256: " + wt(job, "plan_sha256") +
        L"\r\nQueued: " + wt(job, "created_at") + L"\r\nBatch: " + wt(job, "batch_id") +
        L"\r\nExact inputs, sample metadata and options are stored with this frozen analysis.";
    aux_text(queueView, QUEUE_DETAILS, details);
    auxiliary_enabled();
  }
  void queue_response(const Json &value) {
    const auto previousSelected = getstr(queue_selected(), "job_id");
    queueState = value;
    queuePreparing = value.get("preparing").boolean();
    queueRunning = value.get("queue_running").boolean();
    busy = value.get("active").boolean();
    if (!getstr(value, "active_run").empty()) runId = getstr(value, "active_run");
    const auto &jobs = value.get("jobs").array_items();
    int waiting = 0, completed = 0;
    for (const auto &job : jobs) {
      waiting += getstr(job, "status") == "queued";
      completed += getstr(job, "status") == "completed";
    }
    aux_text(queueView, QUEUE_NOTICE,
        (queuePreparing ? L"Freezing inputs and exact tool versions... " : L"") +
        std::to_wstring(waiting) + L" waiting · " + std::to_wstring(completed) + L" completed. " +
        (value.get("paused").boolean() ? L"Queue paused. " : L"Queue started. ") +
        wt(value, "error") + L"\r\nPause lets the current analysis finish. New additions need Start queued. Queued analyses survive restart.");
    const auto label = L"Queue (" + std::to_wstring(waiting) + L")";
    if (queueButton && control_text(queueButton) != label) SetWindowTextW(queueButton, label.c_str());
    Json visibleRows = Json::array();
    for (const auto &job : jobs)
      visibleRows.array_items().push_back(object({{"id", getstr(job, "job_id")}, {"sample", getstr(job, "sample_id")},
          {"name", getstr(job, "name")}, {"status", getstr(job, "status")}, {"created", getstr(job, "created_at")}}));
    const auto rowKey = visibleRows.dump();
    if (queueView.window && rowKey != queueRendered) {
      HWND list = aux(queueView, QUEUE_LIST);
      queueView.rebuilding = true;
      int row = 0, selectedRow = -1;
      for (const auto &job : jobs) {
        aux_row(list, row, {wt(job, "sample_id"), wt(job, "name"), wt(job, "status"), wt(job, "created_at")});
        if (getstr(job, "job_id") == previousSelected) selectedRow = row;
        ++row;
      }
      while (ListView_GetItemCount(list) > row) ListView_DeleteItem(list, ListView_GetItemCount(list) - 1);
      if (selectedRow < 0 && row) selectedRow = 0;
      if (selectedRow >= 0 && ListView_GetNextItem(list, -1, LVNI_SELECTED) != selectedRow)
        ListView_SetItemState(list, selectedRow, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
      queueRendered = rowKey;
      queueView.rebuilding = false;
    }
    queue_selection();
    auxiliary_enabled();
  }
  void index_selection() {
    if (!indexesView.window || indexesView.rebuilding) return;
    const auto &entry = index_selected(), &identity = entry.get("identity");
    const auto key = getstr(entry, "key");
    std::wstring detail = key.empty() ? L"Select an index. Verify rehashes its files; listing alone does not verify their bytes." :
        L"Index: " + wide(key) + L"\r\nReference SHA-256: " + wt(identity.get("reference"), "sha256") +
        L"\r\nReference bytes: " + wt(identity.get("reference"), "bytes") +
        L"\r\nTool: " + wt(identity, "indexTool") + L" · Pack " + wt(identity.get("pack"), "packId") +
        L" " + wt(identity.get("pack"), "packVersion") + L"\r\nManifest SHA-256: " + wt(identity.get("pack"), "manifestSha256") +
        L"\r\nIndex options: " + wide(identity.get("parameters").dump()) +
        L"\r\nExecutables: " + wide(identity.get("executables").dump()) +
        L"\r\n" + wt(entry, "note");
    const auto found = verifiedIndexes.find(key);
    if (found != verifiedIndexes.end() && getstr(entry, "status") != "invalid")
      detail += L"\r\nVerified file inventory: " + wide(found->second.get("files").dump());
    aux_text(indexesView, INDEX_DETAILS, detail);
    auxiliary_enabled();
  }
  void index_rows() {
    if (!indexesView.window) return;
    indexesView.rebuilding = true;
    HWND list = aux(indexesView, INDEX_LIST);
    int row = 0;
    for (const auto &entry : indexState.get("entries").array_items()) {
      const auto &identity = entry.get("identity");
      aux_row(list, row++, {wt(identity, "indexTool"), wt(identity.get("pack"), "packVersion"),
          getstr(entry, "status") != "invalid" && verifiedIndexes.count(getstr(entry, "key")) ? L"Verified this session" : wt(entry, "status"),
          wt(identity.get("reference"), "sha256")});
    }
    while (ListView_GetItemCount(list) > row) ListView_DeleteItem(list, ListView_GetItemCount(list) - 1);
    if (row && ListView_GetNextItem(list, -1, LVNI_SELECTED) < 0)
      ListView_SetItemState(list, 0, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
    indexesView.rebuilding = false;
    aux_text(indexesView, INDEX_NOTICE, indexState.get("truncated").boolean() ?
        L"Showing the first 256 cached indexes. Verify selected checks the complete file inventory." :
        L"Indexes are reused only when reference bytes, tool version and options match. Verify checks the file inventory.");
    index_selection();
  }
  void sample_mode() {
    sample_invalidate();
    sampleMappings.clear();
    sampleTargets = Json::array();
    const bool combined = SendMessageW(aux(samplesView, SAMPLE_MODE), CB_GETCURSEL, 0, 0) == 1;
    if (combined && sampleTargetSchema.get("combined").is_array()) sampleTargets = sampleTargetSchema.get("combined");
    else if (combined) sampleTargets = Json::array();
    else {
      for (const char *key : {"files", "parameters"})
        for (const auto &target : sampleTargetSchema.get(key).array_items())
          sampleTargets.array_items().push_back(target);
      if (!sampleColumns.empty())
        for (size_t i = 0; i < sampleTargets.array_items().size(); ++i)
          if (sampleTargets.array_items()[i].get("binding").boolean()) sampleMappings[i] = "sample_id";
    }
    aux_text(samplesView, -2, combined ? L"Choose one report input and its table column" : L"Map workflow inputs and options to table columns");
    aux_text(samplesView, SAMPLE_NOTICE, combined ?
        L"One report analysis receives the listed report files. This does not pool reads or infer a statistical design. Other required inputs must already be set." :
        L"Each sample gets its own analysis and result folder. Reference inputs retain their shared workflow values. Map the read files explicitly.");
    if (sampleGraph.get("nodes").array_items().empty())
      aux_text(samplesView, SAMPLE_NOTICE, L"Create, edit or save a table now. Select a tool or workflow, then reopen Samples to map its inputs and preview analyses.");
    else if (combined && sampleTargets.array_items().empty())
      aux_text(samplesView, SAMPLE_NOTICE, L"This workflow has no compatible combined-report input. Choose a report tool with an input that accepts multiple metrics or text reports.");
    ListView_DeleteAllItems(aux(samplesView, SAMPLE_TARGETS));
    sample_mapping_rows();
  }
  void auxiliary_layout(Auxiliary &view) {
    if (!view.window || view.controls.empty()) return;
    RECT rect{};
    GetClientRect(view.window, &rect);
    const int w = MulDiv(rect.right, 96, view.dpi), h = MulDiv(rect.bottom, 96, view.dpi);
    auto put = [&](int id, int x, int y, int cw, int ch) {
      SetWindowPos(aux(view, id), nullptr, MulDiv(x, view.dpi, 96), MulDiv(y, view.dpi, 96),
          MulDiv(std::max(1, cw), view.dpi, 96), MulDiv(std::max(1, ch), view.dpi, 96),
          SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS);
    };
    if (view.kind == SHOW_SAMPLE_EDITOR) {
      sample_editor_layout(w, h, put);
    } else if (view.kind == SHOW_CURATED) {
      curated_layout(view, w, h, put);
    } else if (view.kind == SHOW_RESULTS) {
      results_layout(view, w, h, put);
    } else if (view.kind >= SHOW_RESOURCES && view.kind <= SHOW_PROJECTS) {
      recovery_layout(view, w, h, put);
    } else if (view.kind == SHOW_SAMPLES) {
      put(-1, 18, 12, w - 264, 38);
      put(SAMPLE_MODE, w - 234, 14, 216, 220);
      put(SAMPLE_PATH, 18, 58, w - 232, 30);
      put(SAMPLE_BROWSE, w - 204, 58, 90, 30);
      put(SAMPLE_LOAD, w - 104, 58, 86, 30);
      put(SAMPLE_NEW, 18, 98, 112, 30);
      put(SAMPLE_EDIT, 142, 98, 112, 30);
      put(SAMPLE_EXAMPLE, 266, 98, 154, 30);
      put(-2, 18, 140, w - 36, 22);
      put(SAMPLE_TARGETS, 18, 166, w / 2 - 26, 132);
      put(-3, w / 2 + 8, 166, w / 2 - 26, 22);
      put(SAMPLE_COLUMN, w / 2 + 8, 192, w / 2 - 26, 250);
      put(SAMPLE_SHARED, w / 2 + 8, 226, w / 2 - 26, 30);
      put(-4, w / 2 + 8, 262, w / 2 - 26, 40);
      put(SAMPLE_ROWS, 18, 312, w - 36, std::max(64, h - 468));
      put(SAMPLE_NOTICE, 18, h - 144, w - 36, 58);
      put(SAMPLE_OUTPUT, 18, h - 78, w - 202, 30);
      put(SAMPLE_OUTPUT_BROWSE, w - 174, h - 78, 156, 30);
      put(SAMPLE_PREVIEW, 18, h - 40, 122, 30);
      put(SAMPLE_QUEUE, 152, h - 40, 280, 30);
      put(SAMPLE_CLOSE, w - 108, h - 40, 90, 30);
    } else if (view.kind == SHOW_QUEUE) {
      put(-1, 18, 14, w - 36, 40);
      put(QUEUE_LIST, 18, 64, w - 36, std::max(90, h - 314));
      put(QUEUE_DETAILS, 18, h - 240, w - 36, 126);
      put(QUEUE_NOTICE, 18, h - 104, w - 36, 52);
      put(QUEUE_ADD, 18, h - 42, 150, 30);
      put(QUEUE_START, 180, h - 42, 116, 30);
      put(QUEUE_PAUSE, 308, h - 42, 184, 30);
      put(QUEUE_CANCEL, 504, h - 42, 120, 30);
      put(QUEUE_RESULTS, 636, h - 42, 110, 30);
      put(QUEUE_CLOSE, w - 102, h - 42, 84, 30);
    } else {
      put(-1, 18, 14, w - 36, 40);
      put(INDEX_LIST, 18, 64, w - 36, std::max(90, h - 288));
      put(INDEX_DETAILS, 18, h - 212, w - 36, 118);
      put(INDEX_NOTICE, 18, h - 84, w - 36, 38);
      put(INDEX_REFRESH, 18, h - 40, 108, 30);
      put(INDEX_VERIFY, 138, h - 40, 160, 30);
      put(INDEX_CLOSE, w - 108, h - 40, 90, 30);
    }
    RedrawWindow(view.window, nullptr, nullptr, RDW_INVALIDATE | RDW_ALLCHILDREN);
  }
  void auxiliary_command(Auxiliary &view, int id, int notification) {
    if (view.rebuilding) return;
    if (view.kind == SHOW_SAMPLE_EDITOR) { sample_editor_command(id, notification); return; }
    if (view.kind == SHOW_SAMPLES && (id == SAMPLE_CLOSE || id == IDCANCEL) && !sample_editor_close()) return;
    if (id == SAMPLE_CLOSE || id == QUEUE_CLOSE || id == INDEX_CLOSE ||
        id == RESOURCE_CLOSE || id == RESTART_CLOSE || id == PROJECT_CLOSE ||
        id == CURATED_CLOSE || id == RESULTS_CLOSE || id == IDCANCEL) {
      DestroyWindow(view.window);
      return;
    }
    if (view.kind == SHOW_CURATED) {
      curated_command(id, notification);
      return;
    }
    if (view.kind == SHOW_RESULTS) {
      results_command(id, notification);
      return;
    }
    if (view.kind >= SHOW_RESOURCES && view.kind <= SHOW_PROJECTS) {
      recovery_command(view, id, notification);
      return;
    }
    if (view.kind == SHOW_SAMPLES) {
      if (id == SAMPLE_MODE && notification == CBN_SELCHANGE) { sample_mode(); return; }
      if (id == SAMPLE_COLUMN && notification == CBN_SELCHANGE) {
        int row = ListView_GetNextItem(aux(view, SAMPLE_TARGETS), -1, LVNI_SELECTED);
        const int column = static_cast<int>(SendMessageW(aux(view, SAMPLE_COLUMN), CB_GETCURSEL, 0, 0));
        if (row >= 0) {
          sample_invalidate();
          if (SendMessageW(aux(view, SAMPLE_MODE), CB_GETCURSEL, 0, 0) == 1) sampleMappings.clear();
          if (column > 0 && static_cast<size_t>(column) <= sampleColumns.size()) {
            sampleMappings[row] = sampleColumns[column - 1];
            sampleSharedSources.erase(getstr(sampleTargets.array_items()[row], "sourceId"));
          }
          else sampleMappings.erase(row);
          sample_mapping_rows();
        }
        return;
      }
      if (id == SAMPLE_SHARED) {
        const int row = ListView_GetNextItem(aux(view, SAMPLE_TARGETS), -1, LVNI_SELECTED);
        if (row >= 0 && static_cast<size_t>(row) < sampleTargets.array_items().size()) {
          const auto source = getstr(sampleTargets.array_items()[row], "sourceId");
          if (SendMessageW(aux(view, SAMPLE_SHARED), BM_GETCHECK, 0, 0) == BST_CHECKED) sampleSharedSources.insert(source);
          else sampleSharedSources.erase(source);
          sample_invalidate();
          sample_mapping_rows();
        }
        return;
      }
      if (id == SAMPLE_PATH && notification == EN_CHANGE) {
        sample_invalidate();
        aux_text(view, SAMPLE_NOTICE, sampleTable.contains("rows") ?
            L"This path has not been loaded. The previously loaded table remains in use until Load table succeeds." :
            L"Load this table before previewing. Changing the path does not import its contents automatically.");
        return;
      }
      if (!ready || closing || samplePending || sampleEditorView.window) return;
      if (id == SAMPLE_NEW || id == SAMPLE_EDIT || id == SAMPLE_EXAMPLE) {
        show_sample_editor(id);
      } else if (id == SAMPLE_BROWSE) {
        const auto path = pick(view.window, false, false, L"Sample tables|*.csv;*.tsv|All files|*.*", L"Choose a CSV or TSV sample table", control_text(inputFolder));
        if (!path.empty()) aux_text(view, SAMPLE_PATH, path);
      } else if (id == SAMPLE_LOAD) {
        sample_invalidate(); samplePending = true;
        send("sample/table", object({{"path", narrow(control_text(aux(view, SAMPLE_PATH)))}}));
      } else if (id == SAMPLE_OUTPUT_BROWSE) {
        const auto path = pick(view.window, true, false, L"", L"Choose the parent folder for sample results", control_text(aux(view, SAMPLE_OUTPUT)));
        if (!path.empty()) aux_text(view, SAMPLE_OUTPUT, path);
      } else if (id == SAMPLE_PREVIEW) {
        Json bindings = Json::array(), parameters = Json::array(), shared = Json::array(), combined = Json::object();
        const bool combinedMode = SendMessageW(aux(view, SAMPLE_MODE), CB_GETCURSEL, 0, 0) == 1;
        for (const auto &mapping : sampleMappings) {
          if (mapping.first >= sampleTargets.array_items().size()) continue;
          const auto &target = sampleTargets.array_items()[mapping.first];
          if (combinedMode) combined = object({{"nodeId", getstr(target, "nodeId")}, {"portId", getstr(target, "portId")}, {"column", mapping.second}});
          else if (target.contains("nodeId")) parameters.array_items().push_back(object({{"nodeId", getstr(target, "nodeId")}, {"parameterId", getstr(target, "parameterId")}, {"column", mapping.second}}));
          else bindings.array_items().push_back(object({{"sourceId", getstr(target, "sourceId")}, {"fieldId", getstr(target, "fieldId")}, {"column", mapping.second}}));
        }
        for (const auto &source : sampleSharedSources) shared.array_items().push_back(source);
        Json request = object({{"graph", sampleGraph}, {"table_token", getstr(sampleTable, "table_token")},
            {"bindings", bindings}, {"parameter_bindings", parameters}, {"shared_sources", shared},
            {"mode", combinedMode ? "combined" : "independent"}});
        if (combinedMode) request["combined_target"] = combined;
        sample_invalidate(); samplePending = true;
        aux_text(view, SAMPLE_NOTICE, L"Checking the mapped analyses. Nothing is queued or running yet...");
        send("sample/preview", request);
      } else if (id == SAMPLE_QUEUE && !sampleToken.empty()) {
        const auto token = sampleToken;
        sample_invalidate();
        queue_send("queue/add-batch", object({{"token", token}, {"output_folder", narrow(control_text(aux(view, SAMPLE_OUTPUT)))}}));
        aux_text(view, SAMPLE_NOTICE, L"Freezing the reviewed analyses. Open Queue to inspect them and explicitly start execution.");
        show_auxiliary(SHOW_QUEUE);
      }
    } else if (view.kind == SHOW_QUEUE && ready && !closing && !queuePending) {
      if (id == QUEUE_ADD) {
        commit_all();
        queue_send("queue/add", object({{"output_folder", narrow(control_text(output))}}));
      } else if (id == QUEUE_START) queue_send("queue/start");
      else if (id == QUEUE_PAUSE) queue_send("queue/pause");
      else if (id == QUEUE_CANCEL && !getstr(queue_selected(), "job_id").empty())
        queue_send("queue/cancel", object({{"job_id", getstr(queue_selected(), "job_id")}}));
      else if (id == QUEUE_RESULTS && !getstr(queue_selected(), "run_id").empty())
        send("open", object({{"run_id", getstr(queue_selected(), "run_id")}}));
    } else if (view.kind == SHOW_INDEXES && ready && !closing && !indexPending) {
      if (id == INDEX_REFRESH) {
        indexPending = true; verifiedIndexes.clear(); send("index/list");
      } else if (id == INDEX_VERIFY && !getstr(index_selected(), "key").empty()) {
        const auto key = getstr(index_selected(), "key");
        indexPending = true;
        verifiedIndexes.erase(key);
        index_rows();
        aux_text(view, INDEX_NOTICE, L"Rehashing the complete index inventory. This may take time for a large reference...");
        send("index/verify", object({{"key", key}}));
      }
    }
    auxiliary_enabled();
  }
  static LRESULT CALLBACK auxiliary_proc(HWND h, UINT message_, WPARAM w, LPARAM l) {
    auto *view = reinterpret_cast<Auxiliary *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (message_ == WM_NCCREATE) {
      view = static_cast<Auxiliary *>(reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      view->window = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(view));
    }
    if (!view) return DefWindowProcW(h, message_, w, l);
    auto *app = view->app;
    try {
      switch (message_) {
      case WM_COMMAND: app->auxiliary_command(*view, LOWORD(w), HIWORD(w)); return 0;
      case WM_NOTIFY: {
        const auto *notice = reinterpret_cast<NMHDR *>(l);
        if (!view->rebuilding && notice->code == LVN_ITEMCHANGED) {
          if (notice->idFrom == SAMPLE_EDITOR_GRID) {
            const auto *change = reinterpret_cast<NMLISTVIEW *>(l);
            if ((change->uChanged & LVIF_STATE) && ((change->uOldState ^ change->uNewState) & LVIS_SELECTED) &&
                (change->uNewState & LVIS_SELECTED) && change->iItem >= 0) {
              app->sampleEditorRow = change->iItem; app->sample_editor_selection();
            }
          } else if (notice->idFrom == SAMPLE_TARGETS) app->sample_selection();
          else if (notice->idFrom == QUEUE_LIST) app->queue_selection();
          else if (notice->idFrom == INDEX_LIST) app->index_selection();
          else if (notice->idFrom == CURATED_LIST) app->curated_selection();
          else if (notice->idFrom == RESULTS_RUNS) app->results_selection();
          else if (notice->idFrom == RESOURCE_LIST || notice->idFrom == RESTART_LIST || notice->idFrom == PROJECT_LIST) app->recovery_selection(*view);
        }
        if (notice->idFrom == SAMPLE_EDITOR_GRID && notice->code == NM_DBLCLK) {
          const auto *click = reinterpret_cast<NMITEMACTIVATE *>(l);
          if (click->iItem >= 0) {
            app->sampleEditorRow = click->iItem; app->sampleEditorColumn = click->iSubItem;
            app->sample_editor_selection(); SetFocus(app->aux(*view, SAMPLE_EDITOR_VALUE));
          }
        }
        return 0;
      }
      case WM_SIZE: app->auxiliary_layout(*view); return 0;
      case WM_DPICHANGED: {
        view->dpi = HIWORD(w);
        HFONT old = view->font;
        view->font = CreateFontW(-MulDiv(14, view->dpi, 96), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        for (const auto &control : view->controls) SendMessageW(control.second, WM_SETFONT, reinterpret_cast<WPARAM>(view->font), FALSE);
        if (old) DeleteObject(old);
        const auto *rect = reinterpret_cast<RECT *>(l);
        SetWindowPos(h, nullptr, rect->left, rect->top, rect->right - rect->left, rect->bottom - rect->top, SWP_NOZORDER | SWP_NOACTIVATE);
        app->auxiliary_layout(*view);
        return 0;
      }
      case WM_GETMINMAXINFO: {
        auto *info = reinterpret_cast<MINMAXINFO *>(l);
        MONITORINFO monitor{sizeof(monitor)};
        GetMonitorInfoW(MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST), &monitor);
        info->ptMinTrackSize = {std::min<LONG>(MulDiv(view->kind == SHOW_QUEUE ? 900 : view->kind == SHOW_SAMPLE_EDITOR ? 900 : view->kind == SHOW_PROJECTS ? 820 : 740, view->dpi, 96), monitor.rcWork.right - monitor.rcWork.left),
            std::min<LONG>(MulDiv(view->kind == SHOW_SAMPLES || view->kind == SHOW_SAMPLE_EDITOR ? 640 : view->kind == SHOW_PROJECTS ? 580 : 480, view->dpi, 96), monitor.rcWork.bottom - monitor.rcWork.top)};
        return 0;
      }
      case WM_CTLCOLORSTATIC:
      case WM_CTLCOLOREDIT:
      case WM_CTLCOLORBTN: {
        HDC dc = reinterpret_cast<HDC>(w);
        SetTextColor(dc, INK);
        SetBkColor(dc, message_ == WM_CTLCOLOREDIT ? PAPER : BACK);
        return reinterpret_cast<LRESULT>(message_ == WM_CTLCOLOREDIT ? app->paper : app->background);
      }
      case WM_CLOSE:
        if (view->kind == SHOW_SAMPLE_EDITOR) { app->sample_editor_close(); return 0; }
        if (view->kind == SHOW_SAMPLES && !app->sample_editor_close()) return 0;
        DestroyWindow(h); return 0;
      case WM_NCDESTROY:
        view->window = nullptr; view->controls.clear();
        if (view->font) DeleteObject(view->font);
        view->font = nullptr;
        SetWindowLongPtrW(h, GWLP_USERDATA, 0);
        return DefWindowProcW(h, message_, w, l);
      default: break;
      }
    } catch (const std::exception &error) {
      MessageBoxW(h, wide(error.what()).c_str(), L"Native Workbench", MB_OK | MB_ICONERROR);
    }
    return DefWindowProcW(h, message_, w, l);
  }
  void show_auxiliary(int kind) {
    Auxiliary &view = kind == SHOW_SAMPLE_EDITOR ? sampleEditorView : kind == SHOW_CURATED ? curatedView : kind == SHOW_RESULTS ? resultsView : auxiliary_view(kind);
    if (view.window) { ShowWindow(view.window, SW_RESTORE); SetForegroundWindow(view.window); return; }
    view.app = this; view.kind = kind; view.dpi = dpi; ++view.generation;
    view.font = CreateFontW(-px(14), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    WNDCLASSEXW klass{sizeof(klass)};
    klass.lpfnWndProc = auxiliary_proc; klass.hInstance = instance;
    klass.hCursor = LoadCursorW(nullptr, IDC_ARROW); klass.hbrBackground = background;
    klass.lpszClassName = L"WorkbenchAnalysisLibrary0130";
    RegisterClassExW(&klass);
    RECT owner{}; GetWindowRect(window, &owner);
    MONITORINFO monitor{sizeof(monitor)};
    if (!GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor))
      SystemParametersInfoW(SPI_GETWORKAREA, 0, &monitor.rcWork, 0);
    const RECT area = monitor.rcWork;
    const int w = std::min<int>(px(940), area.right - area.left),
              h = std::min<int>(px(kind == SHOW_SAMPLES || kind == SHOW_SAMPLE_EDITOR || kind == SHOW_CURATED || kind == SHOW_RESULTS ? 680 : 590), area.bottom - area.top);
    const wchar_t *title = kind == SHOW_SAMPLE_EDITOR ? L"Sample table editor · Native Workbench" : kind == SHOW_CURATED ? L"Curated workflows · Native Workbench" :
        kind == SHOW_RESULTS ? L"Recorded results · Native Workbench" : kind == SHOW_SAMPLES ? L"Samples · Native Workbench" : kind == SHOW_QUEUE ?
        L"Analysis queue · Native Workbench" : kind == SHOW_RESOURCES ? L"Resources · Native Workbench" :
        kind == SHOW_RESTART ? L"Restart analysis · Native Workbench" : kind == SHOW_PROJECTS ?
        L"Portable projects · Native Workbench" : L"Reference indexes · Native Workbench";
    view.window = CreateWindowExW(WS_EX_CONTROLPARENT, klass.lpszClassName, title,
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
        std::clamp<int>(owner.left + (owner.right - owner.left - w) / 2, area.left, area.right - w),
        std::clamp<int>(owner.top + (owner.bottom - owner.top - h) / 2, area.top, area.bottom - h),
        w, h, kind == SHOW_SAMPLE_EDITOR ? samplesView.window : window, nullptr, instance, &view);
    if (!view.window) throw std::runtime_error("Could not create the analysis library window.");
    auto label = [&](int id, const wchar_t *value) { return aux_make(view, id, L"STATIC", value, SS_LEFT); };
    auto action = [&](int id, const wchar_t *value) { return aux_make(view, id, L"BUTTON", value, WS_TABSTOP | BS_PUSHBUTTON); };
    auto edit = [&](int id, const std::wstring &value, bool multiline) {
      return aux_make(view, id, L"EDIT", value, WS_TABSTOP | (multiline ? ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL : ES_AUTOHSCROLL), WS_EX_CLIENTEDGE);
    };
    auto list = [&](int id) {
      HWND hlist = aux_make(view, id, WC_LISTVIEWW, L"", WS_TABSTOP | LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS, WS_EX_CLIENTEDGE);
      ListView_SetExtendedListViewStyle(hlist, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_LABELTIP);
      return hlist;
    };
    if (kind == SHOW_SAMPLE_EDITOR) {
      sample_editor_controls(view, label, action, edit, list);
    } else if (kind == SHOW_CURATED) {
      curated_controls(view, label, action, edit, list);
    } else if (kind == SHOW_RESULTS) {
      results_controls(view, label, action, edit, list);
    } else if (kind >= SHOW_RESOURCES && kind <= SHOW_PROJECTS) {
      recovery_controls(view, label, action, edit, list);
    } else if (kind == SHOW_SAMPLES) {
      sampleLoadedPath.clear();
      sampleGraph = Json::object(); sampleTable = Json::object(); sampleTargetSchema = Json::object();
      sampleTargets = Json::array(); sampleColumns.clear(); sampleMappings.clear(); sampleSharedSources.clear(); sampleToken.clear();
      label(-1, L"Create, edit or load a sample table, then map its columns. Preview before queueing any analysis.");
      HWND mode = aux_make(view, SAMPLE_MODE, L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL);
      for (const wchar_t *value : {L"Independent samples", L"Combined reports"}) SendMessageW(mode, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(value));
      SendMessageW(mode, CB_SETCURSEL, 0, 0);
      edit(SAMPLE_PATH, L"", false); action(SAMPLE_BROWSE, L"Browse..."); action(SAMPLE_LOAD, L"Load table");
      action(SAMPLE_NEW, L"New table..."); action(SAMPLE_EDIT, L"Edit table..."); action(SAMPLE_EXAMPLE, L"Example table...");
      label(-2, L"Map workflow inputs and options to table columns"); list(SAMPLE_TARGETS);
      aux_columns(view, SAMPLE_TARGETS, {{L"Workflow input / option", 272}, {L"Table column", 180}});
      label(-3, L"Column for the selected input / option");
      aux_make(view, SAMPLE_COLUMN, L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL);
      aux_make(view, SAMPLE_SHARED, L"BUTTON", L"Keep one shared resource", WS_TABSTOP | BS_AUTOCHECKBOX);
      label(-4, L"Select an input or option to map its column."); list(SAMPLE_ROWS);
      edit(SAMPLE_NOTICE, L"Choose a CSV or TSV file with a unique sample_id column. Read 1 and read 2 must be mapped separately.", true);
      edit(SAMPLE_OUTPUT, control_text(output), false); action(SAMPLE_OUTPUT_BROWSE, L"Output folder...");
      action(SAMPLE_PREVIEW, L"Preview analyses"); action(SAMPLE_QUEUE, L"Queue reviewed analyses"); action(SAMPLE_CLOSE, L"Close");
      samplePending = true; send("sample/targets");
    } else if (kind == SHOW_QUEUE) {
      queueRendered.clear();
      label(-1, L"Each queued analysis freezes its files, options and tool versions. You can keep editing the workspace.");
      list(QUEUE_LIST); aux_columns(view, QUEUE_LIST, {{L"Sample", 140}, {L"Analysis", 270}, {L"Status", 120}, {L"Queued", 200}});
      edit(QUEUE_DETAILS, L"Select an analysis to inspect its frozen identity.", true); label(QUEUE_NOTICE, L"Loading the durable queue...");
      action(QUEUE_ADD, L"Queue current analysis"); action(QUEUE_START, L"Start queued"); action(QUEUE_PAUSE, L"Pause after current job");
      action(QUEUE_CANCEL, L"Cancel selected"); action(QUEUE_RESULTS, L"View results"); action(QUEUE_CLOSE, L"Close");
      queue_response(queueState);
      if (!queuePollPending && !queuePending) queue_send("queue/status");
    } else {
      label(-1, L"Reference indexes are created by explicit workflow tools and reused when their exact identity matches.");
      list(INDEX_LIST); aux_columns(view, INDEX_LIST, {{L"Tool", 110}, {L"Pack version", 100}, {L"Integrity", 180}, {L"Reference SHA-256", 420}});
      edit(INDEX_DETAILS, L"Select an index to inspect its reference, tool and options.", true); label(INDEX_NOTICE, L"Loading cached indexes...");
      action(INDEX_REFRESH, L"Refresh"); action(INDEX_VERIFY, L"Verify selected"); action(INDEX_CLOSE, L"Close");
      verifiedIndexes.clear(); indexPending = true; send("index/list");
    }
    auxiliary_layout(view); auxiliary_enabled();
    ShowWindow(view.window, SW_SHOW); SetForegroundWindow(view.window);
    if (kind == SHOW_RESULTS) SetFocus(aux(view, RESULTS_QUERY));
  }
  const Json &graph() const {
    static const Json empty =
        object({{"nodes", Json::array()}, {"sources", Json::array()}});
    const Json &g =
        showingHistory ? historyRun.get("graph") : state.get("graph");
    return g.is_object() && g.get("nodes").is_array() &&
                   g.get("sources").is_array()
               ? g
               : empty;
  }
  const Json &tool(const std::string &id) const {
    return catalog.get("tools").get(id);
  }
  const Json &tool(const Json &node) const {
    static const Json missing = Json::object();
    const auto id = getstr(node, "tool");
    if (!node.contains("pin"))
      return tool(id);
    const auto &pin = node.get("pin");
    if (!pin.is_object() || getstr(pin, "packVersion").empty() ||
        getstr(pin, "manifestSha256").empty())
      return missing;
    const auto matches = [&](const Json &candidate) {
      return getstr(candidate, "packVersion") == getstr(pin, "packVersion") &&
             getstr(candidate, "manifestSha256") == getstr(pin, "manifestSha256") &&
             (!pin.contains("packId") || getstr(candidate, "packId") == getstr(pin, "packId"));
    };
    const auto &versions = catalog.get("toolVersions").get(id);
    if (versions.is_array())
      for (const auto &candidate : versions.array_items())
        if (matches(candidate))
          return candidate;
    const auto &latest = tool(id);
    return matches(latest) ? latest : missing;
  }
  std::string node_name(const Json &n) const {
    std::string label = getstr(n, "label");
    return label.empty()
               ? getstr(tool(n), "name", getstr(n, "tool"))
               : label;
  }
  std::map<std::string, int> ranks() const {
    std::map<std::string, int> r;
    for (const auto &n : graph().get("nodes").array_items())
      r[getstr(n, "id")] = 1;
    for (size_t k = 0; k < r.size(); ++k) {
      bool changed = false;
      for (const auto &n : graph().get("nodes").array_items()) {
        const auto id = getstr(n, "id");
        int rank = 1;
        for (const auto &port : n.get("inputs").object_items())
          for (const auto &ref : port.second.array_items()) {
            auto value = text(ref);
            auto sep = value.find("::");
            if (sep != value.npos) {
              auto found = r.find(value.substr(0, sep));
              if (found != r.end())
                rank = std::max(rank, found->second + 1);
            }
          }
        if (rank != r[id]) {
          r[id] = rank;
          changed = true;
        }
      }
      if (!changed)
        break;
    }
    return r;
  }
  static std::wstring download_size(long long bytes) {
    if (bytes <= 0)
      return L"—";
    std::wostringstream value;
    if (bytes < 1024 * 1024)
      value << std::fixed << std::setprecision(0) << bytes / 1024.0 << L" KB";
    else if (bytes < 1024LL * 1024 * 1024)
      value << std::fixed << std::setprecision(1)
            << bytes / (1024.0 * 1024.0) << L" MB";
    else
      value << std::fixed << std::setprecision(1)
            << bytes / (1024.0 * 1024.0 * 1024.0) << L" GB";
    return value.str();
  }
  static std::string pack_key(const Json &item) {
    return getstr(item, "id") + "\n" + getstr(item, "version") + "\n" +
           getstr(item, "sourceId");
  }
  const Json &selected_pack() const {
    static const Json empty = Json::object();
    if (!packWindow)
      return empty;
    int row = ListView_GetNextItem(packList, -1, LVNI_SELECTED);
    if (row < 0 || static_cast<size_t>(row) >= packRows.size())
      return empty;
    const auto &items = packState.get("packs").array_items();
    size_t at = packRows[static_cast<size_t>(row)];
    return at < items.size() ? items[at] : empty;
  }
  void pack_send(const std::string &method, Json params = Json::object()) {
    if (method != "packs/list" && method != "packs/status")
      packActionPending = true;
    if (method == "packs/status")
      packPollPending = true;
    if (method == "packs/refresh")
      packListAfterOperation = true;
    send(method, std::move(params));
    pack_enabled();
  }
  void pack_enabled() {
    if (!packWindow)
      return;
    const bool idle = ready && !analysis_active() && !closing && !setupBusy && !setupActionPending && !packBusy && !refBusy &&
                      !refActionPending &&
                      !packActionPending;
    const auto &item = selected_pack();
    const bool canInstall = !getstr(item, "id").empty() &&
                            !item.get("installed").boolean() &&
                            item.get("compatible").boolean(true) &&
                            !getstr(item, "sourceId").empty();
    SetWindowTextW(packInstall, item.get("updateAvailable").boolean()
                                   ? L"Install update"
                                   : L"Install selected");
    EnableWindow(packInstall, idle && canInstall);
    for (HWND h : {packImportZip, packImportFolder, packSource, packRefresh})
      EnableWindow(h, idle);
    EnableWindow(packCancel, ready && packBusy && !packActionPending &&
                                 packOperation.get("cancellable").boolean(true) &&
                                 getstr(packOperation, "status") != "cancelling");
  }
  void pack_selection() {
    if (!packWindow)
      return;
    const auto &item = selected_pack();
    std::wstring value;
    if (!getstr(item, "id").empty()) {
      value = wt(item, "name", getstr(item, "id")) + L"  ·  " +
              wt(item, "version") + L"\n\n" + wt(item, "description");
      if (!getstr(item, "category").empty())
        value += L"\n\nCategory: " + wt(item, "category");
      for (const auto &version : item.get("toolVersions").object_items())
        value += L"\n" + wide(version.first) + L": " + wide(text(version.second));
      if (!getstr(item, "sourceId").empty())
        value += L"\nCatalogue: " + wt(item, "sourceId");
      value += L"\nDownload: " + download_size(item.get("size").integer());
      value += item.get("installed").boolean() ? L"\nInstalled on this computer."
                                               : L"\nAvailable to install.";
      if (!item.get("compatible").boolean(true))
        value += L"\nCannot install: " +
                 wt(item, "reason", "This pack requires a different application version.");
      else if (!getstr(item, "reason").empty())
        value += L"\n" + wt(item, "reason");
      if (item.get("updateAvailable").boolean())
        value += L"\nAn update is available. Existing versions are retained for saved pipelines.";
    } else
      value = L"Select a tool pack to see its description and requirements.\n\n"
              L"Install from a trusted catalogue, or import a pack ZIP or folder. "
              L"Analysis and input data stay on this computer.";
    for (const auto &source : packState.get("sources").array_items())
      if (!getstr(source, "error").empty())
        value += L"\n\nCatalogue warning — " + wt(source, "name", getstr(source, "id")) +
                 L": " + wt(source, "error");
    for (const auto &error : packState.get("errors").array_items())
      value += L"\n\nUnavailable local pack — " + wt(error, "folder") +
               L"\n" + wt(error, "message", "This pack could not be loaded.");
    SetWindowTextW(packDetails, lines(value).c_str());
    pack_enabled();
  }
  void refresh_packs(const std::string &selectKey = {}) {
    if (!packWindow)
      return;
    const auto keep = selectKey.empty() ? pack_key(selected_pack()) : selectKey;
    const auto query = lower(control_text(packSearch));
    const int filter = static_cast<int>(SendMessageW(packFilter, CB_GETCURSEL, 0, 0));
    packRebuilding = true;
    SendMessageW(packList, WM_SETREDRAW, FALSE, 0);
    ListView_DeleteAllItems(packList);
    packRows.clear();
    int selectedRow = -1;
    const auto &items = packState.get("packs").array_items();
    for (size_t i = 0; i < items.size(); ++i) {
      const auto &item = items[i];
      const bool installed = item.get("installed").boolean();
      if ((filter == 1 && installed) || (filter == 2 && !installed) ||
          (filter == 3 && !item.get("updateAvailable").boolean()))
        continue;
      std::wstring label = wt(item, "name", getstr(item, "id"));
      if (!query.empty() &&
          lower(label + L" " + wt(item, "id") + L" " +
                wt(item, "category") + L" " + wt(item, "description"))
                  .find(query) == std::wstring::npos)
        continue;
      LVITEMW row{};
      row.mask = LVIF_TEXT;
      row.iItem = static_cast<int>(packRows.size());
      row.pszText = label.data();
      ListView_InsertItem(packList, &row);
      auto version = wt(item, "version");
      auto availability = installed ? L"Installed" : L"Available";
      if (!item.get("compatible").boolean(true))
        availability = L"Incompatible";
      else if (item.get("updateAvailable").boolean() && !installed)
        availability = L"Update available";
      auto size = download_size(item.get("size").integer());
      ListView_SetItemText(packList, row.iItem, 1, version.data());
      ListView_SetItemText(packList, row.iItem, 2,
                          const_cast<wchar_t *>(availability));
      ListView_SetItemText(packList, row.iItem, 3, size.data());
      if (pack_key(item) == keep)
        selectedRow = row.iItem;
      if (!getstr(requiredPack, "packId").empty() &&
          getstr(item, "id") == getstr(requiredPack, "packId") &&
          getstr(item, "version") == getstr(requiredPack, "packVersion") &&
          getstr(item, "manifestSha256") == getstr(requiredPack, "manifestSha256"))
        selectedRow = row.iItem;
      packRows.push_back(i);
    }
    if (selectedRow < 0 && !packRows.empty())
      selectedRow = 0;
    if (selectedRow >= 0) {
      ListView_SetItemState(packList, selectedRow, LVIS_SELECTED | LVIS_FOCUSED,
                            LVIS_SELECTED | LVIS_FOCUSED);
      ListView_EnsureVisible(packList, selectedRow, FALSE);
    }
    SendMessageW(packList, WM_SETREDRAW, TRUE, 0);
    InvalidateRect(packList, nullptr, TRUE);
    packRebuilding = false;
    pack_selection();
  }
  void pack_notice() {
    if (!packWindow)
      return;
    std::wstring value = wt(packOperation, "message");
    if (packBusy && getstr(packOperation, "message").rfind("Cancelling", 0) != 0) {
      if (getstr(packOperation, "phase") == "downloading")
        value = L"Downloading files...";
      else if (getstr(packOperation, "phase") == "verifying")
        value = L"Verifying pack files...";
    }
    if (value.empty())
      value = wt(packState, "notice");
    if (!packBusy)
      for (const auto &source : packState.get("sources").array_items())
        if (!getstr(source, "error").empty()) {
          value = wt(source, "name", getstr(source, "id")) + L": " + wt(source, "error");
          break;
        }
    if (value.empty())
      value = packRows.empty()
                  ? L"No matching packs. Change the filter, import a pack, or add a catalogue."
                  : L"Installed tools work offline. Refresh checks only the catalogues you have added.";
    const auto bytes = packOperation.get("bytes").integer(),
               total = packOperation.get("total").integer();
    if (packBusy && bytes > 0)
      value += L"  " + download_size(bytes) +
               (total > 0 ? L" / " + download_size(total) : L"");
    SetWindowTextW(packNotice, value.c_str());
    SendMessageW(packProgress, PBM_SETRANGE32, 0, 1000);
    SendMessageW(packProgress, PBM_SETPOS,
                 total > 0 ? static_cast<WPARAM>(std::clamp(
                                 1000.0 * static_cast<double>(bytes) /
                                     static_cast<double>(total),
                                 0.0, 1000.0))
                           : 0,
                 0);
    ShowWindow(packProgress, packBusy ? SW_SHOW : SW_HIDE);
  }
  void pack_layout() {
    if (!packWindow)
      return;
    RECT r{};
    GetClientRect(packWindow, &r);
    const int w = MulDiv(r.right, 96, packDpi),
              h = MulDiv(r.bottom, 96, packDpi);
    auto put = [&](HWND control, int x, int y, int cw, int ch) {
      MoveWindow(control, MulDiv(x, packDpi, 96), MulDiv(y, packDpi, 96),
                 MulDiv(std::max(1, cw), packDpi, 96),
                 MulDiv(std::max(1, ch), packDpi, 96), TRUE);
    };
    put(packSearch, 18, 18, w - 218, 32);
    put(packFilter, w - 188, 18, 170, 180);
    const int listHeight = std::max(110, h - 376);
    put(packList, 18, 62, w - 36, listHeight);
    put(packDetails, 18, 74 + listHeight, w - 36, 138);
    put(packInstall, 18, h - 154, 144, 32);
    put(packImportZip, 174, h - 154, 138, 32);
    put(packImportFolder, 324, h - 154, 138, 32);
    put(packSource, 18, h - 112, 144, 32);
    put(packRefresh, 174, h - 112, 138, 32);
    put(packCancel, 324, h - 112, 138, 32);
    put(packSetup, 474, h - 154, 150, 32);
    put(packClose, w - 112, h - 112, 94, 32);
    put(packNotice, 18, h - 69, w - 36, 43);
    put(packProgress, 18, h - 20, w - 36, 7);
    ListView_SetColumnWidth(packList, 0, MulDiv(std::max(210, w - 380), packDpi, 96));
    ListView_SetColumnWidth(packList, 1, MulDiv(112, packDpi, 96));
    ListView_SetColumnWidth(packList, 2, MulDiv(130, packDpi, 96));
    ListView_SetColumnWidth(packList, 3, MulDiv(92, packDpi, 96));
  }
  void pack_command(int id, int notification) {
    if (id == PACK_SETUP && ready && !analysis_active() && !closing) {
      show_setup();
      if (!setupPollPending && !setupActionPending) setup_send("setup/status");
      return;
    }
    if (id == PACK_CLOSE || id == IDCANCEL) {
      DestroyWindow(packWindow);
      return;
    }
    if ((id == PACK_SEARCH && notification == EN_CHANGE) ||
        (id == PACK_FILTER && notification == CBN_SELCHANGE)) {
      refresh_packs();
      pack_notice();
      return;
    }
    if (id == PACK_CANCEL && packBusy && !packActionPending &&
        packOperation.get("cancellable").boolean(true)) {
      pack_send("packs/cancel");
      return;
    }
    if (!ready || analysis_active() || closing || packBusy || packActionPending ||
        refBusy || refActionPending || setupBusy || setupActionPending)
      return;
    if (id == PACK_REFRESH) {
      pack_send("packs/refresh");
      return;
    }
    if (id == PACK_INSTALL) {
      const auto &item = selected_pack();
      if (getstr(item, "id").empty() || item.get("installed").boolean() ||
          !item.get("compatible").boolean(true) || getstr(item, "sourceId").empty())
        return;
      commit_all();
      packReloadAfterOperation = true;
      pack_send("packs/install", object({{"source_id", getstr(item, "sourceId")},
                                          {"pack_id", getstr(item, "id")},
                                          {"version", getstr(item, "version")}}));
      return;
    }
    if (id == PACK_IMPORT_ZIP || id == PACK_IMPORT_FOLDER || id == PACK_SOURCE) {
      const bool folder = id == PACK_IMPORT_FOLDER;
      auto path = pick(packWindow, folder, false,
                       id == PACK_SOURCE ? L"Catalogue source configuration|*.json"
                                         : L"Tool pack archive|*.zip",
                       id == PACK_SOURCE ? L"Choose a trusted catalogue source configuration"
                       : folder ? L"Choose a trusted tool pack folder containing pack.ini"
                                : L"Choose a trusted tool pack ZIP");
      if (path.empty())
        return;
      const auto prompt = id == PACK_SOURCE
          ? L"Add this catalogue source?\n\nOnly add a source configuration supplied by "
            L"a publisher or institution you trust. Its packs contain programs that "
            L"will run on this computer.\n\nAdding the source does not install tools. "
            L"Use Refresh to retrieve its catalogue."
          : L"Import this tool pack?\n\nTool packs contain programs that run on this "
            L"computer. Only import packs from a publisher or institution you trust.";
      if (MessageBoxW(packWindow, prompt, L"Manage tools",
                       MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES)
        return;
      commit_all();
      if (id != PACK_SOURCE)
        packReloadAfterOperation = true;
      pack_send(id == PACK_SOURCE ? "packs/source" : "packs/import",
                object({{"path", narrow(path)}}));
    }
  }
  static LRESULT CALLBACK pack_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *app = reinterpret_cast<Workspace *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      app = static_cast<Workspace *>(reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      app->packWindow = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app)
      return DefWindowProcW(h, m, w, l);
    try {
      switch (m) {
      case WM_COMMAND:
        app->pack_command(LOWORD(w), HIWORD(w));
        return 0;
      case WM_NOTIFY: {
        auto *n = reinterpret_cast<NMHDR *>(l);
        if (n->idFrom == PACK_LIST && n->code == LVN_ITEMCHANGED &&
            !app->packRebuilding) {
          app->requiredPack = Json::object();
          app->pack_selection();
        }
        return 0;
      }
      case WM_SIZE:
        app->pack_layout();
        return 0;
      case WM_DPICHANGED: {
        app->packDpi = HIWORD(w);
        auto *r = reinterpret_cast<RECT *>(l);
        SetWindowPos(h, nullptr, r->left, r->top, r->right - r->left,
                     r->bottom - r->top, SWP_NOZORDER | SWP_NOACTIVATE);
        app->pack_layout();
        return 0;
      }
      case WM_GETMINMAXINFO: {
        auto *info = reinterpret_cast<MINMAXINFO *>(l);
        info->ptMinTrackSize = {MulDiv(680, app->packDpi, 96),
                                MulDiv(570, app->packDpi, 96)};
        return 0;
      }
      case WM_CTLCOLORSTATIC:
      case WM_CTLCOLOREDIT:
      case WM_CTLCOLORBTN: {
        HDC dc = reinterpret_cast<HDC>(w);
        SetTextColor(dc, INK);
        SetBkColor(dc, BACK);
        return reinterpret_cast<LRESULT>(app->background);
      }
      case WM_CLOSE:
        DestroyWindow(h);
        return 0;
      case WM_NCDESTROY:
        app->packWindow = nullptr;
        app->packRows.clear();
        app->requiredPack = Json::object();
        SetWindowLongPtrW(h, GWLP_USERDATA, 0);
        return DefWindowProcW(h, m, w, l);
      default:
        break;
      }
    } catch (const std::exception &e) {
      MessageBoxW(h, wide(e.what()).c_str(), L"Manage tools", MB_OK | MB_ICONERROR);
    }
    return DefWindowProcW(h, m, w, l);
  }
  void show_pack_manager() {
    if (packWindow) {
      ShowWindow(packWindow, SW_RESTORE);
      SetForegroundWindow(packWindow);
      return;
    }
    WNDCLASSEXW wc{sizeof(wc)};
    wc.lpfnWndProc = pack_proc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = background;
    wc.lpszClassName = L"WorkbenchPackManager060";
    RegisterClassExW(&wc);
    RECT r{};
    GetWindowRect(window, &r);
    packDpi = dpi;
    const int w = px(830), h = px(700);
    packWindow = CreateWindowExW(
        WS_EX_CONTROLPARENT, wc.lpszClassName, L"Manage tools · Native Workbench",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
        r.left + std::max<LONG>(0, (r.right - r.left - w) / 2),
        r.top + std::max<LONG>(0, (r.bottom - r.top - h) / 2), w, h,
        window, nullptr, instance, this);
    if (!packWindow)
      throw std::runtime_error("Could not open the tool manager.");
    packSearch = make(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL,
                       PACK_SEARCH, packWindow, WS_EX_CLIENTEDGE);
    SendMessageW(packSearch, EM_SETCUEBANNER, FALSE,
                 reinterpret_cast<LPARAM>(L"Search tools, descriptions or categories"));
    packFilter = make(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL,
                       PACK_FILTER, packWindow);
    for (const auto *label : {L"All packs", L"Available", L"Installed", L"Updates"})
      SendMessageW(packFilter, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label));
    SendMessageW(packFilter, CB_SETCURSEL, 0, 0);
    packList = make(WC_LISTVIEWW, L"Tool packs",
                     WS_TABSTOP | LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS,
                     PACK_LIST, packWindow, WS_EX_CLIENTEDGE);
    ListView_SetExtendedListViewStyle(packList,
        LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_LABELTIP);
    int column = 0;
    for (const auto *label : {L"Tool pack", L"Pack version", L"Status", L"Download"}) {
      LVCOLUMNW col{};
      col.mask = LVCF_TEXT | LVCF_WIDTH;
      col.pszText = const_cast<wchar_t *>(label);
      col.cx = px(120);
      ListView_InsertColumn(packList, column++, &col);
    }
    packDetails = make(L"EDIT", L"",
        WS_TABSTOP | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | WS_VSCROLL,
        PACK_DETAILS, packWindow, WS_EX_CLIENTEDGE);
    SendMessageW(packDetails, EM_SETLIMITTEXT, 256 * 1024, 0);
    packInstall = button(L"Install selected", PACK_INSTALL, packWindow);
    packImportZip = button(L"Import ZIP...", PACK_IMPORT_ZIP, packWindow);
    packImportFolder = button(L"Import folder...", PACK_IMPORT_FOLDER, packWindow);
    packSource = button(L"Add catalogue...", PACK_SOURCE, packWindow);
    packRefresh = button(L"Refresh", PACK_REFRESH, packWindow);
    packCancel = button(L"Cancel download", PACK_CANCEL, packWindow);
    packClose = button(L"Close", PACK_CLOSE, packWindow);
    packSetup = button(L"Tool setup...", PACK_SETUP, packWindow);
    packNotice = make(L"STATIC", L"Loading installed packs...", SS_LEFT | SS_NOPREFIX,
                       PACK_NOTICE, packWindow);
    packProgress = make(PROGRESS_CLASSW, L"Download progress", PBS_SMOOTH,
                         PACK_PROGRESS, packWindow);
    pack_layout();
    refresh_packs();
    pack_notice();
    ShowWindow(packWindow, SW_SHOW);
    SetFocus(packSearch);
    pack_send("packs/list");
  }
  void pack_response(const std::string &method, const Json &result) {
    packPollFailed = false;
    const auto previousSelection = pack_key(selected_pack());
    if (result.get("packs").is_array()) {
      packState = result;
      refresh_packs(previousSelection);
    }
    if (result.contains("operation"))
      packOperation = result.get("operation");
    packBusy = packOperation.get("active").boolean();
    if (result.contains("model")) {
      snapshot(result.get("model"));
      refresh_tasks();
    }
    const bool operationResponse = method == "packs/status" ||
        method == "packs/install" || method == "packs/import" || method == "packs/refresh";
    if (!packBusy && operationResponse && packReloadAfterOperation) {
      packReloadAfterOperation = false;
      packListAfterOperation = false;
      if (!result.contains("model") && packOperation.get("success").boolean())
        send("init");
      pack_send("packs/list");
    } else if (!packBusy && operationResponse && packListAfterOperation) {
      packListAfterOperation = false;
      if (!result.get("packs").is_array())
        pack_send("packs/list");
    } else if ((method == "packs/source" || method == "packs/refresh") &&
               !packBusy && !result.get("packs").is_array())
      pack_send("packs/list");
    if (packBusy)
      status_text(L"Managing tools: " + wt(packOperation, "message"));
    else if (!getstr(packOperation, "message").empty())
      status_text(wt(packOperation, "message"));
    pack_notice();
    pack_enabled();
    enabled();
    if (closing && !packBusy && !busy && !refBusy && !setupBusy)
      send("shutdown");
  }
  static std::wstring setup_size(long long bytes) {
    std::wostringstream value;
    value << std::fixed << std::setprecision(1);
    if (bytes >= 1000000000LL)
      value << bytes / 1000000000.0 << L" GB";
    else if (bytes >= 1000000)
      value << bytes / 1000000.0 << L" MB";
    else if (bytes >= 1000)
      value << bytes / 1000.0 << L" KB";
    else
      value << bytes << L" bytes";
    return value.str();
  }
  bool setup_selected(const Json &row) const {
    if (setupProfile == "starter")
      return row.get("starter").boolean();
    return setupProfile == "full" || row.get("starter").boolean() ||
           setupChosen.count(getstr(row, "id"));
  }
  void setup_send(const std::string &method, Json params = Json::object()) {
    if (method == "setup/status")
      setupPollPending = true;
    else
      setupActionPending = true;
    send(method, std::move(params));
    enabled();
  }
  void setup_enabled() {
    if (!setupWindow)
      return;
    const bool idle = ready && !analysis_active() && !closing && !packBusy &&
        !packActionPending && !refBusy && !refActionPending &&
        !setupBusy && !setupActionPending;
    bool available = true;
    int selectedCount = 0;
    long long bytes = 0;
    int installed = 0;
    for (const auto &row : setupState.get("rows").array_items()) {
      if (!setup_selected(row)) continue;
      ++selectedCount;
      if (row.get("installed").boolean()) ++installed;
      else {
        bytes += row.get("size").integer();
        available = available && row.get("available").boolean() &&
                    row.get("compatible").boolean(true);
      }
    }
    for (HWND h : {setupFull, setupStarter, setupCustom}) EnableWindow(h, idle);
    // Full and Starter still allow scrolling/selection for inspection; the
    // notification handler only changes checks in Custom.
    // The list is also an inspection surface while transfers are active. Keep
    // scrolling and row selection available; LVN_ITEMCHANGING below prevents
    // edits to the installation selection while it is locked.
    EnableWindow(setupList, ready && !closing);
    EnableWindow(setupRefresh, idle && setupState.get("configured").boolean());
    EnableWindow(setupInstall, idle && selectedCount > 0 && available);
    const auto &operation = setupState.get("operation");
    const auto operationStatus = getstr(operation, "status");
    EnableWindow(setupRetry, idle &&
        (operationStatus == "failed" || operationStatus == "cancelled" ||
         operationStatus == "interrupted"));
    EnableWindow(setupCancel, ready && setupBusy && !setupActionPending &&
        operation.get("cancellable").boolean(true) && operationStatus != "cancelling");
    EnableWindow(setupClose, !setupBusy && !setupActionPending && !closing);
    const std::wstring installLabel = setupProfile == "starter" ? L"Use Starter" :
        bytes == 0 ? L"Use installed selection" : L"Install selection";
    if (control_text(setupInstall) != installLabel)
      SetWindowTextW(setupInstall, installLabel.c_str());
    std::wstring summary = std::to_wstring(selectedCount) + L" packs selected · " +
        std::to_wstring(installed) + L" already installed · " + setup_size(bytes) +
        L" additional download\nReferences, databases and working space are separate.";
    if (control_text(setupTotal) != summary) SetWindowTextW(setupTotal, summary.c_str());
  }
  void setup_refresh_rows() {
    if (!setupWindow) return;
    Json rendered = Json::array();
    for (const auto &row : setupState.get("rows").array_items()) {
      std::wstring status = row.get("installed").boolean() ? L"Installed" :
          !row.get("available").boolean() ? L"Catalogue needed" :
          !row.get("compatible").boolean(true) ? L"Incompatible" : L"Ready to download";
      const auto queueStatus = getstr(row, "status");
      if (!row.get("installed").boolean() && !queueStatus.empty() && queueStatus != "pending")
        status = wide(queueStatus);
      rendered.array_items().push_back(object({
          {"id", getstr(row, "id")}, {"name", getstr(row, "name", getstr(row, "id"))},
          {"version", getstr(row, "version")}, {"status", narrow(status)},
          {"size", narrow(row.get("installed").boolean() ? L"—" : setup_size(row.get("size").integer()))},
          {"checked", setup_selected(row)}}));
    }
    if (rendered.dump() == setupRenderedRows.dump()) {
      setup_enabled();
      return;
    }
    const auto &previous = setupRenderedRows.array_items();
    const auto &next = rendered.array_items();
    bool rebuild = previous.size() != next.size();
    if (!rebuild)
      for (size_t i = 0; i < next.size(); ++i)
        if (getstr(previous[i], "id") != getstr(next[i], "id")) rebuild = true;
    const int first = ListView_GetTopIndex(setupList);
    const int selected = ListView_GetNextItem(setupList, -1, LVNI_SELECTED);
    const int focused = ListView_GetNextItem(setupList, -1, LVNI_FOCUSED);
    auto old_id = [&](int index) {
      return index >= 0 && static_cast<size_t>(index) < previous.size()
          ? getstr(previous[static_cast<size_t>(index)], "id") : std::string{};
    };
    const auto topId = old_id(first), selectedId = old_id(selected), focusedId = old_id(focused);
    RECT oldTop{};
    const bool hadTop = !topId.empty() && ListView_GetItemRect(setupList, first, &oldTop, LVIR_BOUNDS);
    const int horizontal = GetScrollPos(setupList, SB_HORZ);
    setupRebuilding = true;
    if (rebuild) {
      SendMessageW(setupList, WM_SETREDRAW, FALSE, 0);
      ListView_DeleteAllItems(setupList);
    }
    int index = 0;
    for (const auto &row : next) {
      if (rebuild) {
        LVITEMW item{};
        item.iItem = index;
        ListView_InsertItem(setupList, &item);
      }
      int column = 0;
      for (const auto *field : {"name", "version", "status", "size"}) {
        if (rebuild || getstr(row, field) != getstr(previous[static_cast<size_t>(index)], field)) {
          auto value = wt(row, field);
          ListView_SetItemText(setupList, index, column, value.data());
        }
        ++column;
      }
      if (ListView_GetCheckState(setupList, index) != row.get("checked").boolean())
        ListView_SetCheckState(setupList, index, row.get("checked").boolean());
      if (rebuild) {
        const auto id = getstr(row, "id");
        ListView_SetItemState(setupList, index,
            (id == selectedId ? LVIS_SELECTED : 0) | (id == focusedId ? LVIS_FOCUSED : 0),
            LVIS_SELECTED | LVIS_FOCUSED);
      }
      ++index;
    }
    if (rebuild) {
      for (size_t i = 0; hadTop && i < next.size(); ++i) {
        if (getstr(next[i], "id") != topId) continue;
        RECT current{};
        if (ListView_GetItemRect(setupList, static_cast<int>(i), &current, LVIR_BOUNDS))
          ListView_Scroll(setupList, horizontal - GetScrollPos(setupList, SB_HORZ), current.top - oldTop.top);
        break;
      }
      SendMessageW(setupList, WM_SETREDRAW, TRUE, 0);
      InvalidateRect(setupList, nullptr, FALSE);
    }
    setupRenderedRows = std::move(rendered);
    setupRebuilding = false;
    setup_enabled();
  }
  void setup_notice() {
    if (!setupWindow) return;
    const auto &operation = setupState.get("operation");
    std::wstring notice = wt(operation, "message");
    if (notice.empty()) notice = wt(setupState, "notice");
    else if (!setupBusy && !getstr(setupState, "notice").empty() &&
             notice != wt(setupState, "notice")) notice += L"\n" + wt(setupState, "notice");
    if (notice.empty())
      notice = setupState.get("configured").boolean()
          ? L"Refresh the official catalogue to verify available downloads. Nothing is downloaded until you choose an action."
          : L"Online setup is unavailable: no official catalogue is configured. Use Starter now; Manage tools still supports trusted pack imports.";
    const auto operationStatus = getstr(operation, "status");
    if (!getstr(operation, "current").empty() &&
        (setupBusy || operationStatus == "failed" || operationStatus == "cancelled" || operationStatus == "interrupted"))
      notice += L" · " + wt(operation, "current");
    if (setupBusy) {
      if (operation.get("count").integer() > 0)
        notice += L"\n" + std::to_wstring(operation.get("completed").integer()) +
            L" / " + std::to_wstring(operation.get("count").integer()) + L" packs ready";
      if (operation.get("total").integer() > 0)
        notice += L" · " + setup_size(operation.get("bytes").integer()) + L" / " +
            setup_size(operation.get("total").integer()) + L" downloaded";
    }
    if (control_text(setupNotice) != notice) SetWindowTextW(setupNotice, notice.c_str());
    const auto bytes = operation.get("bytes").integer(), total = operation.get("total").integer();
    const auto position = total > 0 ?
        static_cast<WPARAM>(std::clamp(1000.0 * bytes / total, 0.0, 1000.0)) : 0;
    if (SendMessageW(setupProgress, PBM_GETPOS, 0, 0) != static_cast<LRESULT>(position))
      SendMessageW(setupProgress, PBM_SETPOS, position, 0);
    if (!!IsWindowVisible(setupProgress) != setupBusy)
      ShowWindow(setupProgress, setupBusy ? SW_SHOW : SW_HIDE);
  }
  void setup_layout() {
    if (!setupWindow) return;
    RECT area{};
    GetClientRect(setupWindow, &area);
    const int w = MulDiv(area.right, 96, setupDpi), h = MulDiv(area.bottom, 96, setupDpi);
    auto put = [&](HWND control, int x, int y, int cw, int ch) {
      SetWindowPos(control, nullptr, MulDiv(x, setupDpi, 96), MulDiv(y, setupDpi, 96),
          MulDiv(std::max(1, cw), setupDpi, 96), MulDiv(std::max(1, ch), setupDpi, 96),
          SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS);
    };
    put(setupIntro, 18, 18, w - 36, 60);
    const int choiceWidth = (w - 36) / 3;
    put(setupFull, 18, 84, choiceWidth, 32);
    put(setupStarter, 18 + choiceWidth, 84, choiceWidth, 32);
    put(setupCustom, 18 + choiceWidth * 2, 84, choiceWidth, 32);
    put(setupHelp, 18, 128, w - 36, 44);
    const int listHeight = std::max(110, h - 396);
    put(setupList, 18, 184, w - 36, listHeight);
    put(setupTotal, 18, 194 + listHeight, w - 36, 46);
    put(setupRefresh, 18, h - 132, 150, 34);
    put(setupInstall, 180, h - 132, 190, 34);
    put(setupRetry, 382, h - 132, 110, 34);
    put(setupCancel, 504, h - 132, 120, 34);
    put(setupClose, w - 166, h - 132, 148, 34);
    put(setupNotice, 18, h - 87, w - 36, 63);
    put(setupProgress, 18, h - 17, w - 36, 7);
    int column = 0;
    for (const int logicalWidth : {std::max(230, w - 385), 90, 160, 99}) {
      const int desired = MulDiv(logicalWidth, setupDpi, 96);
      if (ListView_GetColumnWidth(setupList, column) != desired)
        ListView_SetColumnWidth(setupList, column, desired);
      ++column;
    }
    RedrawWindow(setupWindow, nullptr, nullptr, RDW_INVALIDATE | RDW_ALLCHILDREN);
  }
  void setup_command(int id) {
    if (id == SETUP_CLOSE || id == IDCANCEL) {
      if (!setupBusy && !setupActionPending) {
        setup_send("setup/dismiss");
        DestroyWindow(setupWindow);
      }
      return;
    }
    if (id == SETUP_CANCEL && setupBusy && !setupActionPending &&
        setupState.get("operation").get("cancellable").boolean(true)) {
      setup_send("setup/cancel");
      return;
    }
    if (!ready || analysis_active() || closing || packBusy || packActionPending ||
        refBusy || refActionPending || setupBusy || setupActionPending) return;
    if (id == SETUP_FULL || id == SETUP_STARTER || id == SETUP_CUSTOM) {
      setupProfile = id == SETUP_FULL ? "full" : id == SETUP_STARTER ? "starter" : "custom";
      CheckRadioButton(setupWindow, SETUP_FULL, SETUP_CUSTOM, id);
      setup_refresh_rows();
      return;
    }
    if (id == SETUP_REFRESH) setup_send("setup/refresh");
    else if (id == SETUP_RETRY) {
      commit_all();
      setup_send("setup/retry");
    } else if (id == SETUP_INSTALL) {
      Json ids = Json::array();
      for (const auto &row : setupState.get("rows").array_items())
        if (setup_selected(row)) ids.array_items().push_back(getstr(row, "id"));
      commit_all();
      Json request = object({{"profile", setupProfile}});
      if (setupProfile == "custom") request["pack_ids"] = std::move(ids);
      setup_send("setup/start", std::move(request));
    }
  }
  static LRESULT CALLBACK setup_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *app = reinterpret_cast<Workspace *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      app = static_cast<Workspace *>(reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      app->setupWindow = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app) return DefWindowProcW(h, m, w, l);
    try {
      switch (m) {
      case WM_COMMAND:
        app->setup_command(LOWORD(w));
        return 0;
      case WM_NOTIFY: {
        auto *notice = reinterpret_cast<NMHDR *>(l);
        if (notice->idFrom == SETUP_LIST && notice->code == LVN_ITEMCHANGING && !app->setupRebuilding) {
          const auto *change = reinterpret_cast<NMLISTVIEW *>(l);
          const auto &rows = app->setupState.get("rows").array_items();
          if (change->iItem >= 0 && static_cast<size_t>(change->iItem) < rows.size() &&
              (change->uChanged & LVIF_STATE) &&
              ((change->uOldState ^ change->uNewState) & LVIS_STATEIMAGEMASK))
            return app->setupProfile != "custom" || rows[static_cast<size_t>(change->iItem)].get("starter").boolean() ||
                app->setupBusy || app->setupActionPending || app->analysis_active() || app->closing ||
                app->packBusy || app->packActionPending || app->refBusy || app->refActionPending;
        }
        if (notice->idFrom == SETUP_LIST && notice->code == LVN_ITEMCHANGED && !app->setupRebuilding) {
          const auto *change = reinterpret_cast<NMLISTVIEW *>(l);
          const auto &rows = app->setupState.get("rows").array_items();
          if (change->iItem >= 0 && static_cast<size_t>(change->iItem) < rows.size() &&
              (change->uChanged & LVIF_STATE) &&
              ((change->uOldState ^ change->uNewState) & LVIS_STATEIMAGEMASK)) {
            const auto &row = rows[static_cast<size_t>(change->iItem)];
            if (app->setupProfile != "custom" || row.get("starter").boolean() ||
                app->setupBusy || app->setupActionPending) {
              app->setupRebuilding = true;
              ListView_SetCheckState(app->setupList, change->iItem, app->setup_selected(row));
              app->setupRebuilding = false;
            } else if (ListView_GetCheckState(app->setupList, change->iItem))
              app->setupChosen.insert(getstr(row, "id"));
            else app->setupChosen.erase(getstr(row, "id"));
            // A local checkbox edit changes the rendered row before the next
            // backend reply. Keep the cache synchronized so an immediate
            // profile switch cannot mistake the old checks for current ones.
            if (static_cast<size_t>(change->iItem) < app->setupRenderedRows.array_items().size())
              app->setupRenderedRows.array_items()[static_cast<size_t>(change->iItem)]["checked"] =
                  !!ListView_GetCheckState(app->setupList, change->iItem);
            app->setup_enabled();
          }
        }
        return 0;
      }
      case WM_SIZE: app->setup_layout(); return 0;
      case WM_DPICHANGED: {
        app->setupDpi = HIWORD(w);
        auto *area = reinterpret_cast<RECT *>(l);
        SetWindowPos(h, nullptr, area->left, area->top, area->right - area->left,
            area->bottom - area->top, SWP_NOZORDER | SWP_NOACTIVATE);
        app->setup_layout();
        return 0;
      }
      case WM_GETMINMAXINFO:
        reinterpret_cast<MINMAXINFO *>(l)->ptMinTrackSize = {
            MulDiv(830, app->setupDpi, 96), MulDiv(650, app->setupDpi, 96)};
        return 0;
      case WM_CTLCOLORSTATIC:
      case WM_CTLCOLOREDIT:
      case WM_CTLCOLORBTN:
        SetTextColor(reinterpret_cast<HDC>(w), INK);
        SetBkColor(reinterpret_cast<HDC>(w), BACK);
        return reinterpret_cast<LRESULT>(app->background);
      case WM_CLOSE: app->setup_command(SETUP_CLOSE); return 0;
      case WM_NCDESTROY:
        app->setupWindow = nullptr;
        app->setupRenderedRows = Json::array();
        SetWindowLongPtrW(h, GWLP_USERDATA, 0);
        break;
      default: break;
      }
    } catch (const std::exception &error) {
      MessageBoxW(h, wide(error.what()).c_str(), L"Tool setup", MB_OK | MB_ICONERROR);
    }
    return DefWindowProcW(h, m, w, l);
  }
  void show_setup() {
    if (setupWindow) {
      ShowWindow(setupWindow, SW_RESTORE);
      SetForegroundWindow(setupWindow);
      return;
    }
    WNDCLASSEXW klass{sizeof(klass)};
    klass.lpfnWndProc = setup_proc;
    klass.hInstance = instance;
    klass.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    klass.hbrBackground = background;
    klass.hIcon = appIcon;
    klass.hIconSm = appSmallIcon;
    klass.lpszClassName = L"WorkbenchToolSetup0100";
    RegisterClassExW(&klass);
    RECT area{};
    GetWindowRect(window, &area);
    setupDpi = dpi;
    const int w = px(920), h = px(720);
    // The report list provides its own double buffering. Leave its native
    // header in charge of painting rather than nesting it inside top-level
    // descendant compositing, which also repaints unchanged child controls.
    setupWindow = CreateWindowExW(WS_EX_CONTROLPARENT,
        klass.lpszClassName, L"Tool setup · Native Workbench",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
        area.left + std::max<LONG>(0, (area.right - area.left - w) / 2),
        area.top + std::max<LONG>(0, (area.bottom - area.top - h) / 2),
        w, h, window, nullptr, instance, this);
    if (!setupWindow) throw std::runtime_error("Could not open tool setup.");
    setupIntro = make(L"STATIC", L"Choose your tools\nFull installs the complete current selection. Starter is ready offline. You can add more packs later in Manage tools.",
        SS_LEFT | SS_NOPREFIX, 0, setupWindow);
    setupFull = make(L"BUTTON", L"&Full — recommended", WS_TABSTOP | WS_GROUP | BS_AUTORADIOBUTTON,
        SETUP_FULL, setupWindow);
    setupStarter = make(L"BUTTON", L"&Starter", WS_TABSTOP | BS_AUTORADIOBUTTON, SETUP_STARTER, setupWindow);
    setupCustom = make(L"BUTTON", L"&Custom", WS_TABSTOP | BS_AUTORADIOBUTTON, SETUP_CUSTOM, setupWindow);
    CheckRadioButton(setupWindow, SETUP_FULL, SETUP_CUSTOM,
        setupProfile == "full" ? SETUP_FULL : setupProfile == "starter" ? SETUP_STARTER : SETUP_CUSTOM);
    setupHelp = make(L"STATIC", L"Choose Custom to select individual packs. Downloads require internet access. Completed packs remain installed after cancellation; existing versions and saved workflows are retained.",
        SS_LEFT | SS_NOPREFIX, 0, setupWindow);
    setupList = make(WC_LISTVIEWW, L"Choose tool packs", WS_TABSTOP | LVS_REPORT | LVS_SHOWSELALWAYS,
        SETUP_LIST, setupWindow, WS_EX_CLIENTEDGE);
    ListView_SetExtendedListViewStyle(setupList, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_CHECKBOXES | LVS_EX_LABELTIP);
    int column = 0;
    for (const auto *label : {L"Tool pack", L"Version", L"Status", L"Download"}) {
      LVCOLUMNW col{};
      col.mask = LVCF_TEXT | LVCF_WIDTH;
      col.pszText = const_cast<wchar_t *>(label);
      col.cx = px(120);
      ListView_InsertColumn(setupList, column++, &col);
    }
    setupTotal = make(L"STATIC", L"", SS_LEFT | SS_NOPREFIX, SETUP_TOTAL, setupWindow);
    setupRefresh = button(L"Refresh catalogue", SETUP_REFRESH, setupWindow);
    setupInstall = button(L"Install selection", SETUP_INSTALL, setupWindow);
    setupRetry = button(L"Retry", SETUP_RETRY, setupWindow);
    setupCancel = button(L"Cancel", SETUP_CANCEL, setupWindow);
    setupClose = button(L"Use Workbench", SETUP_CLOSE, setupWindow);
    setupNotice = make(L"STATIC", L"Loading tool selection...", SS_LEFT | SS_NOPREFIX, SETUP_NOTICE, setupWindow);
    setupProgress = make(PROGRESS_CLASSW, L"Tool installation progress", PBS_SMOOTH, SETUP_PROGRESS, setupWindow);
    SendMessageW(setupProgress, PBM_SETRANGE32, 0, 1000);
    setup_refresh_rows();
    setup_notice();
    setup_layout();
    ShowWindow(setupWindow, SW_SHOW);
    SetForegroundWindow(setupWindow);
    SetFocus(setupFull);
  }
  void setup_response(const std::string &method, const Json &result) {
    setupPollFailed = false;
    setupState = result;
    setupBusy = result.get("operation").get("active").boolean();
    if (!setupSelectionLoaded && result.get("rows").is_array()) {
      setupSelectionLoaded = true;
      const auto &selection = result.get("selection");
      const auto profile = getstr(selection, "profile");
      if (profile == "full" || profile == "starter" || profile == "custom") setupProfile = profile;
      if (selection.get("pack_ids").is_array())
        for (const auto &id : selection.get("pack_ids").array_items()) setupChosen.insert(text(id));
      else for (const auto &row : result.get("rows").array_items()) setupChosen.insert(getstr(row, "id"));
    }
    if (result.contains("model")) {
      snapshot(result.get("model"));
      refresh_tasks();
    }
    if (!setupWelcomeChecked && method == "setup/status") {
      setupWelcomeChecked = true;
      if (result.get("offered").boolean()) show_setup();
    }
    if (setupWindow) {
      const int selected = setupProfile == "full" ? SETUP_FULL : setupProfile == "starter" ? SETUP_STARTER : SETUP_CUSTOM;
      if (SendMessageW(GetDlgItem(setupWindow, selected), BM_GETCHECK, 0, 0) != BST_CHECKED)
        CheckRadioButton(setupWindow, SETUP_FULL, SETUP_CUSTOM, selected);
    }
    setup_refresh_rows();
    setup_notice();
    enabled();
    if (closing && !setupBusy && !busy && !packBusy && !refBusy) send("shutdown");
  }
  static std::wstring reference_species(const Json &item) {
    const auto &species = item.get("species");
    return species.is_object() ? wt(species, "name", getstr(species, "id"))
                               : wide(text(species));
  }
  const Json &reference_local_record() const {
    static const Json empty = Json::object();
    if (!refWindow)
      return empty;
    const int row = ListView_GetNextItem(refLocal, -1, LVNI_SELECTED);
    if (row < 0 || static_cast<size_t>(row) >= refLocalRows.size())
      return empty;
    const auto index = refLocalRows[static_cast<size_t>(row)].first;
    const auto &items = refState.get("local").array_items();
    return index < items.size() ? items[index] : empty;
  }
  const Json &reference_local_file() const {
    static const Json empty = Json::object();
    if (!refWindow)
      return empty;
    const int row = ListView_GetNextItem(refLocal, -1, LVNI_SELECTED);
    if (row < 0 || static_cast<size_t>(row) >= refLocalRows.size())
      return empty;
    const auto index = refLocalRows[static_cast<size_t>(row)].second;
    const auto &record = reference_local_record();
    if (!record.get("files").is_array())
      return empty;
    const auto &files = record.get("files").array_items();
    return index < files.size() ? files[index] : empty;
  }
  const Json &reference_selected_species() const {
    static const Json empty = Json::object();
    if (!refWindow)
      return empty;
    const int row = ListView_GetNextItem(refSpecies, -1, LVNI_SELECTED);
    if (row < 0)
      return empty;
    const auto &items = refState.get("species").array_items();
    return static_cast<size_t>(row) < items.size()
               ? items[static_cast<size_t>(row)] : empty;
  }
  void reference_send(const std::string &method, Json params = Json::object()) {
    if (method == "references/status")
      refPollPending = true;
    else
      refActionPending = true;
    send(method, std::move(params));
    enabled();
  }
  void reference_text(HWND control, const std::wstring &value) {
    if (control && control_text(control) != value)
      SetWindowTextW(control, value.c_str());
  }
  void reference_invalidate_review() {
    const auto token = getstr(refReview, "token");
    if (!token.empty()) refInvalidReviewTokens.insert(token);
    refReview = Json::object();
    reference_notice();
  }
  Json reference_release_value() const {
    const auto release = control_text(refRelease);
    if (!release.empty() && std::all_of(release.begin(), release.end(),
        [](wchar_t c) { return c >= L'0' && c <= L'9'; }))
      return std::stoi(release);
    return narrow(release);
  }
  const Json &reference_provider() const {
    static const Json empty;
    const auto index = SendMessageW(refProvider, CB_GETCURSEL, 0, 0);
    const auto &providers = refState.get("providers").array_items();
    return index >= 0 && static_cast<size_t>(index) < providers.size()
        ? providers[static_cast<size_t>(index)] : empty;
  }
  const Json &reference_pending() const {
    static const Json empty;
    const int row = ListView_GetNextItem(refPending, -1, LVNI_SELECTED);
    if (row < 0 || static_cast<size_t>(row) >= refPendingIds.size()) return empty;
    for (const auto &job : refState.get("pending").array_items())
      if (getstr(job, "id") == refPendingIds[static_cast<size_t>(row)]) return job;
    return empty;
  }
  void reference_provider_controls(bool resetRelease) {
    const auto &provider = reference_provider();
    const auto wanted = resetRelease ? wide(text(provider.get("default_release")))
                                    : control_text(refRelease);
    SendMessageW(refRelease, CB_RESETCONTENT, 0, 0);
    Json releases = provider.get("releases");
    if (!releases.is_array()) {
      if (provider.get("default_release").is_string()) {
        releases = Json::array(); releases.array_items().push_back(provider.get("default_release"));
      } else if (provider.get("min_release").is_number() && provider.get("max_release").is_number()) {
        releases = Json::array();
        const auto minimum = provider.get("min_release").integer(), maximum = provider.get("max_release").integer();
        for (auto value = maximum; value >= minimum && maximum - value < 256; --value)
          releases.array_items().push_back(static_cast<int>(value));
      } else releases = refState.get("releases");
    }
    int selectedIndex = 0, count = 0;
    for (const auto &release : releases.array_items()) {
      const auto label = wide(text(release));
      SendMessageW(refRelease, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str()));
      if (label == wanted) selectedIndex = count;
      ++count;
    }
    if (!count) {
      const auto label = wanted.empty() ? L"116" : wanted;
      SendMessageW(refRelease, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str()));
    }
    SendMessageW(refRelease, CB_SETCURSEL, selectedIndex, 0);
    reference_text(refReleaseLabel, wt(provider, "release_label", "Release"));
    const auto hint = wt(provider, "search_label", "Species name, e.g. human or Saccharomyces");
    SendMessageW(refQuery, EM_SETCUEBANNER, FALSE, reinterpret_cast<LPARAM>(hint.c_str()));
  }
  void reference_review() {
    if (!refWindow || refBusy || refActionPending || getstr(refReview, "token").empty()) return;
    const auto kind = getstr(refReview, "kind"), token = getstr(refReview, "token");
    if (kind != "import" && kind != "relocate") return;
    const bool importing = kind == "import";
    Modal modal;
    modal.owner = refWindow; modal.font = refFont; modal.dpi = refDpi; modal.mode = 2;
    modal.title = importing ? L"Review local reference import" : L"Review library relocation";
    modal.message = importing ? L"Review the declared identity and verified files before importing."
                              : L"Review the copy and library switch. Original files will be retained.";
    modal.confirm = importing ? L"Import files" : L"Copy and switch";
    modal.value = wt(refReview, "notice") + L"\n\nDestination: " + wt(refReview, "destination") + L"\n";
    const auto &metadata = refReview.get("metadata");
    for (const auto &field : {"label", "species", "assembly", "assembly_accession", "source", "release"})
      if (!metadata.get(field).is_null()) modal.value += wide(field) + L": " + wide(text(metadata.get(field))) + L"\n";
    modal.value += importing
        ? L"\nMetadata is your declaration. File hashes establish exact bytes, not publisher identity.\n"
        : L"\nSaved workflows and queued plans may still use original paths. No original files will be removed.\n";
    const Json noItems = Json::array();
    const auto &files = refReview.get("files").is_array() ? refReview.get("files") : noItems;
    for (const auto &file : files.array_items()) {
      modal.value += L"\n" + wt(file, "label", getstr(file, "kind", getstr(file, "name"))) +
          L"\nOriginal: " + wt(file, "path", getstr(file, "source")) + L"\n";
      if (file.get("compressed").boolean())
        modal.value += L"Original gzip bytes: " + wide(text(file.get("source_bytes"))) +
                       L"\nOriginal gzip SHA-256: " + wt(file, "source_sha256") + L"\n";
      modal.value += L"Library file: " + wt(file, "filename") + L"\n";
      if (file.contains("bytes")) modal.value += L"Expanded file bytes: " + wide(text(file.get("bytes"))) + L"\n";
      if (!getstr(file, "sha256").empty()) modal.value += L"Expanded file SHA-256: " + wt(file, "sha256") + L"\n";
    }
    const auto &records = refReview.get("records").is_array() ? refReview.get("records") : noItems;
    for (const auto &record : records.array_items()) {
      modal.value += L"\n" + wt(record, "label", getstr(record, "id")) + L"\nOriginal: " + wt(record, "folder") + L"\n";
      if (record.get("files").is_array())
        for (const auto &file : record.get("files").array_items())
          modal.value += wt(file, "filename") + L" · " + download_size(file.get("bytes").integer()) +
                         L"\nSHA-256: " + wt(file, "sha256") + L"\n";
    }
    if (refReview.contains("bytes")) modal.value += L"\nTotal data: " + download_size(refReview.get("bytes").integer());
    if (refReview.contains("bundles")) modal.value += L"\nBundles: " + wide(text(refReview.get("bundles")));
    struct Reviewing { bool &flag; explicit Reviewing(bool &value) : flag(value) { flag = true; } ~Reviewing() { flag = false; } } guard(refReviewOpen);
    if (modal.show() && refWindow && getstr(refReview, "token") == token && !refBusy && !refActionPending) {
      reference_invalidate_review();
      reference_send(importing ? "references/import" : "references/relocate", object({{"token", token}}));
    }
    reference_enabled();
  }
  void reference_enabled() {
    if (!refWindow)
      return;
    const bool idle = ready && !analysis_active() && !closing && !setupBusy && !setupActionPending && !packBusy &&
                      !packActionPending && !refBusy && !refActionPending &&
                      !activeRequest && outgoing.empty();
    for (HWND h : {refProvider, refRelease, refQuery, refSearch, refSpecies, refFiles,
                   refDestination, refBrowse, refLocal, refTarget, refPending, refRelocate})
      EnableWindow(h, idle);
    bool hasImport = false;
    for (HWND h : refImportPaths) {
      EnableWindow(h, idle);
      hasImport = hasImport || !control_text(h).empty();
    }
    for (HWND h : refImportBrowse) EnableWindow(h, idle);
    for (HWND h : refImportMetadata) EnableWindow(h, idle);
    EnableWindow(refImportPreview, idle && hasImport && !control_text(refDestination).empty());
    EnableWindow(refReviewButton, idle && !getstr(refReview, "token").empty());
    const auto &pending = reference_pending();
    EnableWindow(refResume, idle && !getstr(pending, "id").empty() && pending.get("resumable").boolean());
    EnableWindow(refDiscard, idle && !getstr(pending, "id").empty());
    EnableWindow(refDiscover, idle &&
                 !getstr(reference_selected_species(), "id").empty());
    bool checked = false;
    for (int row = 0; row < ListView_GetItemCount(refFiles); ++row)
      checked = checked || ListView_GetCheckState(refFiles, row);
    EnableWindow(refDownload, idle && checked &&
                 !getstr(refState.get("discovery"), "selection_id").empty() &&
                 !control_text(refDestination).empty());
    EnableWindow(refOpen, idle && !getstr(reference_local_record(), "id").empty());
    EnableWindow(refTarget, idle && reference_local_record().get("available").boolean(true));
    EnableWindow(refUse, idle && !showingHistory &&
                 reference_local_record().get("available").boolean(true) &&
                 SendMessageW(refTarget, CB_GETCURSEL, 0, 0) >= 0 &&
                 !refTargets.array_items().empty());
    EnableWindow(refCancel, ready && refBusy && !refActionPending &&
                 refOperation.get("cancellable").boolean(true) &&
                 getstr(refOperation, "status") != "cancelling" &&
                 getstr(refOperation, "status") != "pausing");
    const auto action = getstr(refOperation, "action");
    EnableWindow(refPause, ready && refBusy && !refActionPending &&
                 (action == "download" || action == "resume") &&
                 refOperation.get("cancellable").boolean(true) &&
                 getstr(refOperation, "status") != "cancelling" &&
                 getstr(refOperation, "status") != "pausing");
  }
  void reference_details() {
    if (!refWindow)
      return;
    std::wstring value;
    const int tab = TabCtrl_GetCurSel(refTab);
    if (tab == 2) {
      const auto &job = reference_pending();
      value = getstr(job, "id").empty()
          ? L"Paused and interrupted downloads remain here until resumed or discarded. No incomplete file is available as an input."
          : wt(job, "label") + L"\nProvider: " + wt(job, "provider") + L"\nStatus: " + wt(job, "status") +
            L"\nDestination: " + wt(job, "destination") + L"\n" + wt(job, "error");
      if (!getstr(job, "id").empty())
        value += job.get("resumable").boolean()
            ? L"\nResume verifies saved transfer identity before continuing."
            : L"\nThis transfer cannot currently be resumed. Inspect the error before discarding it.";
    } else if (tab == 3) {
      value = L"Choose one file for each needed resource role. Plain FASTA/GTF and gzip files are supported. "
              L"Files are copied into a verified library bundle; originals are preserved. "
              L"Your metadata is recorded as user-declared, without a publisher claim.";
    } else if (tab == 1) {
      const auto &record = reference_local_record(), &file = reference_local_file();
      if (!getstr(record, "id").empty()) {
        if (!record.get("available").boolean(true))
          value = L"Unavailable: " + wt(record, "error", "This reference bundle needs attention.") + L"\n";
        value += reference_species(record) + L"  ·  " + wt(record, "assembly") +
                L"  ·  " + wt(record, "provider_name", getstr(record, "provider", "Reference")) + L" / " + wt(record, "release") +
                L"\nAssembly accession: " + wt(record, "assembly_accession", "Not recorded") +
                L"\n" + wt(file, "path") + L"\nSHA-256: " + wt(file, "sha256") +
                L"\nDownload record: " + wt(record, "receipt_path");
        if (record.get("warnings").is_array())
          for (const auto &warning : record.get("warnings").array_items())
            value += L"\nWarning: " + wide(text(warning));
        if (!getstr(record, "integrity_notice").empty()) value += L"\n" + wt(record, "integrity_notice");
      } else
        value = L"No local reference files yet. Find and download references online, or import your own FASTA/GTF files.";
      const auto omitted = refState.get("omitted_local").integer();
      if (omitted > 0)
        value += L"\nLibrary display limit: " + std::to_wstring(omitted) +
                 L" older reference bundles are not shown here. Their files remain on disk.";
    } else {
      const auto &discovery = refState.get("discovery");
      value = wt(discovery, "notice");
      if (!getstr(discovery, "selection_id").empty()) {
        const auto &species = discovery.get("species");
        value = reference_species(discovery) + L"  ·  " +
                wt(discovery, "assembly", getstr(species, "assembly")) +
                L"  ·  " + wt(reference_provider(), "name", "Reference") + L" / " + wt(discovery, "release") +
                L"\nAssembly accession: " + wt(discovery, "assembly_accession",
                    getstr(species, "assembly_accession", "Not recorded")) + L"\n" + value;
        if (discovery.get("warnings").is_array())
          for (const auto &warning : discovery.get("warnings").array_items())
            value += L"\nWarning: " + wide(text(warning));
        const int row = ListView_GetNextItem(refFiles, -1, LVNI_SELECTED);
        const auto &files = discovery.get("files").array_items();
        if (row >= 0 && static_cast<size_t>(row) < files.size()) {
          const auto &file = files[static_cast<size_t>(row)];
          value += L"\n" + wt(file, "filename") + L"\n" + wt(file, "detail");
          value += L"\nPublished transfer checksums and gzip integrity are checked; local SHA-256 hashes "
                   L"record exact bytes. Transfer checksums are not publisher signatures.";
        }
      }
      if (value.empty())
        value = L"Select a species, then Find files. Genome, annotation and transcript files "
                L"are tied to the selected release and assembly. Downloads are unpacked to "
                L"plain local files with a provenance record.";
    }
    reference_text(refDetails, lines(value));
    reference_enabled();
  }
  void reference_targets() {
    refTargets = Json::array();
    if (!refWindow)
      return;
    SendMessageW(refTarget, CB_RESETCONTENT, 0, 0);
    const auto &record = reference_local_record(), &file = reference_local_file();
    if (ready && !refBusy && !refActionPending && !packBusy && !analysis_active() && !setupBusy && !setupActionPending &&
        !closing && !showingHistory && !getstr(file, "id").empty() &&
        record.get("available").boolean(true))
      reference_send("references/targets", object({{"record_id", getstr(record, "id")},
                                                   {"file_id", getstr(file, "id")}}));
    reference_details();
  }
  void reference_refresh(const Json &previous) {
    if (!refWindow)
      return;
    refRebuilding = true;
    const bool providersChanged = previous.get("providers").dump() != refState.get("providers").dump();
    if (providersChanged) {
      const auto active = getstr(refState, "active_provider");
      SendMessageW(refProvider, CB_RESETCONTENT, 0, 0);
      int chosen = 0, index = 0;
      for (const auto &provider : refState.get("providers").array_items()) {
        const auto label = wt(provider, "name", getstr(provider, "id"));
        SendMessageW(refProvider, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str()));
        if (getstr(provider, "id") == active) chosen = index;
        ++index;
      }
      SendMessageW(refProvider, CB_SETCURSEL, chosen, 0);
    }
    if (providersChanged || previous.get("releases").dump() != refState.get("releases").dump())
      reference_provider_controls(providersChanged);
    if (previous.get("default_destination").dump() != refState.get("default_destination").dump() &&
        (control_text(refDestination).empty() ||
         control_text(refDestination) == wt(previous, "default_destination") || previous.get("local").is_null()))
      reference_text(refDestination, wt(refState, "default_destination", narrow(root + L"\\user-data\\references")));
    const auto &jobs = refState.get("pending").array_items();
    std::vector<std::string> ids;
    for (const auto &job : jobs) ids.push_back(getstr(job, "id"));
    const bool pendingChanged = ids != refPendingIds;
    std::string keepJob;
    const int oldSelected = ListView_GetNextItem(refPending, -1, LVNI_SELECTED);
    if (oldSelected >= 0 && static_cast<size_t>(oldSelected) < refPendingIds.size())
      keepJob = refPendingIds[static_cast<size_t>(oldSelected)];
    if (pendingChanged) {
      SendMessageW(refPending, WM_SETREDRAW, FALSE, 0);
      ListView_DeleteAllItems(refPending);
      refPendingIds = ids;
    }
    for (size_t index = 0; index < jobs.size(); ++index) {
      const auto &job = jobs[index];
      const auto row = static_cast<int>(index);
      std::vector<std::wstring> cells{wt(job, "label", getstr(job, "id")), wt(job, "status"),
          download_size(job.get("bytes").integer()) + L" / " + download_size(job.get("total").integer())};
      if (pendingChanged) {
        LVITEMW item{}; item.mask = LVIF_TEXT; item.iItem = row; item.pszText = cells[0].data();
        ListView_InsertItem(refPending, &item);
      }
      for (size_t column = 0; column < cells.size(); ++column) {
        wchar_t existing[4096]{};
        ListView_GetItemText(refPending, row, static_cast<int>(column), existing, 4096);
        if (cells[column] != existing)
          ListView_SetItemText(refPending, row, static_cast<int>(column), cells[column].data());
      }
      if (pendingChanged && ((keepJob.empty() && index == 0) || getstr(job, "id") == keepJob))
        ListView_SetItemState(refPending, row, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
    }
    if (pendingChanged) {
      SendMessageW(refPending, WM_SETREDRAW, TRUE, 0);
      RedrawWindow(refPending, nullptr, nullptr, RDW_INVALIDATE | RDW_ALLCHILDREN);
    }
    if (previous.get("species").dump() != refState.get("species").dump()) {
      ListView_DeleteAllItems(refSpecies);
      for (const auto &species : refState.get("species").array_items()) {
        LVITEMW row{};
        row.mask = LVIF_TEXT;
        row.iItem = ListView_GetItemCount(refSpecies);
        auto label = wt(species, "name", getstr(species, "id"));
        row.pszText = label.data();
        ListView_InsertItem(refSpecies, &row);
        auto assembly = wt(species, "assembly") + L" · " + wt(species, "release"),
             accession = wt(species, "assembly_accession");
        ListView_SetItemText(refSpecies, row.iItem, 1, assembly.data());
        ListView_SetItemText(refSpecies, row.iItem, 2, accession.data());
      }
      if (ListView_GetItemCount(refSpecies))
        ListView_SetItemState(refSpecies, 0, LVIS_SELECTED | LVIS_FOCUSED,
                             LVIS_SELECTED | LVIS_FOCUSED);
    }
    if (previous.get("discovery").dump() != refState.get("discovery").dump()) {
      ListView_DeleteAllItems(refFiles);
      // A new species search deliberately clears the previous discovery.
      const auto &files = refState.get("discovery").get("files");
      if (files.is_array()) {
        for (const auto &file : files.array_items()) {
          LVITEMW row{};
          row.mask = LVIF_TEXT;
          row.iItem = ListView_GetItemCount(refFiles);
          auto label = wt(file, "label", getstr(file, "kind"));
          row.pszText = label.data();
          ListView_InsertItem(refFiles, &row);
          auto filename = wt(file, "filename"), size = download_size(file.get("bytes").integer());
          ListView_SetItemText(refFiles, row.iItem, 1, filename.data());
          ListView_SetItemText(refFiles, row.iItem, 2, size.data());
        }
      }
    }
    if (previous.get("local").dump() != refState.get("local").dump()) {
      // Resolve previous row identities against the previous snapshot, not the new one.
      std::string keepRecord, keepFile;
      int selectedRow = ListView_GetNextItem(refLocal, -1, LVNI_SELECTED);
      if (selectedRow >= 0 && static_cast<size_t>(selectedRow) < refLocalRows.size()) {
        const auto pair = refLocalRows[static_cast<size_t>(selectedRow)];
        const auto &oldRecords = previous.get("local").array_items();
        if (pair.first < oldRecords.size()) {
          const auto &old = oldRecords[pair.first];
          keepRecord = getstr(old, "id");
          if (pair.second < old.get("files").array_items().size())
            keepFile = getstr(old.get("files").array_items()[pair.second], "id");
        }
      }
      ListView_DeleteAllItems(refLocal);
      refLocalRows.clear();
      const auto &records = refState.get("local").array_items();
      selectedRow = -1;
      for (size_t r = 0; r < records.size(); ++r) {
        const auto &record = records[r];
        const auto &files = record.get("files").array_items();
        for (size_t f = 0; f < files.size(); ++f) {
          const auto &file = files[f];
          LVITEMW row{};
          row.mask = LVIF_TEXT;
          row.iItem = static_cast<int>(refLocalRows.size());
          auto label = reference_species(record);
          if (!record.get("available").boolean(true))
            label += L" · unavailable";
          row.pszText = label.data();
          ListView_InsertItem(refLocal, &row);
          auto assembly = wt(record, "assembly") + L" · " + wt(record, "release"),
               kind = wt(file, "label", getstr(file, "kind")),
               size = download_size(file.get("bytes").integer());
          ListView_SetItemText(refLocal, row.iItem, 1, assembly.data());
          ListView_SetItemText(refLocal, row.iItem, 2, kind.data());
          ListView_SetItemText(refLocal, row.iItem, 3, size.data());
          if (getstr(record, "id") == keepRecord && getstr(file, "id") == keepFile)
            selectedRow = row.iItem;
          refLocalRows.push_back({r, f});
        }
      }
      if (selectedRow < 0 && !refLocalRows.empty())
        selectedRow = 0;
      if (selectedRow >= 0)
        ListView_SetItemState(refLocal, selectedRow, LVIS_SELECTED | LVIS_FOCUSED,
                             LVIS_SELECTED | LVIS_FOCUSED);
      refTargets = Json::array();
      SendMessageW(refTarget, CB_RESETCONTENT, 0, 0);
    }
    refRebuilding = false;
    reference_details();
  }
  void reference_notice() {
    if (!refWindow)
      return;
    auto value = wt(refOperation, "message", getstr(refState, "notice"));
    if (value.empty())
      value = L"Search and download contact the selected provider. Local library operations stay offline.";
    if (!getstr(refReview, "token").empty())
      value = L"Review is ready. Choose Review changes to confirm; nothing has been imported or relocated yet.";
    else if (!refBusy && refInvalidReviewTokens.count(getstr(refState.get("review"), "token")))
      value = L"The previous review was invalidated. Check the current selection again before confirming changes.";
    const auto omitted = refState.get("omitted_local").integer();
    if (omitted > 0)
      value += L"  " + std::to_wstring(omitted) +
               L" older bundles are outside the library display limit; their files remain on disk.";
    const auto bytes = refOperation.get("bytes").integer(),
               total = refOperation.get("total").integer();
    if (refBusy && bytes > 0)
      value += L"  " + download_size(bytes) +
               (total > 0 ? L" / " + download_size(total) : L"");
    reference_text(refNotice, value);
    const auto position = total > 0 ? static_cast<WPARAM>(std::clamp(
                   1000.0 * static_cast<double>(bytes) / static_cast<double>(total),
                   0.0, 1000.0)) : 0;
    if (static_cast<WPARAM>(SendMessageW(refProgress, PBM_GETPOS, 0, 0)) != position)
      SendMessageW(refProgress, PBM_SETPOS, position, 0);
    ShowWindow(refProgress, refBusy ? SW_SHOW : SW_HIDE);
    reference_text(refClose, refBusy ? L"Hide" : L"Close");
    const auto action = getstr(refOperation, "action");
    reference_text(refCancel, action == "download" || action == "resume" ? L"Cancel + discard" : L"Cancel operation");
  }
  void reference_layout() {
    if (!refWindow) return;
    RECT rect{}; GetClientRect(refWindow, &rect);
    const int w = MulDiv(rect.right, 96, refDpi), h = MulDiv(rect.bottom, 96, refDpi);
    auto put = [&](HWND control, int x, int y, int cw, int ch) {
      MoveWindow(control, MulDiv(x, refDpi, 96), MulDiv(y, refDpi, 96),
                 MulDiv(std::max(1, cw), refDpi, 96), MulDiv(std::max(1, ch), refDpi, 96), TRUE);
    };
    const int tab = TabCtrl_GetCurSel(refTab);
    const bool online = tab == 0, local = tab == 1, downloads = tab == 2, importing = tab == 3;
    put(refTab, 18, 14, w - 36, 30);
    put(refIntro, 18, 54, w - 36, 43);
    reference_text(refIntro, local
      ? L"Local references work offline. Select a file and a compatible workspace input. Relocation copies and verifies your library, then switches its location; originals remain."
      : downloads ? L"Pause keeps partial downloads for later. Cancel discards the active partial download. Resume verifies saved identity; Discard removes only the selected unfinished transfer."
      : importing ? L"Import existing reference files without a network connection. Enter their identity as your own declaration, choose files, then review before importing."
      : getstr(reference_provider(), "id") == "ensembl-archive"
          ? L"Ensembl archive: release-pinned genomes and annotations. Release 116 is the final classic release. Search contacts the selected provider; analysis remains local."
          : L"Choose a provider and search explicitly. NCBI RefSeq requires a versioned assembly accession, for example GCF_000146045.2. No network request occurs when changing providers.");
    const int destinationTop = h - 134, detailsHeight = 76,
              detailsTop = destinationTop - 12 - detailsHeight,
              speciesHeight = std::max(56, (detailsTop - 244) * 2 / 5),
              filesTop = 190 + speciesHeight + 40;
    put(refProviderLabel, 18, 107, 66, 28);
    put(refProvider, 88, 104, 250, 260);
    put(refReleaseLabel, 350, 107, 124, 28);
    put(refRelease, 480, 104, w - 498, 250);
    put(refQuery, 18, 146, w - 146, 32);
    put(refSearch, w - 116, 146, 98, 32);
    put(refSpecies, 18, 190, w - 36, speciesHeight);
    put(refDiscover, 18, 196 + speciesHeight, 132, 30);
    put(refFiles, 18, filesTop, w - 36, detailsTop - 12 - filesTop);
    put(refLocal, 18, 104, w - 36, h - 390);
    put(refRelocate, 18, h - 276, 184, 32);
    put(refPending, 18, 104, w - 36, h - 385);
    put(refResume, 18, h - 269, 142, 32);
    put(refDiscard, 172, h - 269, 158, 32);
    put(refDetails, 18, local ? h - 232 : downloads ? h - 225 : importing ? h - 214 : detailsTop,
        w - 36, local ? 86 : downloads ? 79 : importing ? 68 : detailsHeight);
    put(refTargetLabel, 18, destinationTop + 3, 116, 30);
    put(refTarget, 138, destinationTop, w - 432, 240);
    put(refUse, w - 282, destinationTop, 128, 32);
    put(refOpen, w - 142, destinationTop, 124, 32);
    put(refDestinationLabel, 18, destinationTop + 3, 66, 30);
    put(refDestination, 88, destinationTop, w - 420, 32);
    put(refBrowse, w - 320, destinationTop, 128, 32);
    put(refDownload, w - 180, destinationTop, 162, 32);
    put(refImportPreview, w - 180, destinationTop, 162, 32);
    const int half = (w - 48) / 2;
    for (size_t i = 0; i < refImportMetadata.size(); ++i) {
      const int x = 18 + static_cast<int>(i % 2) * (half + 12), y = 104 + static_cast<int>(i / 2) * 36;
      put(refImportMetadataLabels[i], x, y + 3, 110, 28);
      put(refImportMetadata[i], x + 112, y, half - 112, 30);
    }
    for (size_t i = 0; i < refImportPaths.size(); ++i) {
      const int y = 222 + static_cast<int>(i) * 36;
      put(refImportLabels[i], 18, y + 3, 140, 28);
      put(refImportPaths[i], 160, y, w - 318, 30);
      put(refImportBrowse[i], w - 146, y, 128, 30);
    }
    put(refNotice, 18, h - 92, w - 36, 38);
    put(refReviewButton, 18, h - 44, 168, 30);
    put(refPause, w - 406, h - 44, 118, 30);
    put(refCancel, w - 276, h - 44, 152, 30);
    put(refClose, w - 112, h - 44, 94, 30);
    put(refProgress, 18, h - 7, w - 36, 5);
    for (HWND control : {refProviderLabel, refProvider, refReleaseLabel, refRelease, refQuery,
                         refSearch, refSpecies, refDiscover, refFiles, refDownload})
      ShowWindow(control, online ? SW_SHOW : SW_HIDE);
    for (HWND control : {refDestinationLabel, refDestination, refBrowse})
      ShowWindow(control, online || importing ? SW_SHOW : SW_HIDE);
    for (HWND control : {refLocal, refTargetLabel, refTarget, refUse, refOpen, refRelocate})
      ShowWindow(control, local ? SW_SHOW : SW_HIDE);
    for (HWND control : {refPending, refResume, refDiscard})
      ShowWindow(control, downloads ? SW_SHOW : SW_HIDE);
    ShowWindow(refImportPreview, importing ? SW_SHOW : SW_HIDE);
    for (const auto &controls : {refImportPaths, refImportBrowse, refImportLabels, refImportMetadata, refImportMetadataLabels})
      for (HWND control : controls) ShowWindow(control, importing ? SW_SHOW : SW_HIDE);
    auto column = [&](HWND list, int at, int size) { ListView_SetColumnWidth(list, at, MulDiv(size, refDpi, 96)); };
    column(refSpecies, 0, (w - 70) / 2); column(refSpecies, 1, (w - 70) / 4); column(refSpecies, 2, (w - 70) / 4);
    column(refFiles, 0, 210); column(refFiles, 1, std::max(220, w - 366)); column(refFiles, 2, 98);
    column(refLocal, 0, std::max(180, (w - 170) / 3)); column(refLocal, 1, std::max(180, (w - 170) / 3));
    column(refLocal, 2, std::max(180, (w - 170) / 3)); column(refLocal, 3, 98);
    column(refPending, 0, w - 390); column(refPending, 1, 140); column(refPending, 2, 200);
  }
  void reference_fonts() {
    HFONT replacement = CreateFontW(-MulDiv(14, refDpi, 96), 0, 0, 0, FW_NORMAL,
        FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    EnumChildWindows(refWindow, [](HWND child, LPARAM value) -> BOOL {
      SendMessageW(child, WM_SETFONT, static_cast<WPARAM>(value), TRUE);
      return TRUE;
    }, reinterpret_cast<LPARAM>(replacement));
    if (refFont)
      DeleteObject(refFont);
    refFont = replacement;
  }
  void reference_command(int id, int notification) {
    if (refRebuilding)
      return;
    if (id == REF_CLOSE || id == IDCANCEL) {
      DestroyWindow(refWindow);
      return;
    }
    if (id == REF_DESTINATION || id == REF_TARGET) {
      if (id == REF_DESTINATION && notification == EN_CHANGE) reference_invalidate_review();
      reference_enabled();
      return;
    }
    if ((id >= REF_IMPORT_PATH && id < REF_IMPORT_PATH + 5) ||
        (id >= REF_IMPORT_METADATA && id < REF_IMPORT_METADATA + 6)) {
      if (notification == EN_CHANGE) reference_invalidate_review();
      reference_enabled();
      return;
    }
    if (id == REF_PAUSE && refBusy && !refActionPending &&
        refOperation.get("cancellable").boolean(true) &&
        (getstr(refOperation, "action") == "download" || getstr(refOperation, "action") == "resume")) {
      reference_send("references/pause");
      return;
    }
    if (id == REF_CANCEL && refBusy && !refActionPending &&
        refOperation.get("cancellable").boolean(true)) {
      reference_send("references/cancel");
      return;
    }
    if (!ready || analysis_active() || closing || packBusy || packActionPending ||
        refBusy || refActionPending || setupBusy || setupActionPending)
      return;
    if (id == REF_QUERY && notification == EN_CHANGE)
      return;
    if (id == REF_RELEASE) {
      if (notification == CBN_SELCHANGE) {
        refRebuilding = true;
        refState["species"] = Json::array(); refState["discovery"] = nullptr;
        ListView_DeleteAllItems(refSpecies); ListView_DeleteAllItems(refFiles);
        refRebuilding = false;
        reference_details();
      }
      return;
    }
    if (id == REF_PROVIDER && notification == CBN_SELCHANGE) {
      refRebuilding = true;
      reference_provider_controls(true);
      reference_text(refQuery, L"");
      refState["species"] = Json::array(); refState["discovery"] = nullptr;
      ListView_DeleteAllItems(refSpecies); ListView_DeleteAllItems(refFiles);
      refRebuilding = false;
      reference_layout(); reference_details();
      return;
    }
    if (id == REF_REVIEW) {
      reference_review(); return;
    }
    if (id >= REF_IMPORT_BROWSE && id < REF_IMPORT_BROWSE + 5) {
      const auto index = static_cast<size_t>(id - REF_IMPORT_BROWSE);
      const auto path = pick(refWindow, false, false,
          index == 1 ? L"Annotation GTF|*.gtf;*.gtf.gz|All files|*.*"
                     : L"FASTA files|*.fa;*.fasta;*.fna;*.faa;*.fa.gz;*.fasta.gz;*.fna.gz;*.faa.gz|All files|*.*",
          L"Choose a local reference file");
      if (!path.empty()) reference_text(refImportPaths[index], path);
    } else if (id == REF_IMPORT_PREVIEW) {
      Json files = Json::array(), metadata = Json::object();
      const std::vector<std::string> kinds{"genome", "annotation", "cdna", "ncrna", "protein"},
          names{"label", "species", "assembly", "assembly_accession", "source", "release"};
      for (size_t i = 0; i < kinds.size(); ++i)
        if (!control_text(refImportPaths[i]).empty())
          files.array_items().push_back(object({{"kind", kinds[i]}, {"path", narrow(control_text(refImportPaths[i]))}}));
      for (size_t i = 0; i < names.size(); ++i)
        metadata[names[i]] = narrow(control_text(refImportMetadata[i]));
      reference_invalidate_review();
      reference_send("references/import-preview", object({{"files", files}, {"metadata", metadata},
          {"destination", narrow(control_text(refDestination))}}));
    } else if (id == REF_RELOCATE) {
      const auto destination = pick(refWindow, true, false, L"", L"Choose a new reference library location");
      if (!destination.empty()) {
        reference_invalidate_review();
        reference_send("references/relocate-preview", object({{"destination", narrow(destination)}}));
      }
    } else if (id == REF_RESUME || id == REF_DISCARD) {
      const auto &job = reference_pending();
      if (getstr(job, "id").empty()) return;
      if (id == REF_RESUME)
        reference_send("references/resume", object({{"job_id", getstr(job, "id")}}));
      else if (MessageBoxW(refWindow,
          L"Discard this unfinished download and its partial files? Completed reference bundles will be preserved.",
          L"Discard unfinished download", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) == IDYES)
        reference_send("references/discard", object({{"job_id", getstr(job, "id")}}));
    } else if (id == REF_SEARCH || (id == IDOK && TabCtrl_GetCurSel(refTab) == 0)) {
      if (control_text(refRelease).empty())
        return;
      reference_send("references/search", object({{"provider_id", getstr(reference_provider(), "id")}, {"release", reference_release_value()},
                                                   {"query", narrow(control_text(refQuery))}}));
    } else if (id == REF_DISCOVER) {
      const auto &species = reference_selected_species();
      if (!getstr(species, "id").empty())
        reference_send("references/discover", object({{"provider_id", getstr(reference_provider(), "id")}, {"release", reference_release_value()},
                            {"species_id", getstr(species, "id")}}));
    } else if (id == REF_BROWSE) {
      const auto path = pick(refWindow, true, false, L"", L"Choose where to store reference downloads");
      if (!path.empty())
        SetWindowTextW(refDestination, path.c_str());
    } else if (id == REF_DOWNLOAD) {
      const auto &discovery = refState.get("discovery");
      if (getstr(discovery, "selection_id").empty() || !discovery.get("files").is_array())
        return;
      Json selectedFiles = Json::array();
      const auto &files = discovery.get("files").array_items();
      for (size_t i = 0; i < files.size(); ++i)
        if (ListView_GetCheckState(refFiles, static_cast<int>(i)))
          selectedFiles.array_items().push_back(getstr(files[i], "id"));
      if (!selectedFiles.array_items().empty())
        reference_send("references/download", object({
            {"selection_id", getstr(refState.get("discovery"), "selection_id")},
            {"file_ids", selectedFiles}, {"destination", narrow(control_text(refDestination))}}));
    } else if (id == REF_OPEN || id == REF_USE) {
      const auto &record = reference_local_record(), &file = reference_local_file();
      if (getstr(record, "id").empty())
        return;
      if (id == REF_OPEN)
        reference_send("references/open", object({{"record_id", getstr(record, "id")}}));
      else {
        if (!record.get("available").boolean(true))
          return;
        const auto selectedTarget = SendMessageW(refTarget, CB_GETCURSEL, 0, 0);
        const auto &targets = refTargets.array_items();
        if (selectedTarget >= 0 && static_cast<size_t>(selectedTarget) < targets.size()) {
          const auto &target = targets[static_cast<size_t>(selectedTarget)];
          commit_all();
          reference_send("references/use", object({{"record_id", getstr(record, "id")},
              {"file_id", getstr(file, "id")}, {"source_id", getstr(target, "source_id")},
              {"field_id", getstr(target, "field_id")}}));
        }
      }
    }
    reference_enabled();
  }
  static LRESULT CALLBACK reference_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *app = reinterpret_cast<Workspace *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      app = static_cast<Workspace *>(reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      app->refWindow = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app)
      return DefWindowProcW(h, m, w, l);
    try {
      switch (m) {
      case WM_COMMAND:
        app->reference_command(LOWORD(w), HIWORD(w));
        return 0;
      case WM_NOTIFY: {
        auto *notice = reinterpret_cast<NMHDR *>(l);
        if (app->refRebuilding)
          return 0;
        if (notice->idFrom == REF_TAB && notice->code == TCN_SELCHANGE) {
          app->reference_layout();
          if (TabCtrl_GetCurSel(app->refTab) == 1)
            app->reference_targets();
          app->reference_details();
        } else if (notice->code == LVN_ITEMCHANGED) {
          if (notice->idFrom == REF_LOCAL) {
            const auto *change = reinterpret_cast<NMLISTVIEW *>(l);
            if ((change->uNewState & LVIS_SELECTED) && !(change->uOldState & LVIS_SELECTED))
              app->reference_targets();
          } else if (notice->idFrom == REF_FILES || notice->idFrom == REF_SPECIES || notice->idFrom == REF_PENDING)
            app->reference_details();
        }
        return 0;
      }
      case WM_SIZE:
        app->reference_layout();
        return 0;
      case WM_ACTIVATE:
        if (LOWORD(w) != WA_INACTIVE && app->refTab &&
            TabCtrl_GetCurSel(app->refTab) == 1 && !app->refActionPending && !app->refReviewOpen)
          app->reference_targets();
        break;
      case WM_DPICHANGED: {
        app->refDpi = HIWORD(w);
        app->reference_fonts();
        const auto *rect = reinterpret_cast<RECT *>(l);
        SetWindowPos(h, nullptr, rect->left, rect->top, rect->right - rect->left,
                     rect->bottom - rect->top, SWP_NOZORDER | SWP_NOACTIVATE);
        app->reference_layout();
        return 0;
      }
      case WM_GETMINMAXINFO: {
        auto *info = reinterpret_cast<MINMAXINFO *>(l);
        info->ptMinTrackSize = {MulDiv(820, app->refDpi, 96), MulDiv(680, app->refDpi, 96)};
        return 0;
      }
      case WM_CTLCOLORSTATIC:
      case WM_CTLCOLOREDIT:
      case WM_CTLCOLORBTN: {
        auto dc = reinterpret_cast<HDC>(w);
        SetTextColor(dc, INK);
        SetBkColor(dc, BACK);
        return reinterpret_cast<LRESULT>(app->background);
      }
      case WM_CLOSE:
        DestroyWindow(h);
        return 0;
      case WM_NCDESTROY:
        app->refWindow = nullptr;
        app->refLocalRows.clear();
        app->refPendingIds.clear();
        app->refTargets = Json::array();
        app->refImportPaths.clear(); app->refImportBrowse.clear(); app->refImportLabels.clear();
        app->refImportMetadata.clear(); app->refImportMetadataLabels.clear();
        SetWindowLongPtrW(h, GWLP_USERDATA, 0);
        return DefWindowProcW(h, m, w, l);
      default:
        break;
      }
    } catch (const std::exception &error) {
      MessageBoxW(h, wide(error.what()).c_str(), L"References", MB_OK | MB_ICONERROR);
    }
    return DefWindowProcW(h, m, w, l);
  }
  void show_references() {
    if (refWindow) {
      ShowWindow(refWindow, SW_RESTORE);
      SetForegroundWindow(refWindow);
      return;
    }
    WNDCLASSEXW klass{sizeof(klass)};
    klass.lpfnWndProc = reference_proc;
    klass.hInstance = instance;
    klass.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    klass.hbrBackground = background;
    klass.lpszClassName = L"WorkbenchReferences070";
    RegisterClassExW(&klass);
    RECT owner{}, area{};
    GetWindowRect(window, &owner);
    MONITORINFO monitor{sizeof(monitor)};
    if (GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor))
      area = monitor.rcWork;
    else
      SystemParametersInfoW(SPI_GETWORKAREA, 0, &area, 0);
    refDpi = dpi;
    const int w = std::min<int>(px(960), area.right - area.left),
              h = std::min<int>(px(800), area.bottom - area.top),
              x = std::clamp<int>(owner.left + (owner.right - owner.left - w) / 2,
                                  area.left, area.right - w),
              y = std::clamp<int>(owner.top + (owner.bottom - owner.top - h) / 2,
                                  area.top, area.bottom - h);
    refWindow = CreateWindowExW(WS_EX_CONTROLPARENT, klass.lpszClassName,
        L"References · Native Workbench", WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
        x, y, w, h, window, nullptr, instance, this);
    if (!refWindow)
      throw std::runtime_error("Could not open reference discovery.");
    refRebuilding = true;
    refTab = make(WC_TABCONTROLW, L"Reference views", WS_TABSTOP, REF_TAB, refWindow);
    for (const auto *label : {L"Find online", L"Local library", L"Downloads", L"Import local"}) {
      TCITEMW item{};
      item.mask = TCIF_TEXT;
      item.pszText = const_cast<wchar_t *>(label);
      TabCtrl_InsertItem(refTab, TabCtrl_GetItemCount(refTab), &item);
    }
    refIntro = make(L"STATIC", L"", SS_LEFT | SS_NOPREFIX, 650, refWindow);
    refProviderLabel = make(L"STATIC", L"Provider", SS_LEFT, 654, refWindow);
    refProvider = make(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, REF_PROVIDER, refWindow);
    refReleaseLabel = make(L"STATIC", L"Release", SS_LEFT, 651, refWindow);
    refRelease = make(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL,
                      REF_RELEASE, refWindow);
    SendMessageW(refRelease, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"116"));
    SendMessageW(refRelease, CB_SETCURSEL, 0, 0);
    refQuery = make(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, REF_QUERY,
                   refWindow, WS_EX_CLIENTEDGE);
    SendMessageW(refQuery, EM_SETCUEBANNER, FALSE,
                 reinterpret_cast<LPARAM>(L"Species name, e.g. human or Saccharomyces"));
    refSearch = button(L"Search", REF_SEARCH, refWindow);
    auto list = [&](const wchar_t *title, int id, bool checks,
                    std::initializer_list<const wchar_t *> labels) {
      HWND control = make(WC_LISTVIEWW, title,
          WS_TABSTOP | LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS,
          id, refWindow, WS_EX_CLIENTEDGE);
      ListView_SetExtendedListViewStyle(control, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER |
          LVS_EX_LABELTIP | (checks ? LVS_EX_CHECKBOXES : 0));
      int index = 0;
      for (const auto *label : labels) {
        LVCOLUMNW column{};
        column.mask = LVCF_TEXT | LVCF_WIDTH;
        column.pszText = const_cast<wchar_t *>(label);
        column.cx = px(150);
        ListView_InsertColumn(control, index++, &column);
      }
      return control;
    };
    refSpecies = list(L"Species and assemblies", REF_SPECIES, false,
                       {L"Species", L"Assembly · release", L"Assembly accession"});
    refDiscover = button(L"Find files", REF_DISCOVER, refWindow);
    refFiles = list(L"Reference files to download", REF_FILES, true,
                     {L"Select files", L"Archive filename", L"Download"});
    refDetails = make(L"EDIT", L"", WS_TABSTOP | ES_MULTILINE | ES_READONLY |
        ES_AUTOVSCROLL | WS_VSCROLL, REF_DETAILS, refWindow, WS_EX_CLIENTEDGE);
    SendMessageW(refDetails, EM_SETLIMITTEXT, 256 * 1024, 0);
    refDestinationLabel = make(L"STATIC", L"Save to", SS_LEFT, 652, refWindow);
    refDestination = make(L"EDIT", L"", WS_TABSTOP |
        ES_AUTOHSCROLL, REF_DESTINATION, refWindow, WS_EX_CLIENTEDGE);
    refBrowse = button(L"Choose folder...", REF_BROWSE, refWindow);
    refDownload = button(L"Download selected", REF_DOWNLOAD, refWindow);
    refLocal = list(L"Downloaded reference files", REF_LOCAL, false,
                     {L"Species", L"Assembly · release", L"Reference file", L"Size"});
    refPending = list(L"Unfinished reference downloads", REF_PENDING, false,
                      {L"Reference", L"Status", L"Downloaded / total"});
    refResume = button(L"Resume selected", REF_RESUME, refWindow);
    refDiscard = button(L"Discard selected...", REF_DISCARD, refWindow);
    refRelocate = button(L"Relocate library...", REF_RELOCATE, refWindow);
    const std::vector<std::wstring> metadataLabels{L"Library label", L"Species", L"Assembly", L"Accession (opt.)", L"Source", L"Release / version"},
        fileLabels{L"Genome FASTA", L"Annotation GTF", L"cDNA FASTA", L"ncRNA FASTA", L"Protein FASTA"};
    for (size_t i = 0; i < metadataLabels.size(); ++i) {
      refImportMetadataLabels.push_back(make(L"STATIC", metadataLabels[i], SS_LEFT,
          680 + static_cast<int>(i), refWindow));
      HWND edit = make(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL,
          REF_IMPORT_METADATA + static_cast<int>(i), refWindow, WS_EX_CLIENTEDGE);
      SendMessageW(edit, EM_SETLIMITTEXT, 2048, 0);
      refImportMetadata.push_back(edit);
    }
    for (size_t i = 0; i < fileLabels.size(); ++i) {
      refImportLabels.push_back(make(L"STATIC", fileLabels[i], SS_LEFT, 690 + static_cast<int>(i), refWindow));
      HWND edit = make(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL,
          REF_IMPORT_PATH + static_cast<int>(i), refWindow, WS_EX_CLIENTEDGE);
      SendMessageW(edit, EM_SETLIMITTEXT, 32768, 0);
      refImportPaths.push_back(edit);
      refImportBrowse.push_back(button(L"Choose file...", REF_IMPORT_BROWSE + static_cast<int>(i), refWindow));
    }
    refImportPreview = button(L"Check for import", REF_IMPORT_PREVIEW, refWindow);
    refTargetLabel = make(L"STATIC", L"Workspace input", SS_LEFT, 653, refWindow);
    refTarget = make(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL,
                     REF_TARGET, refWindow);
    refUse = button(L"Use for input", REF_USE, refWindow);
    refOpen = button(L"Open folder", REF_OPEN, refWindow);
    refPause = button(L"Pause download", REF_PAUSE, refWindow);
    refCancel = button(L"Cancel operation", REF_CANCEL, refWindow);
    refReviewButton = button(L"Review changes...", REF_REVIEW, refWindow);
    refProgress = make(PROGRESS_CLASSW, L"Reference download progress", PBS_SMOOTH,
                       REF_PROGRESS, refWindow);
    SendMessageW(refProgress, PBM_SETRANGE32, 0, 1000);
    refNotice = make(L"STATIC", L"Loading local references...", SS_LEFT | SS_NOPREFIX,
                     REF_NOTICE, refWindow);
    refClose = button(L"Close", REF_CLOSE, refWindow);
    refRebuilding = false;
    reference_fonts();
    reference_refresh(Json::object());
    reference_layout();
    reference_notice();
    ShowWindow(refWindow, SW_SHOW);
    SetFocus(refQuery);
    reference_send("references/list");
  }
  void reference_response(const std::string &method, const Json &result) {
    refPollFailed = false;
    if (result.contains("review")) {
      const auto &review = result.get("review");
      // The service keeps a review until it is consumed or replaced. Editing a
      // native form invalidates that exact token locally, including after this
      // window is reopened or an already-requested status reply arrives.
      refReview = refInvalidReviewTokens.count(getstr(review, "token"))
          ? Json::object() : review;
    }
    if (result.contains("operation"))
      refOperation = result.get("operation");
    const bool wasBusy = refBusy;
    refBusy = refOperation.get("active").boolean();
    if (result.get("local").is_array()) {
      Json previous = refState;
      refState = result;
      reference_refresh(previous);
      if (refWindow && previous.get("providers").dump() != refState.get("providers").dump())
        reference_layout();
    }
    if (result.contains("model"))
      snapshot(result.get("model"));
    if (method == "references/targets" && refWindow) {
      refTargets = result.get("targets");
      SendMessageW(refTarget, CB_RESETCONTENT, 0, 0);
      int targetIndex = 0, preferredTarget = 0;
      for (const auto &target : refTargets.array_items()) {
        if (getstr(state.get("inspector"), "kind") == "source" &&
            getstr(target, "source_id") == selected)
          preferredTarget = targetIndex;
        auto label = wt(target, "label") + L" (" + wt(target, "type") + L")";
        if (!getstr(target, "current_path").empty())
          label += L" · replace current file";
        SendMessageW(refTarget, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str()));
        ++targetIndex;
      }
      if (!refTargets.array_items().empty())
        SendMessageW(refTarget, CB_SETCURSEL, preferredTarget, 0);
      else
        SetWindowTextW(refNotice, wt(result, "notice",
            workflowMode ? "No compatible workflow input. Use Add input to create a reference input first."
                         : "No compatible input. Select a tool that accepts this reference first.").c_str());
    } else if (method == "references/open") {
      const auto path = wt(result, "path");
      if (!path.empty() && reinterpret_cast<INT_PTR>(ShellExecuteW(
            refWindow ? refWindow : window, L"open", path.c_str(), nullptr, nullptr, SW_SHOWNORMAL)) <= 32)
        message(L"Windows could not open the reference folder.");
    } else if (method == "references/use") {
      status_text(L"The local reference is assigned to the selected workspace input.");
      if (refWindow)
        reference_text(refNotice, L"Reference assigned. Its recorded provenance will be retained with the run.");
    } else {
      reference_notice();
      if (refBusy)
        status_text(L"References: " + wt(refOperation, "message"));
      else if (wasBusy && !getstr(refOperation, "message").empty())
        status_text(wt(refOperation, "message"));
      const auto action = getstr(refOperation, "action");
      if ((wasBusy || method == "references/download" || method == "references/resume" ||
           method == "references/import" || method == "references/relocate") && !refBusy &&
          (action == "download" || action == "resume" || action == "import" || action == "relocate") &&
          refOperation.get("success").boolean() && refWindow) {
        TabCtrl_SetCurSel(refTab, 1);
        reference_layout();
        reference_targets();
      }
      if (wasBusy && !refBusy && getstr(refOperation, "status") == "paused" && refWindow) {
        TabCtrl_SetCurSel(refTab, 2); reference_layout(); reference_details();
      }
    }
    reference_enabled();
    enabled();
    if (closing && !refBusy && !busy && !packBusy && !setupBusy)
      send("shutdown");
  }
  void controls() {
    HMENU menu = CreateMenu(), file = CreatePopupMenu(),
          view = CreatePopupMenu();
    for (auto pair : std::vector<std::pair<UINT, const wchar_t *>>{
             {FILE_NEW, L"New workspace"},
             {FILE_EXAMPLE, L"Load bundled example"},
             {SHOW_CURATED, L"Curated workflows..."},
             {FILE_SAVE_PIPELINE, L"Save pipeline..."},
             {FILE_SAVE_PRESET, L"Save selected tool settings..."},
             {FILE_LOAD, L"Load saved pipeline or settings..."},
             {FILE_HISTORY, L"Recorded results..."},
             {SHOW_RESULTS, L"Search results..."},
             {SHOW_SAMPLES, L"Samples..."},
             {SHOW_QUEUE, L"Analysis queue..."},
             {SHOW_INDEXES, L"Reference indexes..."},
             {SHOW_RESOURCES, L"Resource settings..."},
             {SHOW_RESTART, L"Restart recorded analysis..."},
             {SHOW_PROJECTS, L"Portable projects..."},
             {FILE_IMPORT, L"Manage tools..."},
             {TOOL_SETUP, L"Tool setup..."},
             {MANAGE_REFERENCES, L"References..."},
             {FILE_CHECK, L"Check installation"},
             {FILE_EXIT, L"Exit"}})
      AppendMenuW(file, MF_STRING, pair.first, pair.second);
    AppendMenuW(view, MF_STRING, VIEW_METHODS, L"Planned methods...");
    AppendMenuW(view, MF_STRING, REVIEW_DIAGNOSTICS, L"Review diagnostics...");
    AppendMenuW(view, MF_STRING, VIEW_LOG, L"Run log...");
    AppendMenuW(view, MF_STRING, VIEW_RESULT_SUMMARY, L"Recorded result summary...");
    AppendMenuW(view, MF_STRING, OPEN_RESULTS, L"Open results folder");
    AppendMenuW(menu, MF_POPUP, reinterpret_cast<UINT_PTR>(file), L"File");
    AppendMenuW(menu, MF_POPUP, reinterpret_cast<UINT_PTR>(view), L"View");
    SetMenu(window, menu);
    modeTools = make(L"BUTTON", L"Tools", WS_TABSTOP | BS_OWNERDRAW, MODE_TOOLS);
    modeWorkflow = make(L"BUTTON", L"Workflow", WS_TABSTOP | BS_OWNERDRAW, MODE_WORKFLOW);
    generalSettings = button(L"General settings", GENERAL_SETTINGS);
    saveCurrent = button(L"Save settings...", SAVE_CURRENT);
    loadCurrent = button(L"Load saved...", LOAD_CURRENT);
    resultsList = make(L"BUTTON", L"Results", WS_TABSTOP | BS_OWNERDRAW, RESULTS_LIST);
    samplesButton = make(L"BUTTON", L"Samples...", WS_TABSTOP | BS_OWNERDRAW, SHOW_SAMPLES);
    queueButton = make(L"BUTTON", L"Queue (0)", WS_TABSTOP | BS_OWNERDRAW, SHOW_QUEUE);
    resetLayout = button(L"Arrange", RESET_LAYOUT);
    addInput = button(L"Add input...", ADD_INPUT);
    zoomOut = button(L"−", ZOOM_OUT);
    zoomIn = button(L"+", ZOOM_IN);
    zoomReset = button(L"100%", ZOOM_RESET);
    toolsHeading = make(L"STATIC", L"Tools", SS_LEFT, 0);
    centerHeading = make(L"STATIC", L"Run a tool", SS_LEFT, 0);
    rightHeading = make(L"STATIC", L"General settings", SS_LEFT, 0);
    nameLabel = make(L"STATIC", L"Analysis name", SS_LEFT, 0);
    inputLabel = make(L"STATIC", L"Input folder", SS_LEFT, 0);
    inputHelp = make(L"STATIC", L"File pickers start here. Select each tool's input files explicitly.", SS_LEFT, 0);
    outputLabel = make(L"STATIC", L"Output folder", SS_LEFT, 0);
    outputHelp = make(L"STATIC", L"Each run gets its own folder with results, methods and logs.", SS_LEFT, 0);
    referenceHelp = make(L"STATIC", L"Discover Ensembl references or reuse verified local downloads.", SS_LEFT, 0);
    inputFolder = make(L"EDIT", root + L"\\examples", WS_TABSTOP | ES_AUTOHSCROLL,
                       INPUT_FOLDER, nullptr, WS_EX_CLIENTEDGE);
    browseInput = button(L"Browse input folder...", BROWSE_INPUT);
    for (HWND h : {toolsHeading, centerHeading, rightHeading, nameLabel, inputLabel, outputLabel})
      SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(bold), FALSE);
    name = make(L"EDIT", L"Untitled analysis", WS_TABSTOP | ES_AUTOHSCROLL,
                NAME, nullptr, WS_EX_CLIENTEDGE);
    output = make(L"EDIT", root + L"\\results", WS_TABSTOP | ES_AUTOHSCROLL,
                  OUTPUT, nullptr, WS_EX_CLIENTEDGE);
    browse = button(L"Browse output folder...", BROWSE_OUTPUT);
    manageReferences = button(L"References...", MANAGE_REFERENCES);
    run = make(L"BUTTON", L"Run tool", WS_TABSTOP | BS_OWNERDRAW, RUN);
    cancel = button(L"Cancel run", CANCEL);
    review = button(L"Methods", REVIEW);
    back = button(L"Back to workspace", BACK_WORKSPACE);
    search = make(L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, SEARCH, nullptr,
                  WS_EX_CLIENTEDGE);
    SendMessageW(search, EM_SETCUEBANNER, FALSE,
                 reinterpret_cast<LPARAM>(L"Search tools"));
    libraryViewport = make(L"WorkbenchLibraryViewport0161", L"", WS_VSCROLL | WS_CLIPCHILDREN,
                           LIBRARY_VIEWPORT, nullptr,
                           WS_EX_CLIENTEDGE | WS_EX_CONTROLPARENT | WS_EX_COMPOSITED);
    SetWindowSubclass(libraryViewport, library_viewport_proc, 1, reinterpret_cast<DWORD_PTR>(this));
    SCROLLINFO libraryScrollInfo{sizeof(libraryScrollInfo), SIF_RANGE | SIF_PAGE | SIF_DISABLENOSCROLL};
    libraryScrollInfo.nPage = 1;
    SetScrollInfo(libraryViewport, SB_VERT, &libraryScrollInfo, FALSE);
    tasks = make(WC_TREEVIEWW, L"Tool library",
                 WS_TABSTOP | TVS_HASBUTTONS | TVS_LINESATROOT |
                     TVS_SHOWSELALWAYS | TVS_FULLROWSELECT | TVS_NOHSCROLL |
                     TVS_NOTOOLTIPS | TVS_NONEVENHEIGHT,
                 TASKS, libraryViewport);
    SendMessageW(tasks, CCM_SETUNICODEFORMAT, TRUE, 0);
    TreeView_SetExtendedStyle(tasks, TVS_EX_DOUBLEBUFFER, TVS_EX_DOUBLEBUFFER);
    TreeView_SetBkColor(tasks, PAPER);
    TreeView_SetTextColor(tasks, INK);
    TreeView_SetItemHeight(tasks, px(30));
    TreeView_SetIndent(tasks, px(16));
    SetWindowTheme(tasks, L"Explorer", nullptr);
    SetWindowSubclass(tasks, library_proc, 1, reinterpret_cast<DWORD_PTR>(this));
    library_colors();
    LVCOLUMNW col{};
    col.mask = LVCF_TEXT | LVCF_WIDTH;
    add = button(L"Add to workflow", ADD);
    manageTools = button(L"Manage tools...", MANAGE_TOOLS);
    clearFilter = button(L"Show all tools", CLEAR_FILTER);
    steps = make(WC_LISTVIEWW, L"Pipeline steps by dependency level",
                 WS_TABSTOP | LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS,
                 STEPS, nullptr, WS_EX_CLIENTEDGE);
    ListView_SetExtendedListViewStyle(
        steps, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_LABELTIP);
    col.pszText = const_cast<wchar_t *>(L"Steps");
    col.cx = px(188);
    ListView_InsertColumn(steps, 0, &col);
    remove = button(L"Remove", REMOVE);
    undo = button(L"Undo", UNDO);
    up = button(L"Move up", UP);
    down = button(L"Move down", DOWN);
    dag = CreateWindowExW(
        0, L"WorkbenchNativeSurface051", L"Pipeline dependency diagram",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_HSCROLL | WS_VSCROLL |
            WS_CLIPSIBLINGS,
        0, 0, 1, 1, window, reinterpret_cast<HMENU>(DAG), instance, this);
    canvas_configure_gestures();
    form = CreateWindowExW(
        WS_EX_CONTROLPARENT | WS_EX_COMPOSITED, L"WorkbenchNativeSurface051",
        L"Step inputs and options",
        WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
        0, 0, 1, 1, window, reinterpret_cast<HMENU>(FORM), instance, this);
    status = make(L"STATIC", L"Starting the local analysis engine...", SS_LEFT,
                  STATUS);
    generalPanel = CreateWindowExW(WS_EX_CONTROLPARENT | WS_EX_COMPOSITED, L"WorkbenchNativeSurface051",
        L"General settings", WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_CLIPCHILDREN,
        0, 0, 1, 1, window, nullptr, instance, this);
    for (HWND h : {nameLabel, name, inputLabel, inputFolder, browseInput, inputHelp,
                   outputLabel, output, browse, outputHelp, manageReferences, referenceHelp})
      SetParent(h, generalPanel);
    for (HWND h : {name, inputFolder, browseInput, output, browse, manageReferences})
      SetWindowSubclass(h, field_proc, 1, reinterpret_cast<DWORD_PTR>(this));
    SetTimer(window, 1, 400, nullptr);
    layout();
  }
  void layout() {
    RECT rc{};
    GetClientRect(window, &rc);
    const int newWidth = std::max(1, MulDiv(rc.right, 96, dpi));
    const int newHeight = std::max(1, MulDiv(rc.bottom, 96, dpi));
    const bool resized = width != newWidth || height != newHeight;
    width = newWidth;
    height = newHeight;
    // MoveWindow(..., TRUE) paints each control immediately. During a resize
    // that can present the old form/General settings children inside their new
    // viewport, while later header/footer controls still have old positions.
    // Place every level without painting or copying old pixels, then present
    // the completed layout once. Ordinary mode changes and scrolling keep
    // their existing repaint behavior.
    auto place = [&](HWND h, int x, int y, int w, int hgt) {
      this->place(h, x, y, w, hgt, !resized);
    };
    const auto geometry = workspace_layout::for_client(width, height);
    const int left = geometry.left, right = geometry.right, center = geometry.center,
              centerWidth = geometry.centerWidth, rightX = geometry.rightX,
              rightWidth = geometry.rightWidth, bodyHeight = geometry.bodyHeight;
    auto place_control = [&](HWND h, workspace_layout::Rect bounds) {
      place(h, bounds.x, bounds.y, bounds.width, bounds.height);
    };
    const bool canvas = workflowMode || showingHistory;
    const bool general = !showingHistory && (!workflowMode || generalVisible || selected.empty());
    place_control(modeTools, geometry.toolsMode);
    place_control(modeWorkflow, geometry.workflowMode);
    place_control(samplesButton, geometry.samples);
    place_control(queueButton, geometry.queue);
    place_control(resultsList, geometry.results);
    place(toolsHeading, 16, 64, left - 32, 24);
    place(search, 12, 98, left - 24, 32);
    const bool filtering = workflowMode && !getstr(state, "pendingSource").empty();
    place(clearFilter, 12, 140, left - 24, 30);
    show_control(clearFilter, filtering);
    place(libraryViewport, 12, filtering ? 180 : 140, left - 24,
          std::max(100, height - (filtering ? 180 : 140) - (workflowMode ? 166 : 84)));
    place(addInput, 12, height - 154, left - 24, 32);
    show_control(addInput, workflowMode && !showingHistory);
    place(add, 12, height - 114, left - 24, 32);
    show_control(add, workflowMode && !showingHistory);
    place(manageTools, 12, height - 72, left - 24, 32);
    place(centerHeading, center + 16, 65, centerWidth - (canvas ? 258 : 32), 26);
    label_control(centerHeading, showingHistory ? L"Recorded results" :
                   workflowMode ? L"Workflow" : L"Run a tool");
    place(rightHeading, rightX, 65, rightWidth - (workflowMode ? 145 : 0), 26);
    label_control(rightHeading, general ? L"General settings" :
        getstr(state.get("inspector"), "kind") == "source" ? L"Input options" : L"Tool options");
    place(generalSettings, width - 157, 59, 141, 32);
    label_control(generalSettings, general ? L"Tool options" : L"General settings");
    show_control(generalSettings, workflowMode && !showingHistory);
    place(generalPanel, width - right + 1, 102, right - 2, bodyHeight);
    show_control(generalPanel, general);
    layout_general(!resized);
    place(dag, center, 102, centerWidth, bodyHeight);
    show_control(dag, canvas);
    place(form, canvas ? width - right + 1 : center, 102,
          canvas ? right - 2 : centerWidth, bodyHeight);
    show_control(form, !canvas || !general);
    show_control(steps, false);
    show_control(up, false);
    show_control(down, false);
    place_control(remove, geometry.remove);
    place_control(undo, geometry.undo);
    place_control(resetLayout, geometry.reset);
    for (HWND h : {remove, undo, resetLayout})
      show_control(h, workflowMode && !showingHistory);
    place_control(run, geometry.run);
    label_control(run, workflowMode ? L"Run workflow" : L"Run tool");
    place_control(review, geometry.readiness);
    place_control(cancel, geometry.cancel);
    show_control(cancel, busy);
    place_control(zoomOut, geometry.zoomOut);
    place_control(zoomReset, geometry.zoomReset);
    place_control(zoomIn, geometry.zoomIn);
    for (HWND h : {zoomOut, zoomReset, zoomIn})
      show_control(h, canvas);
    place_control(saveCurrent, canvas ? geometry.saveWorkflow : geometry.saveSettings);
    place_control(loadCurrent, canvas ? geometry.loadWorkflow : geometry.loadSettings);
    show_control(saveCurrent, !showingHistory);
    show_control(loadCurrent, !showingHistory);
    label_control(saveCurrent, workflowMode ? L"Save workflow..." : L"Save settings...");
    place_control(back, geometry.back);
    show_control(back, showingHistory);
    for (HWND h : {run, review}) show_control(h, !showingHistory);
    place(status, 12, height - 24, width - 24, 22);
    if (TreeView_GetItemHeight(tasks) != px(30)) TreeView_SetItemHeight(tasks, px(30));
    if (static_cast<int>(TreeView_GetIndent(tasks)) != px(16)) TreeView_SetIndent(tasks, px(16));
    library_position(!resized);
    library_reflow(false, !resized);
    layout_fields(!resized);
    if (resized)
      RedrawWindow(window, nullptr, nullptr,
                   RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW);
    else
      InvalidateRect(dag, nullptr, FALSE);
  }
  void layout_general(bool repaint = true) {
    if (!generalPanel) return;
    RECT r{};
    GetClientRect(generalPanel, &r);
    const int w = std::max(200, MulDiv(r.right, 96, dpi)) - 28,
              h = std::max(1, MulDiv(r.bottom, 96, dpi));
    generalScroll = std::clamp(generalScroll, 0, std::max(0, 532 - h));
    SCROLLINFO si{sizeof(si), SIF_RANGE | SIF_PAGE | SIF_POS | SIF_DISABLENOSCROLL};
    si.nMax = 531; si.nPage = h; si.nPos = generalScroll;
    SetScrollInfo(generalPanel, SB_VERT, &si, repaint);
    place_panel(generalPanel, {
      {nameLabel, 14, 10 - generalScroll, w, 22},
      {name, 14, 36 - generalScroll, w, 32},
      {inputLabel, 14, 88 - generalScroll, w, 22},
      {inputFolder, 14, 114 - generalScroll, w, 32},
      {browseInput, 14, 154 - generalScroll, w, 32},
      {inputHelp, 14, 194 - generalScroll, w, 42},
      {outputLabel, 14, 256 - generalScroll, w, 22},
      {output, 14, 282 - generalScroll, w, 32},
      {browse, 14, 322 - generalScroll, w, 32},
      {outputHelp, 14, 362 - generalScroll, w, 42},
      {manageReferences, 14, 428 - generalScroll, w, 34},
      {referenceHelp, 14, 472 - generalScroll, w, 42}}, repaint);
  }
  void enabled() {
    bool edit = ready && !setupBusy && !setupActionPending && !packBusy && !packActionPending &&
                !refBusy && !refActionPending &&
                !showingHistory && !closing &&
                ui_request_idle();
    const bool browseAuxiliary = ready && !closing &&
        (ui_request_idle() || slow_request_pending());
    for (HWND h :
         {name, search, tasks, steps, remove, up, down,
          modeTools, modeWorkflow, generalSettings, saveCurrent, loadCurrent,
          resetLayout, inputFolder, browseInput, addInput})
      enable_control(h, edit);
    enable_control(add, edit && !library_tool(TreeView_GetSelection(tasks)).empty());
    for (HWND h : {zoomOut, zoomReset, zoomIn}) {
      enable_control(h, ready && !closing);
      show_control(h, workflowMode || showingHistory);
    }
    enable_control(undo, edit && state.get("canUndo").boolean());
    enable_control(run, edit && !analysis_active() && !graph().get("nodes").array_items().empty());
    enable_control(review, ready && !closing && ui_request_idle());
    enable_control(resultsList, ready && !closing && ui_request_idle());
    enable_control(samplesButton, browseAuxiliary && !showingHistory);
    enable_control(queueButton, browseAuxiliary);
    enable_control(cancel, busy && !closing && !cancellation_pending());
    show_control(cancel, busy);
    enable_control(output, edit);
    enable_control(browse, edit);
    enable_control(manageTools, ready && !analysis_active() && !closing && !showingHistory);
    enable_control(manageReferences, ready && !analysis_active() && !closing && !showingHistory);
    for (const auto &f : fields) {
      enable_control(f.h, edit || f.kind.rfind("historical-", 0) == 0);
      if (f.button)
        enable_control(f.button, edit);
    }
    HMENU m = GetMenu(window);
    bool menuChanged = false;
    auto menu_enable = [&](UINT id, bool available) {
      const UINT previous = GetMenuState(m, id, MF_BYCOMMAND);
      if (previous != static_cast<UINT>(-1) &&
          ((previous & (MF_DISABLED | MF_GRAYED)) == 0) != available) {
        EnableMenuItem(m, id, MF_BYCOMMAND | (available ? MF_ENABLED : MF_GRAYED));
        menuChanged = true;
      }
    };
    for (UINT id : {FILE_NEW, FILE_EXAMPLE, FILE_SAVE_PIPELINE,
                    FILE_SAVE_PRESET, FILE_LOAD})
      menu_enable(id, edit);
    menu_enable(FILE_IMPORT, ready && !analysis_active() && !closing && !showingHistory);
    menu_enable(MANAGE_REFERENCES, ready && !analysis_active() && !closing && !showingHistory);
    menu_enable(TOOL_SETUP, ready && !analysis_active() && !closing);
    menu_enable(FILE_CHECK, edit && !analysis_active());
    menu_enable(SHOW_SAMPLES, browseAuxiliary && !showingHistory);
    for (UINT id : {SHOW_QUEUE, SHOW_INDEXES, SHOW_RESOURCES, SHOW_PROJECTS})
      menu_enable(id, browseAuxiliary);
    menu_enable(SHOW_CURATED, browseAuxiliary);
    menu_enable(FILE_HISTORY, browseAuxiliary);
    menu_enable(SHOW_RESULTS, browseAuxiliary);
    menu_enable(VIEW_METHODS, ready && !closing && ui_request_idle());
    menu_enable(VIEW_RESULT_SUMMARY, browseAuxiliary &&
        !(showingHistory ? getstr(historyRun, "run_id") : runId).empty());
    menu_enable(SHOW_RESTART, browseAuxiliary &&
        !(showingHistory ? getstr(historyRun, "run_id") : runId).empty() && !analysis_active());
    if (menuChanged) DrawMenuBar(window);
    pack_enabled();
    reference_enabled();
    setup_enabled();
    auxiliary_enabled();
  }
  const LibraryRow *library_row(HTREEITEM item) const {
    if (!item) return nullptr;
    TVITEMW value{};
    value.mask = TVIF_PARAM;
    value.hItem = item;
    if (!SendMessageW(tasks, TVM_GETITEMW, 0, reinterpret_cast<LPARAM>(&value)) ||
        value.lParam <= 0 || static_cast<size_t>(value.lParam) > libraryRows.size())
      return nullptr;
    return &libraryRows[static_cast<size_t>(value.lParam) - 1];
  }
  std::string library_tool(HTREEITEM item) const {
    const auto *row = library_row(item);
    return row ? row->toolId : std::string();
  }
  std::string library_key(HTREEITEM item) const {
    const auto *row = library_row(item);
    return row ? row->key() : std::string();
  }
  void library_colors() {
    HIGHCONTRASTW contrast{sizeof(contrast)};
    libraryHighContrast = SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(contrast),
        &contrast, 0) && (contrast.dwFlags & HCF_HIGHCONTRASTON);
    TreeView_SetBkColor(tasks, libraryHighContrast ? GetSysColor(COLOR_WINDOW) : PAPER);
    TreeView_SetTextColor(tasks, libraryHighContrast ? GetSysColor(COLOR_WINDOWTEXT) : INK);
  }
  int library_text_left(const LibraryRow &row) const {
    return static_cast<int>(TreeView_GetIndent(tasks)) * (row.toolId.empty() ? 1 : 2) + px(4);
  }
  int library_text_right() const {
    RECT client{};
    GetClientRect(libraryViewport, &client);
    // The viewport reserves its scrollbar even with collapsed categories;
    // text uses that exact visible width. The child's own native scrollbar
    // remains outside this clipping viewport so coarse item scrolling works.
    return client.right - px(6);
  }
  const LibraryPosition *library_position_for(HTREEITEM item) const {
    const auto found = std::find_if(libraryVisible.begin(), libraryVisible.end(),
        [&](const auto &position) { return position.item == item; });
    return found == libraryVisible.end() ? nullptr : &*found;
  }
  HTREEITEM library_anchor() const {
    if (libraryVisible.empty()) return nullptr;
    const auto after = std::upper_bound(libraryVisible.begin(), libraryVisible.end(), libraryScroll,
        [](int offset, const auto &position) { return offset < position.top; });
    return (after == libraryVisible.begin() ? after : after - 1)->item;
  }
  int library_anchor_offset(HTREEITEM item) const {
    const auto *position = library_position_for(item);
    return position ? std::max(0, libraryScroll - position->top) : 0;
  }
  void library_update_visible() {
    libraryVisible.clear(); libraryExtent = 0; libraryLargestRow = 0;
    bool expanded = false;
    for (const auto &row : libraryRows) {
      const auto found = libraryItems.find(row.key());
      if (found == libraryItems.end()) continue;
      if (row.toolId.empty())
        expanded = (TreeView_GetItemState(tasks, found->second, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
      if (row.toolId.empty() || expanded) {
        libraryVisible.push_back({found->second, libraryExtent, row.height});
        libraryExtent += row.height;
        libraryLargestRow = std::max(libraryLargestRow, row.height);
      }
    }
    ++libraryGeometry;
  }
  void library_position(bool repaint = true, bool force = false) {
    if (!libraryViewport || !tasks || libraryPlacing) return;
    RECT viewport{};
    GetClientRect(libraryViewport, &viewport);
    const int viewWidth = std::max(1L, viewport.right), viewHeight = std::max(1L, viewport.bottom);
    libraryScroll = std::clamp(libraryScroll, 0, std::max(0, libraryExtent - viewHeight));
    if (!force && libraryPlacedWidth == viewWidth && libraryPlacedHeight == viewHeight &&
        libraryPlacedScroll == libraryScroll && libraryPlacedGeometry == libraryGeometry) return;
    libraryPlacing = true;
    libraryPlacedWidth = viewWidth; libraryPlacedHeight = viewHeight;
    libraryPlacedScroll = libraryScroll; libraryPlacedGeometry = libraryGeometry;
    const bool visible = (GetWindowLongPtrW(tasks, GWL_STYLE) & WS_VISIBLE) != 0;
    if (visible) SendMessageW(tasks, WM_SETREDRAW, FALSE, 0);
    SCROLLINFO scroll{sizeof(scroll), SIF_RANGE | SIF_PAGE | SIF_POS | SIF_DISABLENOSCROLL};
    scroll.nMax = std::max(0, libraryExtent - 1); scroll.nPage = viewHeight; scroll.nPos = libraryScroll;
    SetScrollInfo(libraryViewport, SB_VERT, &scroll, repaint);
    // Native TreeView scrolling stops at item boundaries. A bounded, real
    // child window supplies enough room for the largest row, while the outer
    // viewport scrolls pixels through that row. Native item/hit rectangles
    // remain real screen geometry: no translated painting or fake messages.
    // TVS_NOSCROLL also disables TVGN_FIRSTVISIBLE on native Windows. Keep
    // native coarse scrolling enabled, but put its scrollbar beyond the
    // parent's clip. The extra width remains bounded and never affects wrap.
    const int childWidth = viewWidth + GetSystemMetricsForDpi(SM_CXVSCROLL, dpi);
    const int childHeight = viewHeight + libraryLargestRow;
    SetWindowPos(tasks, nullptr, 0, 0, childWidth, childHeight,
                 SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS);
    int childTop = 0;
    if (const auto anchor = library_anchor()) {
      TreeView_SelectSetFirstVisible(tasks, anchor);
      RECT row{};
      const auto *position = library_position_for(anchor);
      if (position && TreeView_GetItemRect(tasks, anchor, &row, FALSE))
        childTop = -(row.top + libraryScroll - position->top);
    }
    SetWindowPos(tasks, nullptr, 0, childTop, childWidth, childHeight,
                 SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW | SWP_NOCOPYBITS);
    if (visible) SendMessageW(tasks, WM_SETREDRAW, TRUE, 0);
    libraryPlacing = false;
    if (repaint) RedrawWindow(libraryViewport, nullptr, nullptr,
        RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN);
  }
  void library_ensure_visible(HTREEITEM item) {
    if (libraryPlacing || rebuilding || libraryExpanding) return;
    const auto *position = library_position_for(item);
    if (!position) return;
    RECT viewport{};
    GetClientRect(libraryViewport, &viewport);
    // A click on a lower visible part of a tall row retains that reading
    // position. Keyboard selection of a wholly offscreen row reveals its name.
    if (position->top + position->height <= libraryScroll ||
        position->top >= libraryScroll + viewport.bottom)
      libraryScroll = position->top;
    else if (position->height <= viewport.bottom) {
      if (position->top < libraryScroll) libraryScroll = position->top;
      else if (position->top + position->height > libraryScroll + viewport.bottom)
        libraryScroll = position->top + position->height - viewport.bottom;
    }
    library_position(true, true);
  }
  void library_scroll(UINT action, int thumb = 0) {
    RECT viewport{};
    GetClientRect(libraryViewport, &viewport);
    const int line = px(30), page = std::max(line, static_cast<int>(viewport.bottom) - line);
    switch (action) {
    case SB_LINEUP: libraryScroll -= line; break;
    case SB_LINEDOWN: libraryScroll += line; break;
    case SB_PAGEUP: libraryScroll -= page; break;
    case SB_PAGEDOWN: libraryScroll += page; break;
    case SB_TOP: libraryScroll = 0; break;
    case SB_BOTTOM: libraryScroll = libraryExtent; break;
    case SB_THUMBPOSITION:
    case SB_THUMBTRACK: libraryScroll = thumb; break;
    default: return;
    }
    library_position();
  }
  void library_wheel(WPARAM value) {
    UINT lines = 3;
    SystemParametersInfoW(SPI_GETWHEELSCROLLLINES, 0, &lines, 0);
    if (!lines) return;
    RECT viewport{};
    GetClientRect(libraryViewport, &viewport);
    const int step = lines == WHEEL_PAGESCROLL ? std::max(1L, viewport.bottom - px(30))
        : static_cast<int>(std::min(lines, 100u)) * px(30);
    libraryWheelRemainder += GET_WHEEL_DELTA_WPARAM(value) * step;
    const int delta = libraryWheelRemainder / WHEEL_DELTA;
    libraryWheelRemainder %= WHEEL_DELTA;
    if (delta) { libraryScroll -= delta; library_position(); }
  }
  static LRESULT CALLBACK library_viewport_proc(HWND h, UINT message_, WPARAM w, LPARAM l,
                                                UINT_PTR, DWORD_PTR context) {
    auto *app = reinterpret_cast<Workspace *>(context);
    if (message_ == WM_ERASEBKGND) {
      RECT bounds{};
      GetClientRect(h, &bounds);
      FillRect(reinterpret_cast<HDC>(w), &bounds,
               app->libraryHighContrast ? GetSysColorBrush(COLOR_WINDOW) : app->paper);
      return 1;
    }
    if (message_ == WM_NOTIFY)
      return SendMessageW(app->window, message_, w, l);
    if (message_ == WM_MOUSEWHEEL) { app->library_wheel(w); return 0; }
    if (message_ == WM_VSCROLL) {
      SCROLLINFO scroll{sizeof(scroll), SIF_TRACKPOS};
      GetScrollInfo(h, SB_VERT, &scroll);
      app->library_scroll(LOWORD(w), scroll.nTrackPos);
      return 0;
    }
    if (message_ == WM_NCDESTROY) RemoveWindowSubclass(h, library_viewport_proc, 1);
    return DefSubclassProc(h, message_, w, l);
  }
  void library_restore_anchor(HTREEITEM item, int offset) {
    if (!item) return;
    for (HTREEITEM parent = TreeView_GetParent(tasks, item); parent;
         parent = TreeView_GetParent(tasks, parent))
      if (!(TreeView_GetItemState(tasks, parent, TVIS_EXPANDED) & TVIS_EXPANDED)) {
        item = parent; offset = 0;
      }
    const auto *position = library_position_for(item);
    if (position) libraryScroll = position->top + std::clamp(offset, 0, position->height - 1);
    library_position(false);
  }
  void library_reflow(bool force = false, bool repaint = true) {
    if (!tasks || !font || !libraryBold) return;
    const int right = library_text_right();
    if (!force && right == libraryLayoutWidth) return;
    libraryLayoutWidth = right;
    const auto anchor = library_anchor();
    const int anchorOffset = library_anchor_offset(anchor);
    const bool visible = (GetWindowLongPtrW(tasks, GWL_STYLE) & WS_VISIBLE) != 0;
    if (visible) SendMessageW(tasks, WM_SETREDRAW, FALSE, 0);
    HDC dc = GetDC(tasks);
    const int baseHeight = TreeView_GetItemHeight(tasks);
    for (auto &row : libraryRows) {
      const int textWidth = std::max(1, right - library_text_left(row));
      auto wrap = [&](const std::wstring &value, HFONT face, int &lineHeight) {
        const auto previous = SelectObject(dc, face);
        TEXTMETRICW metrics{};
        GetTextMetricsW(dc, &metrics);
        lineHeight = metrics.tmHeight;
        auto lines = library_text_layout::wrap(value, textWidth,
            [&](const std::wstring &line) {
              SIZE size{};
              GetTextExtentPoint32W(dc, line.data(), static_cast<int>(line.size()), &size);
              return static_cast<int>(size.cx);
            });
        SelectObject(dc, previous);
        return lines;
      };
      row.titleLines = wrap(row.label, libraryBold, row.titleLineHeight);
      row.descriptionLines = wrap(row.description, font, row.descriptionLineHeight);
      const auto found = libraryItems.find(row.key());
      if (found != libraryItems.end()) {
        TVITEMEXW item{};
        item.mask = TVIF_INTEGRAL;
        item.hItem = found->second;
        item.iIntegral = library_text_layout::integral_height(
            static_cast<int>(row.titleLines.size()), row.titleLineHeight,
            static_cast<int>(row.descriptionLines.size()), row.descriptionLineHeight,
            px(6), px(3), baseHeight);
        row.height = item.iIntegral * baseHeight;
        SendMessageW(tasks, TVM_SETITEMW, 0, reinterpret_cast<LPARAM>(&item));
      }
    }
    ReleaseDC(tasks, dc);
    library_update_visible();
    library_restore_anchor(anchor, anchorOffset);
    library_position(false);
    if (visible) {
      SendMessageW(tasks, WM_SETREDRAW, TRUE, 0);
      if (repaint) RedrawWindow(libraryViewport, nullptr, nullptr,
          RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN);
    }
  }
  LRESULT library_draw(NMTVCUSTOMDRAW &draw) {
    if (draw.nmcd.dwDrawStage == CDDS_PREPAINT) return CDRF_NOTIFYITEMDRAW;
    if (draw.nmcd.dwDrawStage != CDDS_ITEMPREPAINT) return CDRF_DODEFAULT;
    const auto item = reinterpret_cast<HTREEITEM>(draw.nmcd.dwItemSpec);
    const auto *row = library_row(item);
    if (!row) return CDRF_DODEFAULT;
    RECT bounds{}, client{};
    if (!TreeView_GetItemRect(tasks, item, &bounds, FALSE)) return CDRF_SKIPDEFAULT;
    GetClientRect(libraryViewport, &client);
    bounds.left = 0; bounds.right = client.right;
    const bool selected_ = TreeView_GetSelection(tasks) == item;
    const bool focused = GetFocus() == tasks;
    const COLORREF background_ = selected_
        ? (libraryHighContrast ? GetSysColor(COLOR_HIGHLIGHT)
                               : focused ? RGB(218, 232, 244) : RGB(232, 239, 244))
        : libraryHighContrast ? GetSysColor(COLOR_WINDOW) : PAPER;
    const COLORREF foreground = selected_
        ? (libraryHighContrast ? GetSysColor(COLOR_HIGHLIGHTTEXT) : INK)
        : libraryHighContrast ? GetSysColor(COLOR_WINDOWTEXT) : INK;
    const HDC dc = draw.nmcd.hdc;
    const int saved = SaveDC(dc);
    IntersectClipRect(dc, bounds.left, bounds.top, bounds.right, bounds.bottom);
    const auto brush = CreateSolidBrush(background_);
    FillRect(dc, &bounds, brush); DeleteObject(brush);
    SetBkMode(dc, TRANSPARENT);
    const int left = library_text_left(*row), right = library_text_right();
    int top = bounds.top + px(6);
    auto text_lines = [&](const std::vector<std::wstring> &lines, HFONT face,
                          int lineHeight, COLORREF color) {
      SelectObject(dc, face); SetTextColor(dc, color);
      const RECT clip{left, bounds.top, right, bounds.bottom};
      for (const auto &line : lines) {
        ExtTextOutW(dc, left, top, ETO_CLIPPED, &clip, line.data(),
                    static_cast<UINT>(line.size()), nullptr);
        top += lineHeight;
      }
    };
    text_lines(row->titleLines, libraryBold, row->titleLineHeight, foreground);
    if (!row->descriptionLines.empty()) {
      top += px(3);
      text_lines(row->descriptionLines, font, row->descriptionLineHeight,
                 selected_ || libraryHighContrast ? foreground : MUTED);
    }
    if (row->toolId.empty()) {
      // Use the native button hit zone, including integral-height categories,
      // so the painted expand glyph and native pointer behavior cannot diverge.
      RECT buttonBounds{};
      TVGETITEMPARTRECTINFO part{item, &buttonBounds, TVGIPR_BUTTON};
      if (SendMessageW(tasks, TVM_GETITEMPARTRECT, 0, reinterpret_cast<LPARAM>(&part))) {
        const bool expanded = (TreeView_GetItemState(tasks, item, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
        const int size = std::min({px(10), static_cast<int>(buttonBounds.right - buttonBounds.left),
                                  static_cast<int>(buttonBounds.bottom - buttonBounds.top)});
        const int x = (buttonBounds.left + buttonBounds.right - size) / 2,
                  y = (buttonBounds.top + buttonBounds.bottom - size) / 2;
        RECT glyph{x, y, x + size, y + size};
        HTHEME theme = OpenThemeData(tasks, L"TreeView");
        if (theme && !libraryHighContrast) {
          DrawThemeBackground(theme, dc, TVP_GLYPH, expanded ? GLPS_OPENED : GLPS_CLOSED,
                              &glyph, nullptr);
        } else {
          const auto pen = CreatePen(PS_SOLID, std::max(1, px(1)), foreground);
          const auto oldPen = SelectObject(dc, pen);
          MoveToEx(dc, glyph.left, (glyph.top + glyph.bottom) / 2, nullptr);
          LineTo(dc, glyph.right, (glyph.top + glyph.bottom) / 2);
          if (!expanded) {
            MoveToEx(dc, (glyph.left + glyph.right) / 2, glyph.top, nullptr);
            LineTo(dc, (glyph.left + glyph.right) / 2, glyph.bottom);
          }
          SelectObject(dc, oldPen); DeleteObject(pen);
        }
        if (theme) CloseThemeData(theme);
      }
    }
    if (selected_ && focused && !(SendMessageW(tasks, WM_QUERYUISTATE, 0, 0) & UISF_HIDEFOCUS)) {
      RECT focus = bounds; InflateRect(&focus, -1, -1);
      DrawFocusRect(dc, &focus);
    }
    RestoreDC(dc, saved);
    return CDRF_SKIPDEFAULT;
  }
  void library_expand(HTREEITEM item, UINT action) {
    const auto *row = library_row(item);
    if (!row || !row->toolId.empty()) return;
    const auto category = row->category;
    HTREEITEM anchor = library_anchor();
    const int anchorOffset = library_anchor_offset(anchor);
    const bool visible = (GetWindowLongPtrW(tasks, GWL_STYLE) & WS_VISIBLE) != 0;
    // Native expansion scrolls to expose the new children. Keep the user's
    // existing viewport instead, and present the expand/restore as one update.
    if (visible) SendMessageW(tasks, WM_SETREDRAW, FALSE, 0);
    libraryExpanding = true;
    if (TreeView_GetSelection(tasks) != item) TreeView_SelectItem(tasks, item);
    TreeView_Expand(tasks, item, action);
    libraryExpanding = false;
    library_update_visible();
    // Collapsed children restore to their visible ancestor; otherwise retain
    // both the first item and any partial scroll within its wrapped text.
    library_restore_anchor(anchor, anchorOffset);
    if (visible) {
      SendMessageW(tasks, WM_SETREDRAW, TRUE, 0);
      // The tree already uses TVS_EX_DOUBLEBUFFER. Redraw its changed rows and
      // background together, without forcing intermediate erase/paint cycles.
      RedrawWindow(libraryViewport, nullptr, nullptr,
                   RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN);
    }
    // Programmatic expansion may omit ITEMEXPANDED after EXPANDEDONCE is set.
    if (!libraryFiltered)
      libraryExpanded[category] =
          (TreeView_GetItemState(tasks, item, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
  }
  void library_toggle(HTREEITEM item) { library_expand(item, TVE_TOGGLE); }
  static LRESULT CALLBACK library_proc(HWND h, UINT message_, WPARAM w, LPARAM l,
                                       UINT_PTR, DWORD_PTR context) {
    auto *app = reinterpret_cast<Workspace *>(context);
    if (message_ == WM_MOUSEWHEEL) { app->library_wheel(w); return 0; }
    if (message_ == WM_KEYDOWN && (GetKeyState(VK_CONTROL) & 0x8000)) {
      if (w == VK_HOME || w == VK_END || w == VK_UP || w == VK_DOWN) {
        app->library_scroll(w == VK_HOME ? SB_TOP : w == VK_END ? SB_BOTTOM :
                            w == VK_UP ? SB_LINEUP : SB_LINEDOWN);
        return 0;
      }
    }
    if (message_ == WM_GETDLGCODE) {
      const auto *key = reinterpret_cast<const MSG *>(l);
      if (key && key->message == WM_KEYDOWN &&
          (key->wParam == VK_RETURN || key->wParam == VK_SPACE))
        return DLGC_WANTMESSAGE;
    }
    if (message_ == WM_LBUTTONDOWN || message_ == WM_LBUTTONDBLCLK) {
      TVHITTESTINFO hit{};
      hit.pt = {GET_X_LPARAM(l), GET_Y_LPARAM(l)};
      TreeView_HitTest(h, &hit);
      const auto *row = app->library_row(hit.hItem);
      if (row && row->toolId.empty() &&
          (hit.flags & (TVHT_ONITEM | TVHT_ONITEMBUTTON | TVHT_ONITEMRIGHT))) {
        SetFocus(h);
        // The double-click's first down already toggled this category.
        if (message_ == WM_LBUTTONDOWN) app->library_toggle(hit.hItem);
        return 0;
      }
      if (row && !row->toolId.empty() && message_ == WM_LBUTTONDBLCLK) {
        app->add_task(hit.hItem);
        return 0;
      }
    }
    if (message_ == WM_KEYDOWN && (w == VK_RETURN || w == VK_SPACE)) {
      HTREEITEM item = TreeView_GetSelection(h);
      const auto *row = app->library_row(item);
      if (row && row->toolId.empty()) app->library_toggle(item);
      else if (row && w == VK_RETURN) app->add_task(item);
      return 0;
    }
    if (message_ == WM_KEYDOWN && (w == VK_LEFT || w == VK_RIGHT)) {
      HTREEITEM item = TreeView_GetSelection(h);
      const auto *row = app->library_row(item);
      const bool expanded = (TreeView_GetItemState(h, item, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
      if (row && row->toolId.empty() && ((w == VK_LEFT && expanded) || (w == VK_RIGHT && !expanded))) {
        app->library_expand(item, w == VK_LEFT ? TVE_COLLAPSE : TVE_EXPAND);
        return 0;
      }
    }
    if (message_ == WM_KEYDOWN && (w == VK_PRIOR || w == VK_NEXT)) {
      app->library_scroll(w == VK_PRIOR ? SB_PAGEUP : SB_PAGEDOWN);
      const int readingPosition = app->libraryScroll;
      app->libraryExpanding = true;
      if (const auto item = app->library_anchor()) TreeView_SelectItem(h, item);
      app->libraryExpanding = false;
      app->libraryScroll = readingPosition;
      app->library_position(true, true);
      return 0;
    }
    if (message_ == WM_NCDESTROY)
      RemoveWindowSubclass(h, library_proc, 1);
    const LRESULT result = DefSubclassProc(h, message_, w, l);
    if (!app->libraryPlacing && !app->libraryExpanding &&
        (message_ == WM_KEYDOWN || message_ == WM_CHAR || message_ == WM_LBUTTONDOWN ||
         message_ == TVM_ENSUREVISIBLE || (message_ == TVM_SELECTITEM && w == TVGN_CARET)))
      app->library_ensure_visible(message_ == TVM_ENSUREVISIBLE
          ? reinterpret_cast<HTREEITEM>(l) : TreeView_GetSelection(h));
    return result;
  }
  void refresh_tasks() {
    LibraryView view{library_key(TreeView_GetSelection(tasks)),
                     library_key(library_anchor()), library_anchor_offset(library_anchor())};
    if (libraryRendered && !libraryFiltered) {
      libraryViews[libraryWorkflow] = view;
      for (HTREEITEM item = TreeView_GetRoot(tasks); item;
           item = TreeView_GetNextSibling(tasks, item)) {
        const auto *row = library_row(item);
        if (row) libraryExpanded[row->category] =
            (TreeView_GetItemState(tasks, item, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
      }
    }
    const auto query = lower(control_text(search));
    const auto source = workflowMode ? getstr(state, "pendingSource") : std::string();
    const bool filtered = !query.empty() || !source.empty();
    const bool modeChanged = libraryRendered && libraryWorkflow != workflowMode;
    if (modeChanged || (libraryFiltered && !filtered))
      view = libraryViews[workflowMode];
    const auto inspectorTool = workflowMode ? std::string() :
        getstr(state.get("inspector").get("tool"), "id");
    const bool toolChanged = !workflowMode && inspectorTool != libraryInspectorTool;
    // Loading or clearing a standalone session must not leave a different tool
    // highlighted. Ordinary option edits preserve category navigation.
    if (toolChanged) {
      if (!inspectorTool.empty()) view.selected = "tool:" + inspectorTool;
      else if (view.selected.rfind("tool:", 0) == 0) view.selected.clear();
    } else if (view.selected.empty() && !inspectorTool.empty()) {
      view.selected = "tool:" + inspectorTool;
    }
    std::set<std::string> compatible;
    if (state.get("compatibleTools").is_array())
      for (const auto &c : state.get("compatibleTools").array_items())
        compatible.insert(text(c));
    std::vector<LibraryRow> tools;
    for (const auto &entry : catalog.get("tools").object_items()) {
      const auto &t = entry.second;
      std::wstring label = wt(t, "displayName", getstr(t, "name")),
                   description = wt(t, "displayDescription", getstr(t, "description")),
                   categoryName = wt(t, "category", "Other");
      if (categoryName.empty()) categoryName = L"Other";
      if (!query.empty() &&
          lower(label + L" " + categoryName + L" " + wt(t, "packId") + L" " +
                description + L" " + wt(t, "searchTerms"))
                  .find(query) == std::wstring::npos)
        continue;
      if (!source.empty() && !compatible.count(entry.first)) continue;
      tools.push_back({categoryName, label, description,
                       label + (description.empty() ? L"" : L"\n" + description), entry.first});
    }
    std::sort(tools.begin(), tools.end(), [](const auto &a, const auto &b) {
      const auto ac = lower(a.category), bc = lower(b.category);
      if (ac != bc) return ac < bc;
      if (a.category != b.category) return a.category < b.category;
      const auto al = lower(a.label), bl = lower(b.label);
      return al != bl ? al < bl : a.toolId < b.toolId;
    });
    std::vector<LibraryRow> rows;
    std::wstring previousCategory;
    for (const auto &tool : tools) {
      if (rows.empty() || previousCategory != tool.category) {
        rows.push_back({tool.category, tool.category, {}, tool.category, {}});
        previousCategory = tool.category;
      }
      rows.push_back(tool);
    }
    const bool filterChanged = libraryQuery != query || librarySource != source;
    const bool changed = !libraryRendered || rows != libraryRows || filterChanged;
    // Model snapshots arrive after each edit. An unchanged catalogue/filter
    // must not rebuild the tree, lose its viewport, or flash the category text.
    if (!changed && !modeChanged && !toolChanged) return;
    const bool wasRebuilding = rebuilding;
    rebuilding = true;
    SendMessageW(tasks, WM_SETREDRAW, FALSE, 0);
    if (changed) {
      std::map<std::wstring, bool> visibleExpanded;
      if (libraryFiltered && filtered && !filterChanged)
        for (HTREEITEM item = TreeView_GetRoot(tasks); item;
             item = TreeView_GetNextSibling(tasks, item)) {
          const auto *row = library_row(item);
          if (row) visibleExpanded[row->category] =
              (TreeView_GetItemState(tasks, item, TVIS_EXPANDED) & TVIS_EXPANDED) != 0;
        }
      TreeView_DeleteAllItems(tasks);
      libraryVisible.clear(); libraryScroll = 0;
      libraryRows = std::move(rows);
      libraryItems.clear();
      HTREEITEM parent = TVI_ROOT;
      for (size_t i = 0; i < libraryRows.size(); ++i) {
        auto &row = libraryRows[i];
        TVINSERTSTRUCTW insert{};
        insert.hParent = row.toolId.empty() ? TVI_ROOT : parent;
        insert.hInsertAfter = TVI_LAST;
        insert.item.mask = TVIF_TEXT | TVIF_PARAM | TVIF_STATE;
        insert.item.pszText = row.accessible.data();
        insert.item.lParam = static_cast<LPARAM>(i + 1);
        insert.item.stateMask = TVIS_BOLD;
        insert.item.state = TVIS_BOLD;
        auto item = reinterpret_cast<HTREEITEM>(SendMessageW(
            tasks, TVM_INSERTITEMW, 0, reinterpret_cast<LPARAM>(&insert)));
        libraryItems[row.key()] = item;
        if (row.toolId.empty()) parent = item;
      }
      library_reflow(true, false);
      for (HTREEITEM item = TreeView_GetRoot(tasks); item;
           item = TreeView_GetNextSibling(tasks, item)) {
        const auto *row = library_row(item);
        const auto kept = visibleExpanded.find(row->category);
        const bool expand = filtered ? (kept == visibleExpanded.end() || kept->second)
                                     : libraryExpanded[row->category];
        if (expand) TreeView_Expand(tasks, item, TVE_EXPAND);
      }
      library_update_visible();
    }
    libraryQuery = query;
    librarySource = source;
    libraryFiltered = filtered;
    libraryWorkflow = workflowMode;
    if (!workflowMode) libraryInspectorTool = inspectorTool;
    libraryRendered = true;
    auto chosen = libraryItems.find(view.selected);
    HTREEITEM selection = chosen == libraryItems.end() ? nullptr : chosen->second;
    // Preserve a collapsed group rather than opening it just because its old
    // child was selected in another mode or before searching.
    if (selection) {
      HTREEITEM parent = TreeView_GetParent(tasks, selection);
      if (parent && !(TreeView_GetItemState(tasks, parent, TVIS_EXPANDED) & TVIS_EXPANDED))
        selection = parent;
    }
    if (TreeView_GetSelection(tasks) != selection) TreeView_SelectItem(tasks, selection);
    const auto first = libraryItems.find(view.first);
    if (first != libraryItems.end()) library_restore_anchor(first->second, view.offset);
    library_position(false, true);
    SendMessageW(tasks, WM_SETREDRAW, TRUE, 0);
    RedrawWindow(libraryViewport, nullptr, nullptr,
                 RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN);
    rebuilding = wasRebuilding;
  }
  void refresh_steps() {
    rebuilding = true;
    ListView_DeleteAllItems(steps);
    ListView_RemoveAllGroups(steps);
    ListView_EnableGroupView(steps, TRUE);
    stepIds.clear();
    auto rank = ranks();
    std::map<int, std::vector<const Json *>> groups;
    for (const auto &n : graph().get("nodes").array_items())
      groups[rank[getstr(n, "id")]].push_back(&n);
    int selectedIndex = -1;
    for (const auto &level : groups) {
      std::wstring header = L"Dependency level " + std::to_wstring(level.first);
      LVGROUP group{};
      group.cbSize = sizeof(group);
      group.mask = LVGF_HEADER | LVGF_GROUPID;
      group.pszHeader = header.data();
      group.iGroupId = level.first;
      ListView_InsertGroup(steps, -1, &group);
      for (const auto *n : level.second) {
        std::string id = getstr(*n, "id");
        std::wstring label = wide(display_id(id) + " · " + node_name(*n));
        LVITEMW row{};
        row.mask = LVIF_TEXT | LVIF_GROUPID;
        row.iGroupId = level.first;
        row.iItem = static_cast<int>(stepIds.size());
        row.pszText = label.data();
        ListView_InsertItem(steps, &row);
        if (id == selected)
          selectedIndex = row.iItem;
        stepIds.push_back(id);
      }
    }
    if (selectedIndex >= 0) {
      ListView_SetItemState(steps, selectedIndex, LVIS_SELECTED | LVIS_FOCUSED,
                            LVIS_SELECTED | LVIS_FOCUSED);
      ListView_EnsureVisible(steps, selectedIndex, FALSE);
    }
    rebuilding = false;
  }
  int measured(const std::wstring &value, int width_, HFONT f) {
    if (value.empty())
      return 0;
    HDC dc = GetDC(form);
    HFONT old = static_cast<HFONT>(SelectObject(dc, f));
    RECT r{0, 0, px(std::max(20, width_)), 0};
    DrawTextW(dc, value.c_str(), -1, &r,
              DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX);
    SelectObject(dc, old);
    ReleaseDC(form, dc);
    return std::max(20, MulDiv(r.bottom, 96, dpi));
  }
  HWND form_text(const std::wstring &value, bool strong = false) {
    HWND h = make(L"STATIC", value, SS_LEFT, 0, form);
    SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(strong ? bold : font),
                 FALSE);
    formControls.push_back(h);
    Field f;
    f.h = h;
    f.kind = "label";
    f.initial = value;
    f.schema = object({{"strong", strong}});
    fields.push_back(std::move(f));
    return h;
  }
  void add_field(std::string kind, std::string key, const Json &schema,
                 const std::string &value, const std::string &source = {},
                 const std::string &port = {}) {
    Field f;
    f.kind = std::move(kind);
    f.key = std::move(key);
    f.node = selected;
    f.source = source;
    f.port = port;
    f.schema = schema;
    if (f.kind == "source" && getstr(f.schema, "type") == "files")
      f.schema["type"] = "file";
    f.initial = wide(value);
    int id = FIELD_BASE + static_cast<int>(fields.size()) * 2;
    const auto type = getstr(f.schema, "type", "text");
    if (type == "boolean") {
      f.h = make(L"BUTTON", wt(schema, "label"), WS_TABSTOP | BS_AUTOCHECKBOX,
                 id, form);
      SendMessageW(f.h, BM_SETCHECK,
                   value == "true" ? BST_CHECKED : BST_UNCHECKED, 0);
    } else if (type == "choice") {
      f.h = make(L"COMBOBOX", L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL,
                 id, form);
      int chosen = -1;
      for (const auto &c : schema.get("choices").array_items()) {
        auto label = wt(c, "label", getstr(c, "value"));
        int at = static_cast<int>(SendMessageW(
            f.h, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(label.c_str())));
        if (getstr(c, "value") == value)
          chosen = at;
      }
      SendMessageW(f.h, CB_SETCURSEL, chosen, 0);
    } else {
      f.h = make(L"EDIT", f.initial,
                 WS_TABSTOP | (type == "files"
                                   ? ES_MULTILINE | ES_AUTOVSCROLL | WS_VSCROLL
                                   : ES_AUTOHSCROLL),
                 id, form, WS_EX_CLIENTEDGE);
      SendMessageW(f.h, EM_SETLIMITTEXT,
                   type == "files" ? 8 * 1024 * 1024 : 32767, 0);
    }
    formControls.push_back(f.h);
    if (f.kind == "source" &&
        (type == "file" || type == "files" || type == "directory")) {
      f.button = button(L"Browse...", id + 1, form);
      formControls.push_back(f.button);
    }
    fieldIds[id] = fields.size();
    fieldIds[id + 1] = fields.size();
    SetWindowSubclass(f.h, field_proc, 1, reinterpret_cast<DWORD_PTR>(this));
    if (f.button)
      SetWindowSubclass(f.button, field_proc, 1,
                        reinterpret_cast<DWORD_PTR>(this));
    fields.push_back(std::move(f));
  }
  void form_action(const std::wstring &title, const std::string &kind,
                   const std::string &key = {},
                   const Json &schema = Json::object()) {
    Field f;
    f.kind = kind;
    f.key = key;
    f.node = selected;
    f.schema = schema;
    int id = FIELD_BASE + static_cast<int>(fields.size()) * 2;
    f.h = button(title.c_str(), id, form);
    formControls.push_back(f.h);
    fieldIds[id] = fields.size();
    SetWindowSubclass(f.h, field_proc, 1, reinterpret_cast<DWORD_PTR>(this));
    fields.push_back(std::move(f));
  }
  void rebuild_inspector() {
    rebuilding = true;
    for (HWND h : formControls)
      DestroyWindow(h);
    formControls.clear();
    fields.clear();
    fieldIds.clear();
    const auto &inspector = state.get("inspector");
    if (showingHistory) {
      form_text(L"Recorded run — read only", true);
      form_text(wt(historyRun, "status") + L"\n" + wt(historyRun, "message") +
                L"\n" + wt(historyRun, "folder"));
      form_text(L"This diagram is taken from the saved run graph. Your "
                L"editable workspace is preserved.");
      form_action(L"Show recorded methods", "historical-methods");
      form_action(L"Show result summary", "historical-summary");
      form_action(L"Open results folder", "historical-open");
      form_action(L"Review verified restart...", "historical-restart");
    } else if (selected.empty() || inspector.is_null()) {
      form_text(workflowMode ? L"Build a workflow" : L"Choose a tool to begin", true);
      form_text(workflowMode
          ? L"Drag tools from the left onto the canvas. Connect an output port to a compatible input, then select a tool to edit its options here."
          : L"Select a tool from the panel on the left. Its input files and run options appear here.");
      form_text(L"Analysis runs locally. Use General settings for folders and References for reusable genome and annotation downloads.");
      form_action(L"Explore training workflows...", "curated-workflows");
    } else if (getstr(inspector, "kind") == "source") {
      form_text(wide(display_id(selected)) + L" · " + wt(inspector, "name"), true);
      form_text(L"Workflow input — choose files once and connect this input to each tool that needs them.");
      form_text(L"Input name", true);
      add_field("rename-source", "name", object({{"type", "text"}}), getstr(inspector, "name"));
      for (const auto &field : inspector.get("fields").array_items()) {
        form_text(wt(field, "label", getstr(field, "id")), true);
        add_field("source", getstr(field, "id"), field, getstr(field, "value"), selected);
        if (!getstr(field, "help").empty()) form_text(wt(field, "help"));
      }
      if (getstr(inspector, "type") == "reference")
        form_action(L"Choose from References...", "input-references");
    } else {
      form_text(wide(display_id(selected)) + L" · " + wt(inspector, "name"),
                true);
      const auto &t = inspector.get("tool");
      form_text(wt(t, "displayName", getstr(t, "name")) + L"  ·  " + wt(t, "packVersion"));
      form_text(wt(t, "displayDescription", getstr(t, "description")));
      for (const auto &node : graph().get("nodes").array_items()) {
        if (getstr(node, "id") != selected || !getstr(tool(node), "id").empty())
          continue;
        const auto operation = getstr(node, "tool");
        Json pin = node.get("pin").is_object() ? node.get("pin") : Json::object();
        if (getstr(pin, "packId").empty())
          pin["packId"] = operation.substr(0, operation.find('/'));
        form_text(L"Required tool pack is unavailable", true);
        form_text(wt(pin, "packId") + L"  ·  version " +
                  wt(pin, "packVersion", "not recorded") +
                  L"\nInstall the original pack to restore this step. Its saved settings "
                  L"and connections have been preserved.");
        form_action(L"Find required pack in Manage tools...", "manage-required-pack", "", pin);
        form_action(L"Show required pack details...", "required-pack-details", "", pin);
        break;
      }
      form_text(workflowMode ? L"Step name" : L"Tool run name", true);
      add_field("rename", "name", object({{"type", "text"}}),
                getstr(inspector, "name"));
      for (const auto &port : inspector.get("ports").array_items()) {
        const auto pid = getstr(port, "id");
        form_text(wt(port, "label"), true);
        std::wstring sources;
        const Json &refs = port.get("refs");
        for (const auto &ref : refs.array_items()) {
          if (!sources.empty())
            sources += L"\n";
          sources += wt(ref, "label", getstr(ref, "ref", text(ref)));
        }
        if (workflowMode) {
          form_text(sources.empty()
                      ? L"No source connected — choose a named input or output."
                      : L"From: " + sources);
        form_action(L"Choose connected source(s)...", "connect", pid, port);
        } else if (sources.empty()) {
          form_action(L"Choose files for this input", "add-source", pid, port);
        }
        if (!getstr(port, "help").empty())
          form_text(wt(port, "help"));
      }
      std::set<std::string> seen;
      const Json &sourceList = inspector.contains("sources")
                                   ? inspector.get("sources")
                                   : state.get("sources");
      for (const auto &source : sourceList.array_items()) {
        const auto sid = getstr(source, "id");
        if (sid.empty() || !seen.insert(sid).second)
          continue;
        form_text(wide(display_id(sid)) + L" · " + wt(source, "label"), true);
        for (const auto &field : source.get("fields").array_items()) {
          form_text(wt(field, "label", getstr(field, "id")));
          add_field("source", getstr(field, "id"), field,
                    getstr(field, "value"), sid);
          if (!getstr(field, "help").empty())
            form_text(wt(field, "help"));
        }
      }
      if (!inspector.get("params").array_items().empty())
        form_text(L"Tool settings", true);
      for (const auto &param : inspector.get("params").array_items()) {
        if (getstr(param, "type") != "boolean")
          form_text(wt(param, "label", getstr(param, "id")));
        add_field("param", getstr(param, "id"), param,
                  getstr(param, "value", getstr(param, "default")));
        if (!getstr(param, "help").empty())
          form_text(wt(param, "help"));
      }
      const Json *viewNode = nullptr;
      for (const auto &n : state.get("nodes").array_items())
        if (getstr(n, "id") == selected) {
          viewNode = &n;
          break;
        }
      if (viewNode) {
        form_text(L"Named outputs", true);
        for (const auto &out : viewNode->get("outputs").array_items()) {
          form_text(wt(out, "label"), true);
          std::wstring consumers;
          for (const auto &c : out.get("consumers").array_items()) {
            if (!consumers.empty())
              consumers += L"\n";
            consumers += wt(c, "displayId", getstr(c, "nodeId")) + L" · " +
                         wt(c, "name") + L" → " + wt(c, "portLabel");
          }
          if (workflowMode) {
            form_text(consumers.empty() ? L"No downstream consumer yet."
                                      : L"Used by: " + consumers);
          form_action(L"Use this output in another task...", "use-output",
                      getstr(out, "ref"));
          }
        }
      }
    }
    rebuilding = false;
    layout_fields();
    enabled();
  }
  void layout_fields(bool repaint = true) {
    if (!form)
      return;
    RECT r{};
    GetClientRect(form, &r);
    int fw = std::max(80, MulDiv(r.right, 96, dpi)),
        fh = std::max(30, MulDiv(r.bottom, 96, dpi)), y = 12;
    for (auto &f : fields) {
      f.y = y;
      if (f.kind == "label")
        f.height = measured(f.initial, fw - 34,
                            f.schema.get("strong").boolean() ? bold : font);
      else if (getstr(f.schema, "type") == "files")
        f.height = 76;
      else if (getstr(f.schema, "type") == "boolean")
        f.height =
            std::max(34, measured(wt(f.schema, "label"), fw - 52, font) + 8);
      else
        f.height = 34;
      y += f.height + (f.kind == "label" ? 8 : 12);
    }
    formExtent = y + 8;
    formScroll = std::clamp(formScroll, 0, std::max(0, formExtent - fh));
    SCROLLINFO si{sizeof(si),
                  SIF_RANGE | SIF_PAGE | SIF_POS | SIF_DISABLENOSCROLL};
    si.nMax = formExtent - 1;
    si.nPage = fh;
    si.nPos = formScroll;
    SetScrollInfo(form, SB_VERT, &si, repaint);
    std::vector<PanelPlacement> positions;
    for (auto &f : fields) {
      int fw_ = fw - 32 - (f.button ? 94 : 0);
      positions.push_back({f.h, 12, f.y - formScroll, fw_,
            getstr(f.schema, "type") == "choice" ? 260 : f.height});
      if (f.button)
        positions.push_back({f.button, fw - 108, f.y - formScroll, 88, 34});
    }
    place_panel(form, positions, repaint);
  }
  std::string field_value(const Field &f) const {
    auto type = getstr(f.schema, "type");
    if (type == "boolean")
      return SendMessageW(f.h, BM_GETCHECK, 0, 0) == BST_CHECKED ? "true"
                                                                 : "false";
    if (type == "choice") {
      int i = static_cast<int>(SendMessageW(f.h, CB_GETCURSEL, 0, 0));
      const auto &a = f.schema.get("choices").array_items();
      return i >= 0 && static_cast<size_t>(i) < a.size()
                 ? getstr(a[static_cast<size_t>(i)], "value")
                 : "";
    }
    return narrow(control_text(f.h));
  }
  void commit(Field &f) {
    if (rebuilding || showingHistory)
      return;
    const auto value = field_value(f);
    if (value == narrow(f.initial))
      return;
    f.initial = wide(value);
    if (f.kind == "param")
      model("set_param",
            object({{"nodeId", f.node}, {"paramId", f.key}, {"value", value}}));
    else if (f.kind == "source")
      model("bind_files", object({{"sourceId", f.source},
                                  {"files", object({{f.key, value}})}}));
    else if (f.kind == "rename")
      model("rename_step", object({{"nodeId", f.node}, {"name", value}}));
  }
  void commit_all() {
    if (rebuilding || showingHistory || !ready)
      return;
    Json params = Json::object(), files = Json::object(),
         payload = getstr(state.get("inspector"), "kind") == "source"
                       ? object({{"sourceId", selected}}) : object({{"nodeId", selected}});
    bool changed = false;
    for (const auto &f : fields) {
      if (f.kind != "param" && f.kind != "source" && f.kind != "rename" && f.kind != "rename-source")
        continue;
      auto value = field_value(f);
      if (value == narrow(f.initial))
        continue;
      changed = true;
      if (f.kind == "param")
        params[f.key] = value;
      else if (f.kind == "source")
        files[f.source][f.key] = value;
      else
        payload["name"] = value;
    }
    if (narrow(control_text(name)) != getstr(state.get("graph"), "name")) {
      payload["graphName"] = narrow(control_text(name));
      changed = true;
    }
    if (!changed)
      return;
    payload["params"] = params;
    payload["files"] = files;
    auto encoded = payload.dump();
    if (encoded == submittedFields)
      return;
    submittedFields = encoded;
    model("apply_fields", payload);
  }

  void show_text(const std::wstring &title, const std::wstring &value) {
    Modal m;
    m.owner = window;
    m.font = font;
    m.mode = 2;
    m.title = title;
    m.value = value;
    m.message = L"Select and copy text, or use Copy text.";
    m.confirm = L"Done";
    m.show();
  }
  void connection(const Field &f) {
    Modal m;
    m.owner = window;
    m.font = font;
    m.title = L"Choose sources for " + wt(f.schema, "label");
    m.mode = 0;
    m.multiple = f.schema.get("max").integer(1) > 1;
    m.message =
        m.multiple
            ? L"Ctrl-click to select multiple named sources. Apply replaces "
              L"this input's connections."
            : L"Choose the exact input slot or named output for this input.";
    m.confirm = L"Apply";
    std::vector<std::string> refs;
    if (!m.multiple) {
      refs.push_back("");
      m.labels.push_back(L"No source connected");
    }
    std::set<std::string> current;
    for (const auto &v : f.schema.get("refs").array_items())
      current.insert(v.is_string() ? v.string() : getstr(v, "ref"));
    for (const auto &v : f.schema.get("sources").array_items())
      current.insert(getstr(v, "ref", getstr(v, "id")));
    for (const auto &c : f.schema.get("choices").array_items()) {
      const auto ref = getstr(c, "ref");
      refs.push_back(ref);
      m.labels.push_back(wt(c, "label", ref));
      if (current.count(ref))
        m.selected.push_back(static_cast<int>(refs.size() - 1));
    }
    if (m.show()) {
      commit_all();
      Json::Array chosen;
      for (int n : m.selected)
        if (n >= 0 && static_cast<size_t>(n) < refs.size() &&
            !refs[static_cast<size_t>(n)].empty())
          chosen.emplace_back(refs[static_cast<size_t>(n)]);
      model("connect", object({{"nodeId", f.node},
                               {"portId", f.key},
                               {"refs", Json(chosen)}}));
    }
  }
  void field_command(int id, int notification) {
    auto found = fieldIds.find(id);
    if (found == fieldIds.end())
      return;
    const size_t idx = found->second;
    if (idx >= fields.size())
      return;
    Field &f = fields[idx];
    const bool secondary = f.button && id == GetDlgCtrlID(f.button);
    if (notification == EN_KILLFOCUS || notification == CBN_SELCHANGE ||
        (notification == BN_CLICKED && getstr(f.schema, "type") == "boolean"))
      return;
    if (notification != BN_CLICKED)
      return;
    if (secondary) {
      const auto path = pick(window, getstr(f.schema, "type") == "directory",
                             false, wt(f.schema, "filter", "All files|*.*"),
                             L"Choose " + wt(f.schema, "label"), control_text(inputFolder));
      if (!path.empty()) {
        SetWindowTextW(f.h, path.c_str());
        commit_all();
      }
      return;
    }
    const Field copy = f;
    if (f.kind == "connect") {
      connection(copy);
      return;
    }
    commit_all();
    if (f.kind == "add-source")
      model("add_source", object({{"nodeId", f.node}, {"portId", f.key}}));
    else if (f.kind == "input-references")
      show_references();
    else if (f.kind == "curated-workflows")
      show_auxiliary(SHOW_CURATED);
    else if (f.kind == "use-output")
      model("use_output", object({{"ref", f.key}}));
    else if (f.kind == "historical-methods")
      show_text(
          L"Recorded methods",
          wt(historyRun, "methods",
             getstr(historyRun, "methods_planned",
                    "Recorded methods are available in the run folder.")));
    else if (f.kind == "historical-restart")
      show_auxiliary(SHOW_RESTART);
    else if (f.kind == "historical-summary")
      show_result_summary(getstr(historyRun, "run_id"));
    else if (f.kind == "historical-open")
      send("open", object({{"run_id", getstr(historyRun, "run_id")}}));
    else if (f.kind == "manage-required-pack") {
      requiredPack = copy.schema;
      show_pack_manager();
      SetWindowTextW(packSearch, wt(requiredPack, "packId").c_str());
      SendMessageW(packFilter, CB_SETCURSEL, 0, 0);
      refresh_packs();
      pack_notice();
    } else if (f.kind == "required-pack-details")
      show_text(L"Required tool pack",
                L"Pack: " + wt(copy.schema, "packId") +
                    L"\nVersion: " + wt(copy.schema, "packVersion", "not recorded") +
                    L"\nManifest SHA-256: " + wt(copy.schema, "manifestSha256", "not recorded") +
                    L"\n\nThis exact manifest is required to reproduce the saved step.");
  }
  void snapshot(Json value) {
    if (value.contains("model"))
      value = value.get("model");
    const auto previousSelected = selected;
    const bool previousMode = workflowMode;
    state = std::move(value);
    workflowMode = getstr(state, "mode", "tool") == "workflow";
    if (previousMode != workflowMode) {
      InvalidateRect(modeTools, nullptr, FALSE);
      InvalidateRect(modeWorkflow, nullptr, FALSE);
    }
    if (state.contains("catalog"))
      catalog = state.get("catalog");
    selected =
        getstr(state, "selected", getstr(state.get("inspector"), "nodeId"));
    if (previousMode != workflowMode || previousSelected != selected) {
      formScroll = 0;
      formWheelRemainder = 0;
      generalVisible = false;
    }
    rebuilding = true;
    SetWindowTextW(name,
                   wt(state.get("graph"), "name", "Untitled analysis").c_str());
    rebuilding = false;
    refresh_tasks();
    refresh_steps();
    rebuild_inspector();
    layout();
    if (refWindow) reference_targets();
    InvalidateRect(dag, nullptr, FALSE);
    enabled();
  }
  void add_task(HTREEITEM item = nullptr) {
    if (rebuilding || !IsWindowEnabled(tasks)) return;
    const auto toolId = library_tool(item ? item : TreeView_GetSelection(tasks));
    if (toolId.empty()) return;
    if (!workflowMode && toolId == getstr(state.get("inspector").get("tool"), "id"))
      return;
    commit_all();
    if (!workflowMode) {
      send("workspace/tool", object({{"toolId", toolId}}));
      return;
    }
    const auto pendingSource = getstr(state, "pendingSource");
    Json payload = object({{"toolId", toolId}});
    if (!pendingSource.empty()) payload["fromRef"] = pendingSource;
    model("add_tool", payload);
  }
  void add_workflow_input() {
    // The modal pumps host responses; keep its choices independent of snapshots.
    const Json types = state.get("inputTypes");
    if (!workflowMode || !types.is_array() || types.array_items().empty()) return;
    Modal m;
    m.owner = window; m.font = font; m.mode = 0;
    m.title = L"Add workflow input";
    m.message = L"Choose an input type. Select its files once, give it a name, then connect it to any compatible tools.";
    m.confirm = L"Add input";
    for (const auto &type : types.array_items()) m.labels.push_back(wt(type, "label"));
    m.selected.push_back(0);
    if (m.show() && !m.selected.empty()) {
      const auto at = static_cast<size_t>(m.selected.front());
      if (at < types.array_items().size()) {
        commit_all();
        model("add_input", object({{"inputType", getstr(types.array_items()[at], "id")}}));
      }
    }
  }
  void save(bool pipeline) {
    if (!pipeline && selected.empty()) {
      message(L"Select a step to save its tool settings.");
      return;
    }
    Modal m;
    m.owner = window;
    m.font = font;
    m.mode = 1;
    m.title = pipeline ? L"Save pipeline" : L"Save tool settings";
    m.message = L"Choose a name for reuse. File bindings are excluded.";
    m.value =
        pipeline ? control_text(name) : wt(state.get("inspector"), "name");
    m.confirm = L"Save";
    if (!m.show())
      return;
    commit_all();
    Json request = object({{"name", narrow(m.value)},
                           {"kind", pipeline ? "pipeline" : "preset"}});
    if (!pipeline)
      request["nodeId"] = selected;
    send("save", request);
  }
  void load_saved(const Json &data) {
    Modal m;
    m.owner = window;
    m.font = font;
    m.title = L"Load saved analysis or tool settings";
    m.message = L"Pipelines restore the graph; tool settings apply to the "
                L"selected compatible step.";
    m.confirm = L"Load";
    std::vector<std::pair<std::string, std::string>> items;
    for (const char *kind : {"pipelines", "presets"})
      for (const auto &item : data.get(kind).array_items()) {
        m.labels.push_back(std::wstring(kind == std::string("pipelines")
                                            ? L"Pipeline · "
                                            : L"Tool settings · ") +
                           wt(item, "name"));
        items.push_back(
            {kind == std::string("pipelines") ? "pipeline" : "preset",
             getstr(item, "id")});
      }
    if (m.show() && !m.selected.empty()) {
      const auto &item = items[static_cast<size_t>(m.selected.front())];
      send("load", object({{"kind", item.first},
                           {"id", item.second},
                           {"node_id", selected}}));
    }
  }
  void history(const Json &data) {
    Modal m;
    m.owner = window;
    m.font = font;
    m.title = L"Recorded results";
    m.message = data.get("omitted").integer() > 0
                    ? L"Recent runs are shown; older records remain in their "
                      L"result folders."
                    : L"Open a recorded run to inspect its original diagram "
                      L"and status.";
    m.confirm = L"View run";
    const Json &runs = data.is_array() ? data : data.get("runs");
    for (const auto &r : runs.array_items())
      m.labels.push_back(wt(r, "started_at") + L" · " + wt(r, "status") +
                         L" · " + wt(r, "folder"));
    if (m.show() && !m.selected.empty()) {
      send("run/get",
           object({{"run_id", getstr(runs.array_items()[static_cast<size_t>(
                                         m.selected.front())],
                                     "run_id")}}));
    }
  }
  void update_run(const Json &value) {
    runState = value;
    if (getstr(value, "run_id").empty() && value.contains("run"))
      runState = value.get("run");
    const auto status_ = getstr(runState, "status");
    busy = status_ == "preparing" || status_ == "running" ||
           status_ == "cancelling";
    status_text(wide(status_) + L" · " + wt(runState, "message"));
    logs.clear();
    if (runState.get("events").is_array())
      for (const auto &e : runState.get("events").array_items())
        if (!getstr(e, "message").empty())
          logs += wt(e, "message") + L"\n";
    if (runState.get("events_omitted").integer() > 0)
      logs = L"Some earlier events are omitted here. Full step logs remain in "
             L"the recorded results folder.\n\n" +
             logs;
    if (logs.size() > 250000)
      logs = logs.substr(logs.size() - 250000);
    enabled();
    InvalidateRect(dag, nullptr, FALSE);
    if (closing && !busy && !refBusy && !packBusy && !setupBusy)
      send("shutdown");
  }
  void response(const Json &response_) {
    long long id = response_.get("id").integer();
    const bool concurrent = concurrentRequests.erase(id) != 0;
    if (id != activeRequest && !concurrent) return;
    if (id == activeRequest) activeRequest = 0;
    const auto found = pending.find(id);
    std::string method = found == pending.end() ? "" : found->second;
    if (found != pending.end())
      pending.erase(found);
    const bool standaloneSummary = standaloneResultSummaries.erase(id) != 0;
    std::string verificationKey;
    const auto verification = pendingIndexVerifications.find(id);
    if (verification != pendingIndexVerifications.end()) {
      verificationKey = verification->second;
      pendingIndexVerifications.erase(verification);
    }
    const auto viewContext = pendingViews.find(id);
    if (viewContext != pendingViews.end()) {
      Auxiliary &view = sample_editor_method(method) ? sampleEditorView : method.rfind("examples/", 0) == 0 ? curatedView :
          method.rfind("results/", 0) == 0 ? resultsView : auxiliary_method(method);
      const bool current = view.window && viewContext->second == view.generation;
      pendingViews.erase(viewContext);
      if (!current) {
        // A completed import changes the model even if its dialog was closed.
        // Read-only rows and preview tokens still belong to the old generation.
        if (response_.get("ok").boolean() && (method == "project/import" || method == "project/open") &&
            response_.get("result").contains("model")) {
          showingHistory = false; historyRun = Json::object();
          snapshot(response_.get("result").get("model")); canvas_reset_positions();
        }
        if (response_.get("ok").boolean() && method == "examples/load")
          curated_loaded(response_.get("result"));
        return;
      }
    }
    if (sample_editor_method(method)) { sample_editor_response(method, response_); return; }
    if (method == "setup/status")
      setupPollPending = false;
    else if (method.rfind("setup/", 0) == 0)
      setupActionPending = false;
    if (method == "status")
      pollPending = false;
    if (method == "queue/status") queuePollPending = false;
    else if (method.rfind("queue/", 0) == 0) queuePending = false;
    if (method.rfind("sample/", 0) == 0) samplePending = false;
    if (method.rfind("index/", 0) == 0) indexPending = false;
    if (method.rfind("resources/", 0) == 0) resourcePending = false;
    if (method.rfind("restart/", 0) == 0) restartPending = false;
    if (method.rfind("project/", 0) == 0) projectPending = false;
    if (method == "packs/status")
      packPollPending = false;
    if (method.rfind("packs/", 0) == 0 && method != "packs/list" &&
        method != "packs/status")
      packActionPending = false;
    if (method == "references/status")
      refPollPending = false;
    else if (method.rfind("references/", 0) == 0)
      refActionPending = false;
    if (!response_.get("ok").boolean()) {
      if (method.rfind("examples/", 0) == 0 || method.rfind("results/", 0) == 0) {
        const auto error = wt(response_, "error", "The local catalogue or result could not be read.");
        if (standaloneSummary) {
          message(error);
        } else if (method.rfind("examples/", 0) == 0) {
          aux_text(curatedView, CURATED_NOTICE, error);
        } else {
          aux_text(resultsView, RESULTS_NOTICE, error);
          if (method == "results/summary") aux_text(resultsView, RESULTS_DETAILS, error);
        }
        enabled();
        return;
      }
      if (recovery_method(method)) {
        recovery_error(method, wt(response_, "error", "The local operation returned an error."));
        enabled();
        return;
      }
      if (method.rfind("sample/", 0) == 0 || method.rfind("queue/", 0) == 0 || method.rfind("index/", 0) == 0) {
        const auto error = wt(response_, "error", "The local operation returned an error.");
        Auxiliary &view = method.rfind("sample/", 0) == 0 ? samplesView : method.rfind("queue/", 0) == 0 ? queueView : indexesView;
        if (method == "index/verify") {
          verifiedIndexes.erase(verificationKey);
          index_rows();
        }
        if (method == "sample/table" && sampleTable.contains("rows")) sample_table_rows();
        aux_text(view, view.kind == SHOW_SAMPLES ? SAMPLE_NOTICE : view.kind == SHOW_QUEUE ? QUEUE_NOTICE : INDEX_NOTICE,
            method == "sample/table" && sampleTable.contains("rows") ? error + L"\r\nThe previous table remains loaded; choose another path or edit that table." : error);
        if (method.rfind("sample/", 0) == 0) sample_invalidate();
        if (method != "queue/status" || !queuePollFailed)
          MessageBoxW(view.window ? view.window : window, error.c_str(), L"Native Workbench", MB_OK | MB_ICONERROR);
        if (method == "queue/status") queuePollFailed = true;
        enabled();
        return;
      }
      if (method.rfind("setup/", 0) == 0) {
        setupState["notice"] = getstr(response_, "error", "Tool setup returned an error.");
        setupState["operation"]["message"] = getstr(response_, "error", "Tool setup returned an error.");
        setup_notice();
        if (!setupPollFailed || method != "setup/status")
          MessageBoxW(setupWindow ? setupWindow : window,
              wt(response_, "error", "Tool setup returned an error.").c_str(),
              L"Tool setup", MB_OK | MB_ICONERROR);
        if (method == "setup/status") setupPollFailed = true;
        enabled();
        return;
      }
      if (method.rfind("references/", 0) == 0) {
        refOperation["message"] = getstr(response_, "error", "Reference discovery returned an error.");
        reference_notice();
        if (!refPollFailed || method != "references/status")
          MessageBoxW(refWindow ? refWindow : window,
                      wt(response_, "error", "Reference discovery returned an error.").c_str(),
                      L"References", MB_OK | MB_ICONERROR);
        if (method == "references/status")
          refPollFailed = true;
        enabled();
        return;
      }
      if (method.rfind("packs/", 0) == 0) {
        if (method != "packs/status") {
          packReloadAfterOperation = false;
          packListAfterOperation = false;
        }
        packOperation["message"] = getstr(response_, "error", "The tool manager returned an error.");
        pack_notice();
        if (!packPollFailed || method != "packs/status")
          MessageBoxW(packWindow ? packWindow : window,
                      wt(response_, "error", "The tool manager returned an error.").c_str(),
                      L"Manage tools", MB_OK | MB_ICONERROR);
        if (method == "packs/status")
          packPollFailed = true;
        enabled();
        return;
      }
      if (method == "status" && closing) {
        send("shutdown");
        return;
      }
      if (concurrent) {
        message(wt(response_, "error", "The local monitoring or cancellation request failed."));
        enabled();
        return;
      }
      reviewThenRun = false;
      submittedFields.clear();
      pendingCanvasDrop = false;
      for (const auto &request : outgoing) {
        pending.erase(request.get("id").integer());
        pendingViews.erase(request.get("id").integer());
        pendingIndexVerifications.erase(request.get("id").integer());
      }
      outgoing.clear();
      message(wt(response_, "error", "The local engine returned an error."));
      if (method == "init")
        ready = false;
      enabled();
      return;
    }
    const auto &result = response_.get("result");
    if (method == "examples/list") {
      curated_rows(result);
    } else if (method == "examples/load") {
      curated_loaded(result);
    } else if (method == "results/search") {
      results_rows(result);
    } else if (method == "results/summary") {
      if (standaloneSummary)
        show_text(L"Recorded result summary", wt(result, "summaryText", getstr(result, "details")));
      else results_summary(result);
    } else if (recovery_method(method)) {
      recovery_response(method, result);
    } else if (method == "sample/targets") {
      sampleGraph = state.get("graph");
      sampleTargetSchema = result;
      if (samplesView.window) sample_mode();
    } else if (method == "sample/table") {
      sampleLoadedPath = narrow(control_text(aux(samplesView, SAMPLE_PATH)));
      sampleTable = result;
      sample_table_rows();
    } else if (method == "sample/preview") {
      sample_preview_rows(result);
    } else if (method.rfind("queue/", 0) == 0) {
      queuePollFailed = false;
      queue_response(result);
    } else if (method == "index/list") {
      indexState = result;
      index_rows();
    } else if (method == "index/verify") {
      verifiedIndexes[getstr(result, "key")] = result;
      index_rows();
      aux_text(indexesView, INDEX_NOTICE, L"The selected index matched its complete file inventory. Execution rechecks it before reuse.");
    } else if (method.rfind("setup/", 0) == 0) {
      setup_response(method, result);
    } else if (method.rfind("packs/", 0) == 0) {
      pack_response(method, result);
    } else if (method.rfind("references/", 0) == 0) {
      reference_response(method, result);
    } else if (method == "workspace/connection-targets") {
      canvas_set_targets(result);
    } else if (method == "init") {
      ready = true;
      if (result.contains("catalog"))
        catalog = result.get("catalog");
      snapshot(result);
      refresh_tasks();
      status_text(L"Ready. All computation remains on this computer.");
      if (autoCheck) {
        setupWelcomeChecked = true;
        autoCheck = false;
        send("check",
             object({{"output_folder", narrow(control_text(output))}}));
      } else if (!setupWelcomeChecked && !setupPollPending)
        setup_send("setup/status");
      if (!queuePollPending) queue_send("queue/status");
    } else if (method == "model" || method == "load" || method == "example" ||
               method == "workspace/mode" || method == "workspace/tool") {
      submittedFields.clear();
      snapshot(result);
      if (method == "load" || method == "example") canvas_reset_positions();
      if (pendingCanvasDrop && method == "model" && workflowMode &&
          !selected.empty() && !canvasDropExisting.count(selected)) {
        canvas_place_new_node(selected, canvasDropPoint);
        pendingCanvasDrop = false;
      }
      if (!getstr(state, "pendingSource").empty())
        status_text(L"Tool library now shows tools compatible with the "
                    L"selected named output.");
      else if (method == "workspace/mode" || method == "workspace/tool")
        status_text(workflowMode
                        ? L"Drag tools onto the canvas. Select a tool to edit its options."
                        : L"Select a tool, choose its inputs and options, then run it locally.");
    } else if (method == "methods/preview") {
      std::wstring content = wt(result, "methods", "No planned methods are available.");
      if (!result.get("issues").array_items().empty()) {
        content += L"\n\nWorkflow issues\n";
        for (const auto &issue : result.get("issues").array_items())
          content += wt(issue, "severity") + L": " + wt(issue, "message") + L"\n";
      }
      show_text(L"Planned methods", content);
    } else if (method == "review") {
      std::wstring content;
      if (result.contains("readiness")) {
        const auto &readiness = result.get("readiness");
        content = wt(readiness, "summary") + L"\n\n";
        for (const auto &check : readiness.get("checks").array_items())
          content += wt(check, "label") + L" [" + wt(check, "status") +
                     L"]\n" + wt(check, "message") + L"\n\n";
      }
      for (const auto &issue : result.get("issues").array_items())
        content += wt(issue, "severity") + L": " + wt(issue, "message") + L"\n";
      content += L"\n" + wt(result, "methods");
      bool start = reviewThenRun;
      reviewThenRun = false;
      Modal m;
      m.owner = window;
      m.font = font;
      m.mode = 2;
      m.title = L"Review and run";
      m.message = L"Check the inputs and planned analysis before running.";
      m.value = content;
      m.confirm =
          start && result.get("valid").boolean() ? L"Run analysis" : L"Done";
      if (m.show() && start && result.get("valid").boolean())
        send("run", object({{"output_folder", narrow(control_text(output))}}));
    } else if (method == "diagnostics/review") {
      Modal m;
      m.owner = window;
      m.font = font;
      m.mode = 2;
      m.title = L"Review diagnostic report";
      m.message = L"Review the report, then save it to the selected output folder. Nothing is uploaded.";
      m.value = wt(result, "preview");
      m.confirm = L"Save diagnostic ZIP";
      if (m.show())
        send("diagnostics/save", object({{"token", getstr(result, "token")},
             {"output_folder", narrow(control_text(output))}}));
    } else if (method == "diagnostics/save") {
      show_text(L"Diagnostic report saved", L"Saved locally. Nothing was uploaded.\n\n" + wt(result, "path"));
    } else if (method == "run" || method == "check") {
      runId = getstr(result, "run_id");
      busy = true;
      status_text(L"Preparing local analysis...");
      enabled();
    } else if (method == "run/get") {
      historyRun = result;
      canvas_enter_history();
      showingHistory = true;
      refresh_steps();
      rebuild_inspector();
      layout();
      status_text(L"Recorded run: " + wt(historyRun, "status") +
                  L". Editable workspace preserved.");
      enabled();
    } else if (method == "status")
      update_run(result);
    else if (method == "cancel")
      update_run(result);
    else if (method == "saved")
      load_saved(result);
    else if (method == "history")
      history(result);
    else if (method == "save")
      status_text(L"Saved for reuse without input file bindings.");
    else if (method == "import") {
      if (result.get("success").boolean()) {
        status_text(L"Tool pack import completed.");
        if (result.contains("model"))
          snapshot(result.get("model"));
        else
          send("init");
      } else
        message(wt(result, "message", "The tool pack could not be imported."));
    } else if (method == "shutdown") {
      if (!result.get("closed").boolean(true))
        MessageBoxW(window,
                    L"The engine could not finish every cleanup operation. "
                    L"Workbench will close the remaining processes; incomplete "
                    L"results stay in their run folders.",
                    L"Local cleanup", MB_OK | MB_ICONWARNING);
      close_host_window();
    }
  }
  void command(int id, int notification) {
    if (rebuilding)
      return;
    if (id >= FIELD_BASE) {
      field_command(id, notification);
      return;
    }
    if (id == SEARCH && notification == EN_CHANGE) {
      refresh_tasks();
      enabled();
      return;
    }
    // Native edit notifications are not actions. Keep the draft intact while
    // typing; the next explicit operation commits it transactionally.
    if (id == NAME || id == OUTPUT || id == INPUT_FOLDER || id == SEARCH)
      return;
    if ((id == SHOW_SAMPLES || id == SHOW_QUEUE || id == SHOW_INDEXES ||
         id == SHOW_RESOURCES || id == SHOW_RESTART || id == SHOW_PROJECTS) && ready && !closing) {
      if (id == SHOW_SAMPLES && showingHistory) return;
      commit_all();
      show_auxiliary(id);
      return;
    }
    if (id == GENERAL_SETTINGS) {
      commit_all();
      generalVisible = !generalVisible;
      layout();
      return;
    }
    if (id == RESET_LAYOUT) {
      canvas_reset_positions();
      return;
    }
    // View navigation is also available in read-only recorded workflows.
    if (id == ZOOM_OUT || id == ZOOM_IN || id == ZOOM_RESET) {
      if (id == ZOOM_RESET) canvas_zoom_reset();
      else canvas_zoom_by(id == ZOOM_IN ? 1.2 : 1.0 / 1.2);
      return;
    }
    if (id == BROWSE_INPUT) {
      auto path = pick(window, true, false, L"", L"Choose the starting folder for input file pickers",
                       control_text(inputFolder));
      if (!path.empty()) SetWindowTextW(inputFolder, path.c_str());
      return;
    }
    if (id == ADD) {
      add_task();
      return;
    }
    if (id == CLEAR_FILTER) {
      commit_all();
      model("select", object({{"nodeId", selected}}));
      return;
    }
    if (id == BROWSE_OUTPUT) {
      auto path = pick(window, true, false, L"",
                       L"Choose the parent folder for new run results", control_text(output));
      if (!path.empty())
        SetWindowTextW(output, path.c_str());
      return;
    }
    if (id == CANCEL && !runId.empty() && !cancellation_pending()) {
      if (!getstr(queueState, "active_job").empty() && getstr(queueState, "active_run") == runId)
        queue_send("queue/cancel", object({{"job_id", getstr(queueState, "active_job")}}));
      else send("cancel", object({{"run_id", runId}}));
      return;
    }
    if (id == BACK_WORKSPACE) {
      showingHistory = false;
      canvas_leave_history();
      historyRun = Json::object();
      snapshot(state);
      layout();
      return;
    }
    if (id == FILE_EXIT) {
      SendMessageW(window, WM_CLOSE, 0, 0);
      return;
    }
    if (id == VIEW_LOG) {
      show_text(L"Run log", logs.empty() ? L"No run log yet." : logs);
      return;
    }
    if (id == OPEN_RESULTS) {
      const auto identity =
          showingHistory ? getstr(historyRun, "run_id") : runId;
      if (!identity.empty())
        send("open", object({{"run_id", identity}}));
      return;
    }
    if (id == FILE_HISTORY) {
      commit_all();
      send("history");
      return;
    }
    if (id == RESULTS_LIST || id == SHOW_RESULTS) {
      commit_all();
      show_auxiliary(SHOW_RESULTS);
      return;
    }
    if (id == VIEW_RESULT_SUMMARY) {
      show_result_summary(showingHistory ? getstr(historyRun, "run_id") : runId);
      return;
    }
    if (id == SHOW_CURATED && ready && !closing) {
      commit_all();
      show_auxiliary(SHOW_CURATED);
      return;
    }
    if (id == FILE_SAVE_PIPELINE || id == SAVE_CURRENT) {
      save(id == FILE_SAVE_PIPELINE || workflowMode);
      return;
    }
    if (id == FILE_SAVE_PRESET) {
      save(false);
      return;
    }
    if ((id == FILE_IMPORT || id == MANAGE_TOOLS) && ready && !analysis_active() &&
        !showingHistory && !closing) {
      commit_all();
      show_pack_manager();
      return;
    }
    if (id == TOOL_SETUP && ready && !analysis_active() && !closing) {
      show_setup();
      if (!setupPollPending && !setupActionPending) setup_send("setup/status");
      return;
    }
    if (id == MANAGE_REFERENCES && ready && !analysis_active() && !showingHistory && !closing) {
      if (!refBusy && !refActionPending && !packBusy && !packActionPending)
        commit_all();
      show_references();
      return;
    }
    if (id == REVIEW_DIAGNOSTICS && ready && !closing) {
      const auto identity = showingHistory ? getstr(historyRun, "run_id") : runId;
      send("diagnostics/review", identity.empty() ? object({}) : object({{"run_id", identity}}));
      return;
    }
    if (setupBusy || setupActionPending || packBusy || packActionPending || refBusy || refActionPending || showingHistory) {
      if (id == REVIEW || id == VIEW_METHODS)
        show_text(
            L"Recorded methods",
            wt(showingHistory ? historyRun : runState, "methods",
               getstr(showingHistory ? historyRun : runState, "methods_planned",
                      "Methods are saved in the run folder.")));
      return;
    }
    if ((id == RUN || id == FILE_CHECK) && analysis_active()) return;
    commit_all();
    switch (id) {
    case MODE_TOOLS:
    case MODE_WORKFLOW:
      canvas_cancel_drag();
      send("workspace/mode", object({{"mode", id == MODE_WORKFLOW ? "workflow" : "tool"}}));
      break;
    case ADD_INPUT:
      add_workflow_input();
      break;
    case REMOVE:
      if (!selected.empty()) {
        if (getstr(state.get("inspector"), "kind") == "source")
          model("remove_source", object({{"sourceId", selected}}));
        else model("remove_step", object({{"nodeId", selected}}));
      }
      break;
    case UNDO:
      model("undo");
      break;
    case UP:
    case DOWN:
      if (!selected.empty())
        model("move_step", object({{"nodeId", selected},
                                   {"direction", id == UP ? "up" : "down"}}));
      break;
    case RUN:
      reviewThenRun = true;
      send("review", object({{"output_folder", narrow(control_text(output))}}));
      break;
    case REVIEW:
    case VIEW_METHODS:
      reviewThenRun = false;
      send("methods/preview");
      break;
    case FILE_NEW:
      canvas_reset_positions();
      model("clear");
      break;
    case FILE_EXAMPLE:
      send("example");
      break;
    case FILE_SAVE_PIPELINE:
      save(true);
      break;
    case FILE_SAVE_PRESET:
      save(false);
      break;
    case FILE_LOAD:
    case LOAD_CURRENT:
      send("saved");
      break;
    case FILE_CHECK:
      send("check", object({{"output_folder", narrow(control_text(output))}}));
      break;
    default:
      break;
    }
  }
#include "recovery_ui.h"
#include "curated_ui.h"
#include "results_ui.h"
#include "sample_editor_ui.h"
#include "workflow_canvas.h"
  void panel_mouse_wheel(HWND panel, WPARAM w) {
    // Precision wheels can report less than one logical pixel of movement.
    // Retain that fraction per panel; zero must never become SB_LINEUP (0).
    int &remainder = panel == generalPanel ? generalWheelRemainder : formWheelRemainder;
    remainder -= GET_WHEEL_DELTA_WPARAM(w) * 48;
    const int amount = remainder / WHEEL_DELTA;
    remainder %= WHEEL_DELTA;
    if (amount) scroll(panel, SB_VERT, 0, amount);
  }
  void scroll(HWND h, int bar, int action, int delta = 0) {
    if (h == dag) { canvas_scroll(bar, action, delta); return; }
    RECT r{};
    GetClientRect(h, &r);
    int extent = h == generalPanel ? 532 : h == form ? formExtent
                 : bar == SB_HORZ ? dagWidth
                                  : dagHeight,
        page = MulDiv(bar == SB_HORZ ? r.right : r.bottom, 96, dpi),
        *value = h == generalPanel ? &generalScroll : h == form ? &formScroll
                 : bar == SB_HORZ ? &dagX
                                  : &dagY;
    SCROLLINFO si{sizeof(si), SIF_TRACKPOS};
    GetScrollInfo(h, bar, &si);
    const int previous = *value;
    if (delta)
      *value += delta;
    else
      switch (action) {
      case SB_LINEUP:
        *value -= 32;
        break;
      case SB_LINEDOWN:
        *value += 32;
        break;
      case SB_PAGEUP:
        *value -= page;
        break;
      case SB_PAGEDOWN:
        *value += page;
        break;
      case SB_THUMBTRACK:
      case SB_THUMBPOSITION:
        *value = si.nTrackPos;
        break;
      case SB_TOP:
        *value = 0;
        break;
      case SB_BOTTOM:
        *value = extent;
        break;
      default:
        break;
      }
    *value = std::clamp(*value, 0, std::max(0, extent - page));
    if (*value == previous)
      return;
    if (h == form)
      layout_fields();
    else if (h == generalPanel)
      layout_general();
    else
      InvalidateRect(dag, nullptr, FALSE);
  }
  static LRESULT CALLBACK surface(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *app =
        reinterpret_cast<Workspace *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      app = static_cast<Workspace *>(
          reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app)
      return DefWindowProcW(h, m, w, l);
    try {
      if (h == app->dag) {
        if (m == WM_GESTURE && app->canvas_gesture(l)) return 0;
        if (m == WM_GESTURENOTIFY) app->canvas_configure_gestures();
        if (m == WM_MOUSELEAVE) { app->canvas_mouse_leave(); return 0; }
        if (m == WM_KEYDOWN && app->canvas_key_down(w)) return 0;
        if (m == WM_MOUSEWHEEL || m == WM_MOUSEHWHEEL) {
          app->canvas_mouse_wheel(w, l, m == WM_MOUSEHWHEEL); return 0;
        }
      }
      if (m == WM_PAINT && GetDlgCtrlID(h) == DAG) {
        app->paint_dag();
        return 0;
      }
      if (m == WM_ERASEBKGND) {
        RECT r{};
        GetClientRect(h, &r);
        FillRect(reinterpret_cast<HDC>(w), &r, h == app->generalPanel ? app->background : app->paper);
        return 1;
      }
      if (m == WM_VSCROLL || m == WM_HSCROLL) {
        app->scroll(h, m == WM_HSCROLL ? SB_HORZ : SB_VERT, LOWORD(w));
        return 0;
      }
      if (m == WM_MOUSEWHEEL) {
        app->panel_mouse_wheel(h, w);
        return 0;
      }
      if (h == app->dag) {
        const POINT p{GET_X_LPARAM(l), GET_Y_LPARAM(l)};
        if (m == WM_LBUTTONDOWN && app->canvas_mouse_down(p)) return 0;
        if (m == WM_MOUSEMOVE && app->canvas_mouse_move(p)) return 0;
        if (m == WM_LBUTTONUP && app->canvas_mouse_up(p)) return 0;
        if (m == WM_CAPTURECHANGED || m == WM_CANCELMODE ||
            (m == WM_KEYDOWN && w == VK_ESCAPE)) {
          app->canvas_cancel_drag();
          return 0;
        }
      }
      if (m == WM_COMMAND || m == WM_CTLCOLORSTATIC || m == WM_CTLCOLOREDIT ||
          m == WM_CTLCOLORBTN)
        return SendMessageW(app->window, m, w, l);
    } catch (const std::exception &e) {
      app->message(wide(e.what()));
    }
    return DefWindowProcW(h, m, w, l);
  }
  LRESULT handle(UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CREATE:
      dpi = GetDpiForWindow(window);
      fonts();
      controls();
      PostMessageW(window, WM_APP + 1, 0, 0);
      return 0;
    case WM_APP + 1:
      host.start(root, window, HOST_MESSAGE);
      send("init");
      return 0;
    case HOST_MESSAGE: {
      std::unique_ptr<std::string> bytes(reinterpret_cast<std::string *>(l));
      if (w) {
        ready = false;
        busy = false;
        packBusy = false;
        packActionPending = false;
        setupBusy = false;
        setupActionPending = false;
        refBusy = false;
        refActionPending = false;
        sampleEditorPending = false;
        status_text(L"The local engine stopped. Restart Workbench; "
                    L"incomplete runs remain recorded.");
        if (closing)
          close_host_window();
        else
          message(L"The local analysis engine stopped unexpectedly.\n\nRestart "
                  L"Workbench. Diagnostic information is saved in "
                  L"user-data\\desktop-host.stderr.txt.");
        enabled();
      } else {
        response(Json::parse(*bytes));
        if (IsWindow(window)) {
          pump();
          enabled();
        }
      }
      return 0;
    }
    case WM_SIZE:
      // A minimized client has no visible layout. Keep the normal dimensions
      // and panel scroll positions until the restored size is available.
      if (w != SIZE_MINIMIZED) layout();
      return 0;
    case WM_DPICHANGED:
      dpi = HIWORD(w);
      fonts();
      {
        auto *r = reinterpret_cast<RECT *>(l);
        SetWindowPos(window, nullptr, r->left, r->top, r->right - r->left,
                     r->bottom - r->top, SWP_NOZORDER | SWP_NOACTIVATE);
      }
      layout();
      // Logical dimensions can remain unchanged across a DPI transition.
      // The parent-painted brand and separators still need the new scale.
      InvalidateRect(window, nullptr, FALSE);
      return 0;
    case WM_SYSCOLORCHANGE:
    case WM_THEMECHANGED:
    case WM_SETTINGCHANGE:
      if (tasks) {
        library_colors();
        RedrawWindow(tasks, nullptr, nullptr, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME);
      }
      break;
    case WM_GETMINMAXINFO: {
      auto *p = reinterpret_cast<MINMAXINFO *>(l);
      MONITORINFO monitor{sizeof(monitor)};
      if (!GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &monitor))
        SystemParametersInfoW(SPI_GETWORKAREA, 0, &monitor.rcWork, 0);
      p->ptMinTrackSize = {
          std::min<LONG>(px(workspace_layout::minimum_width), monitor.rcWork.right - monitor.rcWork.left),
          std::min<LONG>(px(workspace_layout::minimum_height), monitor.rcWork.bottom - monitor.rcWork.top)};
      return 0;
    }
    case WM_KEYDOWN:
      if (w == VK_ESCAPE && !showingHistory &&
          !getstr(state, "pendingSource").empty()) {
        model("select", object({{"nodeId", selected}}));
        status_text(L"Showing all tools.");
        return 0;
      }
      break;
    case WM_COMMAND:
      command(LOWORD(w), HIWORD(w));
      return 0;
    case WM_NOTIFY: {
      auto *n = reinterpret_cast<NMHDR *>(l);
      if (n->idFrom == TASKS && n->code == NM_CUSTOMDRAW)
        return library_draw(*reinterpret_cast<NMTVCUSTOMDRAW *>(l));
      if (n->idFrom == TASKS && n->code == TVN_SELCHANGEDW && !rebuilding) {
        const auto *item = reinterpret_cast<NMTREEVIEWW *>(l);
        library_ensure_visible(item->itemNew.hItem);
        if (libraryFiltered && !library_tool(item->itemNew.hItem).empty())
          libraryViews[workflowMode].selected = library_key(item->itemNew.hItem);
        if (!workflowMode) add_task(item->itemNew.hItem);
        enabled();
        return 0;
      }
      if (n->idFrom == TASKS && n->code == TVN_ITEMEXPANDEDW && !rebuilding) {
        const auto *item = reinterpret_cast<NMTREEVIEWW *>(l);
        const auto *row = library_row(item->itemNew.hItem);
        if (row && row->toolId.empty() && !libraryFiltered)
          libraryExpanded[row->category] = (item->itemNew.state & TVIS_EXPANDED) != 0;
        if (!libraryExpanding) {
          const auto anchor = library_anchor();
          const int offset = library_anchor_offset(anchor);
          library_update_visible();
          library_restore_anchor(anchor, offset);
          library_position(true, true);
        }
        return 0;
      }
      if (n->idFrom == TASKS && n->code == TVN_BEGINDRAGW && workflowMode && !rebuilding) {
        const auto *item = reinterpret_cast<NMTREEVIEWW *>(l);
        const auto toolId = library_tool(item->itemNew.hItem);
        if (!toolId.empty()) {
          dragTool = toolId;
          SetCapture(window);
          status_text(L"Drop on the workflow canvas to add this tool.");
        }
        return 0;
      }
      if (n->idFrom == STEPS && n->code == LVN_ITEMCHANGED && !rebuilding &&
          !showingHistory) {
        auto *item = reinterpret_cast<NMLISTVIEW *>(l);
        if ((item->uNewState & LVIS_SELECTED) &&
            !(item->uOldState & LVIS_SELECTED) && item->iItem >= 0 &&
            static_cast<size_t>(item->iItem) < stepIds.size()) {
          commit_all();
          model(
              "select",
              object({{"nodeId", stepIds[static_cast<size_t>(item->iItem)]}}));
        }
      }
      return 0;
    }
    case WM_LBUTTONUP:
      if (!dragTool.empty()) {
        const auto droppedTool = dragTool;
        ReleaseCapture();
        POINT p{GET_X_LPARAM(l), GET_Y_LPARAM(l)};
        ClientToScreen(window, &p);
        RECT r{};
        GetWindowRect(dag, &r);
        if (workflowMode && PtInRect(&r, p)) {
          commit_all();
          ScreenToClient(dag, &p);
          canvasDropPoint = p;
          canvasDropExisting.clear();
          for (const auto &node : graph().get("nodes").array_items())
            canvasDropExisting.insert(getstr(node, "id"));
          pendingCanvasDrop = true;
          model("add_tool", object({{"toolId", droppedTool}}));
        }
        dragTool.clear();
        return 0;
      }
      break;
    case WM_CAPTURECHANGED:
      dragTool.clear();
      return 0;
    case WM_TIMER:
      if (closing && closeStarted && GetTickCount64() - closeStarted > 25000) {
        status_text(L"The engine did not finish shutting down. Forcing "
                    L"cleanup; this run remains interrupted.");
        MessageBoxW(
            window,
            L"The local operation did not stop within 25 seconds. Workbench will "
            L"close its process group now.\n\nCompleted references are preserved. "
            L"Incomplete analysis runs will be marked interrupted when reopened.",
            L"Force local cleanup", MB_OK | MB_ICONWARNING);
        close_host_window();
        return 0;
      }
      if (ready && !closing && !queuePollPending && !queuePending && ((!activeRequest && outgoing.empty()) || slow_request_pending()) &&
          GetTickCount64() - lastQueuePoll > (queuePollFailed ? 5000 : busy || queuePreparing ? 650 : 2000)) {
        lastQueuePoll = GetTickCount64();
        queue_send("queue/status");
      }
      if (ready && !runId.empty() && busy && !pollPending && ((!activeRequest && outgoing.empty()) || slow_request_pending()) &&
          GetTickCount64() - lastPoll > 350) {
        lastPoll = GetTickCount64();
        pollPending = true;
        send("status", object({{"run_id", runId}}));
      }
      if (ready && packBusy && !packPollPending && !packActionPending &&
          GetTickCount64() - lastPackPoll > (packPollFailed ? 3000 : 650)) {
        lastPackPoll = GetTickCount64();
        pack_send("packs/status");
      }
      if (ready && setupBusy && !setupPollPending && !setupActionPending &&
          GetTickCount64() - lastSetupPoll > (setupPollFailed ? 3000 : 650)) {
        lastSetupPoll = GetTickCount64();
        setup_send("setup/status");
      }
      if (ready && refBusy && !refPollPending && !refActionPending &&
          GetTickCount64() - lastRefPoll > (refPollFailed ? 3000 : 650)) {
        lastRefPoll = GetTickCount64();
        reference_send("references/status");
      }
      return 0;
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLOREDIT:
    case WM_CTLCOLORBTN: {
      HDC dc = reinterpret_cast<HDC>(w);
      SetTextColor(dc, INK);
      const bool white = m == WM_CTLCOLOREDIT || GetParent(reinterpret_cast<HWND>(l)) == form;
      SetBkMode(dc, OPAQUE);
      SetBkColor(dc, white ? PAPER : BACK);
      return reinterpret_cast<LRESULT>(white ? paper : background);
    }
    case WM_DRAWITEM: {
      const auto *item = reinterpret_cast<DRAWITEMSTRUCT *>(l);
      if (item->CtlType != ODT_BUTTON) break;
      const int buttonWidth = item->rcItem.right - item->rcItem.left;
      const int buttonHeight = item->rcItem.bottom - item->rcItem.top;
      HDC buffer = CreateCompatibleDC(item->hDC);
      HBITMAP bitmap = buffer ? CreateCompatibleBitmap(item->hDC,
          std::max(1, buttonWidth), std::max(1, buttonHeight)) : nullptr;
      HGDIOBJ previousBitmap = bitmap ? SelectObject(buffer, bitmap) : nullptr;
      HDC dc = bitmap ? buffer : item->hDC;
      const int savedDc = SaveDC(dc);
      if (bitmap) SetWindowOrgEx(dc, item->rcItem.left, item->rcItem.top, nullptr);
      const bool primary = item->CtlID == RUN;
      const bool active = (item->CtlID == MODE_TOOLS && !workflowMode) ||
                          (item->CtlID == MODE_WORKFLOW && workflowMode);
      const bool disabled = (item->itemState & ODS_DISABLED) != 0;
      COLORREF fill = primary ? (disabled ? RGB(151, 169, 184) : ACCENT) :
                      active ? RGB(68, 81, 105) : NAVY;
      if (item->itemState & ODS_SELECTED) fill = RGB(33, 65, 92);
      HBRUSH brush = CreateSolidBrush(fill);
      FillRect(dc, &item->rcItem, brush);
      DeleteObject(brush);
      SetBkMode(dc, TRANSPARENT);
      SetTextColor(dc, disabled ? RGB(216, 221, 228) : PAPER);
      SelectObject(dc, bold);
      RECT r = item->rcItem;
      const auto label = control_text(item->hwndItem);
      DrawTextW(dc, label.c_str(), -1, &r, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
      if (active) {
        RECT underline = r; underline.top = underline.bottom - px(3);
        HBRUSH line = CreateSolidBrush(RGB(141, 199, 233));
        FillRect(dc, &underline, line); DeleteObject(line);
      }
      if (item->itemState & ODS_FOCUS) {
        InflateRect(&r, -px(4), -px(4)); DrawFocusRect(dc, &r);
      }
      if (bitmap)
        BitBlt(item->hDC, item->rcItem.left, item->rcItem.top, buttonWidth, buttonHeight,
               dc, item->rcItem.left, item->rcItem.top, SRCCOPY);
      if (savedDc) RestoreDC(dc, savedDc);
      if (bitmap) { SelectObject(buffer, previousBitmap); DeleteObject(bitmap); }
      if (buffer) DeleteDC(buffer);
      return TRUE;
    }
    case WM_PAINT: {
      PAINTSTRUCT ps{};
      HDC dc = BeginPaint(window, &ps);
      RECT r{};
      GetClientRect(window, &r);
      FillRect(dc, &r, background);
      RECT header{0, 0, r.right, px(48)};
      HBRUSH navy = CreateSolidBrush(NAVY);
      FillRect(dc, &header, navy); DeleteObject(navy);
      const auto geometry = workspace_layout::for_client(width, height);
      RECT center{px(geometry.center), px(49), px(width - geometry.right - 1), px(height - 28)};
      FillRect(dc, &center, paper);
      SetBkMode(dc, TRANSPARENT); SetTextColor(dc, PAPER);
      SelectObject(dc, bold);
      RECT brand{px(16), 0, px(206), px(48)};
      DrawTextW(dc, L"Native Workbench", -1, &brand, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
      HPEN pen = CreatePen(PS_SOLID, 1, BORDER);
      HGDIOBJ old = SelectObject(dc, pen);
      for (int x : {geometry.left, width - geometry.right}) {
        MoveToEx(dc, px(x), px(48), nullptr); LineTo(dc, px(x), px(height - 28));
      }
      MoveToEx(dc, 0, px(height - 28), nullptr); LineTo(dc, r.right, px(height - 28));
      SelectObject(dc, old); DeleteObject(pen);
      EndPaint(window, &ps);
      return 0;
    }
    case WM_ERASEBKGND:
      return 1;
    case WM_CLOSE:
      if (closing)
        return 0;
      if (!sample_editor_close()) return 0;
      if (setupBusy || setupActionPending) {
        if (setupBusy && !setupState.get("operation").get("cancellable").boolean(true)) {
          MessageBoxW(window, L"A tool installation is being committed. Please wait for it to finish.",
              L"Finishing tool installation", MB_OK | MB_ICONINFORMATION);
          return 0;
        }
        if (MessageBoxW(window, L"Cancel tool setup and close Workbench?\n\nCompleted packs will remain installed. Reopen Tool setup to retry unfinished downloads.",
            L"Close Native Workbench", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return 0;
        closing = true;
        closeStarted = GetTickCount64();
        setup_send("setup/cancel");
        status_text(L"Cancelling tool setup before closing...");
        enabled();
        return 0;
      }
      if (refBusy || refActionPending) {
        if (refBusy && !refOperation.get("cancellable").boolean(true)) {
          MessageBoxW(window, L"The reference library change is being committed. Please wait "
                      L"for it to finish before closing Workbench.",
                      L"Finishing reference operation", MB_OK | MB_ICONINFORMATION);
          return 0;
        }
        const bool pauseDownload = refBusy && (getstr(refOperation, "action") == "download" ||
                                               getstr(refOperation, "action") == "resume");
        if (MessageBoxW(window, pauseDownload
                        ? L"Pause the reference download and close Workbench?\n\nPartial downloads will be retained for explicit Resume. Completed references will be preserved."
                        : L"A reference operation is in progress. Cancel it and close Workbench?\n\nCompleted references and original files will be preserved.",
                        L"Close Native Workbench",
                        MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES)
          return 0;
        closing = true;
        closeStarted = GetTickCount64();
        reference_send(pauseDownload ? "references/pause" : "references/cancel");
        status_text(pauseDownload ? L"Pausing the reference download before closing..."
                                  : L"Cancelling the reference operation before closing...");
        enabled();
        return 0;
      }
      if (packBusy || packActionPending) {
        if (packBusy && !packOperation.get("cancellable").boolean(true)) {
          MessageBoxW(window,
                      L"Installation is being committed. Please wait for it to finish "
                      L"before closing Workbench.",
                      L"Finishing tool installation", MB_OK | MB_ICONINFORMATION);
          return 0;
        }
        if (MessageBoxW(window,
                        L"Tools are being managed. Cancel the operation and close "
                        L"Workbench?\n\nInstalled tools will be preserved.",
                        L"Close Native Workbench",
                        MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES)
          return 0;
        closing = true;
        closeStarted = GetTickCount64();
        pack_send("packs/cancel");
        status_text(L"Cancelling the tool operation before closing...");
        enabled();
        return 0;
      }
      if (busy) {
        if (MessageBoxW(window,
                        L"An analysis is running. Cancel it and close "
                        L"Workbench?\n\nChoose No to keep the analysis and "
                        L"window open. Queued analyses remain saved for the next session.",
                        L"Close Native Workbench",
                        MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES)
          return 0;
        closing = true;
        closeStarted = GetTickCount64();
        queue_send("queue/pause");
        send("cancel", object({{"run_id", runId}}));
        status_text(
            L"Cancelling and saving the interrupted run before closing...");
        enabled();
        return 0;
      }
      closing = true;
      closeStarted = GetTickCount64();
      if (ready)
        send("shutdown");
      else
        DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      host.stop();
      KillTimer(window, 1);
      PostQuitMessage(0);
      return 0;
    default:
      break;
    }
    return DefWindowProcW(window, m, w, l);
  }
  static LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    auto *app =
        reinterpret_cast<Workspace *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
      app = static_cast<Workspace *>(
          reinterpret_cast<CREATESTRUCTW *>(l)->lpCreateParams);
      app->window = h;
      SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app)
      return DefWindowProcW(h, m, w, l);
    try {
      return app->handle(m, w, l);
    } catch (const std::exception &e) {
      app->message(wide(e.what()));
      return m == WM_CREATE ? -1 : 0;
    } catch (...) {
      app->message(L"The interface encountered an unexpected error.");
      return m == WM_CREATE ? -1 : 0;
    }
  }

public:
  ~Workspace() {
    if (window && IsWindow(window))
      DestroyWindow(window);
    host.stop();
    // Classes retain their icon handles. Release them before destroying our
    // private icons; an unexpected live class can safely retain them until exit.
    bool iconsUnused = true;
    if (appLibraryViewportClass)
      iconsUnused = UnregisterClassW(MAKEINTATOM(appLibraryViewportClass), instance) != FALSE;
    if (appSurfaceClass)
      iconsUnused = (UnregisterClassW(MAKEINTATOM(appSurfaceClass), instance) != FALSE) && iconsUnused;
    if (appWindowClass)
      iconsUnused = (UnregisterClassW(MAKEINTATOM(appWindowClass), instance) != FALSE) && iconsUnused;
    if (iconsUnused) {
      if (appIcon)
        DestroyIcon(appIcon);
      if (appSmallIcon)
        DestroyIcon(appSmallIcon);
    }
    for (HFONT f : {font, bold, small, libraryBold, refFont})
      if (f)
        DeleteObject(f);
    if (paper)
      DeleteObject(paper);
    if (background)
      DeleteObject(background);
    MSG msg{};
    while (PeekMessageW(&msg, nullptr, HOST_MESSAGE, HOST_MESSAGE, PM_REMOVE))
      delete reinterpret_cast<std::string *>(msg.lParam);
  }
  int run_app(HINSTANCE inst, bool check, const std::wstring &windowClass) {
    instance = inst;
    autoCheck = check;
    root = bw::executable_folder();
    CreateDirectoryW(bw::native_path(root + L"\\results").c_str(), nullptr);
    paper = CreateSolidBrush(PAPER);
    background = CreateSolidBrush(BACK);
    WNDCLASSEXW wc{sizeof(wc)};
    wc.lpfnWndProc = proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    // LR_SHARED caches by resource identity rather than requested size. Own
    // separate images so the small title-bar icon uses its native-size frame.
    appIcon = static_cast<HICON>(LoadImageW(inst, MAKEINTRESOURCEW(IDI_WORKBENCH),
                                         IMAGE_ICON, GetSystemMetrics(SM_CXICON),
                                         GetSystemMetrics(SM_CYICON), LR_DEFAULTCOLOR));
    appSmallIcon = static_cast<HICON>(LoadImageW(inst, MAKEINTRESOURCEW(IDI_WORKBENCH),
                                              IMAGE_ICON, GetSystemMetrics(SM_CXSMICON),
                                              GetSystemMetrics(SM_CYSMICON), LR_DEFAULTCOLOR));
    if (!appIcon || !appSmallIcon)
      throw std::runtime_error("Could not load Native Workbench application icon.");
    wc.hIcon = appIcon;
    wc.hIconSm = appSmallIcon;
    // Both procedures paint their own backgrounds. Do not transfer ownership
    // of our shared brush to these classes when they are unregistered below.
    wc.hbrBackground = nullptr;
    wc.lpszClassName = windowClass.c_str();
    appWindowClass = RegisterClassExW(&wc);
    if (!appWindowClass)
      throw std::runtime_error("Could not register workspace window.");
    wc.lpfnWndProc = surface;
    wc.lpszClassName = L"WorkbenchNativeSurface051";
    appSurfaceClass = RegisterClassExW(&wc);
    if (!appSurfaceClass)
      throw std::runtime_error("Could not register workspace surface.");
    // A composited viewport requires a class without parent/private DC flags.
    // Register that contract explicitly instead of depending on predefined
    // STATIC class styles. The subclass owns erase/notification/scroll handling.
    wc.style = 0;
    wc.lpfnWndProc = DefWindowProcW;
    wc.lpszClassName = L"WorkbenchLibraryViewport0161";
    appLibraryViewportClass = RegisterClassExW(&wc);
    if (!appLibraryViewportClass)
      throw std::runtime_error("Could not register the tool library viewport: " +
                               narrow(bw::windows_error()));
    RECT area{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &area, 0);
    dpi = GetDpiForSystem();
    const auto initial = workspace_layout::centered_window(
        {area.left, area.top, area.right - area.left, area.bottom - area.top},
        px(workspace_layout::preferred_width), px(workspace_layout::preferred_height));
    HWND h = CreateWindowExW(
        WS_EX_CONTROLPARENT, windowClass.c_str(), L"Native Workbench",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN, initial.x, initial.y,
        initial.width, initial.height, nullptr, nullptr, inst,
        this);
    if (!h)
      return 1;
    ShowWindow(h, SW_SHOW);
    UpdateWindow(h);
    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
      if (!(setupWindow && IsDialogMessageW(setupWindow, &msg)) &&
          !(sampleEditorView.window && IsDialogMessageW(sampleEditorView.window, &msg)) &&
          !(samplesView.window && IsDialogMessageW(samplesView.window, &msg)) &&
          !(queueView.window && IsDialogMessageW(queueView.window, &msg)) &&
          !(indexesView.window && IsDialogMessageW(indexesView.window, &msg)) &&
          !(resourcesView.window && IsDialogMessageW(resourcesView.window, &msg)) &&
          !(restartView.window && IsDialogMessageW(restartView.window, &msg)) &&
          !(projectsView.window && IsDialogMessageW(projectsView.window, &msg)) &&
          !(curatedView.window && IsDialogMessageW(curatedView.window, &msg)) &&
          !(resultsView.window && IsDialogMessageW(resultsView.window, &msg)) &&
          !(refWindow && IsDialogMessageW(refWindow, &msg)) &&
          !(packWindow && IsDialogMessageW(packWindow, &msg)) &&
          !IsDialogMessageW(h, &msg)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
      }
    }
    return static_cast<int>(msg.wParam);
  }
};
} // namespace
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
               SEM_NOOPENFILEERRORBOX);
  int count = 0;
  LPWSTR *args = CommandLineToArgvW(GetCommandLineW(), &count);
  bool check = false, classic = false, valid = args && count <= 2;
  if (valid && count == 2) {
    check = std::wstring(args[1]) == L"--check";
    classic = std::wstring(args[1]) == L"--classic";
    valid = check || classic;
  }
  if (args)
    LocalFree(args);
  if (!valid) {
    MessageBoxW(nullptr, L"Supported options are --check and --classic.",
                L"Native Workbench", MB_ICONERROR);
    return 1;
  }
  try {
    if (classic) {
      const auto root = bw::executable_folder(),
                 exe = root + L"\\NativeWorkbenchClassic.exe";
      auto command = quote(exe);
      STARTUPINFOW s{};
      s.cb = sizeof(s);
      PROCESS_INFORMATION p{};
      if (!CreateProcessW(bw::native_path(exe).c_str(), command.data(), nullptr,
                          nullptr, FALSE, 0, nullptr, root.c_str(), &s, &p))
        throw std::runtime_error("Could not start the classic interface.");
      CloseHandle(p.hThread);
      CloseHandle(p.hProcess);
      return 0;
    }
    desktop::SingleInstance single(bw::executable_folder());
    if (!single.owns()) {
      for (int i = 0; i < 20; ++i) {
        if (single.show_existing())
          return 0;
        Sleep(100);
      }
      MessageBoxW(nullptr,
                  L"Native Workbench is already starting or running for this "
                  L"installation. Check the taskbar and try again shortly.",
                  L"Native Workbench", MB_OK | MB_ICONINFORMATION);
      return 0;
    }
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED |
                                              COINIT_DISABLE_OLE1DDE);
    if (FAILED(com))
      throw std::runtime_error(
          "Windows could not initialize native file dialogs.");
    Gdiplus::GdiplusStartupInput input;
    ULONG_PTR token = 0;
    if (Gdiplus::GdiplusStartup(&token, &input, nullptr) != Gdiplus::Ok) {
      CoUninitialize();
      throw std::runtime_error("Windows could not initialize drawing.");
    }
    INITCOMMONCONTROLSEX controls{sizeof(controls), ICC_LISTVIEW_CLASSES | ICC_TREEVIEW_CLASSES |
                                                        ICC_STANDARD_CLASSES |
                                                        ICC_TAB_CLASSES |
                                                        ICC_PROGRESS_CLASS};
    InitCommonControlsEx(&controls);
    int result;
    {
      Workspace app;
      result = app.run_app(instance, check, single.window_class());
    }
    Gdiplus::GdiplusShutdown(token);
    CoUninitialize();
    return result;
  } catch (const std::exception &e) {
    MessageBoxW(nullptr, wide(e.what()).c_str(), L"Native Workbench",
                MB_OK | MB_ICONERROR);
    return 1;
  }
}
