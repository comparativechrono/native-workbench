#include "workbench.h"
#include <shellapi.h>
#include <algorithm>
#include <chrono>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace bw {
namespace {
struct ValidationCheck {
    std::wstring name, error;
    bool passed = false;
    ULONGLONG elapsed_ms = 0;
};
struct TrackedInput { std::wstring path, before, after; };
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
std::wstring error_text(const std::exception& error) {
    try { return utf16(error.what()); }
    catch (...) { return L"An error message could not be decoded as UTF-8."; }
}
void log_line(const Log& log, const std::wstring& line) { if (log) log(line); }
void phase_line(const Phase& phase, const std::wstring& line) { if (phase) phase(line); }

const Tool& tool_named(const Pack& pack, const std::wstring& id) {
    const auto found = std::find_if(pack.tools.begin(), pack.tools.end(),
        [&](const Tool& tool) { return tool.id == id; });
    require(found != pack.tools.end(), "Required tool is absent from its pack");
    return *found;
}
const Workflow& workflow_named(const Pack& pack, const std::wstring& id) {
    const auto found = std::find_if(pack.workflows.begin(), pack.workflows.end(),
        [&](const Workflow& workflow) { return workflow.id == id; });
    require(found != pack.workflows.end(), "Required workflow is absent from its pack");
    return *found;
}
void verify_optional_pack_discovery(const std::wstring& app_root, const std::wstring& id,
                                   const std::vector<Pack>& discovered, const Cancel& cancel) {
    const auto parent = join(app_root, L"packs");
    WIN32_FIND_DATAW data{};
    HANDLE raw = FindFirstFileW(native_path(join(parent, id + L"-*")).c_str(), &data);
    if (raw == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND) return;
        throw std::runtime_error(utf8(L"Cannot inspect optional pack folders: " + windows_error()));
    }
    struct FindHandle { HANDLE value; ~FindHandle() { FindClose(value); } } found{raw};
    for (;;) {
        check_cancel(cancel);
        if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            const auto folder = join(parent, data.cFileName);
            const auto absolute = native_path(folder);
            const auto match = std::find_if(discovered.begin(), discovered.end(), [&](const Pack& pack) {
                return _wcsicmp(native_path(pack.root).c_str(), absolute.c_str()) == 0;
            });
            // A valid differently named pack may share this prefix (for
            // example fastp-custom). Its own integrity check still runs.
            if (match == discovered.end() || (match->id == id && match->format != 2))
                throw std::runtime_error(utf8(L"Installed optional pack folder was not discovered as a compatible pack: " + folder));
        }
        if (!FindNextFileW(raw, &data)) {
            if (GetLastError() != ERROR_NO_MORE_FILES)
                throw std::runtime_error(utf8(L"Cannot finish optional pack discovery: " + windows_error()));
            break;
        }
    }
}
void make_directory(const std::wstring& path) {
    require(CreateDirectoryW(native_path(path).c_str(), nullptr) != 0,
            "Could not create validation fixture directory");
}
bool nonempty_file(const std::wstring& path) {
    WIN32_FILE_ATTRIBUTE_DATA info{};
    require(GetFileAttributesExW(native_path(path).c_str(), GetFileExInfoStandard, &info) != 0,
            "A required output does not exist");
    return !(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
           (info.nFileSizeHigh != 0 || info.nFileSizeLow != 0);
}
void append_byte(const std::wstring& path) {
    HANDLE file = CreateFileW(native_path(path).c_str(), FILE_APPEND_DATA, 0, nullptr,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    require(file != INVALID_HANDLE_VALUE, "Could not open private executable copy for tampering");
    DWORD written = 0;
    const char byte = '\0';
    const BOOL wrote = WriteFile(file, &byte, 1, &written, nullptr);
    const BOOL flushed = FlushFileBuffers(file);
    const BOOL closed = CloseHandle(file);
    require(wrote && written == 1 && flushed && closed, "Could not modify private executable copy");
}
void replace_private_file(const std::wstring& path, const std::string& bytes) {
    // Only called for files in validation-owned copies, never installed packs.
    require(DeleteFileW(native_path(path).c_str()) != 0, "Could not replace a private validation fixture");
    write_file_new(path, bytes);
}
void parse_rejects(const std::wstring& text) {
    bool rejected = false;
    try { (void)parse_pack_text(text); }
    catch (const std::exception&) { rejected = true; }
    require(rejected, "An invalid pack manifest was accepted");
}
std::wstring inject_pack_key(const std::wstring& manifest, const std::wstring& line) {
    const size_t at = manifest.find(L"[pack]");
    require(at != std::wstring::npos, "Fixture manifest lacks [pack]");
    const size_t end = manifest.find(L'\n', at);
    require(end != std::wstring::npos, "Fixture manifest has a truncated pack section");
    std::wstring changed = manifest;
    changed.insert(end + 1, line + L"\n");
    return changed;
}
void quote_and_path_checks() {
    const std::vector<std::wstring> values = {L"", L"plain", L"two words", L"a\tb", L"\"",
        L"embedded\"quote", L"tail with spaces\\", L"a\\\"b", L"\\\\", L"\u00e9\u0394",
        L"%TEMP% & echo > output", L"semi;colon"};
    std::wstring command = L"test.exe";
    for (const auto& value : values) command += L" " + quote_argument(value);
    int count = 0;
    LPWSTR* parsed = CommandLineToArgvW(command.c_str(), &count);
    require(parsed != nullptr, "Windows argument parser failed");
    bool equal = count == static_cast<int>(values.size() + 1);
    if (equal) for (size_t i = 0; i < values.size(); ++i)
        if (parsed[i + 1] != values[i]) equal = false;
    LocalFree(parsed);
    require(equal, "Windows argument quoting did not preserve literal values");
    bool rejected = false;
    try { (void)quote_argument(std::wstring(L"a\0b", 3)); }
    catch (const std::exception&) { rejected = true; }
    require(rejected, "Embedded NUL in an argument was accepted");
    require(native_path(L"C:/alpha/../beta/file.txt") == L"\\\\?\\C:\\beta\\file.txt",
            "Extended local path normalization failed");
    require(native_path(L"\\\\server\\share\\file") == L"\\\\?\\UNC\\server\\share\\file",
            "Extended UNC path normalization failed");
}

std::set<std::string> variant_rows(const std::string& text, bool header_allowed) {
    std::istringstream source(text);
    std::set<std::string> rows;
    std::string line;
    while (std::getline(source, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty() || line[0] == '#') continue;
        if (header_allowed && line == "CHROM\tPOS\tREF\tALT\tGT") continue;
        std::istringstream record(line);
        std::vector<std::string> fields;
        std::string field;
        while (std::getline(record, field, '\t')) fields.push_back(field);
        require(fields.size() == 5, "Expected exactly CHROM, POS, REF, ALT and GT columns");
        require(std::all_of(fields.begin(), fields.end(), [](const std::string& value) {
            return !value.empty(); }), "Empty expected variant field");
        require(fields[1].find_first_not_of("0123456789") == std::string::npos &&
                fields[1] != "0", "Invalid variant position");
        require(rows.insert(line).second, "A variant row is duplicated");
    }
    return rows;
}
struct FastqRecord { std::string name, sequence, quality; };
std::vector<FastqRecord> four_line_fastq(const std::string& text) {
    std::istringstream source(text);
    std::vector<FastqRecord> records;
    auto line = [&](std::string& value) {
        const bool got = static_cast<bool>(std::getline(source, value));
        if (got && !value.empty() && value.back() == '\r') value.pop_back();
        return got;
    };
    std::string name, sequence, plus, quality;
    std::set<std::string> seen;
    while (line(name)) {
        require(line(sequence) && line(plus) && line(quality), "Truncated FASTQ validation output");
        require(!name.empty() && name[0] == '@' && plus == "+" && sequence.size() == quality.size(),
                "Invalid four-line FASTQ validation output");
        require(seen.insert(name).second, "Duplicate read name in FASTQ validation output");
        records.push_back({name, sequence, quality});
    }
    return records;
}
std::map<std::string, std::pair<std::string, std::string>> fastq_by_name(const std::vector<FastqRecord>& records) {
    std::map<std::string, std::pair<std::string, std::string>> result;
    for (const auto& record : records) result.emplace(record.name, std::make_pair(record.sequence, record.quality));
    return result;
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
Json parse_json_file(const std::wstring& path) {
    const auto bytes = read_file(path);
    try { return parse_json(bytes); }
    catch (const std::exception& error) {
        throw std::runtime_error(utf8(L"Cannot parse JSON file " + path + L": ") + error.what());
    }
}


std::string validation_report(const std::vector<ValidationCheck>& checks,
        const std::vector<TrackedInput>& inputs, const std::vector<Pack>& packs,
        bool cancelled, ULONGLONG elapsed_ms, const std::wstring& workflow_folder,
        const std::vector<std::pair<std::wstring, std::wstring>>& additional_runs) {
    const size_t passed = static_cast<size_t>(std::count_if(checks.begin(), checks.end(),
        [](const ValidationCheck& check) { return check.passed; }));
    std::ostringstream json;
    json << "{\n  \"schema_version\": 1,\n  \"application_version\": " << json_string(APP_VERSION)
         << ",\n  \"kind\": \"modular-installation-validation\",\n  \"cancelled\": "
         << (cancelled ? "true" : "false") << ",\n  \"elapsed_ms\": " << elapsed_ms
         << ",\n  \"passed\": " << passed << ",\n  \"failed\": " << checks.size() - passed
         << ",\n  \"pipeline_folder\": " << json_string(workflow_folder) << ",\n  \"packs\": [";
    for (size_t i = 0; i < packs.size(); ++i) {
        if (i) json << ',';
        const auto& pack = packs[i];
        json << "\n    {\"id\":" << json_string(pack.id) << ",\"version\":" << json_string(pack.version)
             << ",\"manifest_sha256\":" << json_string(pack.manifest_sha256)
             << ",\"runtime_asset_count\":" << pack.assets.size() << ",\"tools\":[";
        for (size_t j = 0; j < pack.tools.size(); ++j) {
            if (j) json << ',';
            const auto& tool = pack.tools[j];
            json << "{\"id\":" << json_string(tool.id) << ",\"version\":" << json_string(tool.version)
                 << ",\"sha256\":" << json_string(tool.sha256) << '}';
        }
        json << "]}";
    }
    json << "\n  ],\n  \"checks\": [";
    for (size_t i = 0; i < checks.size(); ++i) {
        if (i) json << ',';
        const auto& check = checks[i];
        json << "\n    {\"name\":" << json_string(check.name)
             << ",\"passed\":" << (check.passed ? "true" : "false")
             << ",\"elapsed_ms\":" << check.elapsed_ms << ",\"error\":" << json_string(check.error) << '}';
    }
    json << "\n  ],\n  \"additional_workflows\": [";
    for (size_t i = 0; i < additional_runs.size(); ++i) {
        if (i) json << ',';
        json << "\n    {\"check\":" << json_string(additional_runs[i].first)
             << ",\"folder\":" << json_string(additional_runs[i].second) << '}';
    }
    json << "\n  ],\n  \"inputs\": [";
    for (size_t i = 0; i < inputs.size(); ++i) {
        if (i) json << ',';
        const auto& input = inputs[i];
        json << "\n    {\"path\":" << json_string(input.path)
             << ",\"sha256_before\":" << json_string(input.before) << ",\"sha256_after\":";
        if (input.after.empty()) json << "null"; else json << json_string(input.after);
        json << '}';
    }
    json << "\n  ]\n}\n";
    return json.str();
}
} // namespace

Result validate_modular_installation(const std::wstring& app_root, const std::wstring& output_parent,
                                    Cancel& cancel, const Log& log, const Phase& phase) {
    Result result;
    const ULONGLONG started = GetTickCount64();
    std::vector<ValidationCheck> checks;
    std::vector<TrackedInput> inputs;
    std::vector<Pack> packs;
    std::wstring pipeline_folder;
    std::wstring research_pipeline_folder;
    Pack imported_trimming;
    std::vector<std::pair<std::wstring, std::wstring>> additional_runs;
    unsigned sequence = 0;
    auto check = [&](const std::wstring& name, const std::function<void()>& action) {
        check_cancel(cancel);
        phase_line(phase, name);
        ValidationCheck item;
        item.name = name;
        const ULONGLONG beginning = GetTickCount64();
        try { action(); check_cancel(cancel); item.passed = true; }
        catch (const std::exception& error) { item.error = error_text(error); }
        catch (...) { item.error = L"Unknown validation error."; }
        item.elapsed_ms = GetTickCount64() - beginning;
        log_line(log, (item.passed ? L"PASS: " : L"FAIL: ") + name +
            (item.error.empty() ? L"" : L" — " + item.error));
        checks.push_back(std::move(item));
        check_cancel(cancel);
    };
    auto pack_named = [&](const std::wstring& id) -> const Pack& {
        // Discovery sorts each ID by descending semantic version. Pack
        // versions are independent of the application release version.
        const auto found = std::find_if(packs.begin(), packs.end(),
            [&](const Pack& pack) { return pack.id == id && pack.format == 2; });
        require(found != packs.end(), "Required compatible format-2 pack is not installed");
        return *found;
    };
    auto has_pack = [&](const std::wstring& id) {
        return std::any_of(packs.begin(), packs.end(), [&](const Pack& pack) {
            return pack.id == id && pack.format == 2;
        });
    };
    auto track = [&](const std::wstring& path) {
        inputs.push_back({path, sha256_file(path, cancel), L""});
    };
    auto invoke = [&](const Tool& tool, const std::vector<std::wstring>& args) {
        const auto stem = std::to_wstring(++sequence);
        const auto output = join(result.folder, L"check-" + stem + L".stdout.txt");
        const auto error = join(result.folder, L"check-" + stem + L".stderr.txt");
        const auto process = execute(tool.path, args, output, error, cancel, log, 60000);
        check_cancel(cancel);
        require(!process.cancelled && process.exit_code == 0, "Validation tool invocation failed; inspect its stderr log");
        return output;
    };
    auto workflow = [&](const WorkflowRequest& request) {
        Cancel local_cancel{false};
        std::atomic_bool done{false}, timed_out{false};
        std::thread monitor([&] {
            const ULONGLONG beginning = GetTickCount64();
            while (!done.load()) {
                if (cancel.load()) { local_cancel.store(true); return; }
                if (GetTickCount64() - beginning > 180000) {
                    timed_out.store(true); local_cancel.store(true); return;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(25));
            }
        });
        try {
            auto ran = run_workflow(request, local_cancel, log, phase);
            done.store(true);
            monitor.join();
            check_cancel(cancel);
            require(!timed_out.load(), "Validation workflow exceeded its three-minute time limit");
            return ran;
        } catch (...) {
            done.store(true);
            if (monitor.joinable()) monitor.join();
            throw;
        }
    };
    auto expect_success = [&](const WorkflowRequest& request, const Result& ran, bool require_pipe = false) {
        require(ran.success && !ran.cancelled, "Workflow failed; inspect its run report and stage logs");
        const auto& definition = workflow_named(request.pack, request.workflow_id);
        std::set<std::wstring> expected_paths;
        for (const auto& output : definition.outputs) if (output.final) {
            const auto path = join(ran.folder, output.path);
            expected_paths.insert(path);
            require(file_exists(path), "A final workflow output is missing");
            if (output.nonempty) require(nonempty_file(path), "A required final workflow output is empty");
        }
        require(std::set<std::wstring>(ran.outputs.begin(), ran.outputs.end()) == expected_paths &&
                ran.outputs.size() == expected_paths.size(), "Workflow published incorrect final paths");
        const auto report = parse_json_file(join(ran.folder, L"run.json"));
        require(report.member("status").text == "success", "Successful workflow lacks successful provenance");
        const auto& steps = report.member("steps");
        require(steps.kind == Json::Array && steps.array.size() == definition.steps.size(),
                "Workflow report is missing declared steps");
        size_t pipes = 0;
        for (size_t i = 0; i < steps.array.size(); ++i) {
            const auto& step = steps.array[i];
            require(step.member("id").text == utf8(definition.steps[i].id) &&
                    step.member("status").text == "success", "A reported workflow step did not succeed");
            if (definition.steps[i].kind == L"exec" || definition.steps[i].kind == L"pipe")
                require(step.member("exit_code").kind == Json::Number && step.member("exit_code").text == "0",
                        "A successful executable step lacks a zero exit code");
            if (definition.steps[i].kind == L"pipe") {
                ++pipes;
                require(step.member("producer_exit_code").kind == Json::Number &&
                        step.member("producer_exit_code").text == "0" &&
                        step.member("sink_exit_code").kind == Json::Number &&
                        step.member("sink_exit_code").text == "0", "A streaming step did not verify both process exits");
            }
        }
        require(!require_pipe || pipes != 0, "Research alignment did not execute a streaming step");
        const auto& artifacts = report.member("artifacts");
        require(artifacts.kind == Json::Array && artifacts.array.size() == definition.outputs.size(),
                "Workflow report is missing declared artifact evidence");
        for (const auto& artifact : artifacts.array) {
            require(artifact.member("checked").text == "true" && artifact.member("sha256").kind == Json::String &&
                    sha256_file(utf16(artifact.member("path").text), cancel) == utf16(artifact.member("sha256").text),
                    "A reported artifact checksum differs from its bytes");
        }
        const auto& evidence = report.member("input_files");
        require(evidence.kind == Json::Array, "Workflow report lacks input integrity evidence");
        for (const auto& input : evidence.array) {
            const auto& before = input.member("sha256_before");
            const auto& after = input.member("sha256_after");
            require(before.kind == Json::String && after.kind == Json::String && before.text == after.text &&
                    input.member("after_check").text == "unchanged" &&
                    sha256_file(utf16(input.member("path").text), cancel) == utf16(after.text),
                    "Workflow report does not demonstrate unchanged input bytes");
        }
    };
    auto trimming_oracle = [&](const Pack& pack, const std::wstring& label) {
        const auto fixture = join(join(app_root, L"examples"), L"trimming-truth");
        const auto truth = parse_json(read_file(join(fixture, L"truth.json")));
        const auto& adapters = truth.member("adapters");
        require(adapters.kind == Json::Array && adapters.array.size() == 2 &&
                adapters.array[0].kind == Json::String && adapters.array[1].kind == Json::String,
                "Trimming truth fixture lacks two adapter sequences");
        for (const auto& name : {L"reads1.fastq", L"reads2.fastq", L"truth.json", L"expected-paired1.fastq",
                                L"expected-paired2.fastq", L"expected-rejected1.fastq", L"expected-rejected2.fastq"})
            track(join(fixture, name));
        WorkflowRequest request;
        request.pack = pack;
        request.workflow_id = L"cutadapt-paired";
        request.output_folder = result.folder;
        request.values = {{L"reads1", join(fixture, L"reads1.fastq")}, {L"reads2", join(fixture, L"reads2.fastq")},
            {L"adapter1", utf16(adapters.array[0].text)}, {L"adapter2", utf16(adapters.array[1].text)},
            {L"threads", L"2"}, {L"trim-quality", L"20"}, {L"min-length", L"50"},
            {L"trim-overlap", L"3"}, {L"trim-error", L"0.1"}};
        const auto ran = workflow(request);
        additional_runs.push_back({label, ran.folder});
        expect_success(request, ran);
        const std::vector<std::pair<std::wstring, std::wstring>> outputs = {
            {L"reads1.trimmed.fastq.gz", L"expected-paired1.fastq"},
            {L"reads2.trimmed.fastq.gz", L"expected-paired2.fastq"},
            {L"reads1.rejected.fastq.gz", L"expected-rejected1.fastq"},
            {L"reads2.rejected.fastq.gz", L"expected-rejected2.fastq"}};
        for (const auto& output : outputs) {
            const auto unpacked = invoke(tool_named(pack, L"python"), {L"-I", L"-B", L"-c",
                L"import gzip,sys;sys.stdout.buffer.write(gzip.open(sys.argv[1],'rb').read())", join(ran.folder, output.first)});
            require(read_file(unpacked) == read_file(join(fixture, output.second)),
                    "Cutadapt retained or rejected FASTQ differs from independent expected bytes");
        }
        const auto metrics = parse_json(read_file(join(ran.folder, L"trimming.json")));
        const auto& counts = metrics.member("read_counts");
        require(counts.member("input").text == "7" && counts.member("output").text == "4" &&
                counts.member("filtered").member("too_short").text == "3",
                "Cutadapt JSON does not record seven input pairs, four retained and three rejected");
    };
    try {
        result.folder = unique_directory(output_parent, L"windows-validation");
        log_line(log, L"Validation folder: " + result.folder);
        check(L"Discover core and research workflow packs", [&] {
            packs = discover_packs(app_root, log);
            for (const auto& id : {L"reads", L"align", L"bam", L"variants", L"variant-pipeline",
                                   L"trimming", L"bwa", L"research-variants"}) {
                const auto& pack = pack_named(id);
                require(pack.format == 2 && !pack.tools.empty() && !pack.workflows.empty(),
                        "A required pack lacks modular tools or workflows");
            }
            for (const auto& id : {L"fastp", L"freebayes"})
                verify_optional_pack_discovery(app_root, id, packs, cancel);
        });
        for (const auto& pack : packs)
            check(L"Executable, runtime and manifest integrity: " + pack.id + L" " + pack.version,
                  [&] { verify_pack(pack, cancel, log); });
        check(L"Pack schema rejects duplicate and unknown keys", [&] {
            const auto& pack = pack_named(L"variant-pipeline");
            const auto manifest = utf16(read_file(join(pack.root, L"pack.ini")));
            require(parse_pack_text(manifest).id == pack.id, "Valid manifest did not parse consistently");
            parse_rejects(inject_pack_key(manifest, L"id=another-id"));
            parse_rejects(inject_pack_key(manifest, L"unexpected-validation-key=yes"));
        });
        check(L"Pack schema rejects traversal and unknown input references", [&] {
            const auto& pack = pack_named(L"variant-pipeline");
            const auto manifest = utf16(read_file(join(pack.root, L"pack.ini")));
            auto traversal = manifest;
            size_t path = traversal.find(L"path=");
            require(path != std::wstring::npos, "Pack fixture contains no executable path");
            size_t end = traversal.find(L'\n', path);
            traversal.replace(path, end == std::wstring::npos ? std::wstring::npos : end - path,
                              L"path=../outside.exe");
            parse_rejects(traversal);
            auto unknown = manifest;
            const auto token = unknown.find(L"{input:");
            require(token != std::wstring::npos, "Pack fixture contains no input placeholder");
            const auto close = unknown.find(L'}', token);
            require(close != std::wstring::npos, "Pack fixture contains a truncated placeholder");
            unknown.replace(token, close - token + 1, L"{input:missing-validation-input}");
            parse_rejects(unknown);
        });
        check(L"Argument expansion preserves file lists and literal user values", [&] {
            const std::map<std::wstring, std::wstring> values = {
                {L"reads", L"C:\\data with spaces\\reads \u00e9.fastq\nC:\\data\\reads2.fastq"},
                {L"sample", L"literal & %TEMP% {output:out}"}};
            const std::map<std::wstring, std::wstring> outputs = {{L"out", L"C:\\results\\result.bam"}};
            const auto args = expand_arguments({L"merge", L"{output:out}", L"{inputs:reads}", L"{input:sample}"},
                                               values, outputs, L"C:\\results");
            require(args == std::vector<std::wstring>({L"merge", L"C:\\results\\result.bam",
                L"C:\\data with spaces\\reads \u00e9.fastq", L"C:\\data\\reads2.fastq",
                L"literal & %TEMP% {output:out}"}), "Pack argument expansion changed a literal value or file boundary");
            bool rejected = false;
            try { (void)expand_arguments({L"{input:absent}"}, values, outputs, L"C:\\results"); }
            catch (const std::exception&) { rejected = true; }
            require(rejected, "Missing placeholder values were silently accepted");
        });
        check(L"Windows argument quoting and extended path normalization", quote_and_path_checks);
        check(L"Reads workflow and independent reverse-complement bytes", [&] {
            const auto input = join(result.folder, L"reads with spaces \u00e9\u0394.fastq");
            write_file_new(input, "@one\nACGTN\n+\nIIIII\n@two\naacg\n+\n!\"#$\n");
            track(input);
            WorkflowRequest request;
            request.pack = pack_named(L"reads");
            request.workflow_id = L"reverse-complement";
            request.output_folder = result.folder;
            request.values = {{L"reads", input}};
            const auto ran = workflow(request);
            require(ran.success && !ran.cancelled, "Standalone reads workflow failed");
            const auto expected_path = join(ran.folder, L"reverse-complement.fastq");
            require(std::find(ran.outputs.begin(), ran.outputs.end(), expected_path) != ran.outputs.end(),
                    "Standalone workflow did not publish its declared output");
            require(read_file(expected_path) == "@one\nNACGT\n+\nIIIII\n@two\ncgtt\n+\n$#\"!\n",
                    "Reverse complement differs from independently expected bytes");
        });
        check(L"Workflow rejects invalid values, missing files and identical mates", [&] {
            WorkflowRequest request;
            request.pack = pack_named(L"variant-pipeline");
            request.workflow_id = L"paired-variants";
            request.output_folder = result.folder;
            const auto fixture = join(join(app_root, L"examples"), L"variant-truth");
            const std::map<std::wstring, std::wstring> valid_values = {{L"reads1", join(fixture, L"reads1.fastq")},
                {L"reads2", join(fixture, L"reads2.fastq")}, {L"reference", join(fixture, L"reference.fa")},
                {L"sample", L"truth"}, {L"threads", L"2"}};
            const std::vector<std::pair<std::wstring, std::wstring>> invalid_values = {
                {L"threads", L"not-a-number"}, {L"reads1", join(result.folder, L"missing.fastq")},
                {L"sample", L"bad\\tname"}, {L"reads2", join(fixture, L".\\reads1.fastq")}};
            for (const auto& invalid : invalid_values) {
                request.values = valid_values;
                request.values[invalid.first] = invalid.second;
                const auto ran = workflow(request);
                require(!ran.success && !ran.cancelled && ran.outputs.empty(),
                        "Invalid workflow input was accepted or published completed outputs");
                require(!ran.folder.empty(), "Rejected workflow did not retain a diagnostic report");
                const auto report = parse_json(read_file(join(ran.folder, L"run.json")));
                require(report.member("status").kind == Json::String &&
                        report.member("status").text == "failed", "Rejected workflow report lacks failed status");
                require(report.member("completed_final_outputs").kind == Json::Array &&
                        report.member("completed_final_outputs").array.empty(),
                        "Rejected workflow report advertises completed outputs");
                const auto& steps = report.member("steps");
                require(steps.kind == Json::Array, "Rejected workflow report lacks step information");
                for (const auto& step : steps.array)
                    require(step.member("status").text == "pending", "Invalid typed input allowed a tool to execute");
            }
        });
        check(L"Mismatched paired-read names stop the pipeline before alignment", [&] {
            const auto reads1 = join(result.folder, L"mismatched names R1.fastq");
            const auto reads2 = join(result.folder, L"mismatched names R2.fastq");
            // Both files are valid, distinct, one-record FASTQs with matching
            // lengths and quality strings. Only the first-token mate ID differs.
            write_file_new(reads1, "@pair-alpha/1\nACGTACGT\n+\nIIIIIIII\n");
            write_file_new(reads2, "@pair-beta/2\nACGTACGT\n+\nIIIIIIII\n");
            track(reads1);
            track(reads2);
            WorkflowRequest request;
            request.pack = pack_named(L"variant-pipeline");
            request.workflow_id = L"paired-variants";
            request.output_folder = result.folder;
            request.values = {{L"reads1", reads1}, {L"reads2", reads2},
                {L"reference", join(join(join(app_root, L"examples"), L"variant-truth"), L"reference.fa")},
                {L"sample", L"truth"}, {L"threads", L"2"}};
            const auto ran = workflow(request);
            require(!ran.success && !ran.cancelled && ran.outputs.empty() && !ran.folder.empty(),
                    "Mismatched read names did not fail the pipeline without completed outputs");
            const auto report = parse_json(read_file(join(ran.folder, L"run.json")));
            require(report.member("status").kind == Json::String && report.member("status").text == "failed",
                    "Mismatched-pair workflow report does not record failure");
            const auto& completed = report.member("completed_final_outputs");
            require(completed.kind == Json::Array && completed.array.empty(),
                    "Failed mate validation published completed outputs");
            const auto& definition = workflow_named(request.pack, request.workflow_id);
            const auto& steps = report.member("steps");
            require(steps.kind == Json::Array && !steps.array.empty() &&
                    steps.array.size() == definition.steps.size(),
                    "Mismatched-pair workflow report lacks its declared steps");
            const auto& gate = steps.array.front();
            require(gate.member("id").text == "check-pairs" && gate.member("tool_id").text == "paircheck" &&
                    gate.member("status").text == "failed" && gate.member("exit_code").kind == Json::Number &&
                    gate.member("exit_code").text != "0", "Mate-name validation did not fail in the paircheck tool");
            for (size_t i = 1; i < steps.array.size(); ++i) {
                const auto& step = steps.array[i];
                require(step.member("status").text == "pending" &&
                        step.member("started_utc").kind == Json::Null &&
                        step.member("exit_code").kind == Json::Null,
                        "A downstream pipeline step started after mate-name validation failed");
            }
            for (const auto& output : definition.outputs) {
                if (output.id == definition.steps.front().stdout_id) continue;
                require(!file_exists(join(ran.folder, output.path)),
                        "A downstream output was created after mate-name validation failed");
            }
        });
        check(L"Import, long paths, discovery and duplicate version protection", [&] {
            const auto& pack = pack_named(L"reads");
            const auto source_app = unique_directory(result.folder, L"import-source");
            const auto destination_app = unique_directory(result.folder, L"import-destination");
            const auto source = import_pack(source_app, pack.root, cancel, log);
            const auto expected_root = join(join(destination_app, L"packs"), pack.id + L"-" + pack.version);
            auto relative = join(L"licenses", L"validation-long-path");
            if (!directory_exists(join(source.root, L"licenses"))) make_directory(join(source.root, L"licenses"));
            make_directory(join(source.root, relative));
            for (unsigned i = 0; ; ++i) {
                const auto shorter = std::min(join(join(source.root, relative), L"notice.txt").size(),
                    join(join(expected_root, relative), L"notice.txt").size());
                if (shorter >= 320) break;
                require(i < 12, "Could not construct bounded long-path regression fixture");
                relative = join(relative, L"segment-" + std::to_wstring(i) + L"-" + std::wstring(36, L'x'));
                make_directory(join(source.root, relative));
            }
            relative = join(relative, L"notice.txt");
            const std::string notice = "Generated validation fixture; preserve these bytes during import.\n";
            write_file_new(join(source.root, relative), notice);
            track(join(source.root, relative));
            const auto imported = import_pack(destination_app, source.root, cancel, log);
            require(imported.root == expected_root && imported.id == pack.id && imported.version == pack.version,
                    "Imported pack destination or identity is incorrect");
            verify_pack(imported, cancel, log);
            require(read_file(join(imported.root, relative)) == notice, "Long-path license fixture changed during import");
            const auto before = sha256_file(join(imported.root, L"pack.ini"), cancel);
            const auto discovered = discover_packs(destination_app, log);
            require(discovered.size() == 1 && discovered[0].root == imported.root,
                    "Imported pack was not discovered exactly once");
            bool duplicate_rejected = false;
            try { (void)import_pack(destination_app, source.root, cancel, log); }
            catch (const std::exception&) { check_cancel(cancel); duplicate_rejected = true; }
            require(duplicate_rejected, "Duplicate pack version was accepted");
            require(sha256_file(join(imported.root, L"pack.ini"), cancel) == before &&
                    read_file(join(imported.root, relative)) == notice,
                    "Duplicate import changed existing pack data");
            verify_pack(imported, cancel, log);
            verify_pack(pack, cancel, log);
        });
        check(L"Modified executable is rejected before workflow execution", [&] {
            const auto app = unique_directory(result.folder, L"tamper-test");
            const auto copy = import_pack(app, pack_named(L"reads").root, cancel, log);
            require(!copy.tools.empty(), "No executable available for tamper test");
            append_byte(copy.tools.front().path);
            require(sha256_file(copy.tools.front().path, cancel) != copy.tools.front().sha256,
                    "Executable tampering did not change its checksum");
            bool rejected = false;
            try { verify_pack(copy, cancel, [](const std::wstring&) {}); }
            catch (const std::exception&) { check_cancel(cancel); rejected = true; }
            require(rejected, "A modified pack executable passed verification");
        });
        check(L"Paired variant pipeline recovers the synthetic truth set", [&] {
            const auto& pack = pack_named(L"variant-pipeline");
            const auto fixture = join(join(app_root, L"examples"), L"variant-truth");
            const auto copies = join(result.folder, L"truth data with spaces \u00e9\u0394");
            make_directory(copies);
            for (const auto& name : {L"reference.fa", L"reads1.fastq", L"reads2.fastq", L"expected-variants.tsv"}) {
                const auto original = join(fixture, name);
                track(original);
                const auto copied = join(copies, name);
                write_file_new(copied, read_file(original));
                track(copied);
            }
            WorkflowRequest request;
            request.pack = pack;
            request.workflow_id = L"paired-variants";
            request.output_folder = result.folder;
            request.values = {{L"reads1", join(copies, L"reads1.fastq")},
                {L"reads2", join(copies, L"reads2.fastq")}, {L"reference", join(copies, L"reference.fa")},
                {L"sample", L"truth"}, {L"threads", L"2"}, {L"ploidy", L"2"},
                {L"min-mapq", L"20"}, {L"min-baseq", L"20"}, {L"max-depth", L"1000"},
                {L"min-qual", L"20"}, {L"min-depth", L"5"}};
            const auto ran = workflow(request);
            pipeline_folder = ran.folder;
            require(ran.success && !ran.cancelled, "Paired variant pipeline failed; inspect its stage logs");
            const auto& definition = workflow_named(pack, request.workflow_id);
            size_t final_count = 0;
            for (const auto& output : definition.outputs) if (output.final) {
                ++final_count;
                const auto path = join(ran.folder, output.path);
                require(std::find(ran.outputs.begin(), ran.outputs.end(), path) != ran.outputs.end(),
                        "A declared pipeline result was not published");
                require(file_exists(path), "A published pipeline output is missing");
                if (output.nonempty) require(nonempty_file(path), "A required pipeline result is empty");
            }
            require(ran.outputs.size() == final_count, "Pipeline published undeclared result paths");
            const auto variants = join(ran.folder, L"variants.vcf.gz");
            const auto query = invoke(tool_named(pack, L"bcftools"),
                {L"query", L"-f", L"%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n", variants});
            const auto expected = variant_rows(read_file(join(copies, L"expected-variants.tsv")), true);
            const auto observed = variant_rows(read_file(query), false);
            require(!expected.empty(), "Synthetic truth fixture is empty");
            require(observed == expected, "Called positions, alleles or genotypes differ from the synthetic truth set");
            const auto samples = invoke(tool_named(pack, L"bcftools"), {L"query", L"-l", variants});
            auto sample_text = read_file(samples);
            sample_text.erase(std::remove(sample_text.begin(), sample_text.end(), '\r'), sample_text.end());
            require(sample_text == "truth\n", "VCF sample name differs from the workflow input");
            require(nonempty_file(join(ran.folder, L"variants.vcf.gz.csi")), "VCF index is missing or empty");
            const auto bam = join(ran.folder, L"alignment.marked.bam");
            (void)invoke(tool_named(pack, L"samtools"), {L"quickcheck", L"-v", bam});
            require(nonempty_file(join(ran.folder, L"alignment.marked.bam.csi")), "BAM index is missing or empty");
            require(nonempty_file(join(ran.folder, L"run.json")), "Workflow provenance report is missing or empty");
        });
        check(L"Successful pipeline report records steps, checksums and completed outputs", [&] {
            require(!pipeline_folder.empty(), "Synthetic pipeline did not create a report folder");
            const auto report = parse_json(read_file(join(pipeline_folder, L"run.json")));
            require(report.member("status").kind == Json::String && report.member("status").text == "success",
                    "Pipeline provenance does not report success");
            const auto& pack = pack_named(L"variant-pipeline");
            const auto& definition = workflow_named(pack, L"paired-variants");
            const auto& identity = report.member("pack");
            require(identity.member("id").text == utf8(pack.id) &&
                    identity.member("version").text == utf8(pack.version) &&
                    identity.member("manifest_sha256").text == utf8(pack.manifest_sha256),
                    "Pipeline report has incorrect pack identity or manifest checksum");
            const auto& steps = report.member("steps");
            require(steps.kind == Json::Array && steps.array.size() == definition.steps.size(),
                    "Pipeline report does not contain every declared step");
            for (size_t i = 0; i < steps.array.size(); ++i) {
                const auto& step = steps.array[i];
                require(step.member("id").text == utf8(definition.steps[i].id) &&
                        step.member("status").text == "success", "A pipeline step is missing or unsuccessful in its report");
                if (definition.steps[i].kind == L"exec")
                    require(step.member("exit_code").kind == Json::Number && step.member("exit_code").text == "0",
                            "A reported executable step lacks a successful exit code");
            }
            const auto& evidence = report.member("input_files");
            require(evidence.kind == Json::Array && evidence.array.size() == 3,
                    "Pipeline report does not describe both read files and the reference");
            for (const auto& input : evidence.array) {
                const auto& before = input.member("sha256_before");
                const auto& after = input.member("sha256_after");
                require(before.kind == Json::String && after.kind == Json::String &&
                        before.text == after.text && input.member("after_check").text == "unchanged",
                        "Pipeline report does not demonstrate unchanged inputs");
                require(sha256_file(utf16(input.member("path").text), cancel) == utf16(after.text),
                        "Reported input checksum does not match the file");
            }
            const auto& artifacts = report.member("artifacts");
            require(artifacts.kind == Json::Array && artifacts.array.size() == definition.outputs.size(),
                    "Pipeline report is missing declared artifacts");
            std::set<std::string> final_paths;
            for (const auto& artifact : artifacts.array) {
                require(artifact.member("checked").kind == Json::Boolean &&
                        artifact.member("checked").text == "true" &&
                        artifact.member("workflow_complete").text == "true", "An artifact lacks completion evidence");
                const auto& path = artifact.member("path");
                const auto& hash = artifact.member("sha256");
                require(path.kind == Json::String && hash.kind == Json::String &&
                        sha256_file(utf16(path.text), cancel) == utf16(hash.text),
                        "Reported artifact checksum does not match its bytes");
                if (artifact.member("final").text == "true") final_paths.insert(path.text);
            }
            const auto& published = report.member("completed_final_outputs");
            require(published.kind == Json::Array && published.array.size() == final_paths.size(),
                    "Pipeline report has an inconsistent completed-output list");
            std::set<std::string> listed;
            for (const auto& path : published.array) {
                require(path.kind == Json::String && listed.insert(path.text).second,
                        "Completed-output list has an invalid or duplicate entry");
            }
            require(listed == final_paths, "Completed-output list differs from verified final artifacts");
        });
        check(L"Cutadapt adapter and quality trimming matches independent paired-read truth", [&] {
            trimming_oracle(pack_named(L"trimming"), L"installed-cutadapt-oracle");
        });
        check(L"Adapter fields reject file expressions before Python starts", [&] {
            const auto fixture = join(join(app_root, L"examples"), L"trimming-truth");
            WorkflowRequest request;
            request.pack = pack_named(L"trimming");
            request.workflow_id = L"cutadapt-paired";
            request.output_folder = result.folder;
            request.values = {{L"reads1", join(fixture, L"reads1.fastq")}, {L"reads2", join(fixture, L"reads2.fastq")},
                {L"adapter1", L"file:C:\\untracked-adapters.fa"}, {L"adapter2", L"ACGTACGT"},
                {L"threads", L"2"}};
            const auto ran = workflow(request);
            additional_runs.push_back({L"adapter-field-rejection", ran.folder});
            require(!ran.success && !ran.cancelled && ran.outputs.empty() && !ran.folder.empty(),
                    "Adapter file expression was accepted as a tracked sequence input");
            const auto report = parse_json(read_file(join(ran.folder, L"run.json")));
            require(report.member("status").text == "failed", "Adapter rejection lacks failed provenance");
            const auto& steps = report.member("steps");
            require(steps.kind == Json::Array, "Adapter rejection lacks step information");
            for (const auto& step : steps.array)
                require(step.member("status").text == "pending" && step.member("started_utc").kind == Json::Null,
                        "A tool started before the invalid adapter expression was rejected");
        });
        check(L"Imported Cutadapt retains runtime assets and runs the same oracle", [&] {
            const auto& original = pack_named(L"trimming");
            require(!original.assets.empty(), "Cutadapt pack contains no declared runtime assets");
            const auto copy_app = unique_directory(result.folder, L"import-runtime");
            imported_trimming = import_pack(copy_app, original.root, cancel, log);
            require(imported_trimming.assets.size() == original.assets.size(),
                    "Runtime pack import changed the declared asset count");
            for (size_t i = 0; i < original.assets.size(); ++i)
                require(imported_trimming.assets[i].id == original.assets[i].id &&
                        sha256_file(imported_trimming.assets[i].path, cancel) == original.assets[i].sha256,
                        "A copied Python runtime asset differs from the installed source");
            verify_pack(imported_trimming, cancel, log);
            trimming_oracle(imported_trimming, L"imported-cutadapt-oracle");
            verify_pack(original, cancel, log);
        });
        check(L"Modified Python module and undeclared runtime file are rejected", [&] {
            require(!imported_trimming.root.empty(), "No private imported runtime is available for tamper validation");
            const auto module = std::find_if(imported_trimming.assets.begin(), imported_trimming.assets.end(),
                [](const Asset& asset) {
                    return asset.path.size() > 3 && asset.path.substr(asset.path.size() - 3) == L".py";
                });
            require(module != imported_trimming.assets.end(), "Runtime fixture contains no Python source module");
            const auto original = read_file(module->path);
            append_byte(module->path);
            bool modified_rejected = false;
            try { verify_pack(imported_trimming, cancel, [](const std::wstring&) {}); }
            catch (const std::exception&) { check_cancel(cancel); modified_rejected = true; }
            replace_private_file(module->path, original);
            require(modified_rejected, "A modified non-executable runtime asset passed verification");
            verify_pack(imported_trimming, cancel, log);
            const auto undeclared = join(join(join(imported_trimming.root, L"runtime"), L"python"),
                                         L"validation_undeclared_module.py");
            write_file_new(undeclared, "# Private validation fixture; never imported.\n");
            bool undeclared_rejected = false;
            try { verify_pack(imported_trimming, cancel, [](const std::wstring&) {}); }
            catch (const std::exception&) { check_cancel(cancel); undeclared_rejected = true; }
            require(DeleteFileW(native_path(undeclared).c_str()) != 0, "Could not remove undeclared private module");
            require(undeclared_rejected, "An undeclared module in the private runtime passed inventory verification");
            verify_pack(imported_trimming, cancel, log);
        });
        check(L"Standalone BWA streams all paired reads to a valid BAM", [&] {
            const auto fixture = join(join(app_root, L"examples"), L"variant-truth");
            WorkflowRequest request;
            request.pack = pack_named(L"bwa");
            request.workflow_id = L"paired-end";
            request.output_folder = result.folder;
            request.values = {{L"reads1", join(fixture, L"reads1.fastq")},
                {L"reads2", join(fixture, L"reads2.fastq")}, {L"reference", join(fixture, L"reference.fa")},
                {L"sample", L"truth"}, {L"read-group", L"validation-rg"}, {L"library", L"validation-library"},
                {L"platform-unit", L"validation-unit"}, {L"platform", L"ILLUMINA"}, {L"threads", L"2"}};
            const auto ran = workflow(request);
            additional_runs.push_back({L"standalone-bwa-stream", ran.folder});
            expect_success(request, ran, true);
            const auto bam = join(ran.folder, L"alignment.unsorted.bam");
            const auto& samtools = tool_named(request.pack, L"samtools");
            (void)invoke(samtools, {L"quickcheck", L"-v", bam});
            const auto header = read_file(invoke(samtools, {L"view", L"-H", bam}));
            bool found_group = false;
            std::istringstream lines(header);
            std::string line;
            while (std::getline(lines, line)) if (line.rfind("@RG\t", 0) == 0) {
                if (!line.empty() && line.back() == '\r') line.pop_back();
                std::set<std::string> fields;
                std::istringstream row(line);
                std::string field;
                while (std::getline(row, field, '\t')) fields.insert(field);
                if (fields.count("ID:validation-rg") && fields.count("SM:truth") &&
                    fields.count("LB:validation-library") && fields.count("PU:validation-unit") &&
                    fields.count("PL:ILLUMINA")) found_group = true;
            }
            require(found_group, "BWA BAM did not preserve the requested read-group fields");
            size_t expected_records = 0;
            for (const auto& name : {L"reads1.fastq", L"reads2.fastq"}) {
                const auto reads = read_file(join(fixture, name));
                const auto count = static_cast<size_t>(std::count(reads.begin(), reads.end(), '\n'));
                require(count != 0 && count % 4 == 0, "BWA validation fixture is not four-line FASTQ");
                expected_records += count / 4;
            }
            auto count = read_file(invoke(samtools, {L"view", L"-c", L"-F", L"2304", bam}));
            count.erase(std::remove(count.begin(), count.end(), '\r'), count.end());
            require(count == std::to_string(expected_records) + "\n", "Streaming alignment lost or duplicated primary read records");
        });
        check(L"Cutadapt, streaming BWA and BCFtools recover all four truth variants", [&] {
            const auto fixture = join(join(app_root, L"examples"), L"variant-truth");
            WorkflowRequest request;
            request.pack = pack_named(L"research-variants");
            request.workflow_id = L"cutadapt-bwa-bcftools-quality-only";
            request.output_folder = result.folder;
            request.values = {{L"reads1", join(fixture, L"reads1.fastq")},
                {L"reads2", join(fixture, L"reads2.fastq")}, {L"reference", join(fixture, L"reference.fa")},
                {L"sample", L"truth"}, {L"read-group", L"truth-rg"}, {L"library", L"truth-library"},
                {L"platform-unit", L"truth-unit"}, {L"platform", L"ILLUMINA"}, {L"threads", L"2"},
                {L"sort-memory", L"64"}, {L"trim-quality", L"20"}, {L"min-length", L"35"},
                {L"ploidy", L"2"}, {L"min-mapq", L"20"}, {L"min-baseq", L"20"},
                {L"max-depth", L"1000"}, {L"min-qual", L"20"}, {L"min-depth", L"5"}};
            const auto ran = workflow(request);
            research_pipeline_folder = ran.folder;
            additional_runs.push_back({L"cutadapt-bwa-bcftools-truth", ran.folder});
            expect_success(request, ran, true);
            const auto& caller = tool_named(request.pack, L"bcftools");
            const auto expected = variant_rows(read_file(join(fixture, L"expected-variants.tsv")), true);
            require(expected.size() == 4, "Variant truth fixture must declare four expected variants");
            for (const auto& name : {L"variants.vcf.gz", L"variants.pass.vcf.gz"}) {
                const auto variants = join(ran.folder, name);
                const auto observed = variant_rows(read_file(invoke(caller,
                    {L"query", L"-f", L"%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n", variants})), false);
                require(observed == expected, "Research workflow calls or PASS subset differ from the four expected variants");
                require(nonempty_file(variants + L".csi"), "A research VCF lacks its CSI index");
            }
            (void)invoke(tool_named(request.pack, L"samtools"),
                {L"quickcheck", L"-v", join(ran.folder, L"alignment.marked.bam")});
            require(nonempty_file(join(ran.folder, L"alignment.marked.bam.csi")), "Research BAM lacks a CSI index");
            require(nonempty_file(join(ran.folder, L"coverage.tsv")), "Research pipeline lacks its coverage report");
        });
        for (const bool fail_producer : {true, false}) {
            check(fail_producer ? L"Streaming producer failure stops all downstream steps" :
                                  L"Streaming sink failure stops all downstream steps", [&] {
                const auto fixture_pack = unique_directory(result.folder,
                    fail_producer ? L"pipe-producer-failure" : L"pipe-sink-failure");
                make_directory(join(fixture_pack, L"bin"));
                const auto& tool = tool_named(pack_named(L"bwa"), L"samtools");
                write_file_new(join(join(fixture_pack, L"bin"), L"samtools.exe"), read_file(tool.path, 128 * 1024 * 1024));
                std::ostringstream manifest;
                manifest << "[pack]\nformat=2\nid=validation-pipe\nversion=" << utf8(APP_VERSION)
                    << "\nname=Private pipeline validation\nplatform=windows-x86_64\ncolor=#4870A0\n\n"
                    << "[tool:samtools]\npath=bin/samtools.exe\nversion=" << utf8(tool.version)
                    << "\nsha256=" << utf8(tool.sha256) << "\n\n"
                    << "[workflow:failure]\nname=Failure isolation\ninputs=\noutputs=pipe-log,after\nsteps=stream,after\n\n"
                    << "[output:failure:pipe-log]\nlabel=Streaming stdout\npath=pipe.stdout.txt\nfinal=false\nnonempty=false\n\n"
                    << "[output:failure:after]\nlabel=Must not execute\npath=after.txt\nfinal=true\nnonempty=true\n\n"
                    << "[step:failure:stream]\nlabel=Intentional streaming failure\nkind=pipe\ntool=samtools\nsink-tool=samtools\nstdout=pipe-log\narg.0="
                    << (fail_producer ? "validation-invalid-command" : "--version") << '\n';
                if (fail_producer) manifest << "sink-arg.0=view\nsink-arg.1=-u\nsink-arg.2=-\n\n";
                else manifest << "sink-arg.0=validation-invalid-command\n\n";
                manifest << "[step:failure:after]\nlabel=Must remain pending\nkind=exec\ntool=samtools\nstdout=after\narg.0=--version\n";
                write_file_new(join(fixture_pack, L"pack.ini"), manifest.str());
                WorkflowRequest request;
                request.pack = load_pack(fixture_pack);
                request.workflow_id = L"failure";
                request.output_folder = result.folder;
                const auto ran = workflow(request);
                additional_runs.push_back({fail_producer ? L"pipe-producer-failure" : L"pipe-sink-failure", ran.folder});
                require(!ran.success && !ran.cancelled && !ran.folder.empty() && ran.outputs.empty(),
                        "A failed streaming process published completed results");
                const auto report = parse_json(read_file(join(ran.folder, L"run.json")));
                require(report.member("status").text == "failed" &&
                        report.member("completed_final_outputs").kind == Json::Array &&
                        report.member("completed_final_outputs").array.empty(), "Streaming failure report advertises success");
                const auto& steps = report.member("steps");
                require(steps.kind == Json::Array && steps.array.size() == 2,
                        "Streaming failure did not produce the expected step report");
                const auto& first = steps.array[0];
                const auto& failed_exit = first.member(fail_producer ? "producer_exit_code" : "sink_exit_code");
                require(first.member("status").text == "failed" && failed_exit.kind == Json::Number && failed_exit.text != "0",
                        "Streaming report did not capture the deliberately failing process exit");
                require(steps.array[1].member("status").text == "pending" &&
                        steps.array[1].member("started_utc").kind == Json::Null &&
                        steps.array[1].member("exit_code").kind == Json::Null && !file_exists(join(ran.folder, L"after.txt")),
                        "A downstream step executed after a streaming process failed");
            });
        }
        if (has_pack(L"freebayes")) check(L"Standalone FreeBayes recovers the four truth alleles and genotypes", [&] {
            require(!research_pipeline_folder.empty(), "Prepared research BAM is unavailable for FreeBayes validation");
            const auto fixture = join(join(app_root, L"examples"), L"variant-truth");
            WorkflowRequest request;
            request.pack = pack_named(L"freebayes");
            request.workflow_id = L"call";
            request.output_folder = result.folder;
            request.values = {{L"alignment", join(research_pipeline_folder, L"alignment.marked.bam")},
                {L"reference", join(fixture, L"reference.fa")}, {L"ploidy", L"2"},
                {L"min-mapq", L"20"}, {L"min-baseq", L"20"}, {L"min-qual", L"20"},
                {L"min-depth", L"5"}, {L"min-alt-count", L"2"}, {L"min-alt-fraction", L"0.2"}};
            const auto ran = workflow(request);
            additional_runs.push_back({L"standalone-freebayes-truth", ran.folder});
            expect_success(request, ran);
            const auto expected = variant_rows(read_file(join(fixture, L"expected-variants.tsv")), true);
            for (const auto& name : {L"variants.vcf.gz", L"variants.pass.vcf.gz"}) {
                const auto observed = variant_rows(read_file(invoke(tool_named(request.pack, L"bcftools"),
                    {L"query", L"-f", L"%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n", join(ran.folder, name)})), false);
                require(observed == expected, "FreeBayes normalized calls or PASS subset differ from synthetic truth");
            }
        });
        if (has_pack(L"fastp")) check(L"fastp preserves known trimming truth and writes an offline report", [&] {
            const auto fixture = join(join(app_root, L"examples"), L"fastp-truth");
            for (const auto& name : {L"reads1.fastq.gz", L"reads2.fastq.gz", L"truth.json",
                                    L"expected-paired1.fastq", L"expected-paired2.fastq"}) track(join(fixture, name));
            const auto truth = parse_json_file(join(fixture, L"truth.json"));
            const auto& adapters = truth.member("adapters");
            require(adapters.kind == Json::Array && adapters.array.size() == 2,
                    "fastp truth fixture lacks adapters");
            WorkflowRequest request;
            request.pack = pack_named(L"fastp");
            request.workflow_id = L"paired";
            request.output_folder = result.folder;
            request.values = {{L"reads1", join(fixture, L"reads1.fastq.gz")}, {L"reads2", join(fixture, L"reads2.fastq.gz")},
                {L"adapter1", utf16(adapters.array[0].text)}, {L"adapter2", utf16(adapters.array[1].text)},
                {L"threads", L"2"}, {L"trim-quality", L"20"}, {L"trim-window", L"1"}, {L"min-length", L"30"},
                {L"qualified-quality", L"15"}, {L"unqualified-percent", L"40"}, {L"max-n", L"5"}};
            const auto ran = workflow(request);
            additional_runs.push_back({L"fastp-known-truth", ran.folder});
            expect_success(request, ran);
            std::vector<std::vector<FastqRecord>> observed;
            for (const auto& mate : {L"1", L"2"}) {
                const auto unpacked = invoke(tool_named(pack_named(L"trimming"), L"python"),
                    {L"-I", L"-B", L"-c", L"import gzip,sys;sys.stdout.buffer.write(gzip.open(sys.argv[1],'rb').read())",
                     join(ran.folder, L"reads" + std::wstring(mate) + L".trimmed.fastq.gz")});
                observed.push_back(four_line_fastq(read_file(unpacked)));
                const auto expected = four_line_fastq(read_file(join(fixture,
                    L"expected-paired" + std::wstring(mate) + L".fastq")));
                require(observed.back().size() == 100 && fastq_by_name(observed.back()) == fastq_by_name(expected),
                        "fastp retained sequences or qualities differ from independent expected records");
            }
            for (size_t i = 0; i < observed[0].size(); ++i) {
                const auto& one = observed[0][i].name;
                const auto& two = observed[1][i].name;
                require(one.size() > 2 && two.size() > 2 && one.substr(one.size() - 2) == "/1" &&
                        two.substr(two.size() - 2) == "/2" && one.substr(0, one.size() - 2) == two.substr(0, two.size() - 2),
                        "fastp output mate order or pairing changed");
            }
            log_line(log, L"fastp trimming truth passed: 100 pairs with exact sequences, qualities and mate order.");
            const auto metrics = parse_json_file(join(ran.folder, L"trimming.json"));
            const auto& summary = metrics.member("summary");
            require(summary.member("before_filtering").member("total_reads").text == "240" &&
                    summary.member("after_filtering").member("total_reads").text == "200" &&
                    summary.member("after_filtering").member("total_bases").text == "13500",
                    "fastp JSON counts differ from the known 120-to-100 paired-read fixture");
            const auto html = read_file(join(ran.folder, L"trimming.html"));
            require(html.find("plotly-1.2.0.min.js") != std::string::npos &&
                    html.find("cdn.plot.ly") == std::string::npos && html.find("window.Plotly ||") == std::string::npos &&
                    html.find("modeBarButtonsToRemove:['sendDataToCloud']") != std::string::npos,
                    "fastp HTML does not use the required offline chart configuration");
            const auto script = std::find_if(request.pack.assets.begin(), request.pack.assets.end(),
                [](const Asset& asset) { return asset.id == L"plotly"; });
            require(script != request.pack.assets.end() &&
                    sha256_file(join(ran.folder, L"plotly-1.2.0.min.js"), cancel) == script->sha256,
                    "The report's local Plotly asset differs from its declared checksum");
        });
        const auto pipeline_companion = join(app_root, L"WindowsPipelineChecks.exe");
        if (file_exists(pipeline_companion)) {
            check(L"Native streaming lifecycle: six companion checks", [&] {
                track(pipeline_companion);
                const auto report_path = join(result.folder, L"pipeline-companion.json");
                const auto process = execute(pipeline_companion, {result.folder, L"--report", report_path},
                    join(result.folder, L"pipeline-companion.stdout.txt"),
                    join(result.folder, L"pipeline-companion.stderr.txt"), cancel, log, 60000, app_root);
                check_cancel(cancel);
                require(!process.cancelled && process.exit_code == 0,
                        "Native pipeline companion failed; inspect pipeline-companion.stderr.txt");
                const auto report = parse_json(read_file(report_path));
                require(report.member("schema_version").kind == Json::Number &&
                        report.member("schema_version").text == "1" &&
                        report.member("application_version").text == utf8(APP_VERSION),
                        "Pipeline companion report has an incompatible schema or application version");
                require(report.member("native_windows_execution").kind == Json::Boolean &&
                        report.member("native_windows_execution").text == "true" &&
                        report.member("passed").kind == Json::Number && report.member("passed").text == "6" &&
                        report.member("failed").kind == Json::Number && report.member("failed").text == "0",
                        "Pipeline companion did not pass all six native lifecycle checks");
                const std::set<std::string> expected{"binary-stream-and-diagnostics", "producer-failure",
                    "sink-failure", "cancel-both", "timeout", "preserve-existing-output"};
                const auto& cases = report.member("checks");
                require(cases.kind == Json::Array && cases.array.size() == expected.size(),
                        "Pipeline companion report has the wrong number of lifecycle cases");
                std::set<std::string> observed;
                for (const auto& item : cases.array) {
                    require(item.kind == Json::String && observed.insert(item.text).second,
                            "Pipeline companion report contains an invalid or duplicate case");
                }
                require(observed == expected, "Pipeline companion omitted a required lifecycle case");
                const auto& folder = report.member("folder");
                require(folder.kind == Json::String && directory_exists(utf16(folder.text)),
                        "Pipeline companion result folder is unavailable");
                additional_runs.push_back({L"native-streaming-lifecycle", utf16(folder.text)});
            });
        } else log_line(log, L"Optional native streaming lifecycle companion is absent; its six checks were not run.");
        check(L"Fixture inputs remain byte-for-byte unchanged", [&] {
            require(!inputs.empty(), "No validation fixture inputs were tracked");
            for (auto& input : inputs) {
                input.after = sha256_file(input.path, cancel);
                require(input.before == input.after, "A source or private validation input was modified");
            }
        });
        result.success = !checks.empty() && std::all_of(checks.begin(), checks.end(),
            [](const ValidationCheck& check) { return check.passed; });
        const size_t passed = static_cast<size_t>(std::count_if(checks.begin(), checks.end(),
            [](const ValidationCheck& check) { return check.passed; }));
        result.message = std::to_wstring(passed) + L" of " + std::to_wstring(checks.size()) + L" checks passed.";
    } catch (const std::exception& error) {
        result.success = false;
        result.cancelled = cancel.load();
        result.message = result.cancelled ? L"Installation validation cancelled." : error_text(error);
        if (!result.folder.empty()) checks.push_back({L"Validation completion", result.message, false, 0});
        log_line(log, result.message);
    } catch (...) {
        result.success = false;
        result.cancelled = cancel.load();
        result.message = L"Installation validation stopped with an unknown error.";
        if (!result.folder.empty()) checks.push_back({L"Validation completion", result.message, false, 0});
    }
    if (!result.folder.empty()) {
        try {
            const auto report = join(result.folder, L"windows-validation.json");
            write_file_new(report, validation_report(checks, inputs, packs, result.cancelled,
                GetTickCount64() - started, pipeline_folder, additional_runs));
            result.outputs.push_back(report);
            log_line(log, L"Validation report saved: " + report);
        } catch (const std::exception& error) {
            result.success = false;
            result.message += L" Could not save the validation report: " + error_text(error);
        }
    }
    return result;
}
} // namespace bw
