#pragma once
#include "workbench.h"

#include <iomanip>
#include <locale>
#include <sstream>

namespace bw {
// Query the already-owned job, without changing its limits, cancellation or
// cleanup. Capture before its handle closes (also on exception paths). A live
// descendant at that boundary makes coverage partial: cleanup work is excluded.
// Windows documents CPU in 100 ns ticks and JobMemory as committed memory;
// this is deliberately not reported as resident-set size or Linux maximum RSS.
// https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
// https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
class JobPerformanceCapture {
    HANDLE job_;
    ProcessPerformance& value_;
    ULONGLONG began_ = 0;
    bool captured_ = false;
public:
    JobPerformanceCapture(HANDLE job, ProcessPerformance& value) noexcept : job_(job), value_(value) {}
    ~JobPerformanceCapture() { capture(); }
    JobPerformanceCapture(const JobPerformanceCapture&) = delete;
    JobPerformanceCapture& operator=(const JobPerformanceCapture&) = delete;
    void begin(ULONGLONG began) noexcept { began_ = began; value_.wall_available = true; }
    void assigned() noexcept { value_.launched = true; }
    void capture() noexcept {
        if (captured_) return;
        captured_ = true;
        if (value_.wall_available) value_.wall_ms = GetTickCount64() - began_;
        if (!value_.launched) return;
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
        if (QueryInformationJobObject(job_, JobObjectBasicAccountingInformation,
                &accounting, sizeof(accounting), nullptr)) {
            value_.accounting_available = true;
            value_.user_ticks = accounting.TotalUserTime.QuadPart;
            value_.kernel_ticks = accounting.TotalKernelTime.QuadPart;
            value_.processes_total = accounting.TotalProcesses;
            value_.processes_active = accounting.ActiveProcesses;
        } else value_.accounting_error = GetLastError();
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION memory{};
        if (QueryInformationJobObject(job_, JobObjectExtendedLimitInformation,
                &memory, sizeof(memory), nullptr)) {
            value_.memory_available = true;
            value_.peak_job_memory_bytes = static_cast<uint64_t>(memory.PeakJobMemoryUsed);
        } else value_.memory_error = GetLastError();
    }
};

inline std::string process_performance_json(const ProcessPerformance& value) {
    const char* coverage = !value.launched ? "not-started" :
        !value.accounting_available && !value.memory_available ? "unavailable" :
        value.accounting_available && value.memory_available && !value.processes_active ? "complete" : "partial";
    std::ostringstream out;
    out.imbue(std::locale::classic());
    out << "{\"schema\":1,\"source\":\"windows-job-object\",\"scope\":\""
        << (value.pipeline ? "pipeline-process-tree" : "command-process-tree")
        << "\",\"wall_ms\":" << (value.wall_available ? std::to_string(value.wall_ms) : "null")
        << ",\"user_cpu_seconds\":";
    if (value.accounting_available) out << std::fixed << std::setprecision(7) << static_cast<double>(value.user_ticks) / 10000000.0;
    else out << "null";
    out << ",\"kernel_cpu_seconds\":";
    if (value.accounting_available) out << std::fixed << std::setprecision(7) << static_cast<double>(value.kernel_ticks) / 10000000.0;
    else out << "null";
    out << ",\"peak_job_memory_bytes\":" << (value.memory_available ? std::to_string(value.peak_job_memory_bytes) : "null")
        << ",\"memory_kind\":\"committed\",\"processes_total\":"
        << (value.accounting_available ? std::to_string(value.processes_total) : "null")
        << ",\"processes_active_at_snapshot\":"
        << (value.accounting_available ? std::to_string(value.processes_active) : "null")
        << ",\"accounting_available\":" << (value.accounting_available ? "true" : "false")
        << ",\"memory_available\":" << (value.memory_available ? "true" : "false")
        << ",\"coverage\":\"" << coverage << "\",\"snapshot\":\"before-job-close\",\"accounting_error\":"
        << (value.accounting_error ? std::to_string(value.accounting_error) : "null")
        << ",\"memory_error\":" << (value.memory_error ? std::to_string(value.memory_error) : "null") << '}';
    return out.str();
}
} // namespace bw
