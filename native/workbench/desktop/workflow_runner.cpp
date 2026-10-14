#include "workbench.h"
#include "process_performance.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <exception>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace bw {
namespace {
class Handle {
    HANDLE value_ = INVALID_HANDLE_VALUE;
public:
    Handle() = default;
    explicit Handle(HANDLE value) : value_(value) {}
    ~Handle() { if (valid()) CloseHandle(value_); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value_(other.value_) { other.value_ = INVALID_HANDLE_VALUE; }
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) { if (valid()) CloseHandle(value_); value_ = other.value_; other.value_ = INVALID_HANDLE_VALUE; }
        return *this;
    }
    bool valid() const { return value_ != nullptr && value_ != INVALID_HANDLE_VALUE; }
    HANDLE get() const { return value_; }
};

[[noreturn]] void fail(const std::wstring& message) { throw std::runtime_error(utf8(message)); }
[[noreturn]] void winfail(const std::wstring& message) { fail(message + L": " + windows_error()); }
void require(bool okay, const std::wstring& message) { if (!okay) fail(message); }
void emit(const Log& log, const std::wstring& message) { if (log) log(message); }
void phase(const Phase& log, const std::wstring& message) { if (log) log(message); }

std::wstring lower(std::wstring text) {
    for (auto& ch : text) if (ch >= L'A' && ch <= L'Z') ch += L'a' - L'A';
    return text;
}
bool clean_text(const std::wstring& text) {
    return std::none_of(text.begin(), text.end(), [](wchar_t ch) { return ch < 32 || ch == 127; });
}
bool safe_component(const std::wstring& value) {
    if (value.empty() || value.size() > 255 || value == L"." || value == L".." ||
        value.back() == L'.' || value.back() == L' ' || !clean_text(value) ||
        value.find_first_of(L"\\/:<>\"|?*") != std::wstring::npos) return false;
    const auto stem = lower(value.substr(0, value.find(L'.')));
    if (stem == L"con" || stem == L"prn" || stem == L"aux" || stem == L"nul" ||
        stem == L"conin$" || stem == L"conout$") return false;
    if (stem.size() == 4 && (stem.substr(0, 3) == L"com" || stem.substr(0, 3) == L"lpt") &&
        stem[3] >= L'1' && stem[3] <= L'9') return false;
    return true;
}
std::wstring relative_output(std::wstring path) {
    std::replace(path.begin(), path.end(), L'/', L'\\');
    require(!path.empty() && path.size() <= 512, L"A declared output path is empty or too long.");
    size_t begin = 0;
    while (begin < path.size()) {
        size_t end = path.find(L'\\', begin);
        if (end == std::wstring::npos) end = path.size();
        require(safe_component(path.substr(begin, end - begin)), L"Unsafe declared output path: " + path);
        begin = end + 1;
    }
    require(path.back() != L'\\', L"An output must name a file: " + path);
    const auto first = lower(path.substr(0, path.find(L'\\')));
    require(first != L"logs" && first != L"run.json" && first != L"run.json.pending" &&
        first != L"workbench.log" && first != L"workbench.log.pending", L"Output path is reserved: " + path);
    return path;
}
std::wstring absolute_path(const std::wstring& path) {
    // native_path performs namespace and length validation. Convert its result
    // back to an ordinary absolute path for tools and human-readable reports.
    require(clean_text(path), L"A filesystem path contains a control character.");
    auto absolute = native_path(path);
    if (absolute.compare(0, 8, L"\\\\?\\UNC\\") == 0) absolute = L"\\\\" + absolute.substr(8);
    else absolute.erase(0, 4);
    const size_t colon = absolute.find(L':', absolute.size() >= 2 && absolute[1] == L':' ? 2 : 0);
    require(colon == std::wstring::npos, L"Alternate streams are not supported as input or output paths.");
    // Tools receive ordinary paths, so exclude names whose ordinary Windows
    // interpretation differs from the explicit namespace used for hashing.
    size_t begin = absolute.compare(0, 2, L"\\\\") == 0 ? 2 : 3;
    while (begin < absolute.size()) {
        size_t end = absolute.find(L'\\', begin);
        if (end == std::wstring::npos) end = absolute.size();
        require(safe_component(absolute.substr(begin, end - begin)),
            L"Unsupported Windows path component: " + absolute);
        begin = end + 1;
    }
    return absolute;
}
std::wstring now_utc() {
    SYSTEMTIME utc{}; GetSystemTime(&utc);
    wchar_t text[64]{};
    swprintf(text, 64, L"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ", utc.wYear, utc.wMonth, utc.wDay,
        utc.wHour, utc.wMinute, utc.wSecond, utc.wMilliseconds);
    return text;
}
uint64_t size_of(HANDLE file, const std::wstring& path) {
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < 0) winfail(L"Cannot measure " + path);
    return static_cast<uint64_t>(size.QuadPart);
}
Handle ordinary_file(const std::wstring& path) {
    // Deny writes and deletion for the lifetime of this handle. This also
    // refuses a pre-existing incompatible writable handle.
    Handle handle(CreateFileW(native_path(path).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
        OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr));
    if (!handle.valid()) winfail(L"Cannot protect input file " + path);
    BY_HANDLE_FILE_INFORMATION information{};
    if (!GetFileInformationByHandle(handle.get(), &information)) winfail(L"Cannot inspect file " + path);
    require(GetFileType(handle.get()) == FILE_TYPE_DISK &&
        !(information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)),
        L"Expected an ordinary file without a symbolic link or reparse point: " + path);
    return handle;
}
struct DirectoryGuards {
    std::map<std::wstring, Handle> handles;
    void lock(const std::wstring& path) {
        if (handles.count(lower(path))) return;
        Handle handle(CreateFileW(native_path(path).c_str(), FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (!handle.valid()) winfail(L"Cannot protect folder " + path);
        BY_HANDLE_FILE_INFORMATION information{};
        if (!GetFileInformationByHandle(handle.get(), &information)) winfail(L"Cannot inspect folder " + path);
        require((information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
            !(information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT),
            L"Folders used by a workflow must not be symbolic links or junctions: " + path);
        handles.emplace(lower(path), std::move(handle));
    }
    void ancestors(const std::wstring& path, bool include_self) {
        size_t start = 0;
        if (path.size() >= 3 && path[1] == L':' && path[2] == L'\\') { lock(path.substr(0, 3)); start = 3; }
        else if (path.compare(0, 2, L"\\\\") == 0) {
            const size_t server = path.find(L'\\', 2);
            require(server != std::wstring::npos, L"Network path is missing its share name.");
            const size_t share = path.find(L'\\', server + 1);
            if (share == std::wstring::npos) { if (include_self) lock(path); return; }
            lock(path.substr(0, share)); start = share + 1;
        } else fail(L"Expected an absolute filesystem path.");
        for (size_t i = start; i < path.size(); ++i)
            if (path[i] == L'\\') lock(path.substr(0, i));
        if (include_self) lock(path);
    }
    void create_parents(const std::wstring& run, const std::wstring& relative) {
        for (size_t i = 0; i < relative.size(); ++i) if (relative[i] == L'\\') {
            const auto path = join(run, relative.substr(0, i));
            if (!CreateDirectoryW(native_path(path).c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS)
                winfail(L"Cannot create output folder " + path);
            lock(path);
        }
    }
};

struct FileEvidence {
    std::wstring input_id, path, before_sha256, after_sha256, after_status = L"not_checked";
    uint64_t bytes = 0;
    DWORD volume_serial = 0, index_high = 0, index_low = 0;
    Handle handle;
};
struct Artifact {
    Output definition;
    std::wstring path, sha256, completed_by;
    uint64_t bytes = 0;
    bool checked = false;
    // Once produced, an artifact is immutable for every later step and final
    // report. Each output has one producer; later steps may only read it.
    Handle handle;
};
struct Stage {
    Step definition;
    Tool tool, sink_tool;
    std::vector<std::wstring> argv, sink_argv;
    std::wstring status = L"pending", source, destination, stdout_path, stderr_path, sink_stderr_path, started, finished;
    DWORD exit_code = 0, producer_exit_code = 0, sink_exit_code = 0;
    ULONGLONG elapsed_ms = 0;
    bool has_exit_code = false, has_pipeline_exit_codes = false;
    ProcessPerformance performance;
};

std::string stage_performance_json(const Stage& stage) {
    if (stage.definition.kind == L"copy") return "null";
    return process_performance_json(stage.performance);
}

std::string workflow_performance_json(const std::vector<Stage>& stages) {
    std::ostringstream out;
    out << "{\"schema\":1,\"source\":\"windows-job-object\",\"scope\":\"workflow-command-stages\",\"stages\":[";
    for (size_t i = 0; i < stages.size(); ++i) {
        if (i) out << ',';
        const auto& stage = stages[i];
        out << "{\"id\":" << json_string(stage.definition.id) << ",\"kind\":" << json_string(stage.definition.kind)
            << ",\"status\":" << json_string(stage.status) << ",\"resources\":" << stage_performance_json(stage) << '}';
    }
    out << "]}";
    return out.str();
}

std::vector<std::wstring> file_list(const std::wstring& text) {
    std::vector<std::wstring> paths;
    if (text.empty()) return paths;
    size_t begin = 0;
    while (begin < text.size()) {
        size_t end = text.find(L'\n', begin);
        if (end == std::wstring::npos) end = text.size();
        std::wstring value = text.substr(begin, end - begin);
        if (!value.empty() && value.back() == L'\r') value.pop_back();
        require(!value.empty(), L"A multiple-file input contains an empty line.");
        paths.push_back(absolute_path(value));
        require(paths.size() <= 256, L"A multiple-file input is limited to 256 files.");
        begin = end + 1;
    }
    return paths;
}
std::wstring joined_files(const std::vector<std::wstring>& paths) {
    std::wstring result;
    for (const auto& path : paths) { if (!result.empty()) result += L'\n'; result += path; }
    return result;
}
void copy_file(const std::wstring& source, const std::wstring& destination, Cancel& cancel) {
    auto input = ordinary_file(source);
    Handle output(CreateFileW(native_path(destination).c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
        CREATE_NEW, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (!output.valid()) winfail(L"Cannot create copied output " + destination);
    const uint64_t expected = size_of(input.get(), source);
    std::array<unsigned char, 1024 * 64> buffer{};
    uint64_t total = 0;
    for (;;) {
        check_cancel(cancel);
        DWORD got = 0;
        if (!ReadFile(input.get(), buffer.data(), static_cast<DWORD>(buffer.size()), &got, nullptr))
            winfail(L"Cannot read copy source " + source);
        if (!got) break;
        total += got;
        DWORD done = 0;
        while (done < got) {
            check_cancel(cancel); DWORD written = 0;
            if (!WriteFile(output.get(), buffer.data() + done, got - done, &written, nullptr) || !written)
                winfail(L"Cannot write copied output " + destination);
            done += written;
        }
    }
    require(total == expected, L"Source size changed while copying " + source);
    if (!FlushFileBuffers(output.get())) winfail(L"Cannot flush copied output " + destination);
}

std::string report_json(const WorkflowRequest& request, const Workflow* workflow,
    const std::map<std::wstring, std::wstring>& values, const std::vector<FileEvidence>& files,
    const std::map<std::wstring, Artifact>& artifacts, const std::vector<Stage>& stages,
    const Result& result, const std::wstring& status, const std::wstring& started, ULONGLONG elapsed,
    bool pack_verified) {
    std::ostringstream out;
    out << "{\n  \"schema\":2,\n  \"application_version\":" << json_string(APP_VERSION)
        << ",\n  \"started_utc\":" << json_string(started) << ",\n  \"updated_utc\":" << json_string(now_utc())
        << ",\n  \"elapsed_ms\":" << elapsed << ",\n  \"status\":" << json_string(status)
        << ",\n  \"message\":" << json_string(result.message) << ",\n  \"folder\":" << json_string(result.folder)
        << ",\n  \"pack\":{\"id\":" << json_string(request.pack.id) << ",\"version\":" << json_string(request.pack.version)
        << ",\"name\":" << json_string(request.pack.name) << ",\"manifest_sha256\":" << json_string(request.pack.manifest_sha256)
        << ",\"integrity_verified\":" << (pack_verified ? "true" : "false")
        << "},\n  \"workflow\":{\"id\":" << json_string(request.workflow_id)
        << ",\"name\":" << json_string(workflow ? workflow->name : L"") << "},\n  \"parameters\":{";
    bool first = true;
    for (const auto& value : values) {
        if (!first) out << ','; first = false;
        out << json_string(value.first) << ':' << json_string(value.second);
    }
    out << "},\n  \"input_files\":[";
    for (size_t i = 0; i < files.size(); ++i) {
        if (i) out << ',';
        const auto& file = files[i];
        out << "\n    {\"input_id\":" << json_string(file.input_id) << ",\"path\":" << json_string(file.path)
            << ",\"bytes\":" << file.bytes << ",\"sha256_before\":"
            << (file.before_sha256.empty() ? "null" : json_string(file.before_sha256))
            << ",\"sha256_after\":" << (file.after_sha256.empty() ? "null" : json_string(file.after_sha256))
            << ",\"after_check\":" << json_string(file.after_status)
            << ",\"file_identity\":{\"volume_serial\":" << file.volume_serial
            << ",\"index_high\":" << file.index_high << ",\"index_low\":" << file.index_low << "}}";
    }
    out << "\n  ],\n  \"input_protection\":\"Ordinary file inputs are held open denying writes and deletion; "
        "directory contents are not individually locked or hashed.\",\n  \"tools\":[";
    for (size_t i = 0; i < request.pack.tools.size(); ++i) {
        if (i) out << ',';
        const auto& tool = request.pack.tools[i];
        out << "{\"id\":" << json_string(tool.id) << ",\"version\":" << json_string(tool.version)
            << ",\"path\":" << json_string(tool.path) << ",\"sha256\":" << json_string(tool.sha256) << '}';
    }
    out << "],\n  \"assets\":[";
    for (size_t i = 0; i < request.pack.assets.size(); ++i) {
        if (i) out << ',';
        const auto& asset = request.pack.assets[i];
        out << "{\"id\":" << json_string(asset.id) << ",\"path\":" << json_string(asset.path)
            << ",\"sha256\":" << json_string(asset.sha256) << '}';
    }
    out << "],\n  \"pack_file_protection\":\"Manifest, declared tools and assets are held open denying writes "
        "and deletion during execution. Ancestor directories reject reparse points.\",\n  \"steps\":[";
    for (size_t i = 0; i < stages.size(); ++i) {
        if (i) out << ',';
        const auto& stage = stages[i];
        out << "\n    {\"id\":" << json_string(stage.definition.id) << ",\"label\":" << json_string(stage.definition.label)
            << ",\"kind\":" << json_string(stage.definition.kind) << ",\"status\":" << json_string(stage.status)
            << ",\"started_utc\":" << (stage.started.empty() ? "null" : json_string(stage.started))
            << ",\"finished_utc\":" << (stage.finished.empty() ? "null" : json_string(stage.finished))
            << ",\"elapsed_ms\":" << stage.elapsed_ms << ",\"exit_code\":"
            << (stage.has_exit_code ? std::to_string(stage.exit_code) : "null")
            << ",\"performance\":" << stage_performance_json(stage)
            << ",\"executable\":" << json_string(stage.tool.path) << ",\"tool_id\":" << json_string(stage.tool.id)
            << ",\"arguments\":[";
        for (size_t j = 0; j < stage.argv.size(); ++j) { if (j) out << ','; out << json_string(stage.argv[j]); }
        out << "],\"sink_tool_id\":" << json_string(stage.sink_tool.id)
            << ",\"sink_executable\":" << json_string(stage.sink_tool.path)
            << ",\"sink_arguments\":[";
        for (size_t j = 0; j < stage.sink_argv.size(); ++j) { if (j) out << ','; out << json_string(stage.sink_argv[j]); }
        out << "],\"producer_exit_code\":" << (stage.has_pipeline_exit_codes ? std::to_string(stage.producer_exit_code) : "null")
            << ",\"sink_exit_code\":" << (stage.has_pipeline_exit_codes ? std::to_string(stage.sink_exit_code) : "null")
            << ",\"sink_stderr\":" << json_string(stage.sink_stderr_path)
            << ",\"working_directory\":" << json_string(result.folder)
            << ",\"source\":" << json_string(stage.source) << ",\"destination\":" << json_string(stage.destination)
            << ",\"stdout\":" << json_string(stage.stdout_path) << ",\"stderr\":" << json_string(stage.stderr_path) << '}';
    }
    out << "\n  ],\n  \"artifacts\":["; first = true;
    for (const auto& entry : artifacts) {
        if (!first) out << ','; first = false;
        const auto& artifact = entry.second;
        out << "\n    {\"id\":" << json_string(entry.first) << ",\"path\":" << json_string(artifact.path)
            << ",\"final\":" << (artifact.definition.final ? "true" : "false")
            << ",\"checked\":" << (artifact.checked ? "true" : "false")
            << ",\"bytes\":" << (artifact.checked ? std::to_string(artifact.bytes) : "null")
            << ",\"sha256\":" << (artifact.sha256.empty() ? "null" : json_string(artifact.sha256))
            << ",\"completed_by_step\":" << (artifact.completed_by.empty() ? "null" : json_string(artifact.completed_by))
            << ",\"workflow_complete\":" << (result.success ? "true" : "false") << '}';
    }
    out << "\n  ],\n  \"artifact_protection\":\"Completed declared artifacts are held open denying writes and deletion "
        "until final verification and report publication.\",\n  \"completed_final_outputs\":[";
    for (size_t i = 0; i < result.outputs.size(); ++i) { if (i) out << ','; out << json_string(result.outputs[i]); }
    out << "],\n  \"retention\":\"Intermediate and incomplete files are retained in this fresh run folder. "
        "Only completed_final_outputs from a successful workflow are completed results.\"\n}\n";
    return out.str();
}
} // namespace

Result run_workflow(const WorkflowRequest& request, Cancel& cancel, const Log& log, const Phase& report_phase) {
    Result result;
    const Workflow* workflow = nullptr;
    std::wstring status = L"preparing", started = now_utc();
    const ULONGLONG began = GetTickCount64();
    std::map<std::wstring, std::wstring> values, output_paths, asset_paths;
    std::vector<FileEvidence> input_files;
    std::map<std::wstring, Artifact> artifacts;
    std::vector<Stage> stages;
    std::vector<Handle> tool_guards;
    DirectoryGuards directories;
    std::string run_log;
    bool own_json = false, own_log = false, pack_verified = false;
    Stage* active = nullptr;
    ULONGLONG active_began = 0;
    Log record = [&](const std::wstring& line) { run_log += utf8(line) + "\r\n"; emit(log, line); };
    auto write_owned = [&](const std::wstring& name, const std::string& bytes, bool& owned) {
        const auto target = join(result.folder, name), pending = target + L".pending";
        write_file_new(pending, bytes);
        if (!MoveFileExW(native_path(pending).c_str(), native_path(target).c_str(),
            MOVEFILE_WRITE_THROUGH | (owned ? MOVEFILE_REPLACE_EXISTING : 0))) {
            const DWORD code = GetLastError(); DeleteFileW(native_path(pending).c_str());
            fail(L"Cannot publish report " + target + L": " + windows_error(code));
        }
        owned = true;
    };
    auto save_report = [&]() {
        std::exception_ptr failure;
        try { write_owned(L"workbench.log", run_log, own_log); } catch (...) { failure = std::current_exception(); }
        try { write_owned(L"run.json", report_json(request, workflow, values, input_files, artifacts, stages,
            result, status, started, GetTickCount64() - began, pack_verified), own_json); }
        catch (...) { if (!failure) failure = std::current_exception(); }
        if (failure) std::rethrow_exception(failure);
    };
    auto check_inputs_after = [&]() {
        for (auto& file : input_files) {
            check_cancel(cancel);
            if (file.before_sha256.empty() || file.after_status == L"unchanged") continue;
            file.after_sha256 = sha256_file(file.path, cancel);
            file.after_status = file.after_sha256 == file.before_sha256 ? L"unchanged" : L"changed";
            require(file.after_status == L"unchanged", L"Input content changed during the workflow: " + file.path);
        }
    };
    try {
        check_cancel(cancel);
        for (const auto& candidate : request.pack.workflows) if (candidate.id == request.workflow_id) {
            require(!workflow, L"The workflow identifier is duplicated."); workflow = &candidate;
        }
        require(workflow != nullptr, L"Choose a workflow supplied by the selected tool pack.");
        require(!workflow->steps.empty(), L"The selected workflow has no steps.");
        std::map<std::wstring, const Input*> definitions;
        for (const auto& input : workflow->inputs)
            require(definitions.emplace(input.id, &input).second, L"Duplicate input identifier: " + input.id);
        for (const auto& supplied : request.values)
            require(definitions.count(supplied.first) != 0, L"Unknown workflow input: " + supplied.first);
        const auto parent = absolute_path(request.output_folder);
        directories.ancestors(parent, true);
        result.folder = unique_directory(parent, L"analysis"); directories.lock(result.folder);
        const auto logs = join(result.folder, L"logs");
        if (!CreateDirectoryW(native_path(logs).c_str(), nullptr)) winfail(L"Cannot create logs folder");
        directories.lock(logs);
        save_report();
        phase(report_phase, L"Validating inputs and protecting source files...");
        for (const auto& input : workflow->inputs) {
            check_cancel(cancel);
            const auto supplied = request.values.find(input.id);
            std::wstring value = supplied == request.values.end() ? input.default_value : supplied->second;
            require(!input.required || !value.empty(), L"Select or enter " + input.label + L".");
            require(value.size() <= (input.type == L"files" ? 256u * 32767u : input.type == L"file" || input.type == L"directory" ? 32767u : input.constraint == L"dna" ? 4096u : 512u),
                L"Input is too long: " + input.label);
            if (input.constraint == L"dna") require(text_constraint_matches(input.constraint, value),
                input.label + L" must be a DNA sequence of 1 to 4096 IUPAC letters (ACGTRYSWKMBDHVN). File names, paths and adapter expressions are not accepted here.");
            if (value.empty()) { values[input.id] = value; continue; }
            std::vector<std::wstring> paths;
            if (input.type == L"file") { value = absolute_path(value); paths.push_back(value); }
            else if (input.type == L"files") { paths = file_list(value); value = joined_files(paths); }
            else if (input.type == L"directory") {
                value = absolute_path(value); directories.ancestors(value, true);
            } else {
                require(clean_text(value), L"Input contains a control character: " + input.label);
                if (input.type == L"integer") {
                    size_t offset = value[0] == L'-' ? 1 : 0;
                    require(offset < value.size() && std::all_of(value.begin() + offset, value.end(),
                        [](wchar_t c) { return c >= L'0' && c <= L'9'; }), L"Enter a whole number for " + input.label + L".");
                    long long number = 0;
                    try { number = std::stoll(value); } catch (...) { fail(L"Number is out of range: " + input.label); }
                    require(number >= input.minimum && number <= input.maximum, input.label + L" must be between " +
                        std::to_wstring(input.minimum) + L" and " + std::to_wstring(input.maximum) + L".");
                    value = std::to_wstring(number);
                } else if (input.type == L"choice") {
                    require(std::any_of(input.choices.begin(), input.choices.end(), [&](const Choice& choice) {
                        return choice.value == value; }), L"Choose a supported value for " + input.label + L".");
                } else if (input.type == L"boolean")
                    require(value == L"true" || value == L"false", L"A boolean input must be true or false: " + input.label);
                else {
                    require(input.type == L"text", L"Unsupported input type: " + input.type);
                    require(input.constraint.empty() || input.constraint == L"identifier" || input.constraint == L"dna",
                        L"Unsupported text constraint: " + input.constraint);
                    if (input.constraint == L"identifier")
                        require(text_constraint_matches(input.constraint, value),
                            input.label + L" must use 1 to 64 letters, digits, underscores, periods or hyphens.");
                }
            }
            values[input.id] = value;
            for (const auto& path : paths) {
                directories.ancestors(path, false);
                FileEvidence file; file.input_id = input.id; file.path = path;
                file.handle = ordinary_file(path); file.bytes = size_of(file.handle.get(), path);
                BY_HANDLE_FILE_INFORMATION identity{};
                if (!GetFileInformationByHandle(file.handle.get(), &identity)) winfail(L"Cannot identify input file " + path);
                file.volume_serial = identity.dwVolumeSerialNumber;
                file.index_high = identity.nFileIndexHigh; file.index_low = identity.nFileIndexLow;
                input_files.push_back(std::move(file));
                input_files.back().before_sha256 = sha256_file(path, cancel);
                record(L"Input checked: " + path);
            }
        }
        for (const auto& input : workflow->inputs) if (!input.different_from.empty()) {
            require(input.type == L"file" && definitions.count(input.different_from) &&
                definitions.at(input.different_from)->type == L"file", L"Invalid different-from constraint: " + input.id);
            const FileEvidence* own = nullptr;
            const FileEvidence* other = nullptr;
            for (const auto& file : input_files) {
                if (file.input_id == input.id) own = &file;
                if (file.input_id == input.different_from) other = &file;
            }
            if (own && other)
                require(own->volume_serial != other->volume_serial || own->index_high != other->index_high ||
                    own->index_low != other->index_low, input.label + L" must be a different file from " +
                    definitions.at(input.different_from)->label + L". Different names or hard links to the same file do not count.");
        }
        phase(report_phase, L"Checking tool pack integrity...");
        directories.ancestors(absolute_path(request.pack.root), true);
        tool_guards.push_back(ordinary_file(join(request.pack.root, L"pack.ini")));
        for (const auto& tool : request.pack.tools) {
            directories.ancestors(absolute_path(tool.path), false);
            tool_guards.push_back(ordinary_file(tool.path));
        }
        for (const auto& asset : request.pack.assets) {
            check_cancel(cancel);
            directories.ancestors(absolute_path(asset.path), false);
            tool_guards.push_back(ordinary_file(asset.path));
            require(asset_paths.emplace(asset.id, asset.path).second, L"Duplicate pack asset ID: " + asset.id);
        }
        verify_pack(request.pack, cancel, record);
        pack_verified = true;
        std::set<std::wstring> paths;
        for (const auto& output : workflow->outputs) {
            const auto relative = relative_output(output.path), key = lower(relative);
            for (const auto& previous : paths)
                require(previous != key && previous.compare(0, key.size() + 1, key + L"\\") != 0 &&
                    key.compare(0, previous.size() + 1, previous + L"\\") != 0, L"Declared output paths overlap.");
            paths.insert(key); directories.create_parents(result.folder, relative);
            Artifact artifact; artifact.definition = output; artifact.path = join(result.folder, relative);
            require(artifacts.emplace(output.id, std::move(artifact)).second, L"Duplicate output identifier: " + output.id);
            output_paths[output.id] = join(result.folder, relative);
        }
        std::set<std::wstring> step_ids;
        for (const auto& definition : workflow->steps) {
            require(safe_component(definition.id) && step_ids.insert(lower(definition.id)).second,
                L"A workflow step identifier is unsafe or duplicated.");
            Stage stage; stage.definition = definition;
            stage.performance.pipeline = definition.kind == L"pipe";
            if (definition.kind == L"exec" || definition.kind == L"pipe") {
                auto tool = std::find_if(request.pack.tools.begin(), request.pack.tools.end(),
                    [&](const Tool& candidate) { return candidate.id == definition.tool; });
                require(tool != request.pack.tools.end(), L"Step refers to an unknown tool: " + definition.tool);
                stage.tool = *tool;
                stage.argv = expand_arguments(definition.args, values, output_paths, result.folder, asset_paths);
                if (definition.stdout_id.empty()) stage.stdout_path = join(logs, definition.id + L".stdout.log");
                else {
                    require(output_paths.count(definition.stdout_id), L"Step stdout refers to an unknown output.");
                    stage.stdout_path = output_paths.at(definition.stdout_id);
                }
                stage.stderr_path = join(logs, definition.id + L".stderr.log");
                if (definition.kind == L"pipe") {
                    const auto sink = std::find_if(request.pack.tools.begin(), request.pack.tools.end(),
                        [&](const Tool& candidate) { return candidate.id == definition.sink_tool; });
                    require(sink != request.pack.tools.end(), L"Pipe refers to an unknown sink tool: " + definition.sink_tool);
                    stage.sink_tool = *sink;
                    stage.sink_argv = expand_arguments(definition.sink_args, values, output_paths, result.folder, asset_paths);
                    stage.sink_stderr_path = join(logs, definition.id + L".sink.stderr.log");
                }
            } else if (definition.kind == L"copy") {
                auto expanded = expand_arguments({definition.source}, values, output_paths, result.folder, asset_paths);
                require(expanded.size() == 1 && !expanded[0].empty(), L"A copy step requires exactly one source file.");
                require(output_paths.count(definition.destination), L"Copy destination is not a declared output.");
                stage.source = expanded[0]; stage.destination = output_paths.at(definition.destination);
            } else fail(L"Unsupported workflow step kind: " + definition.kind);
            stages.push_back(std::move(stage));
        }
        status = L"running"; save_report();
        for (auto& stage : stages) {
            check_cancel(cancel);
            std::vector<std::wstring> produced = stage.definition.produces;
            if (!stage.definition.stdout_id.empty()) produced.push_back(stage.definition.stdout_id);
            if (stage.definition.kind == L"copy") produced.push_back(stage.definition.destination);
            std::set<std::wstring> unique;
            for (const auto& id : produced) {
                require(artifacts.count(id) && unique.insert(id).second, L"Step has an unknown or duplicated produced output.");
                const auto& artifact = artifacts.at(id);
                require(!artifact.checked && GetFileAttributesW(native_path(artifact.path).c_str()) == INVALID_FILE_ATTRIBUTES,
                    L"A workflow step would overwrite an existing output: " + artifact.path);
            }
            active = &stage; active_began = GetTickCount64();
            stage.started = now_utc(); stage.status = L"running";
            phase(report_phase, stage.definition.label); record(L"Starting: " + stage.definition.label); save_report();
            if (stage.definition.kind == L"copy") {
                copy_file(stage.source, stage.destination, cancel);
            } else if (stage.definition.kind == L"pipe") {
                const auto process = execute_pipeline(stage.tool.path, stage.argv, stage.sink_tool.path,
                    stage.sink_argv, stage.stdout_path, stage.stderr_path, stage.sink_stderr_path,
                    cancel, record, 0, result.folder, &stage.performance);
                stage.producer_exit_code = process.producer_exit_code;
                stage.sink_exit_code = process.sink_exit_code;
                stage.has_pipeline_exit_codes = true;
                stage.exit_code = process.producer_exit_code ? process.producer_exit_code : process.sink_exit_code;
                stage.has_exit_code = true;
                if (process.cancelled) { result.cancelled = true; fail(L"Workflow cancelled."); }
                require(process.producer_exit_code == 0 && process.sink_exit_code == 0,
                    stage.definition.label + L" failed (producer exit " + std::to_wstring(process.producer_exit_code) +
                    L", sink exit " + std::to_wstring(process.sink_exit_code) + L"). See " +
                    stage.stderr_path + L" and " + stage.sink_stderr_path + L".");
            } else {
                const auto process = execute(stage.tool.path, stage.argv, stage.stdout_path, stage.stderr_path,
                    cancel, record, 0, result.folder, &stage.performance);
                stage.exit_code = process.exit_code; stage.has_exit_code = true;
                if (process.cancelled) { result.cancelled = true; fail(L"Workflow cancelled."); }
                require(process.exit_code == 0, stage.definition.label + L" failed with exit code " +
                    std::to_wstring(process.exit_code) + L". See " + stage.stderr_path + L".");
            }
            check_cancel(cancel);
            for (const auto& id : produced) {
                auto& artifact = artifacts.at(id);
                auto file = ordinary_file(artifact.path);
                artifact.bytes = size_of(file.get(), artifact.path);
                require(!artifact.definition.nonempty || artifact.bytes > 0, L"Expected output is empty: " + artifact.path);
                artifact.sha256 = sha256_file(artifact.path, cancel);
                artifact.handle = std::move(file);
                artifact.checked = true; artifact.completed_by = stage.definition.id;
            }
            stage.elapsed_ms = GetTickCount64() - active_began;
            stage.finished = now_utc(); stage.status = L"success"; active = nullptr;
            record(L"Completed: " + stage.definition.label); save_report();
        }
        phase(report_phase, L"Verifying final outputs and unchanged inputs...");
        check_inputs_after();
        for (auto& entry : artifacts) {
            auto& artifact = entry.second;
            require(artifact.checked, L"A declared output was not produced: " + artifact.path);
            require(sha256_file(artifact.path, cancel) == artifact.sha256,
                L"A later step changed an already completed output: " + artifact.path);
        }
        check_cancel(cancel);
        result.success = true; status = L"success";
        for (const auto& output : workflow->outputs) if (output.final) result.outputs.push_back(output_paths.at(output.id));
        result.message = L"Workflow complete. Results are saved in " + result.folder;
        record(result.message); save_report(); phase(report_phase, L"Complete");
    } catch (const std::exception& error) {
        result.success = false; result.cancelled = result.cancelled || cancel.load(); result.outputs.clear();
        status = result.cancelled ? L"cancelled" : L"failed";
        if (active) { active->status = status; active->finished = now_utc(); active->elapsed_ms = GetTickCount64() - active_began; }
        try { result.message = result.cancelled ? L"Workflow cancelled." : utf16(error.what()); }
        catch (...) { result.message = L"Workflow failed; the diagnostic could not be decoded."; }
        if (!result.cancelled) {
            try { check_inputs_after(); }
            catch (const std::exception& after_error) { result.message += L" Input verification: " + utf16(after_error.what()); }
        } else for (auto& file : input_files) if (file.after_status == L"not_checked") file.after_status = L"not_checked_cancelled";
        if (!result.folder.empty()) result.message += L" Intermediate files and diagnostics are retained in " + result.folder + L".";
        record(result.message);
        if (!result.folder.empty()) try { save_report(); }
        catch (const std::exception& report_error) {
            result.message += L" Could not save the complete run report: " + utf16(report_error.what()); emit(log, result.message);
        }
        phase(report_phase, result.cancelled ? L"Cancelled" : L"Failed");
    }
    result.performance_json = workflow_performance_json(stages);
    return result;
}
} // namespace bw
