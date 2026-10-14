#include "workbench.h"
#include <algorithm>
#include <limits>
#include <stdexcept>

namespace bw {
namespace {
struct Handle {
    HANDLE value;
    explicit Handle(HANDLE h) : value(h) {}
    ~Handle() { if (value != INVALID_HANDLE_VALUE && value) CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};
[[noreturn]] void error(const char* operation, DWORD code = GetLastError()) {
    throw std::runtime_error(std::string(operation) + ": " + utf8(windows_error(code)));
}
}

std::wstring executable_folder() {
    std::vector<wchar_t> buffer(1024);
    for (;;) {
        DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (!length) error("Find application folder");
        if (length < buffer.size()) {
            std::wstring path(buffer.data(), length);
            size_t slash = path.find_last_of(L"\\/");
            if (slash == std::wstring::npos) throw std::runtime_error("Application folder is unavailable");
            return path.substr(0, slash);
        }
        if (buffer.size() >= 32768) throw std::runtime_error("Application path is too long");
        buffer.resize(std::min<size_t>(32768, buffer.size() * 2));
    }
}

std::wstring join(const std::wstring& parent, const std::wstring& child) {
    if (parent.empty()) return child;
    return parent + ((parent.back() == L'\\' || parent.back() == L'/') ? L"" : L"\\") + child;
}

std::wstring native_path(const std::wstring& path) {
    if (path.empty() || path.find(L'\0') != std::wstring::npos)
        throw std::runtime_error("A filesystem path is empty or contains a null character");
    std::wstring ordinary = path;
    std::replace(ordinary.begin(), ordinary.end(), L'/', L'\\');
    // Accept only filesystem forms of an existing extended path. Normalize
    // dot components before adding the prefix, which disables Win32 parsing.
    if (_wcsnicmp(ordinary.c_str(), L"\\\\?\\UNC\\", 8) == 0)
        ordinary = L"\\\\" + ordinary.substr(8);
    else if (ordinary.compare(0, 4, L"\\\\?\\") == 0) {
        if (ordinary.size() < 7 || ordinary[5] != L':' || ordinary[6] != L'\\')
            throw std::runtime_error("Unsupported filesystem path namespace");
        ordinary.erase(0, 4);
    }
    if (ordinary.compare(0, 4, L"\\\\.\\") == 0 || ordinary.compare(0, 4, L"\\??\\") == 0)
        throw std::runtime_error("Device paths are not filesystem paths");
    DWORD needed = GetFullPathNameW(ordinary.c_str(), 0, nullptr, nullptr);
    if (!needed) error("Resolve filesystem path");
    if (needed > 32767) throw std::runtime_error("Filesystem path exceeds the Windows length limit");
    std::vector<wchar_t> buffer(static_cast<size_t>(needed) + 1);
    DWORD length = GetFullPathNameW(ordinary.c_str(), static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    if (!length || length >= buffer.size()) error("Resolve filesystem path");
    std::wstring absolute(buffer.data(), length), result;
    if (absolute.compare(0, 2, L"\\\\") == 0)
        result = L"\\\\?\\UNC\\" + absolute.substr(2);
    else if (absolute.size() >= 3 && absolute[1] == L':' && absolute[2] == L'\\' &&
             ((absolute[0] >= L'A' && absolute[0] <= L'Z') || (absolute[0] >= L'a' && absolute[0] <= L'z')))
        result = L"\\\\?\\" + absolute;
    else throw std::runtime_error("Cannot form an absolute filesystem path");
    if (result.size() >= 32767) throw std::runtime_error("Filesystem path exceeds the Windows length limit");
    return result;
}

std::wstring utf16(const std::string& text) {
    if (text.empty()) return {};
    if (text.size() > static_cast<size_t>(INT_MAX)) throw std::runtime_error("Text is too long");
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (!length) throw std::runtime_error("Invalid UTF-8 text");
    std::wstring result(static_cast<size_t>(length), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), result.data(), length) != length)
        throw std::runtime_error("UTF-8 conversion failed");
    return result;
}

std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    if (text.size() > static_cast<size_t>(INT_MAX)) throw std::runtime_error("Text is too long");
    int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (!length) throw std::runtime_error("Invalid UTF-16 text");
    std::string result(static_cast<size_t>(length), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), result.data(), length, nullptr, nullptr) != length)
        throw std::runtime_error("UTF-16 conversion failed");
    return result;
}

std::string json_string(const std::wstring& value) {
    const std::string bytes = utf8(value);
    static const char hex[] = "0123456789abcdef";
    std::string result = "\"";
    for (unsigned char byte : bytes) {
        if (byte == '"' || byte == '\\') { result += '\\'; result += static_cast<char>(byte); }
        else if (byte < 32) { result += "\\u00"; result += hex[byte >> 4]; result += hex[byte & 15]; }
        else result += static_cast<char>(byte);
    }
    result += '"';
    return result;
}

std::wstring windows_error(DWORD code) {
    wchar_t* message = nullptr;
    DWORD count = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr, code, 0, reinterpret_cast<wchar_t*>(&message), 0, nullptr);
    std::wstring result = count && message ? std::wstring(message, count) : L"Windows error " + std::to_wstring(code);
    if (message) LocalFree(message);
    while (!result.empty() && (result.back() == L'\r' || result.back() == L'\n' || result.back() == L' ')) result.pop_back();
    return result;
}

bool file_exists(const std::wstring& path) {
    if (path.empty()) return false;
    DWORD attr = GetFileAttributesW(native_path(path).c_str());
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}
bool directory_exists(const std::wstring& path) {
    if (path.empty()) return false;
    DWORD attr = GetFileAttributesW(native_path(path).c_str());
    return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
}

std::string read_file(const std::wstring& path, size_t max_bytes) {
    Handle file(CreateFileW(native_path(path).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) error("Read file");
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file.value, &size)) error("Read file size");
    if (size.QuadPart < 0 || static_cast<unsigned long long>(size.QuadPart) > max_bytes)
        throw std::runtime_error("File exceeds the size allowed for this operation");
    std::string result(static_cast<size_t>(size.QuadPart), '\0');
    size_t done = 0;
    while (done < result.size()) {
        DWORD got = 0, request = static_cast<DWORD>(std::min<size_t>(result.size() - done, 1024 * 1024));
        if (!ReadFile(file.value, result.data() + done, request, &got, nullptr)) error("Read file data");
        if (!got) throw std::runtime_error("File changed while it was being read");
        done += got;
    }
    return result;
}

void write_file_new(const std::wstring& path, const std::string& bytes) {
    const auto filesystem_path = native_path(path);
    HANDLE file = CreateFileW(filesystem_path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) error("Create new file");
    try {
        size_t done = 0;
        while (done < bytes.size()) {
            DWORD wrote = 0, request = static_cast<DWORD>(std::min<size_t>(bytes.size() - done, 1024 * 1024));
            if (!WriteFile(file, bytes.data() + done, request, &wrote, nullptr)) error("Write file");
            if (!wrote) throw std::runtime_error("Writing file made no progress");
            done += wrote;
        }
        if (!FlushFileBuffers(file)) error("Flush file");
        if (!CloseHandle(file)) { file = INVALID_HANDLE_VALUE; error("Close output file"); }
        file = INVALID_HANDLE_VALUE;
    } catch (...) {
        if (file != INVALID_HANDLE_VALUE) CloseHandle(file);
        DeleteFileW(filesystem_path.c_str());
        throw;
    }
}

std::wstring unique_directory(const std::wstring& parent, const std::wstring& prefix) {
    if (!directory_exists(parent)) throw std::runtime_error("Choose an existing output folder");
    if (prefix.empty() || prefix.find_first_not_of(L"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") != std::wstring::npos)
        throw std::runtime_error("Invalid generated folder prefix");
    SYSTEMTIME now{};
    GetSystemTime(&now);
    wchar_t date[64]{};
    swprintf(date, 64, L"%04u%02u%02u-%02u%02u%02u-%lu", now.wYear, now.wMonth, now.wDay, now.wHour, now.wMinute, now.wSecond, GetCurrentProcessId());
    std::wstring stem = join(parent, prefix + L"-" + date);
    for (unsigned i = 0; i < 10000; ++i) {
        std::wstring path = stem + L"-" + std::to_wstring(i);
        if (CreateDirectoryW(native_path(path).c_str(), nullptr)) return path;
        DWORD code = GetLastError();
        if (code != ERROR_ALREADY_EXISTS && code != ERROR_FILE_EXISTS) error("Create results folder", code);
    }
    throw std::runtime_error("Cannot allocate a unique results folder");
}

void check_cancel(const Cancel& cancel) {
    if (cancel.load()) throw std::runtime_error("Cancelled");
}
} // namespace bw
