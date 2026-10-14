// Core-update entry point. Use the updater's own private interpreter so an
// application runtime can be replaced without locking its DLLs or executable.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <shobjidl.h>
#include <algorithm>
#include <string>
#include <vector>

namespace {
struct Failure { std::wstring message; };
[[noreturn]] void fail(const std::wstring& message) { throw Failure{message}; }
struct Handle {
    HANDLE value = nullptr;
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
};
template<class T> struct Com {
    T* value = nullptr;
    ~Com() { if (value) value->Release(); }
    T** address() { return &value; }
    T* operator->() const { return value; }
};
std::wstring windows_error(DWORD code) {
    wchar_t* buffer = nullptr;
    const DWORD length = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
        FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, code, 0, reinterpret_cast<wchar_t*>(&buffer), 0, nullptr);
    std::wstring message = length && buffer ? std::wstring(buffer, length) : L"Windows error";
    if (buffer) LocalFree(buffer);
    while (!message.empty() && (message.back() == L'\r' || message.back() == L'\n')) message.pop_back();
    return message + L" (" + std::to_wstring(code) + L")";
}
void check(HRESULT code, const wchar_t* operation) {
    if (FAILED(code)) fail(std::wstring(operation) + L"\n\n" + windows_error(static_cast<DWORD>(code)));
}
std::wstring filesystem_path(std::wstring path) {
    std::replace(path.begin(), path.end(), L'/', L'\\');
    if (path.compare(0, 4, L"\\\\?\\") == 0) return path;
    if (path.compare(0, 2, L"\\\\") == 0) return L"\\\\?\\UNC\\" + path.substr(2);
    return L"\\\\?\\" + path;
}
bool file_exists(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(filesystem_path(path).c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}
std::wstring updater_folder() {
    std::vector<wchar_t> buffer(1024);
    for (;;) {
        const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (!length) fail(L"Windows could not locate the updater folder.\n\n" + windows_error(GetLastError()));
        if (length < buffer.size()) {
            const std::wstring path(buffer.data(), length);
            const auto slash = path.find_last_of(L"\\/");
            if (slash == path.npos) fail(L"The updater folder is unavailable.");
            return path.substr(0, slash);
        }
        if (buffer.size() >= 32768) fail(L"The updater path exceeds the Windows path limit.");
        buffer.resize(std::min<size_t>(32768, buffer.size() * 2));
    }
}
std::wstring quote(const std::wstring& argument) {
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
std::wstring choose_workbench() {
    Com<IFileOpenDialog> dialog;
    check(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(dialog.address())), L"Windows could not create the folder picker.");
    FILEOPENDIALOGOPTIONS options = 0;
    check(dialog->GetOptions(&options), L"Windows could not read the folder picker options.");
    check(dialog->SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST |
        FOS_NOCHANGEDIR | FOS_DONTADDTORECENT), L"Windows could not configure the folder picker.");
    check(dialog->SetTitle(L"Select your existing native-workbench folder"), L"Windows could not name the folder picker.");
    check(dialog->SetOkButtonLabel(L"Update this Workbench"), L"Windows could not label the folder picker.");
    const HRESULT selected = dialog->Show(nullptr);
    if (selected == HRESULT_FROM_WIN32(ERROR_CANCELLED)) return {};
    check(selected, L"Windows could not show the folder picker.");
    Com<IShellItem> item;
    check(dialog->GetResult(item.address()), L"Windows could not read the selected folder.");
    PWSTR raw = nullptr;
    check(item->GetDisplayName(SIGDN_FILESYSPATH, &raw), L"Windows could not read the selected folder path.");
    struct Name { PWSTR value; ~Name() { CoTaskMemFree(value); } } name{raw};
    return raw;
}
int run_update(const std::wstring& root, const std::wstring& script, const std::wstring& selected) {
    const std::wstring python = root + L"\\runtime\\python\\python.exe";
    if (!file_exists(python)) fail(L"The updater's private Python runtime is missing. Extract the complete update ZIP before running it.");
    const std::vector<std::wstring> arguments{python, L"-I", script, L"--app-root", selected};
    std::wstring command;
    for (const auto& argument : arguments) { if (!command.empty()) command += L' '; command += quote(argument); }
    if (command.size() >= 32767) fail(L"The update command exceeds the Windows path limit.\n\nMove the extracted updater and Workbench folders closer to the root of the drive and try again.");
    int count = 0;
    LPWSTR* parsed = CommandLineToArgvW(command.c_str(), &count);
    if (!parsed) fail(L"Windows could not verify the updater arguments.");
    bool equal = static_cast<size_t>(count) == arguments.size();
    if (equal) for (size_t i = 0; i < arguments.size(); ++i) if (parsed[i] != arguments[i]) { equal = false; break; }
    LocalFree(parsed);
    if (!equal) fail(L"Windows could not preserve the updater arguments.");
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_SHOWNORMAL;
    PROCESS_INFORMATION info{};
    if (!CreateProcessW(filesystem_path(python).c_str(), command.data(), nullptr, nullptr, FALSE,
            CREATE_NEW_CONSOLE, nullptr, root.c_str(), &startup, &info))
        fail(L"Windows could not start the bundled update interpreter.\n\n" + windows_error(GetLastError()));
    Handle process{info.hProcess};
    Handle thread{info.hThread};
    if (WaitForSingleObject(process.value, INFINITE) != WAIT_OBJECT_0)
        fail(L"Windows could not monitor the updater process.\n\n" + windows_error(GetLastError()));
    DWORD exit_code = 0;
    if (!GetExitCodeProcess(process.value, &exit_code)) fail(L"Windows could not read the updater exit status.\n\n" + windows_error(GetLastError()));
    if (exit_code != 0) fail(L"The Workbench update did not finish successfully (exit code " +
        std::to_wstring(exit_code) + L").\n\nSee the updater console output or update report for details.");
    MessageBoxW(nullptr, L"The Workbench update is installed.\n\nOpen NativeWorkbench.exe in your Workbench folder to start the new workspace.",
        L"Native Workbench update", MB_OK | MB_ICONINFORMATION);
    return 0;
}
} // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    try {
        const auto root = updater_folder();
        const auto script = root + L"\\update\\apply_workspace_update.py";
        if (!file_exists(script)) fail(L"The updater script is missing (update\\apply_workspace_update.py).\n\nExtract the complete update ZIP into a folder, then start UpdateWorkbench.exe again.");
        check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE),
              L"Windows could not initialize the folder picker.");
        struct Apartment { ~Apartment() { CoUninitialize(); } } apartment;
        for (;;) {
            const auto selected = choose_workbench();
            if (selected.empty()) return 0;
            if (file_exists(selected + L"\\NativeWorkbench.exe") && file_exists(selected + L"\\manifest.json"))
                return run_update(root, script, selected);
            MessageBoxW(nullptr, L"This folder does not contain the expected Workbench installation.\n\nSelect the existing native-workbench folder containing NativeWorkbench.exe and manifest.json.",
                L"Choose your existing Workbench", MB_OK | MB_ICONWARNING);
        }
    } catch (const Failure& failure) {
        MessageBoxW(nullptr, failure.message.c_str(), L"Native Workbench update", MB_OK | MB_ICONERROR);
    } catch (...) {
        MessageBoxW(nullptr, L"The Workbench updater could not start.\n\nExtract the complete update ZIP into a new folder and try again.",
            L"Native Workbench update", MB_OK | MB_ICONERROR);
    }
    return 1;
}
