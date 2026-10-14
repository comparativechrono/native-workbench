// Native Windows checks for the production runner's Job Object accounting.
// Cross-compilation alone does not pass these checks; execute the PE on Windows.
#include "workbench.h"
#include "process_performance.h"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <locale>
#include <stdexcept>

namespace {
constexpr SIZE_T ALLOCATION = 16 * 1024 * 1024;
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
bool write(HANDLE destination, const char* bytes, DWORD size) {
    while (size) {
        DWORD count = 0;
        if (!WriteFile(destination, bytes, size, &count, nullptr) || !count) return false;
        bytes += count; size -= count;
    }
    return true;
}
std::wstring self() {
    std::vector<wchar_t> path(32768);
    const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    require(length && length < path.size(), "Cannot locate performance test executable");
    return std::wstring(path.data(), length);
}
bool report_job_membership() {
    // With NULL, Windows queries the calling process's immediate job even in a
    // nested hierarchy. This observes membership independently of the runner's
    // numeric accounting snapshot; console/OS descendants must remain in scope.
    // https://learn.microsoft.com/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject
    struct Members { DWORD assigned, count; ULONG_PTR ids[128]; } members{};
    if (!QueryInformationJobObject(nullptr, JobObjectBasicProcessIdList, &members, sizeof(members), nullptr)) {
        const auto error = "scope-error:" + std::to_string(GetLastError()) + "\n";
        write(GetStdHandle(STD_ERROR_HANDLE), error.data(), static_cast<DWORD>(error.size()));
        return false;
    }
    if (members.count > 128 || members.assigned != members.count) return false;
    bool own_pid_found = false;
    std::string images = "[";
    for (DWORD i = 0; i < members.count; ++i) {
        if (i) images += ',';
        const auto pid = static_cast<DWORD>(members.ids[i]);
        own_pid_found = own_pid_found || pid == GetCurrentProcessId();
        std::wstring name;
        DWORD error = ERROR_SUCCESS;
        const auto process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        if (process) {
            std::vector<wchar_t> path(32768);
            DWORD length = static_cast<DWORD>(path.size());
            if (QueryFullProcessImageNameW(process, 0, path.data(), &length)) name.assign(path.data(), length);
            else error = GetLastError();
            CloseHandle(process);
        } else error = GetLastError();
        images += "{\"pid\":" + std::to_string(pid) + ",\"image\":" +
            (name.empty() ? "null" : bw::json_string(name)) + ",\"image_error\":" +
            (error ? std::to_string(error) : "null") + "}";
    }
    images += ']';
    const auto probe = "{\"caller_pid\":" + std::to_string(GetCurrentProcessId()) +
        ",\"assigned\":" + std::to_string(members.assigned) + ",\"listed\":" + std::to_string(members.count) +
        ",\"own_pid_found\":" + (own_pid_found ? "true" : "false") + ",\"members\":" + images + "}";
    const auto lines = "scope-count:" + std::to_string(members.count) + "\nscope-members:" + probe + "\n";
    return write(GetStdHandle(STD_ERROR_HANDLE), lines.data(), static_cast<DWORD>(lines.size())) && own_pid_found;
}
int child(int argc, wchar_t** argv) {
    const std::wstring mode = argv[2];
    if (mode == L"quiet-wait") { Sleep(INFINITE); return 41; }
    if (mode == L"wait") {
        if (!write(GetStdHandle(STD_ERROR_HANDLE), "waiting\n", 8)) return 40;
        Sleep(INFINITE); return 41;
    }
    if (mode == L"sink") {
        std::array<char, 4096> bytes{};
        for (;;) {
            DWORD count = 0;
            if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), bytes.data(), static_cast<DWORD>(bytes.size()), &count, nullptr))
                return GetLastError() == ERROR_BROKEN_PIPE ? 0 : 42;
            if (!count) return 0;
            if (!write(GetStdHandle(STD_OUTPUT_HANDLE), bytes.data(), count)) return 43;
        }
    }
    if (mode == L"detached") {
        auto command = bw::quote_argument(self()) + L" --child quiet-wait";
        STARTUPINFOW startup{}; startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                nullptr, nullptr, &startup, &process)) return 44;
        const auto pid = std::to_string(process.dwProcessId) + "\n";
        CloseHandle(process.hThread); CloseHandle(process.hProcess);
        return write(GetStdHandle(STD_OUTPUT_HANDLE), pid.data(), static_cast<DWORD>(pid.size())) ? 0 : 45;
    }
    if (mode != L"work") return 46;
    if (argc > 4 && std::wstring(argv[4]) == L"--probe-job" && !report_job_membership()) return 49;
    auto* memory = static_cast<volatile unsigned char*>(VirtualAlloc(nullptr, ALLOCATION, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!memory) return 47;
    for (SIZE_T i = 0; i < ALLOCATION; i += 4096) memory[i] = static_cast<unsigned char>(i / 4096);
    volatile unsigned long value = 1;
    const auto began = GetTickCount64();
    while (GetTickCount64() - began < 100) for (unsigned i = 0; i < 10000; ++i) value = value * 1664525UL + 1013904223UL;
    if (!write(GetStdHandle(STD_OUTPUT_HANDLE), "measured output\n", 16)) return 48;
    VirtualFree(const_cast<unsigned char*>(memory), 0, MEM_RELEASE);
    return argc > 3 ? _wtoi(argv[3]) : 0;
}
void measured(const bw::ProcessPerformance& value, DWORD processes, bool memory = false) {
    // GetTickCount64 can legitimately return zero for a short command.
    require(value.launched && value.wall_available, "Missing command wall time");
    require(value.accounting_available && value.memory_available, "Job accounting query was unavailable");
    require(!value.accounting_error && !value.memory_error, "Successful accounting retained a query error");
    // A Job Object accounts for all associated processes, including OS-created
    // console hosts and other descendants, not just our explicit CreateProcess
    // calls. The independent immediate-job probe below retains their identities.
    if (value.processes_total < processes)
        throw std::runtime_error("Job accounting omitted an explicit process: expected at least " +
            std::to_string(processes) + ", observed " + std::to_string(value.processes_total) +
            "; snapshot=" + bw::process_performance_json(value));
    require(value.user_ticks >= 0 && value.kernel_ticks >= 0, "Negative Windows CPU accounting");
    if (memory) {
        require(value.wall_ms >= 100, "Timed work has an inconsistent command duration");
        require(value.peak_job_memory_bytes >= ALLOCATION, "Peak committed memory missed the allocation");
        require(value.user_ticks + value.kernel_ticks > 0, "CPU work was not observed");
    }
}
struct CommaDecimal : std::numpunct<char> { char do_decimal_point() const override { return ','; } };
} // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc >= 3 && std::wstring(argv[1]) == L"--child") return child(argc, argv);
    std::wstring folder, active_name;
    std::vector<std::string> observations;
    std::string active_membership;
    bw::ProcessPerformance active_performance;
    bool has_active = false;
    auto observation = [&](const std::wstring& name, const bw::ProcessPerformance& value) {
        return "{\"check\":" + bw::json_string(name) + ",\"performance\":" + bw::process_performance_json(value) +
            (active_membership.empty() ? "" : ",\"membership_probe\":" + active_membership) + "}";
    };
    auto report_json = [&](const std::wstring& error = std::wstring{}) {
        std::string report = "{\"schema\":1,\"native_windows_execution\":true,\"passed\":" +
            std::to_string(observations.size()) + ",\"failed\":" + (error.empty() ? "0" : "1") +
            ",\"skipped\":0,\"error\":" + (error.empty() ? "null" : bw::json_string(error)) + ",\"observations\":[";
        for (size_t i = 0; i < observations.size(); ++i) { if (i) report += ','; report += observations[i]; }
        report += "],\"failed_observation\":" + (error.empty() || !has_active ? "null" : observation(active_name, active_performance)) + "}\n";
        return report;
    };
    auto write_report = [&](const std::string& report) {
        if (!folder.empty()) bw::write_file_new(bw::join(folder, L"performance-validation.json"), report);
        if (argc == 4 && std::wstring(argv[2]) == L"--report") bw::write_file_new(argv[3], report);
    };
    try {
        require(argc == 2 || (argc == 4 && std::wstring(argv[2]) == L"--report"),
            "Usage: WindowsPerformanceChecks.exe OUTPUT_PARENT [--report NEW_REPORT_FILE]");
        const auto binary = self();
        folder = bw::unique_directory(argv[1], L"performance-native-checks");
        bw::Cancel cancel{false};
        auto save = [&](const wchar_t* name, const bw::ProcessPerformance& value) {
            observations.push_back(observation(name, value));
            has_active = false; active_membership.clear();
        };
        auto command = [&](const wchar_t* name, const std::wstring& mode, const std::wstring& code = L"0",
                const bw::Log& log = bw::Log{}, DWORD timeout = 10000, bw::ProcessPerformance* performance = nullptr) {
            const auto base = bw::join(folder, name);
            active_name = name; active_performance = {}; has_active = true; active_membership.clear();
            auto* measured = performance ? performance : &active_performance;
            try {
                std::vector<std::wstring> arguments{L"--child", mode, code};
                if (active_name == L"exec-success") arguments.push_back(L"--probe-job");
                const auto result = bw::execute(binary, arguments, base + L".stdout", base + L".stderr",
                    cancel, log, timeout, folder, measured);
                active_performance = *measured;
                return result;
            } catch (...) { active_performance = *measured; throw; }
        };
        auto result = command(L"exec-success", L"work");
        const auto membership_log = bw::read_file(bw::join(folder, L"exec-success.stderr"));
        const auto members_begin = membership_log.find("scope-members:");
        if (members_begin != std::string::npos) {
            const auto begin = members_begin + std::string("scope-members:").size();
            const auto end = membership_log.find('\n', begin);
            active_membership = membership_log.substr(begin, end == std::string::npos ? end : end - begin);
        }
        require(!result.exit_code && !result.cancelled && !result.performance.pipeline, "Exec outcome changed");
        require(!active_membership.empty() && membership_log.find("scope-count:") == 0 &&
            active_membership.find("\"own_pid_found\":true") != std::string::npos, "Immediate-job membership did not contain the fixture process");
        const auto member_count = std::stoul(membership_log.substr(std::string("scope-count:").size()));
        require(member_count > 0 && member_count <= result.performance.processes_total,
            "Accounting omitted a process independently observed in the command's immediate job");
        require(bw::read_file(bw::join(folder, L"exec-success.stdout")) == "measured output\n", "Exec output changed");
        measured(result.performance, 1, true); save(L"exec-success", result.performance);
        result = command(L"exec-failure", L"work", L"17");
        require(result.exit_code == 17 && !result.cancelled, "Exec failure was hidden");
        measured(result.performance, 1, true); save(L"exec-failure", result.performance);

        auto pipe = [&](const wchar_t* name, const std::wstring& producer, const std::wstring& sink,
                const std::wstring& code = L"0", const bw::Log& log = bw::Log{}, DWORD timeout = 10000,
                bw::ProcessPerformance* performance = nullptr) {
            const auto base = bw::join(folder, name);
            active_name = name; active_performance = {}; has_active = true; active_membership.clear();
            auto* measured = performance ? performance : &active_performance;
            try {
                const auto result = bw::execute_pipeline(binary, {L"--child", producer, code}, binary, {L"--child", sink},
                    base + L".stdout", base + L".producer.stderr", base + L".sink.stderr",
                    cancel, log, timeout, folder, measured);
                active_performance = *measured;
                return result;
            } catch (...) { active_performance = *measured; throw; }
        };
        auto piped = pipe(L"pipe-success", L"work", L"sink");
        require(!piped.producer_exit_code && !piped.sink_exit_code && !piped.cancelled && piped.performance.pipeline,
            "Pipeline outcome changed");
        require(bw::read_file(bw::join(folder, L"pipe-success.stdout")) == "measured output\n", "Pipe bytes changed");
        measured(piped.performance, 2, true); save(L"pipe-success", piped.performance);
        piped = pipe(L"pipe-failure", L"work", L"sink", L"17");
        require(piped.producer_exit_code == 17 && !piped.cancelled, "Pipeline failure was hidden");
        measured(piped.performance, 2, true); save(L"pipe-failure", piped.performance);

        result = command(L"exec-cancel", L"wait", L"0", [&](const std::wstring& line) {
            if (line == L"waiting") cancel.store(true);
        });
        require(result.cancelled && result.exit_code, "Exec cancellation changed");
        measured(result.performance, 1); save(L"exec-cancel", result.performance); cancel.store(false);
        bool producer_waiting = false, sink_waiting = false;
        piped = pipe(L"pipe-cancel", L"wait", L"wait", L"0", [&](const std::wstring& line) {
            producer_waiting = producer_waiting || line == L"[producer] waiting";
            sink_waiting = sink_waiting || line == L"[sink] waiting";
            if (producer_waiting && sink_waiting) cancel.store(true);
        });
        require(producer_waiting && sink_waiting && piped.cancelled && piped.producer_exit_code && piped.sink_exit_code,
            "Pipeline cancellation changed");
        measured(piped.performance, 2); save(L"pipe-cancel", piped.performance); cancel.store(false);

        bw::ProcessPerformance timeout;
        bool threw = false;
        try { (void)command(L"exec-timeout", L"wait", L"0", {}, 100, &timeout); }
        catch (const std::exception& error) { threw = std::string(error.what()).find("time limit") != std::string::npos; }
        require(threw, "Exec timeout no longer throws"); measured(timeout, 1); save(L"exec-timeout", timeout);
        threw = false;
        try { (void)pipe(L"pipe-timeout", L"wait", L"wait", L"0", {}, 100, &timeout); }
        catch (const std::exception& error) { threw = std::string(error.what()).find("time limit") != std::string::npos; }
        require(threw, "Pipeline timeout no longer throws"); measured(timeout, 2); save(L"pipe-timeout", timeout);

        bw::ProcessPerformance interrupted_exec;
        threw = false;
        try {
            (void)command(L"exec-observer-exception", L"wait", L"0", [&](const std::wstring& line) {
                if (line == L"waiting") throw std::runtime_error("deliberate observer failure");
            }, 10000, &interrupted_exec);
        } catch (const std::exception& error) {
            threw = std::string(error.what()) == "deliberate observer failure";
        }
        require(threw && interrupted_exec.launched && interrupted_exec.accounting_available &&
            interrupted_exec.memory_available && interrupted_exec.processes_total >= 1 && interrupted_exec.processes_active >= 1,
            "Exec exception discarded the live child's accounting");
        require(bw::process_performance_json(interrupted_exec).find("\"coverage\":\"partial\"") != std::string::npos,
            "Exec exception claimed complete coverage");
        save(L"exec-observer-exception", interrupted_exec);

        // The sink is suspended inside the job when producer creation fails.
        // This exercises exception unwinding before the ordinary exit snapshot.
        bw::ProcessPerformance interrupted;
        threw = false;
        const auto interrupted_base = bw::join(folder, L"producer-start-failure");
        try {
            (void)bw::execute_pipeline(bw::join(folder, L"missing.exe"), {}, binary, {L"--child", L"wait"},
                interrupted_base + L".stdout", interrupted_base + L".producer.stderr", interrupted_base + L".sink.stderr",
                cancel, {}, 10000, folder, &interrupted);
        } catch (const std::exception& error) {
            threw = std::string(error.what()).find("Cannot start pipeline executable") != std::string::npos;
        }
        active_name = L"pipeline-start-exception"; active_performance = interrupted; has_active = true;
        require(threw && interrupted.launched && interrupted.accounting_available && interrupted.memory_available &&
            interrupted.processes_total >= 1 && interrupted.processes_active >= 1,
            "Partial-start exception discarded the live sink's accounting");
        require(bw::process_performance_json(interrupted).find("\"coverage\":\"partial\"") != std::string::npos,
            "Partial-start exception claimed complete coverage");
        save(L"pipeline-start-exception", interrupted);

        result = command(L"live-descendant", L"detached");
        require(!result.exit_code && result.performance.processes_active > 0, "Live descendant was not reflected in coverage");
        measured(result.performance, 2);
        require(bw::process_performance_json(result.performance).find("\"coverage\":\"partial\"") != std::string::npos,
            "Live descendant incorrectly reported complete coverage");
        const auto pid = static_cast<DWORD>(std::stoul(bw::read_file(bw::join(folder, L"live-descendant.stdout"))));
        const auto descendant = OpenProcess(SYNCHRONIZE, FALSE, pid);
        if (descendant) {
            const auto stopped = WaitForSingleObject(descendant, 5000);
            CloseHandle(descendant);
            require(stopped == WAIT_OBJECT_0, "Existing job cleanup did not stop the descendant");
        } else require(GetLastError() == ERROR_INVALID_PARAMETER, "Cannot establish descendant cleanup");
        save(L"live-descendant-partial-coverage-and-cleanup", result.performance);

        cancel.store(true);
        result = command(L"not-started", L"work");
        require(result.cancelled && !result.performance.launched && !result.performance.wall_available,
            "Cancelled-before-start execution fabricated observations");
        const auto absent = bw::process_performance_json(result.performance);
        require(absent.find("\"user_cpu_seconds\":null") != std::string::npos &&
            absent.find("\"peak_job_memory_bytes\":null") != std::string::npos &&
            absent.find("\"coverage\":\"not-started\"") != std::string::npos, "Unavailable values were not null");
        save(L"cancel-before-start", result.performance); cancel.store(false);

        bw::ProcessPerformance unavailable; unavailable.launched = true;
        { bw::JobPerformanceCapture invalid(INVALID_HANDLE_VALUE, unavailable); invalid.capture(); }
        active_name = L"unavailable-query"; active_performance = unavailable; has_active = true;
        require(!unavailable.accounting_available && !unavailable.memory_available &&
            unavailable.accounting_error == ERROR_INVALID_HANDLE && unavailable.memory_error == ERROR_INVALID_HANDLE,
            "Unavailable counters were silently reported as zero");
        const auto invalid_json = bw::process_performance_json(unavailable);
        require(invalid_json.find("\"user_cpu_seconds\":null") != std::string::npos &&
            invalid_json.find("\"peak_job_memory_bytes\":null") != std::string::npos &&
            invalid_json.find("\"coverage\":\"unavailable\"") != std::string::npos, "Failed queries fabricated metrics");
        save(L"unavailable-query", unavailable);

        bw::ProcessPerformance decimal; decimal.launched = true; decimal.accounting_available = true; decimal.user_ticks = 1234567;
        const auto previous = std::locale();
        std::locale::global(std::locale(previous, new CommaDecimal));
        const auto locale_json = bw::process_performance_json(decimal);
        std::locale::global(previous);
        active_name = L"locale-independent-json"; active_performance = decimal; has_active = true;
        require(locale_json.find("\"user_cpu_seconds\":0.1234567") != std::string::npos, "Locale corrupted JSON CPU seconds");
        save(L"locale-independent-json", decimal);

        write_report(report_json());
        std::wprintf(L"PASS: %zu native Windows performance checks. Results: %ls\n", observations.size(), folder.c_str());
        return 0;
    } catch (const std::exception& error) {
        try { write_report(report_json(bw::utf16(error.what()))); }
        catch (const std::exception& report_error) { std::fprintf(stderr, "Cannot retain failed report: %s\n", report_error.what()); }
        std::fprintf(stderr, "FAIL: %s\n", error.what()); return 1;
    }
}
