#include "workbench.h"
#include "child_environment.h"
#include "process_performance.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <exception>
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
    ~Handle() { reset(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value_(other.release()) {}
    Handle& operator=(Handle&& other) noexcept { reset(other.release()); return *this; }
    bool valid() const { return value_ && value_ != INVALID_HANDLE_VALUE; }
    HANDLE get() const { return value_; }
    HANDLE release() { HANDLE result = value_; value_ = INVALID_HANDLE_VALUE; return result; }
    void reset(HANDLE value = INVALID_HANDLE_VALUE) { if (valid()) CloseHandle(value_); value_ = value; }
};

[[noreturn]] void fail(const std::wstring& what, DWORD code = GetLastError()) {
    throw std::runtime_error(utf8(what + L": " + windows_error(code)));
}
void require(bool condition, const std::wstring& message) {
    if (!condition) throw std::runtime_error(utf8(message));
}
void emit(const Log& log, const std::wstring& text) { if (log) log(text); }
void phase(const Phase& report, const std::wstring& text) { if (report) report(text); }

std::wstring absolute_path(const std::wstring& path) {
    require(!path.empty() && path.find(L'\0') == std::wstring::npos, L"A file path is empty or contains a null character.");
    DWORD needed = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (!needed) fail(L"Cannot resolve path " + path);
    std::vector<wchar_t> buffer(static_cast<size_t>(needed) + 1);
    DWORD length = GetFullPathNameW(path.c_str(), static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    if (!length || length >= buffer.size()) fail(L"Cannot resolve path " + path);
    return std::wstring(buffer.data(), length);
}

std::wstring utc_time(const FILETIME& time) {
    SYSTEMTIME utc{};
    if (!FileTimeToSystemTime(&time, &utc)) fail(L"Cannot convert file time");
    wchar_t value[64]{};
    swprintf(value, 64, L"%04u-%02u-%02uT%02u:%02u:%02u.%03uZ", utc.wYear, utc.wMonth,
        utc.wDay, utc.wHour, utc.wMinute, utc.wSecond, utc.wMilliseconds);
    return value;
}
std::wstring now_utc() { FILETIME value{}; GetSystemTimeAsFileTime(&value); return utc_time(value); }

struct InputInfo {
    std::wstring path, modified;
    uint64_t size = 0;
    uint64_t modified_ticks = 0;
};
InputInfo input_info(const std::wstring& path, bool allow_empty) {
    InputInfo result;
    result.path = absolute_path(path);
    Handle file(CreateFileW(native_path(result.path).c_str(), FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!file.valid()) fail(L"Cannot open input " + result.path);
    BY_HANDLE_FILE_INFORMATION data{};
    if (!GetFileInformationByHandle(file.get(), &data)) fail(L"Cannot inspect input " + result.path);
    require(GetFileType(file.get()) == FILE_TYPE_DISK && !(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY),
        L"Input must be a regular file: " + result.path);
    result.size = (static_cast<uint64_t>(data.nFileSizeHigh) << 32) | data.nFileSizeLow;
    require(allow_empty || result.size > 0, L"Input file is empty: " + result.path);
    result.modified_ticks = (static_cast<uint64_t>(data.ftLastWriteTime.dwHighDateTime) << 32) | data.ftLastWriteTime.dwLowDateTime;
    result.modified = utc_time(data.ftLastWriteTime);
    return result;
}

void write_all(HANDLE file, const char* data, size_t size, const std::wstring& path) {
    while (size) {
        DWORD written = 0;
        DWORD count = static_cast<DWORD>(std::min<size_t>(size, 1024 * 1024));
        if (!WriteFile(file, data, count, &written, nullptr)) fail(L"Cannot write " + path);
        if (!written) fail(L"Cannot write " + path, ERROR_WRITE_FAULT);
        data += written;
        size -= written;
    }
}
void flush_close(Handle& file, const std::wstring& path) {
    if (!FlushFileBuffers(file.get())) fail(L"Cannot flush " + path);
    HANDLE raw = file.release();
    if (!CloseHandle(raw)) fail(L"Cannot close " + path);
}

struct Pipe {
    Handle read, write;
    bool ended = false;
    Pipe() {
        SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        HANDLE reader = nullptr, writer = nullptr;
        if (!CreatePipe(&reader, &writer, &security, 64 * 1024)) fail(L"Cannot create process output pipe");
        read.reset(reader); write.reset(writer);
        if (!SetHandleInformation(read.get(), HANDLE_FLAG_INHERIT, 0)) fail(L"Cannot protect pipe handle");
    }
};

// Tool diagnostics can contain malformed UTF-8. Preserve original bytes on disk;
// the GUI replaces invalid sequences and bounds each displayed chunk and total.
class DiagnosticText {
    const Log& log_;
    std::string pending_;
    size_t displayed_ = 0;
    bool truncated_ = false;
    void output(std::string part) {
        if (displayed_ >= 1024 * 1024) {
            if (!truncated_) emit(log_, L"Further tool messages are saved in the stderr log.");
            truncated_ = true;
            return;
        }
        if (!part.empty() && part.back() == '\r') part.pop_back();
        int needed = MultiByteToWideChar(CP_UTF8, 0, part.data(), static_cast<int>(part.size()), nullptr, 0);
        if (needed) {
            std::wstring decoded(static_cast<size_t>(needed), L'\0');
            if (!MultiByteToWideChar(CP_UTF8, 0, part.data(), static_cast<int>(part.size()), decoded.data(), needed))
                fail(L"Cannot decode tool diagnostic");
            // An embedded null must not hide the remainder in an edit control.
            std::replace(decoded.begin(), decoded.end(), L'\0', L'\ufffd');
            emit(log_, decoded);
        }
        displayed_ += part.size();
    }
public:
    explicit DiagnosticText(const Log& log) : log_(log) {}
    void consume(const char* bytes, size_t count) {
        if (truncated_) return;
        pending_.append(bytes, count);
        for (;;) {
            size_t newline = pending_.find('\n');
            if (newline != std::string::npos && newline <= 8192) {
                output(pending_.substr(0, newline)); pending_.erase(0, newline + 1);
            } else if (pending_.size() > 8192) {
                size_t split = 8192;
                while (split && (static_cast<unsigned char>(pending_[split]) & 0xc0) == 0x80) --split;
                if (!split) split = 8192;
                output(pending_.substr(0, split)); pending_.erase(0, split);
            } else break;
            if (truncated_) { pending_.clear(); break; }
        }
    }
    void finish() { if (!pending_.empty()) output(std::move(pending_)); }
};

bool drain(Pipe& pipe, HANDLE destination, const std::wstring& path, DiagnosticText* diagnostics) {
    if (pipe.ended) return false;
    std::array<char, 64 * 1024> bytes{};
    bool activity = false;
    // Alternate streams after at most 1 MiB so neither can starve the other.
    for (unsigned iteration = 0; iteration < 16; ++iteration) {
        DWORD available = 0;
        if (!PeekNamedPipe(pipe.read.get(), nullptr, 0, nullptr, &available, nullptr)) {
            DWORD code = GetLastError();
            if (code == ERROR_BROKEN_PIPE) { pipe.ended = true; return activity; }
            fail(L"Cannot inspect process output pipe", code);
        }
        if (!available) break;
        DWORD count = 0;
        DWORD wanted = std::min<DWORD>(available, static_cast<DWORD>(bytes.size()));
        if (!ReadFile(pipe.read.get(), bytes.data(), wanted, &count, nullptr)) {
            DWORD code = GetLastError();
            if (code == ERROR_BROKEN_PIPE) { pipe.ended = true; return activity; }
            fail(L"Cannot read process output pipe", code);
        }
        if (!count) { pipe.ended = true; return activity; }
        write_all(destination, bytes.data(), count, path);
        if (diagnostics) diagnostics->consume(bytes.data(), count);
        activity = true;
    }
    return activity;
}

class AttributeList {
    std::vector<unsigned char> data_;
    LPPROC_THREAD_ATTRIBUTE_LIST list_ = nullptr;
public:
    AttributeList() {
        SIZE_T size = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &size);
        require(size > 0, L"Cannot determine process attribute size.");
        data_.resize(size);
        list_ = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(data_.data());
        if (!InitializeProcThreadAttributeList(list_, 1, 0, &size)) { list_ = nullptr; fail(L"Cannot initialize process attributes"); }
    }
    ~AttributeList() { if (list_) DeleteProcThreadAttributeList(list_); }
    LPPROC_THREAD_ATTRIBUTE_LIST get() const { return list_; }
};

struct Stage {
    Tool tool;
    std::wstring name, final, partial, stderr_path;
    std::vector<std::wstring> args;
    bool started = false, finished = false, cancelled = false, published = false;
    DWORD exit_code = 0;
    ULONGLONG elapsed_ms = 0;
    std::wstring sha256;
    ProcessPerformance performance;
};

std::string input_json(const InputInfo& input) {
    std::ostringstream out;
    out << "{\"path\":" << json_string(input.path) << ",\"bytes\":" << input.size
        << ",\"modified_utc\":" << json_string(input.modified)
        << ",\"modified_filetime_ticks\":" << input.modified_ticks << ",\"sha256\":null}";
    return out.str();
}

std::string manifest(const Request& request, const InputInfo& input, const InputInfo* reference,
    const std::vector<Stage>& stages, const Result& result, const std::wstring& started, ULONGLONG elapsed) {
    std::ostringstream out;
    out << "{\n  \"schema\":1,\n  \"application_version\":" << json_string(APP_VERSION)
        << ",\n  \"started_utc\":" << json_string(started) << ",\n  \"finished_utc\":" << json_string(now_utc())
        << ",\n  \"elapsed_ms\":" << elapsed << ",\n  \"status\":"
        << json_string(result.cancelled ? L"cancelled" : result.success ? L"success" : L"failed")
        << ",\n  \"message\":" << json_string(result.message)
        << ",\n  \"pack\":{\"id\":" << json_string(request.pack.id) << ",\"version\":" << json_string(request.pack.version)
        << ",\"name\":" << json_string(request.pack.name) << "},\n  \"input\":" << input_json(input)
        << ",\n  \"reference\":" << (reference ? input_json(*reference) : "null")
        << ",\n  \"input_hashing\":\"not performed; paths, sizes and modification times recorded\""
        << ",\n  \"threads_requested\":" << request.threads << ",\n  \"alignment_preset\":" << json_string(request.preset)
        << ",\n  \"stages\":[";
    for (size_t i = 0; i < stages.size(); ++i) {
        const Stage& stage = stages[i];
        if (i) out << ',';
        out << "\n    {\"name\":" << json_string(stage.name) << ",\"tool\":" << json_string(stage.tool.id)
            << ",\"version\":" << json_string(stage.tool.version) << ",\"executable\":" << json_string(stage.tool.path)
            << ",\"executable_sha256\":" << json_string(stage.tool.sha256) << ",\"arguments\":[";
        for (size_t arg = 0; arg < stage.args.size(); ++arg) { if (arg) out << ','; out << json_string(stage.args[arg]); }
        out << "],\"started\":" << (stage.started ? "true" : "false")
            << ",\"finished\":" << (stage.finished ? "true" : "false")
            << ",\"exit_code\":" << (stage.finished ? std::to_string(stage.exit_code) : "null")
            << ",\"cancelled\":" << (stage.cancelled ? "true" : "false")
            << ",\"elapsed_ms\":" << stage.elapsed_ms
            << ",\"performance\":" << process_performance_json(stage.performance)
            << ",\"stderr\":" << json_string(stage.stderr_path)
            << ",\"output\":" << json_string(stage.final)
            << ",\"published\":" << (stage.published ? "true" : "false")
            << ",\"output_sha256\":" << (stage.sha256.empty() ? "null" : json_string(stage.sha256)) << '}';
    }
    out << "\n  ]\n}\n";
    return out.str();
}

void cleanup_outputs(std::vector<Stage>& stages, std::wstring& warning) {
    for (Stage& stage : stages) {
        for (const std::wstring* path : {&stage.partial, stage.published ? &stage.final : nullptr}) {
            if (!path || path->empty()) continue;
            if (!DeleteFileW(native_path(*path).c_str())) {
                DWORD code = GetLastError();
                if (code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND)
                    warning += L" Could not remove incomplete output " + *path + L": " + windows_error(code) + L".";
            } else if (path == &stage.final) stage.published = false;
        }
    }
}
} // namespace

std::wstring quote_argument(const std::wstring& argument) {
    require(argument.find(L'\0') == std::wstring::npos, L"A process argument contains a null character.");
    // MS C runtime / CommandLineToArgvW-compatible quoting, including empty
    // strings, embedded quotes and trailing backslashes before the closing quote.
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (wchar_t c : argument) {
        if (c == L'\\') { ++slashes; continue; }
        if (c == L'\"') {
            result.append(slashes * 2 + 1, L'\\'); result.push_back(c);
        } else {
            result.append(slashes, L'\\'); result.push_back(c);
        }
        slashes = 0;
    }
    result.append(slashes * 2, L'\\'); result.push_back(L'\"');
    return result;
}

ProcessResult execute(const std::wstring& executable, const std::vector<std::wstring>& args,
    const std::wstring& stdout_file, const std::wstring& stderr_file, Cancel& cancel, const Log& log, DWORD timeout_ms,
    const std::wstring& working_directory, ProcessPerformance* performance) {
    ProcessPerformance local_performance;
    ProcessPerformance& measured = performance ? *performance : local_performance;
    measured = {};
    if (cancel.load()) return {ERROR_CANCELLED, true, measured};
    std::wstring binary = absolute_path(executable);
    const std::wstring child_directory = working_directory.empty() ? std::wstring{} : absolute_path(working_directory);
    std::wstring command = quote_argument(binary);
    for (const auto& argument : args) command += L" " + quote_argument(argument);
    require(command.size() < 32767, L"The tool command line is too long for Windows.");

    Handle output(CreateFileW(native_path(stdout_file).c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!output.valid()) fail(L"Cannot create output " + stdout_file);
    Handle errors(CreateFileW(native_path(stderr_file).c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!errors.valid()) fail(L"Cannot create diagnostic log " + stderr_file);
    Pipe standard_out, standard_error;
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    Handle null_input(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!null_input.valid()) fail(L"Cannot open process input");
    Handle job(CreateJobObjectW(nullptr, nullptr));
    if (!job.valid()) fail(L"Cannot create process job");
    JobPerformanceCapture metrics(job.get(), measured);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
        fail(L"Cannot configure process job");
    std::array<HANDLE, 3> inherited{null_input.get(), standard_out.write.get(), standard_error.write.get()};
    AttributeList attributes;
    if (!UpdateProcThreadAttribute(attributes.get(), 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        inherited.data(), sizeof(inherited), nullptr, nullptr)) fail(L"Cannot restrict inherited process handles");
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.StartupInfo.wShowWindow = SW_HIDE;
    startup.StartupInfo.hStdInput = null_input.get();
    startup.StartupInfo.hStdOutput = standard_out.write.get();
    startup.StartupInfo.hStdError = standard_error.write.get();
    startup.lpAttributeList = attributes.get();
    PROCESS_INFORMATION information{};
    emit(log, L"Running: " + command);
    ULONGLONG started = GetTickCount64();
    metrics.begin(started);
    auto environment = pack_child_environment();
    if (!CreateProcessW(binary.c_str(), command.data(), nullptr, nullptr, TRUE,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, environment.data(),
        child_directory.empty() ? nullptr : child_directory.c_str(),
        &startup.StartupInfo, &information)) fail(L"Cannot start " + binary);
    Handle process(information.hProcess), thread(information.hThread);
    if (!AssignProcessToJobObject(job.get(), process.get())) {
        DWORD code = GetLastError();
        TerminateProcess(process.get(), ERROR_PROCESS_ABORTED);
        WaitForSingleObject(process.get(), 5000);
        fail(L"Windows did not permit the tool to enter its cancellable process job", code);
    }
    metrics.assigned();
    // All exceptions after assignment close the job and kill the entire tree.
    if (ResumeThread(thread.get()) == static_cast<DWORD>(-1)) fail(L"Cannot resume tool process");
    thread.reset();
    standard_out.write.reset(); standard_error.write.reset(); null_input.reset();
    DiagnosticText diagnostics(log);
    bool exited = false, cancelled = false, timed_out = false, terminated = false;
    ULONGLONG exited_at = 0;
    DWORD exit_code = 0;
    while (!exited || !standard_out.ended || !standard_error.ended) {
        if (!terminated && !exited && (cancel.load() || (timeout_ms && GetTickCount64() - started >= timeout_ms))) {
            cancelled = cancel.load(); timed_out = !cancelled;
            if (!TerminateJobObject(job.get(), cancelled ? ERROR_CANCELLED : ERROR_TIMEOUT)) fail(L"Cannot stop tool process tree");
            terminated = true;
            emit(log, cancelled ? L"Cancelling the tool and its child processes..." : L"The validation command timed out; stopping it...");
        }
        bool activity = drain(standard_out, output.get(), stdout_file, nullptr);
        activity = drain(standard_error, errors.get(), stderr_file, &diagnostics) || activity;
        if (!exited) {
            DWORD waited = WaitForSingleObject(process.get(), 0);
            if (waited == WAIT_FAILED) fail(L"Cannot monitor tool process");
            if (waited == WAIT_OBJECT_0) {
                if (!GetExitCodeProcess(process.get(), &exit_code)) fail(L"Cannot retrieve tool exit status");
                exited = true; exited_at = GetTickCount64();
                // A command has ended. Do not leave detached descendants keeping
                // pipes or files open after the main executable has returned.
                metrics.capture();
                job.reset();
            }
        }
        if (exited && GetTickCount64() - exited_at > 10000 && (!standard_out.ended || !standard_error.ended))
            throw std::runtime_error("The tool exited, but a process output pipe did not close. The output is incomplete.");
        if (!activity && (!exited || !standard_out.ended || !standard_error.ended)) Sleep(10);
    }
    diagnostics.finish();
    flush_close(output, stdout_file); flush_close(errors, stderr_file);
    emit(log, L"Tool exit code: " + std::to_wstring(exit_code));
    if (timed_out) throw std::runtime_error("The validation command exceeded its time limit.");
    return {exit_code, cancelled || cancel.load(), measured};
}

Result run_job(const Request& request, Cancel& cancel, const Log& log, const Phase& report_phase) {
    Result result;
    InputInfo input, reference;
    bool has_reference = request.kind == JobKind::Alignment || request.kind == JobKind::StatisticsAndAlignment;
    std::vector<Stage> stages;
    ULONGLONG began = GetTickCount64();
    std::wstring started = now_utc();
    std::string run_log;
    bool owns_manifest = false, owns_log = false;
    Log record_log = [&](const std::wstring& line) {
        run_log += utf8(line) + "\r\n";
        emit(log, line);
    };
    auto write_owned_report = [&](const std::wstring& name, const std::string& bytes, bool& owned) {
        const std::wstring target = join(result.folder, name);
        const std::wstring temporary = target + L".pending";
        write_file_new(temporary, bytes);
        if (!MoveFileExW(native_path(temporary).c_str(), native_path(target).c_str(), owned ? MOVEFILE_REPLACE_EXISTING : 0)) {
            DWORD code = GetLastError();
            DeleteFileW(native_path(temporary).c_str());
            fail(L"Cannot publish report " + target, code);
        }
        owned = true;
    };
    auto write_report = [&]() {
        // If saving the readable log fails, still try the authoritative JSON.
        // Subsequent attempts may replace only reports this call already owns.
        std::exception_ptr error;
        try { write_owned_report(L"workbench.log", run_log, owns_log); }
        catch (...) { error = std::current_exception(); }
        try {
            write_owned_report(L"run.json", manifest(request, input,
                has_reference ? &reference : nullptr, stages, result, started, GetTickCount64() - began), owns_manifest);
        } catch (...) { if (!error) error = std::current_exception(); }
        if (error) std::rethrow_exception(error);
    };
    try {
        require(request.threads >= 1 && request.threads <= 64, L"Choose between 1 and 64 threads.");
        require(request.kind == JobKind::Statistics || request.kind == JobKind::ReverseComplement ||
            request.kind == JobKind::Alignment || request.kind == JobKind::StatisticsAndAlignment, L"Unknown analysis type.");
        require(!has_reference || request.preset == L"sr" || request.preset == L"map-ont" || request.preset == L"map-hifi",
            L"Choose a supported alignment preset.");
        check_cancel(cancel);
        input = input_info(request.input, true);
        if (has_reference) reference = input_info(request.reference, false);
        std::wstring parent = absolute_path(request.output_folder);
        require(directory_exists(parent), L"Select an existing output folder.");
        // A fresh child directory prevents accidental overwrite, including when
        // inputs and the selected output parent are in the same directory.
        result.folder = unique_directory(parent, L"analysis");
        phase(report_phase, L"Checking tool-pack integrity...");
        verify_pack(request.pack, cancel, record_log);
        auto add_stage = [&](const Tool& tool, const std::wstring& name, const std::wstring& output,
            std::vector<std::wstring> args) {
            Stage stage;
            stage.tool = tool; stage.name = name; stage.args = std::move(args);
            stage.final = join(result.folder, output); stage.partial = stage.final + L".partial";
            stage.stderr_path = join(result.folder, name + L".stderr.log");
            stages.push_back(std::move(stage));
        };
        if (request.kind == JobKind::Statistics || request.kind == JobKind::StatisticsAndAlignment)
            add_stage(request.pack.fastq, L"statistics", L"reads.stats.json",
                {L"stats", L"--input", input.path, L"--output", L"-", L"--threads", std::to_wstring(request.threads)});
        if (request.kind == JobKind::ReverseComplement)
            add_stage(request.pack.seqtk, L"reverse-complement", L"reverse.fastq", {L"seq", L"-r", input.path});
        if (has_reference)
            add_stage(request.pack.minimap, L"alignment", L"alignment.sam",
                {L"-a", L"-x", request.preset, L"-t", std::to_wstring(request.threads), reference.path, input.path});
        for (Stage& stage : stages) {
            check_cancel(cancel);
            phase(report_phase, stage.name == L"statistics" ? L"Calculating FASTQ statistics..." :
                stage.name == L"alignment" ? L"Aligning reads with minimap2..." : L"Reverse-complementing reads with seqtk...");
            ULONGLONG stage_start = GetTickCount64();
            stage.started = true;
            ProcessResult process;
            try { process = execute(stage.tool.path, stage.args, stage.partial, stage.stderr_path,
                cancel, record_log, 0, {}, &stage.performance); }
            catch (...) { stage.elapsed_ms = GetTickCount64() - stage_start; throw; }
            stage.elapsed_ms = GetTickCount64() - stage_start;
            stage.finished = true; stage.exit_code = process.exit_code; stage.cancelled = process.cancelled;
            if (process.cancelled) { result.cancelled = true; throw std::runtime_error("Analysis cancelled."); }
            require(process.exit_code == 0, stage.name + L" failed with exit code " + std::to_wstring(process.exit_code) +
                L". Open " + stage.stderr_path + L" for details.");
            if (stage.name == L"reverse-complement") {
                Handle output(CreateFileW(native_path(stage.partial).c_str(), GENERIC_READ, FILE_SHARE_READ,
                    nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
                if (!output.valid()) fail(L"Cannot inspect reverse-complement output");
                char first = 0;
                DWORD count = 0;
                if (!ReadFile(output.get(), &first, 1, &count, nullptr)) fail(L"Cannot read reverse-complement output format");
                if (count && first == '>') stage.final = join(result.folder, L"reverse.fasta");
                else require(!count || first == '@', L"seqtk returned an unexpected output format.");
            }
        }
        // Detect ordinary concurrent changes to input without claiming content
        // verification. Inputs are not copied or hashed by this prototype.
        auto unchanged = [](const InputInfo& before) {
            InputInfo after = input_info(before.path, true);
            require(after.size == before.size && after.modified_ticks == before.modified_ticks,
                L"An input file changed during analysis: " + before.path);
        };
        unchanged(input); if (has_reference) unchanged(reference);
        phase(report_phase, L"Checking and publishing results...");
        for (Stage& stage : stages) { check_cancel(cancel); stage.sha256 = sha256_file(stage.partial, cancel); }
        check_cancel(cancel);
        for (Stage& stage : stages) {
            if (!MoveFileExW(native_path(stage.partial).c_str(), native_path(stage.final).c_str(), 0)) fail(L"Cannot publish output " + stage.final);
            stage.published = true;
        }
        check_cancel(cancel);
        result.success = true; result.message = L"Analysis complete. Results are saved in " + result.folder;
        for (const Stage& stage : stages) result.outputs.push_back(stage.final);
        record_log(result.message);
        write_report();
        phase(report_phase, L"Complete");
    } catch (const std::exception& error) {
        result.success = false; result.cancelled = result.cancelled || cancel.load(); result.outputs.clear();
        try { result.message = result.cancelled ? L"Analysis cancelled." : utf16(error.what()); }
        catch (...) { result.message = L"Analysis failed; an error message could not be decoded."; }
        std::wstring cleanup_warning;
        cleanup_outputs(stages, cleanup_warning);
        if (result.cancelled && cleanup_warning.empty()) result.message += L" No completed outputs were kept.";
        result.message += cleanup_warning;
        record_log(result.message);
        if (!result.folder.empty()) {
            try { write_report(); }
            catch (const std::exception& report_error) {
                result.message += L" Could not save the full run report: " + utf16(report_error.what());
                emit(log, result.message);
            }
        }
        phase(report_phase, result.cancelled ? L"Cancelled" : L"Failed");
    }
    return result;
}
} // namespace bw
