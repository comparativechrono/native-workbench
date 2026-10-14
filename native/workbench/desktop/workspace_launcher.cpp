// Native, console-free entry point. All analysis and web hosting stay local.
// The private Python runtime is addressed explicitly; PATH and the registry are
// never used to find an interpreter, and no shell command is constructed.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <algorithm>
#include <string>
#include <vector>

namespace {
struct Handle {
    HANDLE value = nullptr;
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
};
struct Failure { std::wstring message; };
[[noreturn]] void fail(const std::wstring& message) { throw Failure{message}; }
std::wstring error(DWORD code) {
    wchar_t* message = nullptr;
    const DWORD size = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
        FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, code, 0, reinterpret_cast<wchar_t*>(&message), 0, nullptr);
    std::wstring text = size && message ? std::wstring(message, size) : L"Windows error " + std::to_wstring(code);
    if (message) LocalFree(message);
    while (!text.empty() && (text.back() == L'\r' || text.back() == L'\n')) text.pop_back();
    return text + L" (" + std::to_wstring(code) + L")";
}
std::wstring application_folder() {
    std::vector<wchar_t> buffer(1024);
    for (;;) {
        const DWORD size = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (!size) fail(L"Windows could not locate the Workbench application folder.\n\n" + error(GetLastError()));
        if (size < buffer.size()) {
            const std::wstring path(buffer.data(), size);
            const auto slash = path.find_last_of(L"\\/");
            if (slash == path.npos) fail(L"The Workbench application folder is unavailable.");
            return path.substr(0, slash);
        }
        if (buffer.size() >= 32768) fail(L"The Workbench application path exceeds the Windows path limit.");
        buffer.resize(std::min<size_t>(32768, buffer.size() * 2));
    }
}
std::wstring filesystem_path(std::wstring path) {
    std::replace(path.begin(), path.end(), L'/', L'\\');
    if (path.compare(0, 4, L"\\\\?\\") == 0) return path;
    if (path.compare(0, 2, L"\\\\") == 0) return L"\\\\?\\UNC\\" + path.substr(2);
    return L"\\\\?\\" + path;
}
bool file_exists(const std::wstring& path) {
    const DWORD attrs = GetFileAttributesW(filesystem_path(path).c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}
std::wstring quote(const std::wstring& argument) {
    // CommandLineToArgvW / Microsoft CRT quoting. A filename such as a trailing
    // backslash or containing quotes cannot change the following argv element.
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (const wchar_t c : argument) {
        if (c == L'\\') { ++slashes; continue; }
        if (c == L'"') { result.append(slashes * 2 + 1, L'\\'); result += c; }
        else { result.append(slashes, L'\\'); result += c; }
        slashes = 0;
    }
    result.append(slashes * 2, L'\\');
    return result + L'"';
}
void verify_arguments(const std::vector<std::wstring>& arguments) {
    // Check our quoting against Windows' parser before executing anything.
    std::wstring line;
    for (const auto& argument : arguments) { if (!line.empty()) line += L' '; line += quote(argument); }
    if (line.size() >= 32767) fail(L"The Workbench command exceeds the Windows command-line limit.\n\nMove the extracted Workbench folder closer to the root of your drive, then try again.");
    int count = 0;
    LPWSTR* parsed = CommandLineToArgvW(line.c_str(), &count);
    if (!parsed) fail(L"Windows could not verify the Workbench launch arguments.");
    bool same = static_cast<size_t>(count) == arguments.size();
    if (same) for (size_t i = 0; i < arguments.size(); ++i) if (parsed[i] != arguments[i]) { same = false; break; }
    LocalFree(parsed);
    if (!same) fail(L"Windows could not preserve the Workbench launch arguments.");
}
int launch(const std::wstring& root, bool classic, bool check) {
    const std::wstring executable = root + (classic ? L"\\NativeWorkbenchClassic.exe" : L"\\runtime\\python\\pythonw.exe");
    const std::wstring script = root + L"\\workspace\\launch.py";
    if (!file_exists(executable)) fail(classic ?
        L"NativeWorkbenchClassic.exe is missing.\n\nExtract the complete Workbench ZIP into a new folder and try again." :
        L"The bundled Python runtime is missing (runtime\\python\\pythonw.exe).\n\nExtract the complete Workbench ZIP into a new folder and try again. You do not need to install Python.");
    if (!classic && !file_exists(script)) fail(L"The Workbench startup file is missing (workspace\\launch.py).\n\nExtract the complete Workbench ZIP into a new folder and try again.");
    std::vector<std::wstring> arguments{executable};
    if (!classic) {
        arguments.insert(arguments.end(), {L"-I", script, L"--app-root", root});
        if (check) arguments.emplace_back(L"--check");
    }
    verify_arguments(arguments);
    std::wstring command;
    for (const auto& argument : arguments) { if (!command.empty()) command += L' '; command += quote(argument); }
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = classic ? SW_SHOWNORMAL : SW_HIDE;
    PROCESS_INFORMATION info{};
    if (!CreateProcessW(filesystem_path(executable).c_str(), command.data(), nullptr, nullptr, FALSE,
            classic ? 0 : CREATE_NO_WINDOW, nullptr, root.c_str(), &startup, &info))
        fail(L"Windows could not start Native Workbench.\n\n" + error(GetLastError()) +
             L"\n\nExtract the complete ZIP into a writable folder and try again.");
    Handle process{info.hProcess};
    Handle thread{info.hThread};
    const DWORD waited = WaitForSingleObject(process.value, INFINITE);
    if (waited != WAIT_OBJECT_0) fail(L"Windows could not monitor the Workbench process.\n\n" + error(GetLastError()));
    DWORD code = 0;
    if (!GetExitCodeProcess(process.value, &code)) fail(L"Windows could not read the Workbench exit status.\n\n" + error(GetLastError()));
    if (code != 0) {
        fail(L"Native Workbench closed with an error (exit code " + std::to_wstring(code) +
             L").\n\nIf workspace-startup-error.txt was created in the Workbench folder, it contains the startup details.\n\nRun check-workspace-windows.cmd for installation diagnostics.");
    }
    return 0;
}
} // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    try {
        int count = 0;
        LPWSTR* args = CommandLineToArgvW(GetCommandLineW(), &count);
        if (!args) fail(L"Windows could not read the Workbench startup options.");
        bool classic = false, check = false, valid = count >= 1 && count <= 2;
        if (valid && count == 2) {
            classic = std::wstring(args[1]) == L"--classic";
            check = std::wstring(args[1]) == L"--check";
            valid = classic || check;
        }
        LocalFree(args);
        if (!valid) fail(L"Unsupported Workbench startup option.\n\nStart NativeWorkbench.exe normally, use --check for installation diagnostics, or --classic for the previous interface.");
        return launch(application_folder(), classic, check);
    } catch (const Failure& failure) {
        MessageBoxW(nullptr, failure.message.c_str(), L"Native Workbench", MB_OK | MB_ICONERROR);
    } catch (...) {
        MessageBoxW(nullptr, L"Native Workbench could not start.\n\nExtract the complete ZIP into a new folder, then run check-workspace-windows.cmd for installation diagnostics.",
            L"Native Workbench", MB_OK | MB_ICONERROR);
    }
    return 1;
}
