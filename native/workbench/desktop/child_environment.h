#pragma once

#include <string>
#include <vector>
#include <stdexcept>
#include <utility>

#ifdef _WIN32
#include <windows.h>
#endif

namespace bw {

// Pack commands supply their own JVM/Perl arguments and module locations.
// Keep the user's normal Windows environment (including TEMP and SystemRoot),
// but do not let interpreter startup variables silently replace those choices.
// This is process-local reproducibility control, not a security sandbox.
inline bool interpreter_startup_variable(const std::wstring& entry) {
    const auto equals = entry.find(L'=');
    if (equals == std::wstring::npos || equals == 0) return false;
    auto name = entry.substr(0, equals);
    for (auto& c : name) if (c >= L'a' && c <= L'z') c -= L'a' - L'A';
    for (const auto* blocked : {
        L"JAVA_TOOL_OPTIONS", L"_JAVA_OPTIONS", L"JDK_JAVA_OPTIONS", L"CLASSPATH",
        L"PERL5OPT", L"PERL5LIB", L"PERLLIB", L"PERL5SHELL", L"PERL_UNICODE",
        L"PERLIO", L"PERLIO_DEBUG"
    }) if (name == blocked) return true;
    return false;
}

inline std::vector<wchar_t> pack_environment_block(const std::vector<std::wstring>& entries) {
    std::vector<wchar_t> result;
    for (const auto& entry : entries) {
        if (entry.empty() || entry.find(L'\0') != std::wstring::npos)
            throw std::runtime_error("Invalid child environment entry");
        if (interpreter_startup_variable(entry)) continue;
        result.insert(result.end(), entry.begin(), entry.end());
        result.push_back(L'\0');
    }
    if (result.empty()) result.push_back(L'\0');
    result.push_back(L'\0');
    return result;
}

#ifdef _WIN32
inline std::vector<wchar_t> pack_child_environment() {
    wchar_t* raw = GetEnvironmentStringsW();
    if (!raw) throw std::runtime_error("Cannot read the child process environment");
    struct Environment {
        wchar_t* value;
        ~Environment() { FreeEnvironmentStringsW(value); }
    } environment{raw};
    std::vector<std::wstring> entries;
    for (const wchar_t* p = raw; *p;) {
        std::wstring entry(p);
        p += entry.size() + 1;
        entries.push_back(std::move(entry));
    }
    return pack_environment_block(entries);
}
#endif

} // namespace bw
