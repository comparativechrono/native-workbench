#include "workbench.h"
#include "child_environment.h"
#include "process_performance.h"

#include <algorithm>
#include <array>
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
    HANDLE get() const { return value_; }
    bool valid() const { return value_ && value_ != INVALID_HANDLE_VALUE; }
    HANDLE release() { auto value = value_; value_ = INVALID_HANDLE_VALUE; return value; }
    void reset(HANDLE value = INVALID_HANDLE_VALUE) {
        if (valid()) CloseHandle(value_);
        value_ = value;
    }
};

[[noreturn]] void fail(const std::wstring& message, DWORD code = GetLastError()) {
    throw std::runtime_error(utf8(message + L": " + windows_error(code)));
}
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
void emit(const Log& log, const std::wstring& message) { if (log) log(message); }

std::wstring absolute(const std::wstring& path) {
    require(!path.empty() && path.find(L'\0') == std::wstring::npos,
            "A pipeline executable or directory path is empty or contains a null character.");
    const auto size = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (!size) fail(L"Cannot resolve pipeline path " + path);
    require(size < 32767, "A pipeline path exceeds the Windows length limit.");
    std::vector<wchar_t> buffer(static_cast<size_t>(size) + 1);
    const auto length = GetFullPathNameW(path.c_str(), static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    if (!length || length >= buffer.size()) fail(L"Cannot resolve pipeline path " + path);
    return std::wstring(buffer.data(), length);
}

std::wstring command_line(const std::wstring& executable, const std::vector<std::wstring>& args) {
    auto command = quote_argument(executable);
    for (const auto& argument : args) command += L" " + quote_argument(argument);
    require(command.size() < 32767, "A pipeline command exceeds the Windows command-line length limit.");
    return command;
}

struct Pipe {
    Handle read, write;
    bool ended = false;
    explicit Pipe(bool inherited_reader = false) {
        SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        HANDLE reader = nullptr, writer = nullptr;
        if (!CreatePipe(&reader, &writer, &security, 64 * 1024)) fail(L"Cannot create pipeline pipe");
        read.reset(reader); write.reset(writer);
        if (!inherited_reader && !SetHandleInformation(read.get(), HANDLE_FLAG_INHERIT, 0))
            fail(L"Cannot protect pipeline pipe reader");
    }
};

void write_all(HANDLE file, const char* data, DWORD size, const std::wstring& path) {
    while (size) {
        DWORD written = 0;
        if (!WriteFile(file, data, size, &written, nullptr)) fail(L"Cannot write pipeline log " + path);
        if (!written) fail(L"Cannot write pipeline log " + path, ERROR_WRITE_FAULT);
        data += written; size -= written;
    }
}
void flush_close(Handle& file, const std::wstring& path) {
    if (!FlushFileBuffers(file.get())) fail(L"Cannot flush pipeline output " + path);
    const auto raw = file.release();
    if (!CloseHandle(raw)) fail(L"Cannot close pipeline output " + path);
}

// Raw stderr is always preserved; only the GUI copy is decoded and bounded.
class Diagnostics {
    const Log& log_;
    std::wstring prefix_;
    std::string pending_;
    size_t displayed_ = 0;
    bool truncated_ = false;
    void output(std::string part) {
        if (displayed_ >= 1024 * 1024) {
            if (!truncated_) emit(log_, prefix_ + L"Further messages are saved in the stderr log.");
            truncated_ = true;
            return;
        }
        if (!part.empty() && part.back() == '\r') part.pop_back();
        const int size = MultiByteToWideChar(CP_UTF8, 0, part.data(), static_cast<int>(part.size()), nullptr, 0);
        if (size) {
            std::wstring text(static_cast<size_t>(size), L'\0');
            if (!MultiByteToWideChar(CP_UTF8, 0, part.data(), static_cast<int>(part.size()), text.data(), size))
                fail(L"Cannot decode pipeline diagnostics");
            std::replace(text.begin(), text.end(), L'\0', L'\ufffd');
            emit(log_, prefix_ + text);
        }
        displayed_ += part.size();
    }
public:
    Diagnostics(const Log& log, const std::wstring& prefix) : log_(log), prefix_(prefix) {}
    void consume(const char* bytes, DWORD size) {
        if (truncated_) return;
        pending_.append(bytes, size);
        for (;;) {
            const auto newline = pending_.find('\n');
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

bool drain(Pipe& pipe, HANDLE destination, const std::wstring& path, Diagnostics* diagnostics) {
    if (pipe.ended) return false;
    std::array<char, 64 * 1024> buffer{};
    bool activity = false;
    // Bound each turn, so stderr from one child cannot starve the other child
    // or prevent cancellation/status checks. The transfer pipe is never copied
    // through this parent; the operating system supplies its backpressure.
    for (unsigned i = 0; i < 8; ++i) {
        DWORD available = 0;
        if (!PeekNamedPipe(pipe.read.get(), nullptr, 0, nullptr, &available, nullptr)) {
            const auto code = GetLastError();
            if (code == ERROR_BROKEN_PIPE) { pipe.ended = true; return activity; }
            fail(L"Cannot inspect pipeline output pipe", code);
        }
        if (!available) break;
        DWORD count = 0;
        if (!ReadFile(pipe.read.get(), buffer.data(), std::min<DWORD>(available, static_cast<DWORD>(buffer.size())), &count, nullptr)) {
            const auto code = GetLastError();
            if (code == ERROR_BROKEN_PIPE) { pipe.ended = true; return activity; }
            fail(L"Cannot read pipeline output pipe", code);
        }
        if (!count) { pipe.ended = true; return activity; }
        write_all(destination, buffer.data(), count, path);
        if (diagnostics) diagnostics->consume(buffer.data(), count);
        activity = true;
    }
    return activity;
}

class Attributes {
    std::vector<unsigned char> storage_;
    LPPROC_THREAD_ATTRIBUTE_LIST list_ = nullptr;
public:
    Attributes() {
        SIZE_T size = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &size);
        require(size > 0, "Cannot determine pipeline process attribute size.");
        storage_.resize(size);
        list_ = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage_.data());
        if (!InitializeProcThreadAttributeList(list_, 1, 0, &size)) {
            list_ = nullptr; fail(L"Cannot initialize pipeline process attributes");
        }
    }
    ~Attributes() { if (list_) DeleteProcThreadAttributeList(list_); }
    LPPROC_THREAD_ATTRIBUTE_LIST get() const { return list_; }
};

struct Child {
    Handle process, thread;
    bool exited = false;
    DWORD exit_code = 0;
    ~Child() {
        // Also covers CreateProcess succeeding but job assignment failing.
        if (process.valid() && WaitForSingleObject(process.get(), 0) != WAIT_OBJECT_0) {
            TerminateProcess(process.get(), ERROR_PROCESS_ABORTED);
            WaitForSingleObject(process.get(), 5000);
        }
    }
    void poll() {
        if (exited) return;
        const auto status = WaitForSingleObject(process.get(), 0);
        if (status == WAIT_FAILED) fail(L"Cannot monitor pipeline child");
        if (status == WAIT_OBJECT_0) {
            if (!GetExitCodeProcess(process.get(), &exit_code)) fail(L"Cannot retrieve pipeline exit code");
            exited = true;
        }
    }
};

struct Session {
    Handle job;
    Child producer, sink;
    Session() : job(CreateJobObjectW(nullptr, nullptr)) {
        if (!job.valid()) fail(L"Cannot create pipeline process job");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
            fail(L"Cannot configure pipeline process job");
    }
    ~Session() {
        // Exception paths must stop children before the caller hashes or reports
        // outputs. Both are created suspended and assigned before either starts.
        if (job.valid()) {
            TerminateJobObject(job.get(), ERROR_PROCESS_ABORTED);
            job.reset();
        }
        for (Child* child : {&producer, &sink}) {
            if (!child->process.valid()) continue;
            if (WaitForSingleObject(child->process.get(), 0) != WAIT_OBJECT_0)
                TerminateProcess(child->process.get(), ERROR_PROCESS_ABORTED);
            WaitForSingleObject(child->process.get(), 5000);
        }
    }
};

void start(Child& child, HANDLE job, const std::wstring& executable, std::wstring command,
           HANDLE input, HANDLE output, HANDLE error, const std::wstring& directory) {
    std::array<HANDLE, 3> handles{input, output, error};
    // Attribute values must outlive DeleteProcThreadAttributeList.
    Attributes attributes;
    if (!UpdateProcThreadAttribute(attributes.get(), 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                    handles.data(), sizeof(handles), nullptr, nullptr))
        fail(L"Cannot restrict pipeline inherited handles");
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.StartupInfo.wShowWindow = SW_HIDE;
    startup.StartupInfo.hStdInput = input;
    startup.StartupInfo.hStdOutput = output;
    startup.StartupInfo.hStdError = error;
    startup.lpAttributeList = attributes.get();
    PROCESS_INFORMATION information{};
    auto environment = pack_child_environment();
    if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, TRUE,
                        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT, environment.data(),
                        directory.empty() ? nullptr : directory.c_str(), &startup.StartupInfo, &information))
        fail(L"Cannot start pipeline executable " + executable);
    child.process.reset(information.hProcess); child.thread.reset(information.hThread);
    if (!AssignProcessToJobObject(job, child.process.get()))
        fail(L"Windows did not permit a pipeline child to enter its cancellable process job");
}
} // namespace

PipelineProcessResult execute_pipeline(const std::wstring& producer, const std::vector<std::wstring>& producer_args,
    const std::wstring& sink, const std::vector<std::wstring>& sink_args,
    const std::wstring& stdout_file, const std::wstring& producer_stderr_file,
    const std::wstring& sink_stderr_file, Cancel& cancel, const Log& log, DWORD timeout_ms,
    const std::wstring& working_directory, ProcessPerformance* performance) {
    ProcessPerformance local_performance;
    ProcessPerformance& measured = performance ? *performance : local_performance;
    measured = {}; measured.pipeline = true;
    if (cancel.load()) return {ERROR_CANCELLED, ERROR_CANCELLED, true, measured};
    const auto producer_binary = absolute(producer), sink_binary = absolute(sink);
    const auto directory = working_directory.empty() ? std::wstring{} : absolute(working_directory);
    const auto producer_command = command_line(producer_binary, producer_args);
    const auto sink_command = command_line(sink_binary, sink_args);
    Handle output(CreateFileW(native_path(stdout_file).c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                              CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!output.valid()) fail(L"Cannot create pipeline output " + stdout_file);
    Handle producer_errors(CreateFileW(native_path(producer_stderr_file).c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                                       nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!producer_errors.valid()) fail(L"Cannot create producer stderr log " + producer_stderr_file);
    Handle sink_errors(CreateFileW(native_path(sink_stderr_file).c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                                   nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!sink_errors.valid()) fail(L"Cannot create sink stderr log " + sink_stderr_file);
    Pipe transfer(true), sink_output, producer_error, sink_error;
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    Handle null_input(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!null_input.valid()) fail(L"Cannot open pipeline input");
    Diagnostics producer_diagnostics(log, L"[producer] "), sink_diagnostics(log, L"[sink] ");
    Session session;
    JobPerformanceCapture metrics(session.job.get(), measured);
    if (cancel.load()) return {ERROR_CANCELLED, ERROR_CANCELLED, true, measured};
    emit(log, L"Pipeline producer: " + producer_command);
    emit(log, L"Pipeline sink: " + sink_command);
    const auto started = GetTickCount64();
    metrics.begin(started);
    start(session.sink, session.job.get(), sink_binary, sink_command,
          transfer.read.get(), sink_output.write.get(), sink_error.write.get(), directory);
    metrics.assigned();
    start(session.producer, session.job.get(), producer_binary, producer_command,
          null_input.get(), transfer.write.get(), producer_error.write.get(), directory);
    // Children own exactly their three standard handles. Closing every parent's
    // copy before resuming is essential for EOF and broken-pipe propagation.
    transfer.read.reset(); transfer.write.reset();
    sink_output.write.reset(); producer_error.write.reset(); sink_error.write.reset(); null_input.reset();
    if (ResumeThread(session.sink.thread.get()) == static_cast<DWORD>(-1)) fail(L"Cannot resume pipeline sink");
    session.sink.thread.reset();
    if (ResumeThread(session.producer.thread.get()) == static_cast<DWORD>(-1)) fail(L"Cannot resume pipeline producer");
    session.producer.thread.reset();
    bool terminated = false, cancelled = false, timed_out = false;
    ULONGLONG stopped_at = 0, exited_at = 0;
    while (true) {
        // Read natural exit codes before stopping a peer; this preserves the
        // originating failure even if a valid prefix reached the other child.
        session.producer.poll(); session.sink.poll();
        const bool complete = session.producer.exited && session.sink.exited;
        if (complete && !exited_at) {
            exited_at = GetTickCount64();
            // Main processes have both exited. Kill remaining descendants that
            // might otherwise keep a stderr/stdout handle or output file open.
            metrics.capture();
            session.job.reset();
        }
        if (!complete && !terminated) {
            cancelled = cancel.load();
            timed_out = !cancelled && timeout_ms && GetTickCount64() - started >= timeout_ms;
            const bool failed = (session.producer.exited && session.producer.exit_code) ||
                                (session.sink.exited && session.sink.exit_code);
            if (cancelled || timed_out || failed) {
                const DWORD code = cancelled ? ERROR_CANCELLED : timed_out ? ERROR_TIMEOUT : ERROR_PROCESS_ABORTED;
                if (!TerminateJobObject(session.job.get(), code)) fail(L"Cannot stop pipeline process tree");
                terminated = true; stopped_at = GetTickCount64();
                emit(log, cancelled ? L"Cancelling both pipeline processes..." : timed_out ?
                     L"Pipeline timed out; stopping both processes..." : L"A pipeline process failed; stopping its peer...");
            }
        }
        bool activity = drain(sink_output, output.get(), stdout_file, nullptr);
        activity = drain(producer_error, producer_errors.get(), producer_stderr_file, &producer_diagnostics) || activity;
        activity = drain(sink_error, sink_errors.get(), sink_stderr_file, &sink_diagnostics) || activity;
        if (complete && sink_output.ended && producer_error.ended && sink_error.ended) break;
        if (terminated && !complete && GetTickCount64() - stopped_at > 10000)
            throw std::runtime_error("A pipeline process did not stop after termination; outputs are incomplete.");
        if (complete && GetTickCount64() - exited_at > 10000)
            throw std::runtime_error("A pipeline output pipe did not close after both processes exited; outputs are incomplete.");
        if (!activity) Sleep(10);
    }
    producer_diagnostics.finish(); sink_diagnostics.finish();
    flush_close(output, stdout_file);
    flush_close(producer_errors, producer_stderr_file); flush_close(sink_errors, sink_stderr_file);
    emit(log, L"Pipeline exit codes: producer=" + std::to_wstring(session.producer.exit_code) +
              L", sink=" + std::to_wstring(session.sink.exit_code));
    if (timed_out) throw std::runtime_error("The pipeline exceeded its time limit.");
    return {session.producer.exit_code, session.sink.exit_code, cancelled || cancel.load(), measured};
}
} // namespace bw
