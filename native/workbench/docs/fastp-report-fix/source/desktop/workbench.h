#pragma once
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <functional>
#include <string>
#include <vector>
#include "pack_model.h"

namespace bw {
inline constexpr wchar_t APP_VERSION[] = L"0.4.1";
using Log = std::function<void(const std::wstring&)>;
using Phase = std::function<void(const std::wstring&)>;
using Cancel = std::atomic_bool;
enum class JobKind { Statistics, ReverseComplement, Alignment, StatisticsAndAlignment };
struct Request {
    Pack pack;
    JobKind kind = JobKind::Statistics;
    std::wstring input, reference, output_folder;
    std::wstring preset = L"sr";
    unsigned threads = 2;
};
struct Result {
    bool success = false;
    bool cancelled = false;
    std::wstring folder, message;
    std::vector<std::wstring> outputs;
};
struct ProcessResult { DWORD exit_code = 0; bool cancelled = false; };
struct PipelineProcessResult {
    DWORD producer_exit_code = 0, sink_exit_code = 0;
    bool cancelled = false;
};
struct WorkflowRequest {
    Pack pack;
    std::wstring workflow_id, output_folder;
    std::map<std::wstring, std::wstring> values;
};

// common.cpp, implemented by the coordinator. UTF conversions throw on errors.
std::wstring executable_folder();
std::wstring join(const std::wstring&, const std::wstring&);
// For Win32 filesystem calls only: normalize to an absolute path, then use
// the explicit extended-length namespace. Keep display paths/argv ordinary.
std::wstring native_path(const std::wstring&);
std::wstring utf16(const std::string&);
std::string utf8(const std::wstring&);
std::string json_string(const std::wstring&);
std::wstring windows_error(DWORD code = GetLastError());
bool file_exists(const std::wstring&);
bool directory_exists(const std::wstring&);
std::string read_file(const std::wstring&, size_t max_bytes = 8 * 1024 * 1024);
void write_file_new(const std::wstring&, const std::string&);
std::wstring unique_directory(const std::wstring& parent, const std::wstring& prefix);
void check_cancel(const Cancel&);

// packs.cpp: fixed, documented pack.ini schema; all paths remain in pack root.
Pack load_pack(const std::wstring& folder);
std::vector<Pack> discover_packs(const std::wstring& app_root, const Log&);
std::wstring sha256_file(const std::wstring& path, const Cancel&);
void verify_pack(const Pack&, const Cancel&, const Log&);
Pack import_pack(const std::wstring& app_root, const std::wstring& source, const Cancel&, const Log&);

// runner.cpp: no shell. Each child belongs to a kill-on-close Job Object.
// stdout_file is newly created (CREATE_NEW); stderr_file is also newly created.
// Runtime status and decoded stderr lines are passed to log. Timeout 0 means none.
ProcessResult execute(const std::wstring& executable, const std::vector<std::wstring>& args,
    const std::wstring& stdout_file, const std::wstring& stderr_file,
    Cancel&, const Log&, DWORD timeout_ms = 0, const std::wstring& working_directory = {});
std::wstring quote_argument(const std::wstring&);
PipelineProcessResult execute_pipeline(const std::wstring& producer, const std::vector<std::wstring>& producer_args,
    const std::wstring& sink, const std::vector<std::wstring>& sink_args,
    const std::wstring& stdout_file, const std::wstring& producer_stderr_file,
    const std::wstring& sink_stderr_file, Cancel&, const Log&, DWORD timeout_ms = 0,
    const std::wstring& working_directory = {});
Result run_job(const Request&, Cancel&, const Log&, const Phase&);
Result run_workflow(const WorkflowRequest&, Cancel&, const Log&, const Phase&);
Result validate_modular_installation(const std::wstring& app_root, const std::wstring& output_parent,
    Cancel&, const Log&, const Phase&);

// validation.cpp: native self-checks using the same runner. New report folder.
Result validate_installation(const std::wstring& app_root, const Pack&, const std::wstring& output_parent,
    Cancel&, const Log&, const Phase&);
} // namespace bw
