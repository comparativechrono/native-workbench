#include "workbench.h"
#include <shellapi.h>
#include <algorithm>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

namespace bw {
namespace {
struct Check {
    std::wstring name, error;
    bool passed = false;
    ULONGLONG elapsed_ms = 0;
};
struct Input {
    std::wstring path, before, after;
};
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
std::wstring exception_text(const std::exception& e) {
    try { return utf16(e.what()); }
    catch (...) { return L"An error occurred; its message could not be decoded as UTF-8."; }
}

// A deliberately small, strict parser for a flat JSON object of unsigned
// statistics. Duplicate keys, overflowing values and trailing text are errors.
std::map<std::string, uint64_t> statistics(const std::string& s) {
    size_t p = 0;
    auto space = [&] {
        while (p < s.size() && (s[p] == ' ' || s[p] == '\t' || s[p] == '\r' || s[p] == '\n')) ++p;
    };
    auto take = [&](char c) {
        space();
        require(p < s.size() && s[p++] == c, "Malformed statistics JSON");
    };
    std::map<std::string, uint64_t> out;
    take('{');
    space();
    if (p < s.size() && s[p] == '}') ++p;
    else for (;;) {
        take('"');
        std::string key;
        while (p < s.size() && s[p] != '"') {
            char c = s[p++];
            require((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                    (c >= '0' && c <= '9') || c == '_', "Invalid statistics key");
            key += c;
        }
        take('"');
        take(':');
        space();
        require(p < s.size() && s[p] >= '0' && s[p] <= '9', "Expected unsigned statistic");
        bool zero = s[p] == '0';
        size_t start = p;
        uint64_t n = 0;
        while (p < s.size() && s[p] >= '0' && s[p] <= '9') {
            unsigned d = static_cast<unsigned>(s[p++] - '0');
            require(n <= (std::numeric_limits<uint64_t>::max() - d) / 10, "Statistic overflow");
            n = n * 10 + d;
        }
        require(!zero || p == start + 1, "Leading zero in statistic");
        require(out.emplace(key, n).second, "Duplicate statistics key");
        space();
        require(p < s.size(), "Truncated statistics JSON");
        if (s[p] == '}') { ++p; break; }
        take(',');
    }
    space();
    require(p == s.size(), "Trailing text after statistics JSON");
    return out;
}
void expect_statistics(const std::wstring& path, const std::map<std::string, uint64_t>& expected) {
    require(statistics(read_file(path)) == expected, "Statistics differ from independent expected values");
}

struct Json {
    enum Kind { Null, String, Number, Boolean, Array, Object } kind = Null;
    std::string text;
    std::map<std::string, Json> object;
    std::vector<Json> array;
    const Json& member(const std::string& key) const {
        require(kind == Object, "Expected a JSON object");
        auto found = object.find(key);
        require(found != object.end(), "Required run-report field is missing");
        return found->second;
    }
};
// Parse the entire run report, so a field-like substring in a log or pathname
// cannot satisfy the manifest checks. Reports are small and depth is bounded.
Json parse_json(const std::string& source) {
    size_t p = 0;
    auto space = [&] {
        while (p < source.size() && (source[p] == ' ' || source[p] == '\t' ||
               source[p] == '\r' || source[p] == '\n')) ++p;
    };
    auto take = [&](char c) {
        space();
        require(p < source.size() && source[p++] == c, "Invalid run-report JSON punctuation");
    };
    auto hex4 = [&] {
        unsigned n = 0;
        for (unsigned i = 0; i < 4; ++i) {
            require(p < source.size(), "Truncated JSON Unicode escape");
            const char c = source[p++];
            unsigned d = c >= '0' && c <= '9' ? unsigned(c - '0') :
                         c >= 'a' && c <= 'f' ? unsigned(c - 'a' + 10) :
                         c >= 'A' && c <= 'F' ? unsigned(c - 'A' + 10) : 16;
            require(d < 16, "Invalid JSON Unicode escape");
            n = n * 16 + d;
        }
        return n;
    };
    auto string = [&] {
        take('"');
        std::string out;
        for (;;) {
            require(p < source.size(), "Unterminated JSON string");
            unsigned char c = static_cast<unsigned char>(source[p++]);
            if (c == '"') break;
            require(c >= 32, "Unescaped JSON control character");
            if (c != '\\') { out += static_cast<char>(c); continue; }
            require(p < source.size(), "Truncated JSON escape");
            c = static_cast<unsigned char>(source[p++]);
            if (c == '"' || c == '\\' || c == '/') out += static_cast<char>(c);
            else if (c == 'b') out += '\b';
            else if (c == 'f') out += '\f';
            else if (c == 'n') out += '\n';
            else if (c == 'r') out += '\r';
            else if (c == 't') out += '\t';
            else {
                require(c == 'u', "Invalid JSON escape");
                unsigned cp = hex4();
                if (cp >= 0xd800 && cp <= 0xdbff) {
                    require(p + 1 < source.size() && source[p] == '\\' && source[p + 1] == 'u',
                            "Unpaired JSON Unicode surrogate");
                    p += 2;
                    unsigned low = hex4();
                    require(low >= 0xdc00 && low <= 0xdfff, "Invalid JSON Unicode surrogate pair");
                    cp = 0x10000 + (cp - 0xd800) * 1024 + low - 0xdc00;
                } else require(cp < 0xdc00 || cp > 0xdfff, "Unpaired JSON Unicode surrogate");
                if (cp < 0x80) out += static_cast<char>(cp);
                else if (cp < 0x800) {
                    out += static_cast<char>(0xc0 | (cp >> 6));
                    out += static_cast<char>(0x80 | (cp & 63));
                } else if (cp < 0x10000) {
                    out += static_cast<char>(0xe0 | (cp >> 12));
                    out += static_cast<char>(0x80 | ((cp >> 6) & 63));
                    out += static_cast<char>(0x80 | (cp & 63));
                } else {
                    out += static_cast<char>(0xf0 | (cp >> 18));
                    out += static_cast<char>(0x80 | ((cp >> 12) & 63));
                    out += static_cast<char>(0x80 | ((cp >> 6) & 63));
                    out += static_cast<char>(0x80 | (cp & 63));
                }
            }
        }
        (void)utf16(out); // reject malformed UTF-8 in literal string bytes
        return out;
    };
    std::function<Json(unsigned)> value = [&](unsigned depth) -> Json {
        require(depth < 64, "Excessively nested run-report JSON");
        space();
        require(p < source.size(), "Truncated run-report JSON");
        Json v;
        char c = source[p];
        if (c == '"') { v.kind = Json::String; v.text = string(); }
        else if (c == '{') {
            v.kind = Json::Object; ++p; space();
            if (p < source.size() && source[p] == '}') ++p;
            else for (;;) {
                std::string key = string(); take(':');
                require(v.object.emplace(key, value(depth + 1)).second, "Duplicate run-report JSON key");
                space(); require(p < source.size(), "Truncated JSON object");
                if (source[p] == '}') { ++p; break; }
                take(',');
            }
        } else if (c == '[') {
            v.kind = Json::Array; ++p; space();
            if (p < source.size() && source[p] == ']') ++p;
            else for (;;) {
                v.array.push_back(value(depth + 1));
                space(); require(p < source.size(), "Truncated JSON array");
                if (source[p] == ']') { ++p; break; }
                take(',');
            }
        } else if (c == 'n' || c == 't' || c == 'f') {
            const std::string literal = c == 'n' ? "null" : c == 't' ? "true" : "false";
            require(source.compare(p, literal.size(), literal) == 0, "Invalid JSON literal");
            p += literal.size();
            v.kind = c == 'n' ? Json::Null : Json::Boolean;
            v.text = literal;
        } else {
            const size_t start = p;
            if (source[p] == '-') ++p;
            require(p < source.size(), "Truncated JSON number");
            if (source[p] == '0') ++p;
            else {
                require(source[p] >= '1' && source[p] <= '9', "Invalid JSON number");
                while (p < source.size() && source[p] >= '0' && source[p] <= '9') ++p;
            }
            auto digits = [&] {
                const size_t first = p;
                while (p < source.size() && source[p] >= '0' && source[p] <= '9') ++p;
                require(p != first, "Expected JSON numeric digits");
            };
            if (p < source.size() && source[p] == '.') { ++p; digits(); }
            if (p < source.size() && (source[p] == 'e' || source[p] == 'E')) {
                ++p;
                if (p < source.size() && (source[p] == '+' || source[p] == '-')) ++p;
                digits();
            }
            v.kind = Json::Number; v.text = source.substr(start, p - start);
        }
        return v;
    };
    Json root = value(0);
    space();
    require(p == source.size(), "Trailing text after run-report JSON");
    return root;
}

void expect_twenty_mapped(const std::wstring& path) {
    std::istringstream sam(read_file(path));
    std::string line;
    std::map<std::string, unsigned> observed;
    unsigned count = 0;
    while (std::getline(sam, line)) {
        if (line.empty() || line[0] == '@') continue;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::istringstream fields(line);
        std::string name, flag_text, reference, position;
        require(static_cast<bool>(std::getline(fields, name, '\t')) &&
                static_cast<bool>(std::getline(fields, flag_text, '\t')) &&
                static_cast<bool>(std::getline(fields, reference, '\t')) &&
                static_cast<bool>(std::getline(fields, position, '\t')), "Malformed SAM record");
        size_t used = 0;
        unsigned long flag = std::stoul(flag_text, &used);
        require(used == flag_text.size() && (flag & 4) == 0 && reference == "reference",
                "Unexpected unmapped or wrong-reference alignment");
        used = 0;
        const unsigned long start = std::stoul(position, &used);
        require(start > 0 && used == position.size(), "Invalid alignment position");
        ++observed[name]; ++count;
    }
    require(count == 20 && observed.size() == 20, "Expected exactly twenty mapped example reads");
    for (unsigned i = 0; i < 20; ++i)
        require(observed["read" + std::to_string(i)] == 1, "An expected read is missing or duplicated");
}

std::string utc_now() {
    SYSTEMTIME t{};
    GetSystemTime(&t);
    char b[40];
    std::snprintf(b, sizeof(b), "%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",
                  t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    return b;
}
std::string os_json() {
    OSVERSIONINFOW v{};
    v.dwOSVersionInfoSize = sizeof(v);
    using RtlGetVersionFn = LONG(WINAPI*)(OSVERSIONINFOW*);
    HMODULE module = GetModuleHandleW(L"ntdll.dll");
    auto rtl = module ? reinterpret_cast<RtlGetVersionFn>(GetProcAddress(module, "RtlGetVersion")) : nullptr;
    bool known = rtl && rtl(&v) == 0;
    SYSTEM_INFO si{};
    GetNativeSystemInfo(&si);
    std::wstring arch = L"unknown";
    if (si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_AMD64) arch = L"x86-64";
    else if (si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_ARM64) arch = L"ARM64";
    else if (si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_INTEL) arch = L"x86";
    std::ostringstream s;
    s << "{\"name\":\"Windows\",\"version_source\":\"RtlGetVersion\",\"version\":";
    if (known) s << '"' << v.dwMajorVersion << '.' << v.dwMinorVersion << '.' << v.dwBuildNumber << '"';
    else s << "null";
    s << ",\"native_architecture\":" << json_string(arch)
      << ",\"application_architecture\":\"x86-64\"}";
    return s.str();
}
std::string report_json(const Pack& pack, const std::vector<Check>& checks,
                        const std::vector<Input>& inputs, bool cancelled, ULONGLONG elapsed_ms) {
    unsigned passed = 0;
    for (const auto& c : checks) if (c.passed) ++passed;
    std::ostringstream s;
    s << "{\n  \"kind\": \"native Windows installation validation\",\n"
      << "  \"utc\": \"" << utc_now() << "\",\n"
      << "  \"application_version\": " << json_string(APP_VERSION) << ",\n"
      << "  \"os\": " << os_json() << ",\n"
      << "  \"pack\": {\"id\":" << json_string(pack.id)
      << ",\"version\":" << json_string(pack.version) << ",\"verified_before_execution\":true,\"tools\":[";
    const Tool* tools[] = {&pack.fastq, &pack.seqtk, &pack.minimap};
    for (size_t i = 0; i < 3; ++i) {
        if (i) s << ',';
        s << "{\"id\":" << json_string(tools[i]->id) << ",\"version\":" << json_string(tools[i]->version)
          << ",\"sha256\":" << json_string(tools[i]->sha256) << '}';
    }
    s << "]},\n  \"cancelled\": " << (cancelled ? "true" : "false")
      << ",\n  \"elapsed_ms\": " << elapsed_ms << ",\n  \"passed\": " << passed
      << ",\n  \"failed\": " << checks.size() - passed << ",\n  \"checks\": [\n";
    for (size_t i = 0; i < checks.size(); ++i) {
        const auto& c = checks[i];
        if (i) s << ",\n";
        s << "    {\"name\":" << json_string(c.name) << ",\"passed\":" << (c.passed ? "true" : "false")
          << ",\"elapsed_ms\":" << c.elapsed_ms;
        if (!c.error.empty()) s << ",\"error\":" << json_string(c.error);
        s << '}';
    }
    s << "\n  ],\n  \"inputs\": [\n";
    for (size_t i = 0; i < inputs.size(); ++i) {
        const auto& f = inputs[i];
        if (i) s << ",\n";
        s << "    {\"path\":" << json_string(f.path) << ",\"sha256_before\":" << json_string(f.before)
          << ",\"sha256_after\":";
        if (f.after.empty()) s << "null"; else s << json_string(f.after);
        s << '}';
    }
    s << "\n  ]\n}\n";
    return s.str();
}

void quote_roundtrips() {
    const std::vector<std::wstring> cases = {
        L"", L"plain", L"two words", L"a\tb", L"\"", L"embedded\"quote", L"tail\\",
        L"tail with spaces\\", L"a\\\"b", L"a\\\\\"b", L"\\\\", L"\u00e9\u0394",
        L"%TEMP% & echo > output", L"semi;colon", L"line\nbreak"
    };
    std::wstring command = L"test.exe";
    for (const auto& arg : cases) command += L" " + quote_argument(arg);
    int count = 0;
    LPWSTR* parsed = CommandLineToArgvW(command.c_str(), &count);
    require(parsed != nullptr, "CommandLineToArgvW failed");
    bool equal = count == static_cast<int>(cases.size() + 1);
    if (equal) for (size_t i = 0; i < cases.size(); ++i) if (parsed[i + 1] != cases[i]) equal = false;
    LocalFree(parsed);
    require(equal, "Windows argument quoting roundtrip failed");
    bool rejected = false;
    try { quote_argument(std::wstring(L"a\0b", 3)); }
    catch (const std::exception&) { rejected = true; }
    require(rejected, "Embedded NUL argument was accepted");
    // These only normalize path strings; no drive or network share is opened.
    require(native_path(L"C:/alpha/../beta/file.txt") == L"\\\\?\\C:\\beta\\file.txt",
            "Local extended-length path normalization failed");
    require(native_path(L"\\\\server\\share\\file") == L"\\\\?\\UNC\\server\\share\\file",
            "UNC extended-length path normalization failed");
    const std::wstring extended = L"\\\\?\\C:\\beta\\file.txt";
    require(native_path(extended) == extended, "Extended-length local path normalization is not idempotent");
}

// Keep the child blocked in ReadFile on a local named pipe, then ask the same
// Job Object runner used by analyses to cancel it. This needs no helper binary,
// shell, policy change, wall-clock workload estimate or external data.
void active_cancellation(const Pack& pack, const std::wstring& folder, Cancel& user_cancel, const Log& log) {
    const std::wstring name = L"\\\\.\\pipe\\native-workbench-validation-" +
        std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(GetTickCount64());
    HANDLE pipe = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_OUTBOUND | FILE_FLAG_OVERLAPPED |
        FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_TYPE_BYTE | PIPE_WAIT, 1, 4096, 4096, 0, nullptr);
    require(pipe != INVALID_HANDLE_VALUE, "Could not create local cancellation-test pipe");
    HANDLE event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!event) { CloseHandle(pipe); throw std::runtime_error("Could not create pipe event"); }
    OVERLAPPED ov{};
    ov.hEvent = event;
    BOOL immediate = ConnectNamedPipe(pipe, &ov);
    DWORD error = immediate ? ERROR_SUCCESS : GetLastError();
    if (error == ERROR_PIPE_CONNECTED || immediate) SetEvent(event);
    else if (error != ERROR_IO_PENDING) {
        CloseHandle(event); CloseHandle(pipe);
        throw std::runtime_error("Could not await local test-pipe connection");
    }
    auto close_pipe = [&] {
        if (pipe == INVALID_HANDLE_VALUE) return;
        if (error == ERROR_IO_PENDING) {
            // Keep OVERLAPPED and its event alive until cancellation completes.
            CancelIoEx(pipe, &ov);
            DWORD transferred = 0;
            GetOverlappedResult(pipe, &ov, &transferred, TRUE);
        }
        CloseHandle(pipe);
        pipe = INVALID_HANDLE_VALUE;
    };
    Cancel local_cancel{false};
    std::atomic_bool done{false}, connected{false};
    std::thread trigger;
    try {
        trigger = std::thread([&] {
            const ULONGLONG started = GetTickCount64();
            while (!done.load()) {
                if (user_cancel.load()) { local_cancel.store(true); return; }
                if (WaitForSingleObject(event, 10) == WAIT_OBJECT_0) {
                    connected.store(true);
                    // Connection proves the process started and entered its
                    // input path; an open, unwritten pipe keeps it blocked.
                    local_cancel.store(true);
                    return;
                }
                if (GetTickCount64() - started > 10000) { local_cancel.store(true); return; }
            }
        });
        ProcessResult r = execute(pack.fastq.path, {L"stats", L"--input", name, L"--output", L"-"},
            join(folder, L"cancel.stdout.log"), join(folder, L"cancel.stderr.log"), local_cancel, log, 15000);
        done.store(true);
        trigger.join();
        close_pipe();
        CloseHandle(event); event = nullptr;
        check_cancel(user_cancel);
        require(connected.load(), "Test child did not connect to the local pipe");
        require(r.cancelled, "Active cancellation was not reported by the runner");
        require(read_file(join(folder, L"cancel.stdout.log")).empty(), "Cancelled process produced a completed result");
    } catch (...) {
        done.store(true);
        if (trigger.joinable()) trigger.join();
        close_pipe();
        if (event) CloseHandle(event);
        throw;
    }
}
} // namespace

Result validate_installation(const std::wstring& app_root, const Pack& pack, const std::wstring& output_parent,
                             Cancel& cancel, const Log& log, const Phase& phase) {
    Result result;
    const ULONGLONG started = GetTickCount64();
    std::vector<Check> checks;
    std::vector<Input> inputs;
    unsigned sequence = 0;
    auto check = [&](const std::wstring& name, const std::function<void()>& fn) {
        check_cancel(cancel);
        phase(name);
        Check c;
        c.name = name;
        const ULONGLONG beginning = GetTickCount64();
        try { fn(); check_cancel(cancel); c.passed = true; }
        catch (const std::exception& e) { c.error = exception_text(e); }
        catch (...) { c.error = L"Unknown validation error"; }
        c.elapsed_ms = GetTickCount64() - beginning;
        log((c.passed ? L"PASS: " : L"FAIL: ") + name + (c.error.empty() ? L"" : L" — " + c.error));
        checks.push_back(std::move(c));
        check_cancel(cancel);
    };
    auto keep_input = [&](const std::wstring& path, const std::string& data) {
        write_file_new(path, data);
        inputs.push_back({path, sha256_file(path, cancel), L""});
    };
    auto invoke = [&](const std::wstring& executable, const std::vector<std::wstring>& args) {
        const std::wstring stem = std::to_wstring(++sequence);
        const std::wstring out = join(result.folder, stem + L".stdout.log");
        const std::wstring err = join(result.folder, stem + L".stderr.log");
        ProcessResult r = execute(executable, args, out, err, cancel, log, 60000);
        check_cancel(cancel);
        require(!r.cancelled, "Process was unexpectedly cancelled");
        return std::make_pair(r, out);
    };
    auto workflow = [&](const Request& req) {
        Cancel local_cancel{false};
        std::atomic_bool done{false}, timed_out{false};
        std::thread monitor([&] {
            const ULONGLONG start = GetTickCount64();
            while (!done.load()) {
                if (cancel.load()) { local_cancel.store(true); return; }
                if (GetTickCount64() - start > 60000) {
                    timed_out.store(true); local_cancel.store(true); return;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(25));
            }
        });
        try {
            Result ran = run_job(req, local_cancel, log, phase);
            done.store(true); monitor.join();
            check_cancel(cancel);
            require(!timed_out.load(), "Workflow validation exceeded its sixty-second time limit");
            return ran;
        } catch (...) {
            done.store(true);
            if (monitor.joinable()) monitor.join();
            throw;
        }
    };
    try {
        phase(L"Verifying installed tool checksums");
        verify_pack(pack, cancel, log);
        check_cancel(cancel);
        result.folder = unique_directory(output_parent, L"windows-validation");
        checks.push_back({L"Installed tool checksums", L"", true, GetTickCount64() - started});
        log(L"Validation folder: " + result.folder);
        const std::string tiny = "@read1\nACGTN\n+\nIIIII\n@read2\naacg\n+\n!\"#$\n";
        const std::string reverse = "@read1\nNACGT\n+\nIIIII\n@read2\ncgtt\n+\n$#\"!\n";
        const auto tiny_path = join(result.folder, L"reads with spaces \u00e9\u0394.fastq");
        const auto stats_path = join(result.folder, L"statistics with spaces \u00e9\u0394.json");
        keep_input(tiny_path, tiny);
        const auto bad_path = join(result.folder, L"malformed.fastq");
        keep_input(bad_path, "@bad\nAC\n+\nI\n");
        check(L"Native tool version", [&] {
            auto r = invoke(pack.fastq.path, {L"--version"});
            require(r.first.exit_code == 0, "Version command failed");
            const auto version = read_file(r.second);
            require(version.find("bwfastq ") == 0 && version.find("ABI 1") != std::string::npos,
                    "Unexpected native tool version output");
        });
        check(L"Statistics and Unicode file paths", [&] {
            auto r = invoke(pack.fastq.path, {L"stats", L"--input", tiny_path, L"--output", stats_path,
                L"--threads", L"4"});
            require(r.first.exit_code == 0, "Statistics command failed");
            expect_statistics(stats_path, {{"records", 2}, {"bases", 9}, {"gc_bases", 4}, {"n_bases", 1},
                {"min_length", 4}, {"max_length", 5}, {"phred33_sum", 206}});
        });
        check(L"Existing output is protected", [&] {
            const auto out = join(result.folder, L"existing.json");
            const std::string sentinel = "Existing user data must remain unchanged.\n";
            write_file_new(out, sentinel);
            auto r = invoke(pack.fastq.path, {L"stats", L"--input", tiny_path, L"--output", out});
            require(r.first.exit_code != 0, "An existing output was accepted");
            require(read_file(out) == sentinel, "Existing output was modified");
        });
        check(L"Malformed FASTQ is rejected without publishing output", [&] {
            const auto out = join(result.folder, L"malformed.json");
            auto r = invoke(pack.fastq.path, {L"stats", L"--input", bad_path, L"--output", out});
            require(r.first.exit_code == 2, "Malformed input did not return exit code 2");
            require(!file_exists(out), "Failed statistics output was published");
            WIN32_FIND_DATAW data{};
            HANDLE found = FindFirstFileW(native_path(out + L".partial.*").c_str(), &data);
            if (found != INVALID_HANDLE_VALUE) { FindClose(found); throw std::runtime_error("Temporary output leaked"); }
            require(GetLastError() == ERROR_FILE_NOT_FOUND, "Could not inspect temporary output cleanup");
        });
        check(L"Long-read statistics with four workers requested", [&] {
            const auto in = join(result.folder, L"long.fastq");
            const auto out = join(result.folder, L"long.json");
            std::string bases;
            bases.reserve(100000);
            for (unsigned i = 0; i < 20000; ++i) bases += "ACGTN";
            keep_input(in, "@long\n" + bases + "\n+\n" + std::string(100000, 'I') + "\n");
            auto r = invoke(pack.fastq.path, {L"stats", L"--input", in, L"--output", out, L"--threads", L"4"});
            require(r.first.exit_code == 0, "Long-read statistics failed");
            expect_statistics(out, {{"records", 1}, {"bases", 100000}, {"gc_bases", 40000}, {"n_bases", 20000},
                {"min_length", 100000}, {"max_length", 100000}, {"phred33_sum", 4000000}});
        });
        check(L"Reverse complement and exact roundtrip", [&] {
            const auto one = join(result.folder, L"reverse.fastq");
            const auto two = join(result.folder, L"restored.fastq");
            auto r = invoke(pack.fastq.path, {L"revcomp", L"--input", tiny_path, L"--output", one});
            require(r.first.exit_code == 0, "Reverse complement failed");
            require(read_file(one) == reverse, "Reverse complement differs from independent expected bytes");
            r = invoke(pack.fastq.path, {L"revcomp", L"--input", one, L"--output", two});
            require(r.first.exit_code == 0 && read_file(two) == tiny, "Reverse-complement roundtrip changed bytes");
        });
        check(L"Portable seqtk matches independent expected output", [&] {
            auto r = invoke(pack.seqtk.path, {L"seq", L"-r", tiny_path});
            require(r.first.exit_code == 0, "Portable seqtk failed");
            require(read_file(r.second) == reverse, "Portable seqtk differs from independent expected bytes");
        });
        check(L"Portable minimap2 maps all twenty example reads", [&] {
            const auto ref = join(result.folder, L"example reference.fa");
            const auto reads = join(result.folder, L"example reads.fastq");
            keep_input(ref, read_file(join(join(app_root, L"examples"), L"reference.fa")));
            keep_input(reads, read_file(join(join(app_root, L"examples"), L"reads.fastq")));
            auto r = invoke(pack.minimap.path, {L"-a", L"-x", L"sr", L"-t", L"2", ref, reads});
            require(r.first.exit_code == 0, "Portable minimap2 failed");
            expect_twenty_mapped(r.second);
        });
        check(L"Windows argument quoting and path normalization", [&] { quote_roundtrips(); });
        check(L"Modified tool pack is rejected", [&] {
            const auto copy_root = unique_directory(result.folder, L"tampered-pack");
            const auto copy_bin = join(copy_root, L"bin");
            require(CreateDirectoryW(native_path(copy_bin).c_str(), nullptr) != 0, "Could not create copied pack directory");
            write_file_new(join(copy_root, L"pack.ini"), read_file(join(pack.root, L"pack.ini")));
            const wchar_t* names[] = {L"bwfastq.exe", L"seqtk.exe", L"minimap2.exe"};
            const Tool* originals[] = {&pack.fastq, &pack.seqtk, &pack.minimap};
            for (size_t i = 0; i < 3; ++i) {
                write_file_new(join(copy_bin, names[i]), read_file(originals[i]->path, 128 * 1024 * 1024));
            }
            Pack altered = load_pack(copy_root);
            HANDLE file = CreateFileW(native_path(altered.fastq.path).c_str(), FILE_APPEND_DATA, 0, nullptr,
                                      OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
            require(file != INVALID_HANDLE_VALUE, "Could not open copied binary for tamper test");
            DWORD written = 0;
            const char added = '\0';
            const BOOL appended = WriteFile(file, &added, 1, &written, nullptr);
            const BOOL flushed = FlushFileBuffers(file);
            const BOOL closed = CloseHandle(file);
            require(appended && written == 1 && flushed && closed, "Could not alter the copied executable");
            require(sha256_file(altered.fastq.path, cancel) != pack.fastq.sha256, "Tampering did not change hash");
            bool rejected = false;
            try { verify_pack(altered, cancel, [](const std::wstring&) {}); }
            catch (const std::exception& e) {
                check_cancel(cancel);
                std::string error = e.what();
                std::transform(error.begin(), error.end(), error.begin(), [](unsigned char c) { return char(std::tolower(c)); });
                rejected = error.find("hash") != std::string::npos || error.find("checksum") != std::string::npos ||
                           error.find("sha-256 mismatch") != std::string::npos;
            }
            require(rejected, "Modified executable was not rejected with a checksum error");
        });
        check(L"Failed workflow does not publish analysis results", [&] {
            Request req;
            req.pack = pack; req.kind = JobKind::Statistics; req.input = bad_path;
            req.output_folder = result.folder; req.threads = 2;
            Result failed = workflow(req);
            check_cancel(cancel);
            require(!failed.success && !failed.cancelled, "Invalid FASTQ workflow did not fail");
            require(failed.outputs.empty(), "Failed workflow advertised completed analysis outputs");
            require(!failed.folder.empty(), "Failure test did not reach job execution");
            require(!file_exists(join(failed.folder, L"reads.stats.json")) &&
                    !file_exists(join(failed.folder, L"reverse.fastq")) &&
                    !file_exists(join(failed.folder, L"alignment.sam")), "Failed workflow published analysis output");
        });
        check(L"Statistics and alignment workflow publishes correct results and report", [&] {
            const auto ref = join(result.folder, L"workflow reference.fa");
            const auto reads = join(result.folder, L"workflow reads.fastq");
            keep_input(ref, read_file(join(join(app_root, L"examples"), L"reference.fa")));
            keep_input(reads, read_file(join(join(app_root, L"examples"), L"reads.fastq")));
            Request req;
            req.pack = pack; req.kind = JobKind::StatisticsAndAlignment;
            req.input = reads; req.reference = ref; req.output_folder = result.folder; req.threads = 2;
            Result ran = workflow(req);
            require(ran.success && !ran.cancelled && ran.outputs.size() == 2,
                    "Combined workflow did not publish exactly two successful results");
            const auto stats = join(ran.folder, L"reads.stats.json");
            const auto sam = join(ran.folder, L"alignment.sam");
            require(std::find(ran.outputs.begin(), ran.outputs.end(), stats) != ran.outputs.end() &&
                    std::find(ran.outputs.begin(), ran.outputs.end(), sam) != ran.outputs.end(),
                    "Combined workflow advertised incorrect result paths");
            expect_statistics(stats, {{"records", 20}, {"bases", 3000}, {"gc_bases", 1522}, {"n_bases", 0},
                {"min_length", 150}, {"max_length", 150}, {"phred33_sum", 120000}});
            expect_twenty_mapped(sam);
            const Json report = parse_json(read_file(join(ran.folder, L"run.json")));
            const Json& status = report.member("status");
            require(status.kind == Json::String && status.text == "success", "Run report does not record success");
            require(report.member("input").member("sha256").kind == Json::Null &&
                    report.member("reference").member("sha256").kind == Json::Null,
                    "Uncomputed input hashes must be represented by explicit JSON null");
            const Json& stages = report.member("stages");
            require(stages.kind == Json::Array && stages.array.size() == 2, "Run report must contain two stages");
            for (const Json& stage : stages.array) {
                const Json& published = stage.member("published");
                const Json& hash = stage.member("output_sha256");
                const Json& output = stage.member("output");
                require(published.kind == Json::Boolean && published.text == "true" &&
                        hash.kind == Json::String && output.kind == Json::String,
                        "Run report has incomplete output provenance");
                require(sha256_file(utf16(output.text), cancel) == utf16(hash.text), "Reported output checksum is incorrect");
            }
        });
        check(L"FASTA workflow preserves format and independent expected bytes", [&] {
            const auto fasta = join(result.folder, L"short sequences.fasta");
            keep_input(fasta, ">one description\nACGTN\n>two\naacg\n");
            Request req;
            req.pack = pack; req.kind = JobKind::ReverseComplement;
            req.input = fasta; req.output_folder = result.folder; req.threads = 2;
            Result ran = workflow(req);
            const auto output = join(ran.folder, L"reverse.fasta");
            require(ran.success && !ran.cancelled && ran.outputs.size() == 1 && ran.outputs[0] == output,
                    "FASTA reverse complement was not published under reverse.fasta");
            require(!file_exists(join(ran.folder, L"reverse.fastq")), "FASTA output was mislabeled as FASTQ");
            require(read_file(output) == ">one description\nNACGT\n>two\ncgtt\n",
                    "FASTA reverse complement differs from independent expected bytes");
        });
        check(L"Tool pack import, long paths, discovery and duplicate version protection", [&] {
            const auto sandbox_app = unique_directory(result.folder, L"import-test-application");
            const auto expected_root = join(join(sandbox_app, L"packs"), pack.id + L"-" + pack.version);
            const auto source_manifest_hash = sha256_file(join(pack.root, L"pack.ini"), cancel);
            // Modify only a private source copy. Reproduce the MAX_PATH
            // regression even when the application starts from a short path.
            const auto source_app = unique_directory(result.folder, L"import-source-application");
            Pack source = import_pack(source_app, pack.root, cancel, log);
            std::wstring relative = join(L"licenses", L"native-workbench-path-regression");
            auto add_directory = [&](const std::wstring& path) {
                require(CreateDirectoryW(native_path(path).c_str(), nullptr) != 0,
                        "Could not create long-path regression fixture directory");
            };
            add_directory(join(source.root, relative));
            const std::wstring leaf = L"generated-path-copy-notice.txt";
            for (unsigned i = 0; ; ++i) {
                const auto source_length = join(join(source.root, relative), leaf).size();
                const auto destination_length = join(join(expected_root, relative), leaf).size();
                if (std::min(source_length, destination_length) >= 320) break;
                require(i < 8, "Could not construct bounded long-path fixture");
                relative = join(relative, L"path-segment-" + std::to_wstring(i) + L"-" + std::wstring(40, L'x'));
                add_directory(join(source.root, relative));
            }
            relative = join(relative, leaf);
            const auto source_notice = join(source.root, relative);
            const auto expected_notice = join(expected_root, relative);
            require(source_notice.size() > 260 && expected_notice.size() > 260,
                    "Import regression fixture did not exceed the legacy Windows path limit");
            const std::string notice =
                "Generated Native Workbench long-path copy fixture.\n"
                "This is test data, not a third-party license.\n"
                "Its bytes must survive import and duplicate-version rejection unchanged.\n";
            keep_input(source_notice, notice);
            const auto notice_hash = sha256_file(source_notice, cancel);
            log(L"Long-path import fixture: source " + std::to_wstring(source_notice.size()) +
                L" characters; destination " + std::to_wstring(expected_notice.size()) + L" characters.");
            Pack imported = import_pack(sandbox_app, source.root, cancel, log);
            require(imported.root == expected_root && imported.id == pack.id && imported.version == pack.version,
                    "Imported tool pack has incorrect destination or metadata");
            verify_pack(imported, cancel, log);
            require(read_file(expected_notice) == notice && sha256_file(expected_notice, cancel) == notice_hash,
                    "Long license-tree path did not copy with identical bytes and checksum");
            const Tool* originals[] = {&pack.fastq, &pack.seqtk, &pack.minimap};
            const Tool* copies[] = {&imported.fastq, &imported.seqtk, &imported.minimap};
            std::vector<std::wstring> before;
            for (unsigned i = 0; i < 3; ++i) {
                before.push_back(sha256_file(copies[i]->path, cancel));
                require(before.back() == originals[i]->sha256, "Imported executable differs from its source");
            }
            const auto manifest_hash = sha256_file(join(imported.root, L"pack.ini"), cancel);
            auto found = discover_packs(sandbox_app, log);
            require(found.size() == 1 && found[0].id == pack.id && found[0].version == pack.version &&
                    found[0].root == imported.root, "Imported pack was not discovered exactly once");
            bool duplicate_rejected = false;
            try { (void)import_pack(sandbox_app, source.root, cancel, log); }
            catch (const std::exception& e) {
                check_cancel(cancel);
                duplicate_rejected = std::string(e.what()).find("already installed") != std::string::npos;
            }
            require(duplicate_rejected, "Duplicate tool pack version was not rejected");
            for (unsigned i = 0; i < 3; ++i) {
                require(sha256_file(copies[i]->path, cancel) == before[i], "Duplicate import changed an installed executable");
                require(sha256_file(originals[i]->path, cancel) == originals[i]->sha256, "Import changed its source executable");
            }
            require(sha256_file(join(imported.root, L"pack.ini"), cancel) == manifest_hash &&
                    sha256_file(join(pack.root, L"pack.ini"), cancel) == source_manifest_hash,
                    "Import changed an existing or source manifest");
            require(read_file(expected_notice) == notice && sha256_file(expected_notice, cancel) == notice_hash &&
                    read_file(source_notice) == notice && sha256_file(source_notice, cancel) == notice_hash,
                    "Duplicate import changed the source or installed long-path fixture");
            verify_pack(imported, cancel, log);
        });
        check(L"Active process cancellation", [&] { active_cancellation(pack, result.folder, cancel, log); });
        check(L"All test input files remain unchanged", [&] {
            for (auto& f : inputs) {
                f.after = sha256_file(f.path, cancel);
                require(f.before == f.after, "A validation input file was modified");
            }
        });
        result.success = std::all_of(checks.begin(), checks.end(), [](const Check& c) { return c.passed; });
        unsigned passed = static_cast<unsigned>(std::count_if(checks.begin(), checks.end(), [](const Check& c) { return c.passed; }));
        result.message = std::to_wstring(passed) + L" of " + std::to_wstring(checks.size()) + L" checks passed.";
    } catch (const std::exception& e) {
        result.success = false;
        result.cancelled = cancel.load();
        result.message = result.cancelled ? L"Validation cancelled." : exception_text(e);
        log(result.message);
        if (!result.folder.empty()) checks.push_back({L"Validation completion", result.message, false, 0});
    } catch (...) {
        result.success = false;
        result.cancelled = cancel.load();
        result.message = L"Validation stopped with an unknown error.";
        if (!result.folder.empty()) checks.push_back({L"Validation completion", result.message, false, 0});
    }
    if (!result.folder.empty()) {
        try {
            const auto report = join(result.folder, L"windows-validation.json");
            write_file_new(report, report_json(pack, checks, inputs, result.cancelled, GetTickCount64() - started));
            result.outputs.push_back(report);
            log(L"Validation report saved: " + report);
        } catch (const std::exception& e) {
            result.success = false;
            result.message += L" Could not save the validation report: " + exception_text(e);
        }
    }
    return result;
}
} // namespace bw
