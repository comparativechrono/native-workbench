#include "desktop_ipc.h"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace desktop {
namespace {
constexpr unsigned max_depth = 64;
constexpr std::size_t max_values = 200000;

void valid_utf8(const std::string& text) {
    for (std::size_t p = 0; p < text.size();) {
        const unsigned char first = static_cast<unsigned char>(text[p++]);
        if (first < 0x80) continue;
        unsigned code = 0, continuation = 0, minimum = 0;
        if (first >= 0xc2 && first <= 0xdf) { code = first & 31; continuation = 1; minimum = 0x80; }
        else if (first >= 0xe0 && first <= 0xef) { code = first & 15; continuation = 2; minimum = 0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { code = first & 7; continuation = 3; minimum = 0x10000; }
        else throw std::runtime_error("Invalid UTF-8 in desktop protocol");
        if (text.size() - p < continuation) throw std::runtime_error("Incomplete UTF-8 in desktop protocol");
        while (continuation--) {
            const unsigned char next = static_cast<unsigned char>(text[p++]);
            if ((next & 0xc0) != 0x80) throw std::runtime_error("Invalid UTF-8 continuation in desktop protocol");
            code = (code << 6) | (next & 63);
        }
        if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff))
            throw std::runtime_error("Invalid Unicode scalar in desktop protocol");
    }
}
void append_unicode(std::string& text, unsigned code) {
    if (code < 0x80) text += static_cast<char>(code);
    else if (code < 0x800) {
        text += static_cast<char>(0xc0 | (code >> 6));
        text += static_cast<char>(0x80 | (code & 63));
    } else if (code < 0x10000) {
        text += static_cast<char>(0xe0 | (code >> 12));
        text += static_cast<char>(0x80 | ((code >> 6) & 63));
        text += static_cast<char>(0x80 | (code & 63));
    } else {
        text += static_cast<char>(0xf0 | (code >> 18));
        text += static_cast<char>(0x80 | ((code >> 12) & 63));
        text += static_cast<char>(0x80 | ((code >> 6) & 63));
        text += static_cast<char>(0x80 | (code & 63));
    }
}
class Parser {
    const std::string& source_;
    std::size_t position_ = 0, values_ = 0;
    [[noreturn]] void fail() const {
        throw std::runtime_error("Invalid desktop protocol JSON at byte " + std::to_string(position_));
    }
    void whitespace() {
        while (position_ < source_.size() && (source_[position_] == ' ' || source_[position_] == '\t' ||
            source_[position_] == '\n' || source_[position_] == '\r')) ++position_;
    }
    bool take(char wanted) {
        if (position_ < source_.size() && source_[position_] == wanted) { ++position_; return true; }
        return false;
    }
    unsigned hex4() {
        unsigned value = 0;
        for (unsigned i = 0; i < 4; ++i) {
            if (position_ == source_.size()) fail();
            const char digit = source_[position_++];
            value <<= 4;
            if (digit >= '0' && digit <= '9') value += digit - '0';
            else if (digit >= 'a' && digit <= 'f') value += digit - 'a' + 10;
            else if (digit >= 'A' && digit <= 'F') value += digit - 'A' + 10;
            else fail();
        }
        return value;
    }
    std::string string() {
        if (!take('"')) fail();
        std::string result;
        while (position_ < source_.size()) {
            const unsigned char current = static_cast<unsigned char>(source_[position_++]);
            if (current == '"') return result;
            if (current < 0x20) fail();
            if (current != '\\') { result += static_cast<char>(current); continue; }
            if (position_ == source_.size()) fail();
            switch (source_[position_++]) {
            case '"': result += '"'; break;
            case '\\': result += '\\'; break;
            case '/': result += '/'; break;
            case 'b': result += '\b'; break;
            case 'f': result += '\f'; break;
            case 'n': result += '\n'; break;
            case 'r': result += '\r'; break;
            case 't': result += '\t'; break;
            case 'u': {
                unsigned code = hex4();
                if (code >= 0xd800 && code <= 0xdbff) {
                    if (!take('\\') || !take('u')) fail();
                    const unsigned low = hex4();
                    if (low < 0xdc00 || low > 0xdfff) fail();
                    code = 0x10000 + ((code - 0xd800) << 10) + low - 0xdc00;
                } else if (code >= 0xdc00 && code <= 0xdfff) fail();
                append_unicode(result, code);
                break;
            }
            default: fail();
            }
        }
        fail();
    }
    bool literal(const char* word) {
        const std::string wanted(word);
        if (source_.compare(position_, wanted.size(), wanted) != 0) return false;
        position_ += wanted.size();
        return true;
    }
    Json number() {
        const std::size_t begin = position_;
        take('-');
        if (take('0')) {
            if (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') fail();
        } else {
            if (position_ == source_.size() || source_[position_] < '1' || source_[position_] > '9') fail();
            while (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') ++position_;
        }
        if (take('.')) {
            const std::size_t begin_fraction = position_;
            while (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') ++position_;
            if (position_ == begin_fraction) fail();
        }
        if (take('e') || take('E')) {
            if (!take('+')) take('-');
            const std::size_t begin_exponent = position_;
            while (position_ < source_.size() && source_[position_] >= '0' && source_[position_] <= '9') ++position_;
            if (position_ == begin_exponent) fail();
        }
        if (position_ - begin > 128) fail();
        std::istringstream stream(source_.substr(begin, position_ - begin));
        stream.imbue(std::locale::classic());
        double result = 0;
        stream >> result;
        if (!stream || !stream.eof() || !std::isfinite(result)) fail();
        return Json(result);
    }
    Json value(unsigned depth) {
        whitespace();
        if (position_ == source_.size() || depth > max_depth || ++values_ > max_values) fail();
        if (source_[position_] == '"') return Json(string());
        if (take('{')) {
            Json::Object result;
            whitespace();
            if (take('}')) return result;
            for (;;) {
                whitespace();
                const auto key = string();
                whitespace();
                if (!take(':')) fail();
                if (!result.emplace(key, value(depth + 1)).second) fail();
                whitespace();
                if (take('}')) return result;
                if (!take(',')) fail();
            }
        }
        if (take('[')) {
            Json::Array result;
            whitespace();
            if (take(']')) return result;
            for (;;) {
                result.emplace_back(value(depth + 1));
                whitespace();
                if (take(']')) return result;
                if (!take(',')) fail();
            }
        }
        if (literal("null")) return nullptr;
        if (literal("true")) return true;
        if (literal("false")) return false;
        return number();
    }
public:
    explicit Parser(const std::string& source) : source_(source) {}
    Json parse() {
        if (source_.size() > Json::max_bytes) throw std::runtime_error("Desktop protocol JSON exceeds 8 MiB");
        valid_utf8(source_);
        Json result = value(0);
        whitespace();
        if (position_ != source_.size()) fail();
        return result;
    }
};
void bounded_append(std::string& result, const std::string& text) {
    if (text.size() > Json::max_bytes - result.size()) throw std::runtime_error("Desktop protocol JSON exceeds 8 MiB");
    result += text;
}
void dump_string(std::string& result, const std::string& text) {
    valid_utf8(text);
    bounded_append(result, "\"");
    static constexpr char hex[] = "0123456789abcdef";
    for (const unsigned char current : text) {
        switch (current) {
        case '"': bounded_append(result, "\\\""); break;
        case '\\': bounded_append(result, "\\\\"); break;
        case '\b': bounded_append(result, "\\b"); break;
        case '\f': bounded_append(result, "\\f"); break;
        case '\n': bounded_append(result, "\\n"); break;
        case '\r': bounded_append(result, "\\r"); break;
        case '\t': bounded_append(result, "\\t"); break;
        default:
            if (current < 0x20) {
                std::string escape = "\\u00";
                escape += hex[current >> 4]; escape += hex[current & 15];
                bounded_append(result, escape);
            } else bounded_append(result, std::string(1, static_cast<char>(current)));
        }
    }
    bounded_append(result, "\"");
}
void dump_value(std::string& result, const Json& value, unsigned depth, std::size_t& values) {
    if (depth > max_depth || ++values > max_values) throw std::runtime_error("Desktop protocol JSON is too complex");
    switch (value.type()) {
    case Json::Type::Null: bounded_append(result, "null"); break;
    case Json::Type::Bool: bounded_append(result, value.boolean() ? "true" : "false"); break;
    case Json::Type::Number: {
        std::ostringstream stream;
        stream.imbue(std::locale::classic());
        stream << std::setprecision(std::numeric_limits<double>::max_digits10) << value.number();
        bounded_append(result, stream.str()); break;
    }
    case Json::Type::String: dump_string(result, value.string()); break;
    case Json::Type::Array: {
        bounded_append(result, "[");
        bool first = true;
        for (const auto& item : value.array_items()) {
            if (!first) bounded_append(result, ",");
            first = false;
            dump_value(result, item, depth + 1, values);
        }
        bounded_append(result, "]"); break;
    }
    case Json::Type::Object: {
        bounded_append(result, "{");
        bool first = true;
        for (const auto& item : value.object_items()) {
            if (!first) bounded_append(result, ",");
            first = false;
            dump_string(result, item.first);
            bounded_append(result, ":");
            dump_value(result, item.second, depth + 1, values);
        }
        bounded_append(result, "}"); break;
    }
    }
}
} // namespace

Json::Json(double value) : value_(value) {
    if (!std::isfinite(value)) throw std::runtime_error("JSON numbers must be finite");
}
Json Json::parse(const std::string& text) { return Parser(text).parse(); }
std::string Json::dump() const {
    std::string result;
    std::size_t values = 0;
    dump_value(result, *this, 0, values);
    return result;
}
bool Json::contains(const std::string& key) const { return is_object() && object_items().count(key) != 0; }
std::size_t Json::size() const noexcept {
    if (is_array()) return std::get<Array>(value_).size();
    if (is_object()) return std::get<Object>(value_).size();
    if (is_string()) return std::get<std::string>(value_).size();
    return 0;
}
const Json& Json::get(const std::string& key) const noexcept {
    static const Json missing;
    if (!is_object()) return missing;
    const auto& members = std::get<Object>(value_);
    const auto found = members.find(key);
    return found == members.end() ? missing : found->second;
}
Json& Json::operator[](const std::string& key) {
    if (is_null()) value_ = Object{};
    return object_items()[key];
}
const Json& Json::operator[](std::size_t index) const { return array_items().at(index); }
Json& Json::operator[](std::size_t index) { return array_items().at(index); }
std::string Json::string(const std::string& fallback) const { return is_string() ? std::get<std::string>(value_) : fallback; }
double Json::number(double fallback) const noexcept { return is_number() ? std::get<double>(value_) : fallback; }
long long Json::integer(long long fallback) const noexcept {
    if (!is_number()) return fallback;
    const double value = std::get<double>(value_);
    if (value < -9223372036854775808.0 || value >= 9223372036854775808.0 || std::floor(value) != value) return fallback;
    return static_cast<long long>(value);
}
bool Json::boolean(bool fallback) const noexcept { return is_bool() ? std::get<bool>(value_) : fallback; }
const Json::Array& Json::array_items() const {
    if (!is_array()) throw std::runtime_error("Expected a JSON array");
    return std::get<Array>(value_);
}
Json::Array& Json::array_items() {
    if (!is_array()) throw std::runtime_error("Expected a JSON array");
    return std::get<Array>(value_);
}
const Json::Object& Json::object_items() const {
    if (!is_object()) throw std::runtime_error("Expected a JSON object");
    return std::get<Object>(value_);
}
Json::Object& Json::object_items() {
    if (!is_object()) throw std::runtime_error("Expected a JSON object");
    return std::get<Object>(value_);
}

void JsonLineFramer::feed(const char* bytes, std::size_t size, const std::function<void(std::string)>& emit) {
    if (!size) return;
    if (!bytes) throw std::runtime_error("Invalid desktop host protocol chunk");
    std::size_t begin = 0;
    for (std::size_t p = 0; p < size; ++p) {
        if (bytes[p] != '\n') continue;
        if (p - begin > Json::max_bytes - pending_.size())
            throw std::runtime_error("The desktop host protocol line exceeds 8 MiB");
        pending_.append(bytes + begin, p - begin);
        if (!pending_.empty() && pending_.back() == '\r') pending_.pop_back();
        if (pending_.empty()) throw std::runtime_error("The desktop host returned an empty protocol line");
        valid_utf8(pending_);
        auto line = std::move(pending_);
        pending_.clear();
        emit(std::move(line));
        begin = p + 1;
    }
    if (size - begin > Json::max_bytes - pending_.size())
        throw std::runtime_error("The desktop host protocol line exceeds 8 MiB");
    pending_.append(bytes + begin, size - begin);
}
void JsonLineFramer::finish() const {
    if (!pending_.empty()) throw std::runtime_error("The desktop host returned an incomplete protocol message");
}

} // namespace desktop

#ifndef DESKTOP_JSON_ONLY
#include <bcrypt.h>
#include <atomic>
#include <mutex>

namespace desktop {
namespace {
class Handle {
public:
    HANDLE value = nullptr;
    Handle() = default;
    explicit Handle(HANDLE handle) : value(handle) {}
    ~Handle() { reset(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    void reset(HANDLE handle = nullptr) noexcept {
        if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value);
        value = handle;
    }
    HANDLE release() noexcept { const HANDLE result = value; value = nullptr; return result; }
};
[[noreturn]] void windows_error(const char* operation, DWORD code = GetLastError()) {
    throw std::runtime_error(std::string(operation) + " (Windows error " + std::to_string(code) + ")");
}
std::wstring native_path(const std::wstring& path) {
    if (path.rfind(L"\\\\?\\", 0) == 0) return path;
    if (path.rfind(L"\\\\", 0) == 0) return L"\\\\?\\UNC\\" + path.substr(2);
    return L"\\\\?\\" + path;
}
std::wstring absolute_path(const std::wstring& path) {
    if (path.empty() || path.find(L'\0') != std::wstring::npos)
        throw std::runtime_error("The desktop host application folder is invalid");
    const DWORD size = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (!size) windows_error("Cannot resolve application folder");
    std::wstring result(size, L'\0');
    const DWORD used = GetFullPathNameW(path.c_str(), size, result.data(), nullptr);
    if (!used || used >= size) windows_error("Cannot resolve application folder");
    result.resize(used);
    while (result.size() > 3 && (result.back() == L'\\' || result.back() == L'/')) result.pop_back();
    return result;
}
void require_file(const std::wstring& path, const char* description) {
    const DWORD attributes = GetFileAttributesW(native_path(path).c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY))
        throw std::runtime_error(std::string("The bundled ") + description + " is missing. Extract the complete Workbench archive and try again.");
}
std::wstring quote(const std::wstring& argument) {
    if (argument.find(L'\0') != std::wstring::npos) throw std::runtime_error("Invalid NUL in desktop launch argument");
    std::wstring result = L"\"";
    std::size_t backslashes = 0;
    for (const wchar_t current : argument) {
        if (current == L'\\') { ++backslashes; continue; }
        if (current == L'"') result.append(backslashes * 2 + 1, L'\\');
        else result.append(backslashes, L'\\');
        result += current;
        backslashes = 0;
    }
    result.append(backslashes * 2, L'\\');
    return result + L'"';
}
std::wstring launch_directory(const std::wstring& root) {
    // Windows documents that CreateProcessW can fail when its current
    // directory exceeds MAX_PATH, even with long-path-aware file APIs. All
    // interpreter/script/application arguments are absolute, so a short
    // Windows directory is a safe launch cwd for a deeply nested install.
    if (root.size() <= MAX_PATH - 2) return root;
    std::wstring directory(MAX_PATH + 1, L'\0');
    const UINT used = GetWindowsDirectoryW(directory.data(), static_cast<UINT>(directory.size()));
    if (!used || used > MAX_PATH - 2)
        throw std::runtime_error("Cannot choose a short working directory for the desktop host. Move Workbench closer to the root of the drive.");
    directory.resize(used);
    return directory;
}
void make_pipe(Handle& read, Handle& write, bool parent_reads) {
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    if (!CreatePipe(&read.value, &write.value, &security, 65536)) windows_error("Cannot create desktop host pipe");
    if (!SetHandleInformation(parent_reads ? read.value : write.value, HANDLE_FLAG_INHERIT, 0))
        windows_error("Cannot secure desktop host pipe inheritance");
}
struct AttributeList {
    std::vector<unsigned char> storage;
    LPPROC_THREAD_ATTRIBUTE_LIST value = nullptr;
    explicit AttributeList(const std::vector<HANDLE>& handles) {
        SIZE_T bytes = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
        if (!bytes) windows_error("Cannot size desktop host process attributes");
        storage.resize(bytes);
        value = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        if (!InitializeProcThreadAttributeList(value, 1, 0, &bytes)) { value = nullptr; windows_error("Cannot initialize desktop host process attributes"); }
        if (!UpdateProcThreadAttribute(value, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                const_cast<HANDLE*>(handles.data()), handles.size() * sizeof(HANDLE), nullptr, nullptr)) {
            const DWORD code = GetLastError();
            DeleteProcThreadAttributeList(value); value = nullptr;
            windows_error("Cannot restrict desktop host handle inheritance", code);
        }
    }
    ~AttributeList() { if (value) DeleteProcThreadAttributeList(value); }
};

std::wstring instance_digest(const std::wstring& app_root) {
    auto path = absolute_path(app_root);
    Handle directory(CreateFileW(native_path(path).c_str(), 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS, nullptr));
    if (directory.value != INVALID_HANDLE_VALUE) {
        const DWORD size = GetFinalPathNameByHandleW(directory.value, nullptr, 0, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
        if (size) {
            std::wstring canonical(size + 1, L'\0');
            const DWORD used = GetFinalPathNameByHandleW(directory.value, canonical.data(), static_cast<DWORD>(canonical.size()),
                FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
            if (used && used < canonical.size()) { canonical.resize(used); path = std::move(canonical); }
        }
    }
    std::replace(path.begin(), path.end(), L'/', L'\\');
    if (path.rfind(L"\\\\?\\UNC\\", 0) == 0) path = L"\\\\" + path.substr(8);
    else if (path.rfind(L"\\\\?\\", 0) == 0) path.erase(0, 4);
    while (path.size() > 3 && path.back() == L'\\') path.pop_back();
    const int count = LCMapStringEx(LOCALE_NAME_INVARIANT, LCMAP_LOWERCASE, path.c_str(), static_cast<int>(path.size()),
        nullptr, 0, nullptr, nullptr, 0);
    if (!count) windows_error("Cannot normalize the Workbench instance path");
    std::wstring normalized(static_cast<std::size_t>(count), L'\0');
    if (LCMapStringEx(LOCALE_NAME_INVARIANT, LCMAP_LOWERCASE, path.c_str(), static_cast<int>(path.size()),
        normalized.data(), count, nullptr, nullptr, 0) != count) windows_error("Cannot normalize the Workbench instance path");
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        throw std::runtime_error("Cannot initialize the Workbench instance identity");
    unsigned char digest[32]{};
    const NTSTATUS result = BCryptHash(algorithm, nullptr, 0, reinterpret_cast<PUCHAR>(normalized.data()),
        static_cast<ULONG>(normalized.size() * sizeof(wchar_t)), digest, sizeof(digest));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (result < 0) throw std::runtime_error("Cannot hash the Workbench instance identity");
    static constexpr wchar_t digits[] = L"0123456789abcdef";
    std::wstring text;
    for (const unsigned char value : digest) { text += digits[value >> 4]; text += digits[value & 15]; }
    return text;
}
} // namespace

SingleInstance::SingleInstance(const std::wstring& app_root) {
    const auto digest = instance_digest(app_root);
    window_class_ = L"WorkbenchNativeWorkspace051_" + digest;
    const auto name = L"Local\\WorkbenchNativeWorkspace_" + digest;
    SetLastError(ERROR_SUCCESS);
    mutex_ = CreateMutexW(nullptr, TRUE, name.c_str());
    const DWORD code = GetLastError();
    if (!mutex_) windows_error("Cannot create the Workbench instance lock", code);
    owned_ = code != ERROR_ALREADY_EXISTS;
}
SingleInstance::~SingleInstance() {
    if (owned_) ReleaseMutex(mutex_);
    if (mutex_) CloseHandle(mutex_);
}
bool SingleInstance::show_existing() const noexcept {
    const HWND window = FindWindowW(window_class_.c_str(), nullptr);
    if (!window) return false;
    ShowWindow(window, IsIconic(window) ? SW_RESTORE : SW_SHOW);
    SetForegroundWindow(window);
    return true;
}

struct HostProcess::Impl {
    Handle process, job, input, output, error, diagnostic, reader, error_reader;
    HWND notify_window = nullptr;
    UINT notification_message = 0;
    std::atomic_bool stopping{true};
    std::mutex write_mutex;

    void post(std::string text, WPARAM kind) noexcept {
        if (stopping.load()) return;
        try {
            auto message = std::make_unique<std::string>(std::move(text));
            if (PostMessageW(notify_window, notification_message, kind, reinterpret_cast<LPARAM>(message.get())))
                message.release();
        } catch (...) { /* Nothing may escape the Win32 reader thread. */ }
    }
    void terminal(const std::string& message) noexcept {
        if (stopping.load()) return;
        try {
            DWORD code = STILL_ACTIVE;
            // EOF normally arrives just before process teardown. Do not hold
            // up the GUI if the host closed stdout but has not exited.
            if (process.value) {
                WaitForSingleObject(process.value, 100);
                GetExitCodeProcess(process.value, &code);
            }
            post(Json(Json::Object{{"event", "transport"}, {"message", message}, {"exitCode", code}}).dump(), 1);
        } catch (...) { }
    }
    static DWORD WINAPI read_output(void* context) noexcept {
        auto& self = *static_cast<Impl*>(context);
        try {
            char buffer[16384];
            JsonLineFramer frames;
            while (!self.stopping.load()) {
                DWORD count = 0;
                const BOOL read = ReadFile(self.output.value, buffer, sizeof(buffer), &count, nullptr);
                if (!read || !count) {
                    const DWORD code = read ? ERROR_SUCCESS : GetLastError();
                    if (!self.stopping.load()) {
                        frames.finish();
                        self.terminal("The desktop host closed its output pipe (Windows error " + std::to_string(code) + ")");
                    }
                    return 0;
                }
                frames.feed(buffer, count, [&](std::string line) { self.post(std::move(line), 0); });
            }
        } catch (const std::exception& exception) {
            self.terminal(exception.what());
            if (self.job.value) TerminateJobObject(self.job.value, ERROR_INVALID_DATA);
        } catch (...) {
            self.terminal("The desktop host output reader failed");
            if (self.job.value) TerminateJobObject(self.job.value, ERROR_INVALID_DATA);
        }
        return 0;
    }
    static DWORD WINAPI read_error(void* context) noexcept {
        auto& self = *static_cast<Impl*>(context);
        constexpr std::size_t limit = 4 * 1024 * 1024;
        constexpr char marker[] = "\r\n[Desktop host diagnostic truncated at 4 MiB.]\r\n";
        const std::size_t content_limit = limit - (sizeof(marker) - 1);
        std::size_t total = 0;
        bool truncated = false;
        char buffer[16384];
        while (!self.stopping.load()) {
            DWORD count = 0;
            if (!ReadFile(self.error.value, buffer, sizeof(buffer), &count, nullptr) || !count) break;
            const DWORD keep = static_cast<DWORD>(std::min<std::size_t>(count, content_limit - total));
            DWORD written = 0;
            if (keep) {
                // A diagnostic failure must not stop pipe draining and block
                // the child. Once a disk write fails, discard further stderr.
                if (!WriteFile(self.diagnostic.value, buffer, keep, &written, nullptr) || written != keep) {
                    total = content_limit;
                } else total += keep;
            }
            if (keep < count && !truncated) {
                WriteFile(self.diagnostic.value, marker, sizeof(marker) - 1, &written, nullptr);
                truncated = true;
            }
        }
        return 0;
    }
    void stop() noexcept {
        stopping.store(true);
        // Termination first unblocks a concurrent pipe write before acquiring
        // its mutex. This job also contains all bridge/tool descendants.
        if (job.value) TerminateJobObject(job.value, ERROR_CANCELLED);
        if (reader.value) CancelSynchronousIo(reader.value);
        if (error_reader.value) CancelSynchronousIo(error_reader.value);
        if (reader.value) WaitForSingleObject(reader.value, INFINITE);
        if (error_reader.value) WaitForSingleObject(error_reader.value, INFINITE);
        std::lock_guard<std::mutex> lock(write_mutex);
        input.reset(); output.reset(); error.reset();
        reader.reset(); error_reader.reset(); diagnostic.reset();
        if (process.value) WaitForSingleObject(process.value, 5000);
        process.reset(); job.reset();
        notify_window = nullptr;
        notification_message = 0;
    }
};

HostProcess::HostProcess() : impl_(std::make_unique<Impl>()) {}
HostProcess::~HostProcess() { stop(); }
void HostProcess::start(const std::wstring& app_root, HWND window, UINT message) {
    if (!window || !IsWindow(window) || message < WM_APP || message > 0xbfff)
        throw std::runtime_error("Invalid desktop host notification window or message");
    stop();
    const auto root = absolute_path(app_root);
    const auto python = root + L"\\runtime\\python\\python.exe";
    const auto script = root + L"\\workspace\\desktop_host.py";
    require_file(python, "Python runtime (runtime\\python\\python.exe)");
    require_file(script, "desktop host (workspace\\desktop_host.py)");
    const auto user_data = root + L"\\user-data";
    if (!CreateDirectoryW(native_path(user_data).c_str(), nullptr)) {
        const DWORD code = GetLastError();
        const DWORD attributes = GetFileAttributesW(native_path(user_data).c_str());
        if (code != ERROR_ALREADY_EXISTS || attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY))
            windows_error("Cannot create the Workbench user-data folder", code);
    }
    Handle diagnostic(CreateFileW(native_path(user_data + L"\\desktop-host.stderr.txt").c_str(), GENERIC_WRITE,
        FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (diagnostic.value == INVALID_HANDLE_VALUE) windows_error("Cannot create the desktop host diagnostic log");
    Handle child_input, parent_input, parent_output, child_output, parent_error, child_error;
    make_pipe(child_input, parent_input, false);
    make_pipe(parent_output, child_output, true);
    make_pipe(parent_error, child_error, true);
    Handle job(CreateJobObjectW(nullptr, nullptr));
    if (!job.value) windows_error("Cannot create the desktop host process job");
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
        windows_error("Cannot secure the desktop host process job");
    const std::vector<HANDLE> inherited{child_input.value, child_output.value, child_error.value};
    AttributeList attributes(inherited);
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.StartupInfo.wShowWindow = SW_HIDE;
    startup.StartupInfo.hStdInput = child_input.value;
    startup.StartupInfo.hStdOutput = child_output.value;
    startup.StartupInfo.hStdError = child_error.value;
    startup.lpAttributeList = attributes.value;
    std::wstring command;
    for (const auto& argument : std::vector<std::wstring>{python, L"-I", L"-u", script, L"--app-root", root}) {
        if (!command.empty()) command += L' ';
        command += quote(argument);
    }
    if (command.size() >= 32767) throw std::runtime_error("The Workbench folder path exceeds the Windows command-line limit");
    const auto working_directory = launch_directory(root);
    PROCESS_INFORMATION information{};
    if (!CreateProcessW(native_path(python).c_str(), command.data(), nullptr, nullptr, TRUE,
        CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT,
        nullptr, working_directory.c_str(), &startup.StartupInfo, &information)) windows_error("Cannot start the bundled desktop host");
    Handle process(information.hProcess), main_thread(information.hThread);
    if (!AssignProcessToJobObject(job.value, process.value)) {
        const DWORD code = GetLastError();
        TerminateProcess(process.value, ERROR_CANCELLED);
        windows_error("Cannot attach the desktop host to its process job", code);
    }
    child_input.reset(); child_output.reset(); child_error.reset();
    impl_->process.reset(process.release()); impl_->job.reset(job.release());
    impl_->input.reset(parent_input.release()); impl_->output.reset(parent_output.release());
    impl_->error.reset(parent_error.release()); impl_->diagnostic.reset(diagnostic.release());
    impl_->notify_window = window; impl_->notification_message = message;
    impl_->stopping.store(false);
    try {
        impl_->reader.reset(CreateThread(nullptr, 0, Impl::read_output, impl_.get(), 0, nullptr));
        if (!impl_->reader.value) windows_error("Cannot create the desktop host output reader");
        impl_->error_reader.reset(CreateThread(nullptr, 0, Impl::read_error, impl_.get(), 0, nullptr));
        if (!impl_->error_reader.value) windows_error("Cannot create the desktop host diagnostic reader");
        if (ResumeThread(main_thread.value) == static_cast<DWORD>(-1)) windows_error("Cannot resume the desktop host");
    } catch (...) { stop(); throw; }
}
void HostProcess::send(const Json& request) {
    const std::string line = request.dump() + '\n';
    if (line.size() > max_request_bytes)
        throw std::runtime_error("The native request exceeds the 2 MiB limit. Use a smaller workspace.");
    std::lock_guard<std::mutex> lock(impl_->write_mutex);
    if (impl_->stopping.load() || !impl_->input.value || !alive())
        throw std::runtime_error("The desktop host is not running");
    std::size_t position = 0;
    while (position < line.size()) {
        DWORD written = 0;
        const DWORD count = static_cast<DWORD>(std::min<std::size_t>(65536, line.size() - position));
        if (!WriteFile(impl_->input.value, line.data() + position, count, &written, nullptr) || !written)
            windows_error("Cannot send a request to the desktop host");
        position += written;
    }
}
void HostProcess::stop() noexcept { if (impl_) impl_->stop(); }
bool HostProcess::alive() const noexcept {
    return impl_ && !impl_->stopping.load() && impl_->process.value &&
        WaitForSingleObject(impl_->process.value, 0) == WAIT_TIMEOUT;
}
DWORD HostProcess::exit_code() const noexcept {
    DWORD result = ERROR_INVALID_HANDLE;
    if (impl_ && impl_->process.value) GetExitCodeProcess(impl_->process.value, &result);
    return result;
}
} // namespace desktop
#endif
