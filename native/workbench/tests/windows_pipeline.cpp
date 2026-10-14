// Native Windows companion for the exact production pipeline executor.
// Build using tests/build_windows_pipeline.sh; run its .exe on Windows.
#include "workbench.h"
#include <array>
#include <cstdio>
#include <stdexcept>

namespace {
constexpr size_t TOTAL = 2 * 1024 * 1024;
const std::wstring marker = L"literal & %TEMP% {output:x} \u00e9\u0394 \\\" end\\";
bool write(HANDLE handle, const char* bytes, DWORD size) {
    while (size) {
        DWORD count = 0;
        if (!WriteFile(handle, bytes, size, &count, nullptr) || !count) return false;
        bytes += count; size -= count;
    }
    return true;
}
bool diagnostics(char value) {
    std::array<char, 8192> bytes{};
    bytes.fill(value); bytes.back() = '\n';
    for (int i = 0; i < 32; ++i)
        if (!write(GetStdHandle(STD_ERROR_HANDLE), bytes.data(), static_cast<DWORD>(bytes.size()))) return false;
    return true;
}
char pattern(size_t offset) { return static_cast<char>((offset * 19 + 7) & 255); }
int child(int argc, wchar_t** argv) {
    const std::wstring mode = argv[2];
    if (mode == L"wait") {
        if (!write(GetStdHandle(STD_ERROR_HANDLE), "waiting\n", 8)) return 50;
        Sleep(INFINITE); return 51;
    }
    if (mode == L"sink-fail") return 23;
    if (mode == L"producer" || mode == L"producer-fail") {
        if (argc != 4 || argv[3] != marker) return 61;
        if (!diagnostics('P')) return 62;
        std::array<char, 8192> bytes{};
        for (size_t offset = 0; offset < TOTAL; offset += bytes.size()) {
            for (size_t i = 0; i < bytes.size(); ++i) bytes[i] = pattern(offset + i);
            if (!write(GetStdHandle(STD_OUTPUT_HANDLE), bytes.data(), static_cast<DWORD>(bytes.size()))) return 31;
        }
        return mode == L"producer-fail" ? 17 : 0;
    }
    if (mode == L"sink") {
        if (!diagnostics('S')) return 63;
        std::array<char, 8192> bytes{};
        size_t offset = 0;
        for (;;) {
            DWORD size = 0;
            if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), bytes.data(), static_cast<DWORD>(bytes.size()), &size, nullptr)) {
                if (GetLastError() == ERROR_BROKEN_PIPE) break;
                return 64;
            }
            if (!size) break;
            for (DWORD i = 0; i < size; ++i) if (bytes[i] != pattern(offset + i)) return 65;
            if (!write(GetStdHandle(STD_OUTPUT_HANDLE), bytes.data(), size)) return 66;
            offset += size;
        }
        return offset == TOTAL ? 0 : 67;
    }
    return 68;
}
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::wstring self() {
    std::vector<wchar_t> path(32768);
    DWORD size = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    require(size && size < path.size(), "Cannot find test executable");
    return std::wstring(path.data(), size);
}
} // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc >= 3 && std::wstring(argv[1]) == L"--child") return child(argc, argv);
    try {
        require(argc == 1 || argc == 2 || (argc == 4 && std::wstring(argv[2]) == L"--report"),
                "Usage: WindowsPipelineChecks.exe [OUTPUT_PARENT [--report NEW_REPORT_FILE]]");
        const auto binary = self();
        const auto parent = argc >= 2 ? std::wstring(argv[1]) : bw::executable_folder();
        const auto folder = bw::unique_directory(parent, L"pipeline-native-checks");
        unsigned passed = 0;
        auto check = [&](const wchar_t* name, const std::wstring& producer_mode, const std::wstring& sink_mode,
                         bw::Cancel& cancel, DWORD timeout, const bw::Log& log = {}) {
            const auto base = bw::join(folder, name);
            return bw::execute_pipeline(binary, {L"--child", producer_mode, marker},
                binary, {L"--child", sink_mode}, base + L".stdout", base + L".producer.stderr",
                base + L".sink.stderr", cancel, log, timeout, folder);
        };
        bw::Cancel cancel{false};
        auto result = check(L"success with spaces \u00e9\u0394", L"producer", L"sink", cancel, 10000);
        require(!result.cancelled && !result.producer_exit_code && !result.sink_exit_code, "Pipeline success codes failed");
        auto output = bw::read_file(bw::join(folder, L"success with spaces \u00e9\u0394.stdout"));
        require(output.size() == TOTAL, "Streaming output size differs");
        for (size_t i = 0; i < output.size(); ++i) require(output[i] == pattern(i), "Streaming output differs");
        require(bw::read_file(bw::join(folder, L"success with spaces \u00e9\u0394.producer.stderr")).size() == 32 * 8192,
                "Producer stderr was truncated");
        require(bw::read_file(bw::join(folder, L"success with spaces \u00e9\u0394.sink.stderr")).size() == 32 * 8192,
                "Sink stderr was truncated");
        ++passed;
        result = check(L"producer-fails", L"producer-fail", L"sink", cancel, 10000);
        require(!result.cancelled && result.producer_exit_code == 17, "Producer failure was hidden by sink success");
        ++passed;
        result = check(L"sink-fails", L"producer", L"sink-fail", cancel, 10000);
        require(!result.cancelled && result.sink_exit_code == 23 && result.producer_exit_code != 0,
                "Sink failure did not stop producer or preserve its status");
        ++passed;
        bool producer_waiting = false, sink_waiting = false;
        bw::Log cancellation = [&](const std::wstring& line) {
            producer_waiting = producer_waiting || line == L"[producer] waiting";
            sink_waiting = sink_waiting || line == L"[sink] waiting";
            if (producer_waiting && sink_waiting) cancel.store(true);
        };
        result = check(L"cancel-both", L"wait", L"wait", cancel, 10000, cancellation);
        require(producer_waiting && sink_waiting && result.cancelled && result.producer_exit_code && result.sink_exit_code,
                "Cancellation did not stop both running children");
        ++passed;
        cancel.store(false);
        bool timeout_threw = false;
        try { (void)check(L"timeout", L"wait", L"wait", cancel, 100); }
        catch (const std::exception& error) { timeout_threw = std::string(error.what()).find("time limit") != std::string::npos; }
        require(timeout_threw, "Timeout was not reported as an exception");
        ++passed;
        const auto sentinel = bw::join(folder, L"exists.stdout");
        bw::write_file_new(sentinel, "keep this existing file\n");
        bool protected_output = false;
        try { (void)check(L"exists", L"producer", L"sink", cancel, 10000); }
        catch (const std::exception&) { protected_output = true; }
        require(protected_output && bw::read_file(sentinel) == "keep this existing file\n", "Existing output was overwritten");
        ++passed;
        const auto report = "{\"schema_version\":1,\"application_version\":" + bw::json_string(bw::APP_VERSION) +
            ",\"native_windows_execution\":true,\"folder\":" + bw::json_string(folder) +
            ",\"passed\":" + std::to_string(passed) + ",\"failed\":0," +
            "\"checks\":[\"binary-stream-and-diagnostics\",\"producer-failure\",\"sink-failure\","
            "\"cancel-both\",\"timeout\",\"preserve-existing-output\"]}\n";
        bw::write_file_new(bw::join(folder, L"pipeline-validation.json"), report);
        if (argc == 4) bw::write_file_new(argv[3], report);
        std::wprintf(L"PASS: %u native Windows pipeline checks. Results: %ls\n", passed, folder.c_str());
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL: %s\n", error.what());
        return 1;
    }
}
