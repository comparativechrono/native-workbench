// Local machine bridge for the graph workbench. The bridge deliberately exposes
// only manifest workflows and native pickers, never an arbitrary command runner.
// stdout is UTF-8 JSON Lines; it contains no console banners or locale encoding.
#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace bridgejson {
struct Value {
    bool is_object = false;
    std::string text;
    std::map<std::string, Value> members;
};
class Parser {
    const std::string& source;
    size_t position = 0;
    [[noreturn]] void fail() const { throw std::runtime_error("Invalid bridge request JSON"); }
    void space() {
        while (position < source.size() && (source[position] == ' ' || source[position] == '\t' ||
               source[position] == '\r' || source[position] == '\n')) ++position;
    }
    unsigned hex4() {
        unsigned value = 0;
        for (unsigned i = 0; i < 4; ++i) {
            if (position == source.size()) fail();
            const char c = source[position++];
            unsigned digit;
            if (c >= '0' && c <= '9') digit = static_cast<unsigned>(c - '0');
            else if (c >= 'a' && c <= 'f') digit = static_cast<unsigned>(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') digit = static_cast<unsigned>(c - 'A' + 10);
            else fail();
            value = value * 16 + digit;
        }
        return value;
    }
    static void unicode(std::string& result, unsigned code) {
        if (code < 0x80) result += static_cast<char>(code);
        else if (code < 0x800) {
            result += static_cast<char>(0xc0 | (code >> 6));
            result += static_cast<char>(0x80 | (code & 63));
        } else if (code < 0x10000) {
            result += static_cast<char>(0xe0 | (code >> 12));
            result += static_cast<char>(0x80 | ((code >> 6) & 63));
            result += static_cast<char>(0x80 | (code & 63));
        } else {
            result += static_cast<char>(0xf0 | (code >> 18));
            result += static_cast<char>(0x80 | ((code >> 12) & 63));
            result += static_cast<char>(0x80 | ((code >> 6) & 63));
            result += static_cast<char>(0x80 | (code & 63));
        }
    }
    std::string string() {
        if (position == source.size() || source[position++] != '"') fail();
        std::string result;
        while (position < source.size()) {
            const unsigned char c = static_cast<unsigned char>(source[position++]);
            if (c == '"') return result;
            if (c < 32) fail();
            if (c != '\\') result += static_cast<char>(c);
            else {
                if (position == source.size()) fail();
                switch (source[position++]) {
                case '"': result += '"'; break;
                case '\\': result += '\\'; break;
                case '/': result += '/'; break;
                case 'b': result += '\b'; break;
                case 'f': result += '\f'; break;
                case 'n': result += '\n'; break;
                case 'r': result += '\r'; break;
                case 't': result += '\t'; break;
                case 'u': {
                    unsigned code = hex4();
                    if (code >= 0xd800 && code <= 0xdbff) {
                        if (source.size() - position < 2 || source[position++] != '\\' || source[position++] != 'u') fail();
                        const unsigned low = hex4();
                        if (low < 0xdc00 || low > 0xdfff) fail();
                        code = 0x10000 + ((code - 0xd800) << 10) + low - 0xdc00;
                    } else if (code >= 0xdc00 && code <= 0xdfff) fail();
                    if (code == 0) fail(); // NUL is never valid in a path or argv.
                    unicode(result, code);
                    break;
                }
                default: fail();
                }
            }
            if (result.size() > 8 * 1024 * 1024) fail();
        }
        fail();
    }
    Value value(unsigned depth) {
        space();
        if (position == source.size()) fail();
        Value result;
        if (source[position] == '"') { result.text = string(); return result; }
        if (source[position++] != '{' || depth > 1) fail();
        result.is_object = true;
        space();
        if (position < source.size() && source[position] == '}') { ++position; return result; }
        for (;;) {
            space();
            const auto key = string();
            if (key.empty() || key.size() > 256) fail();
            space();
            if (position == source.size() || source[position++] != ':') fail();
            if (!result.members.emplace(key, value(depth + 1)).second || result.members.size() > 512) fail();
            space();
            if (position == source.size()) fail();
            const char next = source[position++];
            if (next == '}') return result;
            if (next != ',') fail();
        }
    }
public:
    explicit Parser(const std::string& bytes) : source(bytes) {}
    Value parse() {
        if (source.size() > 16 * 1024 * 1024) fail();
        Value result = value(0);
        space();
        if (!result.is_object || position != source.size()) fail();
        return result;
    }
};
} // namespace bridgejson

#ifdef BW_BRIDGE_JSON_SELF_TEST
#include <iostream>
int main() {
    using bridgejson::Parser;
    const auto valid = Parser("{\"values\":{\"read\":\"C:\\\\a b\\u00e9\\ud83d\\ude00\\nother\"},\"empty\":\"\"}").parse();
    if (valid.members.at("values").members.at("read").text != "C:\\a b\xc3\xa9\xf0\x9f\x98\x80\nother") return 1;
    const std::vector<std::string> bad = {
        "", "[]", "null", "\"x\"", "{} {}", "{\"x\":true}", "{\"x\":1}",
        "{\"x\":\"a\",\"x\":\"b\"}", "{\"values\":{\"nested\":{}}}",
        "{\"x\":\"\\u0000\"}", "{\"x\":\"\\ud800\"}", "{\"x\":\"\\udfff\"}",
        "{\"x\":\"\\ud800\\u0001\"}", "{\"x\":\"\\z\"}", "{\"x\":\"line\nbreak\"}",
        "{\"x\":\"\\uqqqq\"}", "{\"x\":\"a\",}", "{\"x\" \"a\"}", "{\"\":\"a\"}"
    };
    for (const auto& input : bad) {
        bool rejected = false;
        try { (void)Parser(input).parse(); } catch (const std::exception&) { rejected = true; }
        if (!rejected) { std::cerr << "Accepted malformed request: " << input << '\n'; return 1; }
    }
    std::cout << "Bridge request parser: valid Unicode and 19 malformed requests passed\n";
}
#else
#include "workbench.h"
#include <shobjidl.h>
#include <chrono>
#include <mutex>
#include <thread>

namespace {
std::mutex stdout_mutex;
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
void emit(const std::string& json) {
    const std::string line = json + "\n";
    std::lock_guard<std::mutex> lock(stdout_mutex);
    const HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    size_t position = 0;
    while (position < line.size()) {
        DWORD written = 0;
        if (!WriteFile(out, line.data() + position, static_cast<DWORD>(line.size() - position), &written, nullptr) || !written)
            throw std::runtime_error("Cannot write bridge response");
        position += written;
    }
}
void event(const char* kind, const std::wstring& message) {
    emit(std::string("{\"type\":\"") + kind + "\",\"message\":" + bw::json_string(message) + "}");
}
std::string paths_json(const std::vector<std::wstring>& paths) {
    std::string out = "[";
    for (size_t i = 0; i < paths.size(); ++i) { if (i) out += ','; out += bw::json_string(paths[i]); }
    return out + ']';
}
int result(const bw::Result& value, const std::string& extra = "") {
    emit(std::string("{\"type\":\"result\",\"success\":") + (value.success ? "true" : "false") +
        ",\"cancelled\":" + (value.cancelled ? "true" : "false") +
        ",\"folder\":" + bw::json_string(value.folder) + ",\"message\":" + bw::json_string(value.message) +
        ",\"outputs\":" + paths_json(value.outputs) +
        (value.performance_json.empty() ? "" : ",\"performance\":" + value.performance_json) + extra + "}");
    return value.cancelled ? 2 : value.success ? 0 : 1;
}
std::wstring field(const bridgejson::Value& object, const char* key, bool optional = false) {
    const auto found = object.members.find(key);
    if (found == object.members.end() && optional) return {};
    require(found != object.members.end() && !found->second.is_object, "Missing or non-string bridge request field");
    require(optional || !found->second.text.empty(), "Empty required bridge request field");
    return bw::utf16(found->second.text);
}
class Cancellation {
    bw::Cancel& cancel;
    std::atomic_bool done{false};
    std::thread watcher;
public:
    Cancellation(bw::Cancel& state, const std::wstring& file) : cancel(state) {
        if (file.empty()) return;
        const auto native = bw::native_path(file);
        watcher = std::thread([this, native]() {
            while (!done.load()) {
                const DWORD attrs = GetFileAttributesW(native.c_str());
                if (attrs != INVALID_FILE_ATTRIBUTES) { cancel.store(true); return; }
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
        });
    }
    ~Cancellation() { done.store(true); if (watcher.joinable()) watcher.join(); }
    Cancellation(const Cancellation&) = delete;
    Cancellation& operator=(const Cancellation&) = delete;
};
using Options = std::map<std::wstring, std::wstring>;
Options options(int argc, wchar_t** argv, const std::set<std::wstring>& allowed, bool multiple = false) {
    Options result;
    for (int i = 2; i < argc; ++i) {
        const std::wstring key = argv[i];
        require(allowed.count(key) != 0, "Unknown bridge command option");
        require(result.count(key) == 0, "Duplicate bridge command option");
        if (multiple && key == L"--multiple") { result[key] = L"true"; continue; }
        require(i + 1 < argc, "Missing bridge option value");
        result[key] = argv[++i];
        require(!result[key].empty(), "Empty bridge option value");
    }
    return result;
}
std::wstring option(const Options& opts, const wchar_t* key, bool optional = false) {
    const auto found = opts.find(key);
    if (found == opts.end() && optional) return {};
    require(found != opts.end(), "Missing required bridge command option");
    return found->second;
}
template<class T> struct Com {
    T* ptr = nullptr;
    ~Com() { if (ptr) ptr->Release(); }
    T** address() { return &ptr; }
    T* operator->() const { return ptr; }
};
void check(HRESULT code, const char* operation) {
    if (FAILED(code)) throw std::runtime_error(std::string(operation) + ": " + bw::utf8(bw::windows_error(static_cast<DWORD>(code))));
}
int choose(bool folder, const Options& opts) {
    const HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    check(initialized, "Initialize native file picker");
    struct Apartment { ~Apartment() { CoUninitialize(); } } apartment;
    Com<IFileOpenDialog> dialog;
    check(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(dialog.address())), "Create native file picker");
    FILEOPENDIALOGOPTIONS flags = 0;
    check(dialog->GetOptions(&flags), "Read picker options");
    flags |= FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR | FOS_DONTADDTORECENT;
    if (folder) flags |= FOS_PICKFOLDERS;
    else flags |= FOS_FILEMUSTEXIST;
    if (opts.count(L"--multiple")) flags |= FOS_ALLOWMULTISELECT;
    check(dialog->SetOptions(flags), "Set picker options");
    check(dialog->SetTitle(folder ? L"Choose a Workbench folder" : L"Choose Workbench input files"), "Set picker title");
    std::vector<std::wstring> filter_parts;
    std::vector<COMDLG_FILTERSPEC> filters;
    const auto filter = option(opts, L"--filter", true);
    if (!folder && !filter.empty()) {
        size_t start = 0;
        for (;;) {
            const auto end = filter.find(L'|', start);
            filter_parts.push_back(filter.substr(start, end == filter.npos ? filter.npos : end - start));
            require(!filter_parts.back().empty(), "Empty native picker filter field");
            if (end == filter.npos) break;
            start = end + 1;
        }
        require(filter_parts.size() % 2 == 0 && filter_parts.size() <= 64, "Invalid native picker filter");
        for (size_t i = 0; i < filter_parts.size(); i += 2)
            filters.push_back({filter_parts[i].c_str(), filter_parts[i + 1].c_str()});
        check(dialog->SetFileTypes(static_cast<UINT>(filters.size()), filters.data()), "Set picker file types");
    }
    const HRESULT shown = dialog->Show(nullptr);
    bw::Result selected;
    if (shown == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
        selected.cancelled = true; selected.message = L"Selection cancelled.";
        return result(selected, ",\"paths\":[]");
    }
    check(shown, "Show native file picker");
    Com<IShellItemArray> items;
    check(dialog->GetResults(items.address()), "Read native file selection");
    DWORD count = 0;
    check(items->GetCount(&count), "Read native file count");
    require(count <= 256, "Choose at most 256 files at a time");
    std::vector<std::wstring> paths;
    for (DWORD i = 0; i < count; ++i) {
        Com<IShellItem> item;
        check(items->GetItemAt(i, item.address()), "Read selected native file");
        PWSTR path = nullptr;
        check(item->GetDisplayName(SIGDN_FILESYSPATH, &path), "Read selected filesystem path");
        struct Name { PWSTR value; ~Name() { CoTaskMemFree(value); } } name{path};
        paths.emplace_back(path);
    }
    selected.success = true;
    return result(selected, ",\"paths\":" + paths_json(paths));
}
bool direct_pack_child(const std::wstring& app_root, const std::wstring& folder) {
    auto root = bw::native_path(bw::join(app_root, L"packs"));
    auto child = bw::native_path(folder);
    while (!root.empty() && root.back() == L'\\') root.pop_back();
    while (!child.empty() && child.back() == L'\\') child.pop_back();
    const auto slash = child.find_last_of(L'\\');
    return slash == root.size() && _wcsnicmp(child.c_str(), root.c_str(), root.size()) == 0;
}
int run(const std::wstring& path, bw::Cancel& cancel) {
    const auto bytes = bw::read_file(path, 16 * 1024 * 1024);
    (void)bw::utf16(bytes); // Validate unescaped UTF-8 before the structural parser.
    const auto request = bridgejson::Parser(bytes).parse();
    const std::set<std::string> allowed = {"app_root", "pack_folder", "pack_sha256", "workflow_id", "output_folder", "values", "cancel_file"};
    for (const auto& entry : request.members) require(allowed.count(entry.first) != 0, "Unknown bridge request field");
    const auto app_root = field(request, "app_root");
    const auto pack_folder = field(request, "pack_folder");
    const auto hash = field(request, "pack_sha256");
    require(hash.size() == 64 && std::all_of(hash.begin(), hash.end(), [](wchar_t c) { return (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f'); }),
        "Expected a lowercase SHA-256 pack manifest pin");
    require(direct_pack_child(app_root, pack_folder), "Workflow pack must be installed directly inside this application's packs folder");
    bw::WorkflowRequest work;
    work.workflow_id = field(request, "workflow_id");
    work.output_folder = field(request, "output_folder");
    const auto values = request.members.find("values");
    require(values != request.members.end() && values->second.is_object, "Workflow values must be a JSON object");
    for (const auto& entry : values->second.members) {
        require(!entry.second.is_object, "Workflow values must be strings");
        work.values.emplace(bw::utf16(entry.first), bw::utf16(entry.second.text));
    }
    Cancellation monitor(cancel, field(request, "cancel_file", true));
    work.pack = bw::load_pack(pack_folder);
    require(work.pack.manifest_sha256 == hash, "Pack manifest changed after the plan was created; refresh the tool catalogue and review the plan again");
    return result(bw::run_workflow(work, cancel,
        [](const std::wstring& text) { event("log", text); },
        [](const std::wstring& text) { event("phase", text); }));
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    // Error dialogs must not strand an unattended backend worker.
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    bw::Cancel cancel{false};
    try {
        require(argc >= 2, "Choose a bridge command: run, choose-file, choose-folder, check or import");
        const std::wstring command = argv[1];
        if (command == L"run") return run(option(options(argc, argv, {L"--request"}), L"--request"), cancel);
        if (command == L"choose-file") return choose(false, options(argc, argv, {L"--multiple", L"--filter"}, true));
        if (command == L"choose-folder") return choose(true, options(argc, argv, {}));
        if (command == L"check" || command == L"import") {
            const auto opts = options(argc, argv, command == L"check" ?
                std::set<std::wstring>{L"--app-root", L"--output-folder", L"--cancel-file"} :
                std::set<std::wstring>{L"--app-root", L"--source", L"--cancel-file"});
            const auto app_root = option(opts, L"--app-root");
            Cancellation monitor(cancel, option(opts, L"--cancel-file", true));
            const bw::Log log = [](const std::wstring& text) { event("log", text); };
            if (command == L"check") return result(bw::validate_modular_installation(app_root,
                option(opts, L"--output-folder"), cancel, log, [](const std::wstring& text) { event("phase", text); }));
            const auto pack = bw::import_pack(app_root, option(opts, L"--source"), cancel, log);
            bw::Result imported; imported.success = true; imported.folder = pack.root; imported.message = L"Tool pack imported.";
            return result(imported, ",\"pack_id\":" + bw::json_string(pack.id) + ",\"pack_version\":" + bw::json_string(pack.version));
        }
        throw std::runtime_error("Unknown bridge command");
    } catch (const std::exception& error) {
        bw::Result failed;
        failed.cancelled = cancel.load();
        try { failed.message = bw::utf16(error.what()); } catch (...) { failed.message = L"Native bridge operation failed."; }
        try { return result(failed); } catch (...) { return 1; }
    }
}
#endif
