#include "workbench.h"
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <sstream>
#include <set>
#include <stdexcept>
#include <utility>

namespace bw {
namespace {
// GATK's pinned local JAR is 407 MiB. A self-contained pack also includes
// its Java runtime and corresponding source; retain finite import bounds.
constexpr uint64_t MAX_PACK_BYTES = 1024ull * 1024 * 1024;
constexpr uint64_t MAX_PACK_FILE_BYTES = 512ull * 1024 * 1024;
constexpr size_t MAX_PACK_FILES = 2000;
constexpr size_t MAX_MANIFEST_BYTES = 2 * 1024 * 1024;

[[noreturn]] void fail(const std::wstring& message) { throw std::runtime_error(utf8(message)); }
void log_line(const Log& log, const std::wstring& message) { if (log) log(message); }

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    Handle() = default;
    explicit Handle(HANDLE h) : value(h) {}
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& h) noexcept : value(h.value) { h.value = INVALID_HANDLE_VALUE; }
    Handle& operator=(Handle&& h) noexcept {
        if (this != &h) { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); value = h.value; h.value = INVALID_HANDLE_VALUE; }
        return *this;
    }
    ~Handle() { if (value != INVALID_HANDLE_VALUE) CloseHandle(value); }
};

std::wstring absolute_local(const std::wstring& path) {
    if (path.empty() || path.find(L'\0') != std::wstring::npos) fail(L"A pack folder path is empty or invalid.");
    DWORD needed = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
    if (!needed || needed > 32760) fail(L"Cannot resolve the pack folder: " + windows_error());
    std::vector<wchar_t> buffer(needed + 1);
    DWORD length = GetFullPathNameW(path.c_str(), DWORD(buffer.size()), buffer.data(), nullptr);
    if (!length || length >= buffer.size()) fail(L"Cannot resolve the pack folder.");
    std::wstring result(buffer.data(), length);
    std::replace(result.begin(), result.end(), L'/', L'\\');
    if (result.size() < 3 || result[1] != L':' || result[2] != L'\\' ||
        !((result[0] >= L'A' && result[0] <= L'Z') || (result[0] >= L'a' && result[0] <= L'z')) ||
        result.find(L':', 2) != std::wstring::npos) {
        fail(L"Tool packs must be in a local drive folder, such as C:\\BioWorkbench. Network and device paths are not supported.");
    }
    const std::wstring drive = result.substr(0, 3);
    const UINT type = GetDriveTypeW(drive.c_str());
    if (type != DRIVE_FIXED && type != DRIVE_REMOVABLE && type != DRIVE_RAMDISK && type != DRIVE_CDROM)
        fail(L"Tool packs must be on a local drive; mapped network drives are not supported.");
    while (result.size() > 3 && result.back() == L'\\') result.pop_back();
    for (size_t start = 3; start < result.size();) {
        size_t end = result.find(L'\\', start);
        if (end == std::wstring::npos) end = result.size();
        const auto component = result.substr(start, end - start);
        if (component.empty() || component.back() == L'.' || component.back() == L' ' ||
            component.find_first_of(L"<>\"|?*") != std::wstring::npos)
            fail(L"A tool pack path has an unsupported Windows path component.");
        start = end + 1;
    }
    return result;
}

// Keep checked components open without FILE_SHARE_DELETE. Pack descendants also
// deny writable opens, so they cannot be replaced or changed while being read.
struct PathGuard {
    std::vector<Handle> handles;
    std::set<std::wstring> held;
    void directory(const std::wstring& path, bool lock_writes = true) {
        const auto key = path + (lock_writes ? L"|locked" : L"|shared");
        if (held.count(key)) return;
        Handle h(CreateFileW(native_path(path).c_str(), FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | (lock_writes ? 0 : FILE_SHARE_WRITE), nullptr, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (h.value == INVALID_HANDLE_VALUE) fail(L"Cannot safely open folder " + path + L": " + windows_error());
        BY_HANDLE_FILE_INFORMATION info{};
        if (!GetFileInformationByHandle(h.value, &info)) fail(L"Cannot inspect folder " + path + L": " + windows_error());
        if (!(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
            fail(L"Pack folders must be ordinary folders, without symbolic links, junctions, or other reparse points: " + path);
        handles.push_back(std::move(h));
        held.insert(key);
    }
    void ancestors(const std::wstring& absolute) {
        directory(absolute.substr(0, 3), false);
        for (size_t i = 3; i < absolute.size(); ++i)
            if (absolute[i] == L'\\') directory(absolute.substr(0, i), false);
        if (absolute.size() > 3) directory(absolute);
    }
    void file_parents(const std::wstring& root, std::wstring relative) {
        std::replace(relative.begin(), relative.end(), L'/', L'\\');
        for (size_t i = 0; i < relative.size(); ++i)
            if (relative[i] == L'\\') directory(join(root, relative.substr(0, i)));
    }
};

Handle open_regular(const std::wstring& path) {
    Handle h(CreateFileW(native_path(path).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                        FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr));
    if (h.value == INVALID_HANDLE_VALUE) fail(L"Cannot read " + path + L": " + windows_error());
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(h.value, &info)) fail(L"Cannot inspect " + path + L": " + windows_error());
    if ((info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)) || GetFileType(h.value) != FILE_TYPE_DISK)
        fail(L"Expected an ordinary file without a symbolic link or reparse point: " + path);
    return h;
}

uint64_t file_size(HANDLE h, const std::wstring& path) {
    LARGE_INTEGER length{};
    if (!GetFileSizeEx(h, &length) || length.QuadPart < 0) fail(L"Cannot measure " + path + L": " + windows_error());
    return static_cast<uint64_t>(length.QuadPart);
}

std::string read_bounded(const std::wstring& path, size_t maximum) {
    auto h = open_regular(path);
    const uint64_t length = file_size(h.value, path);
    if (length > maximum) fail(L"File is larger than the supported limit: " + path);
    std::string out(static_cast<size_t>(length), '\0');
    size_t done = 0;
    while (done < out.size()) {
        DWORD got = 0;
        if (!ReadFile(h.value, out.data() + done, DWORD(out.size() - done), &got, nullptr) || !got)
            fail(L"Cannot completely read " + path + L": " + windows_error());
        done += got;
    }
    return out;
}

void validate_pe(const std::wstring& path) {
    auto h = open_regular(path);
    const uint64_t size = file_size(h.value, path);
    if (size < 88 || size > MAX_PACK_FILE_BYTES) fail(L"Tool executable has an unsupported size: " + path);
    std::array<unsigned char, 64> dos{};
    DWORD got = 0;
    if (!ReadFile(h.value, dos.data(), DWORD(dos.size()), &got, nullptr) || got != dos.size() || dos[0] != 'M' || dos[1] != 'Z')
        fail(L"Tool is not a Windows executable: " + path);
    const uint32_t offset = uint32_t(dos[60]) | (uint32_t(dos[61]) << 8) | (uint32_t(dos[62]) << 16) | (uint32_t(dos[63]) << 24);
    if (offset < 64 || uint64_t(offset) + 26 > size || offset > 1024 * 1024) fail(L"Invalid executable header: " + path);
    LARGE_INTEGER target{}; target.QuadPart = offset;
    std::array<unsigned char, 26> pe{};
    if (!SetFilePointerEx(h.value, target, nullptr, FILE_BEGIN) ||
        !ReadFile(h.value, pe.data(), DWORD(pe.size()), &got, nullptr) || got != pe.size() ||
        pe[0] != 'P' || pe[1] != 'E' || pe[2] || pe[3] || pe[4] != 0x64 || pe[5] != 0x86 || pe[24] != 0x0b || pe[25] != 0x02)
        fail(L"Tool must be a Windows x86-64 PE32+ executable: " + path);
}

std::array<unsigned long, 3> version_parts(const std::wstring& value) {
    std::array<unsigned long, 3> result{};
    size_t start = 0;
    for (size_t i = 0; i < result.size(); ++i) {
        const size_t end = value.find(L'.', start);
        result[i] = std::stoul(value.substr(start, end - start)); start = end + 1;
    }
    return result;
}
bool safe_leaf(const std::wstring& leaf) {
    if (leaf.empty() || leaf.size() > 180 || leaf == L"." || leaf == L".." || leaf.back() == L'.' || leaf.back() == L' ' ||
        leaf.find_first_of(L"\\/:<>\"|?*") != std::wstring::npos) return false;
    for (auto c : leaf) if (c < 32) return false;
    std::wstring stem = leaf.substr(0, leaf.find(L'.'));
    std::transform(stem.begin(), stem.end(), stem.begin(), [](wchar_t c) { return c >= L'a' && c <= L'z' ? c - L'a' + L'A' : c; });
    if (stem == L"CON" || stem == L"PRN" || stem == L"AUX" || stem == L"NUL" || stem == L"CONIN$" || stem == L"CONOUT$") return false;
    if (stem.size() == 4 && (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT") && stem[3] >= L'1' && stem[3] <= L'9') return false;
    return true;
}

void create_directory(const std::wstring& path) {
    if (!CreateDirectoryW(native_path(path).c_str(), nullptr)) fail(L"Cannot create " + path + L": " + windows_error());
}

struct CopyBudget { size_t files = 0; uint64_t bytes = 0; };
void copy_file_checked(const std::wstring& source, const std::wstring& destination, CopyBudget& budget, const Cancel& cancel) {
    check_cancel(cancel);
    auto input = open_regular(source);
    const uint64_t size = file_size(input.value, source);
    if (++budget.files > MAX_PACK_FILES || size > MAX_PACK_BYTES - budget.bytes) fail(L"A tool pack import is limited to 2000 files and folders and 1024 MiB.");
    budget.bytes += size;
    Handle output(CreateFileW(native_path(destination).c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (output.value == INVALID_HANDLE_VALUE) fail(L"Cannot create imported file " + destination + L": " + windows_error());
    std::array<unsigned char, 65536> buffer{};
    uint64_t copied = 0;
    for (;;) {
        check_cancel(cancel);
        DWORD got = 0;
        if (!ReadFile(input.value, buffer.data(), DWORD(buffer.size()), &got, nullptr)) fail(L"Cannot read imported file " + source + L": " + windows_error());
        if (!got) break;
        copied += got;
        if (copied > size) fail(L"Pack file changed while being copied: " + source);
        DWORD done = 0;
        while (done < got) {
            check_cancel(cancel);
            DWORD written = 0;
            if (!WriteFile(output.value, buffer.data() + done, got - done, &written, nullptr) || !written)
                fail(L"Cannot write imported file " + destination + L": " + windows_error());
            done += written;
        }
    }
    if (copied != size || !FlushFileBuffers(output.value)) fail(L"Could not complete imported file: " + destination);
}

void copy_licenses(const std::wstring& source, const std::wstring& destination, CopyBudget& budget, const Cancel& cancel, unsigned depth = 0) {
    if (depth > 12) fail(L"The licenses folder is nested too deeply.");
    check_cancel(cancel);
    PathGuard lock; lock.directory(source);
    create_directory(destination);
    WIN32_FIND_DATAW data{};
    HANDLE raw = FindFirstFileW(native_path(join(source, L"*")).c_str(), &data);
    if (raw == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND) return;
        fail(L"Cannot read the licenses folder: " + windows_error());
    }
    struct FindHandle { HANDLE h; ~FindHandle() { FindClose(h); } } find{raw};
    for (;;) {
        const std::wstring name = data.cFileName;
        if (name != L"." && name != L"..") {
            check_cancel(cancel);
            if (!safe_leaf(name) || (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) fail(L"Unsafe file or reparse point in licenses: " + name);
            if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
                // Count directories too, so thousands of empty directories are bounded.
                if (++budget.files > MAX_PACK_FILES) fail(L"A tool pack import is limited to 2000 files and folders.");
                copy_licenses(join(source, name), join(destination, name), budget, cancel, depth + 1);
            } else copy_file_checked(join(source, name), join(destination, name), budget, cancel);
        }
        if (!FindNextFileW(raw, &data)) {
            if (GetLastError() != ERROR_NO_MORE_FILES) fail(L"Cannot enumerate licenses: " + windows_error());
            break;
        }
    }
}

std::wstring relative_key(std::wstring value) {
    for (auto& c : value) {
        if (c == L'\\') c = L'/';
        else if (c >= L'A' && c <= L'Z') c += L'a' - L'A';
    }
    return value;
}
void verify_inventory(const Pack& pack, PathGuard& guard, const Cancel& cancel) {
    std::set<std::wstring> declared{L"pack.ini", L"pack-readme.md", L"pack-readme.txt", L"readme.txt"};
    for (const auto& tool : pack.tools) declared.insert(relative_key(tool.path.substr(pack.root.size() + 1)));
    for (const auto& asset : pack.assets) declared.insert(relative_key(asset.path.substr(pack.root.size() + 1)));
    CopyBudget budget;
    std::function<void(const std::wstring&, unsigned)> walk = [&](const std::wstring& relative, unsigned depth) {
        check_cancel(cancel);
        if (depth > 16) fail(L"A pack directory is nested too deeply.");
        const auto folder = relative.empty() ? pack.root : join(pack.root, relative);
        guard.directory(folder);
        WIN32_FIND_DATAW data{};
        HANDLE raw = FindFirstFileW(native_path(join(folder, L"*")).c_str(), &data);
        if (raw == INVALID_HANDLE_VALUE) {
            if (GetLastError() == ERROR_FILE_NOT_FOUND) return;
            fail(L"Cannot inspect pack inventory: " + windows_error());
        }
        struct FindHandle { HANDLE h; ~FindHandle() { FindClose(h); } } find{raw};
        for (;;) {
            const std::wstring name = data.cFileName;
            if (name != L"." && name != L"..") {
                check_cancel(cancel);
                if (!safe_leaf(name) || (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
                    fail(L"Unsafe file or reparse point in pack inventory: " + join(folder, name));
                if (++budget.files > MAX_PACK_FILES) fail(L"A tool pack is limited to 2000 files and folders.");
                const auto child = relative.empty() ? name : join(relative, name);
                if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) walk(child, depth + 1);
                else {
                    const auto key = relative_key(child);
                    if (!declared.count(key) && key.rfind(L"licenses/", 0) != 0)
                        fail(L"Undeclared file in tool pack: " + child + L". Reinstall the pack or declare this runtime asset.");
                    auto file = open_regular(join(pack.root, child));
                    const auto size = file_size(file.value, child);
                    if (size > MAX_PACK_BYTES - budget.bytes) fail(L"A tool pack is limited to 1024 MiB.");
                    budget.bytes += size;
                }
            }
            if (!FindNextFileW(raw, &data)) {
                if (GetLastError() != ERROR_NO_MORE_FILES) fail(L"Cannot enumerate pack inventory: " + windows_error());
                break;
            }
        }
    };
    walk(L"", 0);
}

// Called only for our newly allocated staging directory. Never traverse reparse
// points even during error cleanup, and never remove a published pack.
void remove_staging(const std::wstring& path) noexcept {
    try {
        const auto native = native_path(path);
        DWORD attrs = GetFileAttributesW(native.c_str());
        if (attrs == INVALID_FILE_ATTRIBUTES) return;
        if (attrs & FILE_ATTRIBUTE_REPARSE_POINT) {
            if (attrs & FILE_ATTRIBUTE_DIRECTORY) RemoveDirectoryW(native.c_str()); else DeleteFileW(native.c_str());
            return;
        }
        WIN32_FIND_DATAW data{};
        HANDLE raw = FindFirstFileW(native_path(join(path, L"*")).c_str(), &data);
        if (raw != INVALID_HANDLE_VALUE) {
            struct FindHandle { HANDLE h; ~FindHandle() { FindClose(h); } } find{raw};
            do {
                const std::wstring name = data.cFileName;
                if (name == L"." || name == L"..") continue;
                auto child = join(path, name);
                if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) remove_staging(child);
                else DeleteFileW(native_path(child).c_str());
            } while (FindNextFileW(raw, &data));
        }
        RemoveDirectoryW(native.c_str());
    } catch (...) {
        // Cleanup is best effort. Preserve the original import error even if
        // resolving a native path or allocating traversal state fails here.
    }
}
} // namespace

Pack load_pack(const std::wstring& folder) {
    const auto root = absolute_local(folder);
    PathGuard guard; guard.ancestors(root);
    const auto manifest = join(root, L"pack.ini");
    // Keep this handle open across parsing and hashing. Another process cannot
    // replace or write the manifest between the UI model and its stored digest.
    auto manifest_lock = open_regular(manifest);
    Pack result = parse_pack_text(utf16(read_bounded(manifest, MAX_MANIFEST_BYTES)));
    result.root = root;
    Cancel cancel{false};
    result.manifest_sha256 = sha256_file(manifest, cancel);
    for (auto& tool : result.tools) {
        guard.file_parents(root, tool.path);
        std::replace(tool.path.begin(), tool.path.end(), L'/', L'\\');
        tool.path = join(root, tool.path);
        validate_pe(tool.path);
        if (result.format == 1) {
            if (tool.id == L"bwfastq") result.fastq = tool;
            else if (tool.id == L"seqtk") result.seqtk = tool;
            else if (tool.id == L"minimap2") result.minimap = tool;
        }
    }
    for (auto& asset : result.assets) {
        guard.file_parents(root, asset.path);
        std::replace(asset.path.begin(), asset.path.end(), L'/', L'\\');
        asset.path = join(root, asset.path);
        auto checked = open_regular(asset.path);
        if (file_size(checked.value, asset.path) > MAX_PACK_FILE_BYTES)
            fail(L"Pack asset exceeds the supported size: " + asset.path);
    }
    return result;
}

std::wstring sha256_file(const std::wstring& path, const Cancel& cancel) {
    check_cancel(cancel);
    auto file = open_regular(path);
    struct Algorithm { BCRYPT_ALG_HANDLE h = nullptr; ~Algorithm() { if (h) BCryptCloseAlgorithmProvider(h, 0); } } algorithm;
    if (BCryptOpenAlgorithmProvider(&algorithm.h, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) fail(L"Windows SHA-256 is unavailable.");
    DWORD object_length = 0, returned = 0;
    if (BCryptGetProperty(algorithm.h, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length), &returned, 0) < 0 ||
        returned != sizeof(object_length) || object_length > 1024 * 1024) fail(L"Cannot initialize SHA-256.");
    std::vector<unsigned char> object(object_length);
    // Destroy the hash before releasing its caller-owned object buffer.
    struct Hash { BCRYPT_HASH_HANDLE h = nullptr; ~Hash() { if (h) BCryptDestroyHash(h); } } hash;
    if (BCryptCreateHash(algorithm.h, &hash.h, object.data(), object_length, nullptr, 0, 0) < 0) fail(L"Cannot create SHA-256 state.");
    std::array<unsigned char, 65536> buffer{};
    for (;;) {
        check_cancel(cancel);
        DWORD got = 0;
        if (!ReadFile(file.value, buffer.data(), DWORD(buffer.size()), &got, nullptr)) fail(L"Cannot hash " + path + L": " + windows_error());
        if (!got) break;
        if (BCryptHashData(hash.h, buffer.data(), got, 0) < 0) fail(L"SHA-256 failed while reading " + path + L".");
    }
    check_cancel(cancel);
    std::array<unsigned char, 32> digest{};
    if (BCryptFinishHash(hash.h, digest.data(), DWORD(digest.size()), 0) < 0) fail(L"Could not complete SHA-256.");
    constexpr wchar_t hex[] = L"0123456789abcdef";
    std::wstring result; result.reserve(64);
    for (auto byte : digest) { result.push_back(hex[byte >> 4]); result.push_back(hex[byte & 15]); }
    return result;
}

void verify_pack(const Pack& pack, const Cancel& cancel, const Log& log) {
    check_cancel(cancel);
    PathGuard guard; guard.ancestors(absolute_local(pack.root));
    // Reload metadata to reject stale or caller-supplied paths before hashing.
    const Pack current = load_pack(pack.root);
    if (current.id != pack.id || current.version != pack.version ||
        current.manifest_sha256 != pack.manifest_sha256 || current.tools.size() != pack.tools.size() ||
        current.assets.size() != pack.assets.size())
        fail(L"Tool pack manifest changed. Select the pack again.");
    verify_inventory(current, guard, cancel);
    for (size_t i = 0; i < current.tools.size(); ++i) {
        check_cancel(cancel);
        const Tool& expected = pack.tools[i];
        const Tool& actual = current.tools[i];
        if (expected.id != actual.id || expected.path != actual.path || expected.version != actual.version || expected.sha256 != actual.sha256)
            fail(L"Tool pack metadata changed. Select the pack again.");
        guard.file_parents(current.root, actual.path.substr(current.root.size() + 1));
        log_line(log, L"Checking " + actual.id + L" " + actual.version + L"...");
        if (sha256_file(actual.path, cancel) != actual.sha256)
            fail(L"SHA-256 mismatch for " + actual.id + L". The tool pack is incomplete or has changed.");
    }
    for (size_t i = 0; i < current.assets.size(); ++i) {
        check_cancel(cancel);
        const Asset& expected = pack.assets[i];
        const Asset& actual = current.assets[i];
        if (expected.id != actual.id || expected.path != actual.path || expected.sha256 != actual.sha256)
            fail(L"Tool pack asset metadata changed. Select the pack again.");
        guard.file_parents(current.root, actual.path.substr(current.root.size() + 1));
        if (sha256_file(actual.path, cancel) != actual.sha256)
            fail(L"SHA-256 mismatch for asset " + actual.id + L". The tool pack is incomplete or has changed.");
    }
    if (!current.assets.empty()) log_line(log, L"Checked " + std::to_wstring(current.assets.size()) + L" bundled runtime/data assets.");
    log_line(log, L"Tool pack hashes match the manifest.");
}

std::vector<Pack> discover_packs(const std::wstring& app_root, const Log& log) {
    std::vector<Pack> result;
    try {
        const auto folder = join(absolute_local(app_root), L"packs");
        if (GetFileAttributesW(native_path(folder).c_str()) == INVALID_FILE_ATTRIBUTES && GetLastError() == ERROR_FILE_NOT_FOUND) return result;
        PathGuard guard; guard.ancestors(folder);
        WIN32_FIND_DATAW data{};
        HANDLE raw = FindFirstFileW(native_path(join(folder, L"*")).c_str(), &data);
        if (raw == INVALID_HANDLE_VALUE) {
            if (GetLastError() == ERROR_FILE_NOT_FOUND) return result;
            fail(L"Cannot discover tool packs: " + windows_error());
        }
        struct FindHandle { HANDLE h; ~FindHandle() { FindClose(h); } } find{raw};
        for (;;) {
            std::wstring name = data.cFileName;
            if (name != L"." && name != L".." && name.rfind(L"_import-", 0) != 0 && (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
                try {
                    if (!safe_leaf(name) || (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) fail(L"Linked or invalid pack folder is not supported.");
                    Pack pack = load_pack(join(folder, name));
                    if (name != pack.id + L"-" + pack.version) fail(L"Pack folder name must be " + pack.id + L"-" + pack.version + L".");
                    result.push_back(std::move(pack));
                } catch (const std::exception& error) { log_line(log, L"Skipped pack " + name + L": " + utf16(error.what())); }
            }
            if (!FindNextFileW(raw, &data)) {
                if (GetLastError() != ERROR_NO_MORE_FILES) fail(L"Cannot enumerate tool packs: " + windows_error());
                break;
            }
        }
    } catch (const std::exception& error) { log_line(log, L"Tool pack discovery: " + utf16(error.what())); }
    std::sort(result.begin(), result.end(), [](const Pack& a, const Pack& b) {
        if (a.id != b.id) return a.id < b.id;
        return version_parts(a.version) > version_parts(b.version);
    });
    return result;
}

Pack import_pack(const std::wstring& app_root, const std::wstring& source, const Cancel& cancel, const Log& log) {
    check_cancel(cancel);
    const Pack candidate = load_pack(source);
    PathGuard source_guard; source_guard.ancestors(candidate.root);
    for (const auto& tool : candidate.tools)
        source_guard.file_parents(candidate.root, tool.path.substr(candidate.root.size() + 1));
    for (const auto& asset : candidate.assets)
        source_guard.file_parents(candidate.root, asset.path.substr(candidate.root.size() + 1));
    verify_pack(candidate, cancel, log);
    const auto base = absolute_local(app_root);
    PathGuard parent_guard; parent_guard.ancestors(base);
    const auto parent = join(base, L"packs");
    DWORD attrs = GetFileAttributesW(native_path(parent).c_str());
    if (attrs == INVALID_FILE_ATTRIBUTES) {
        const DWORD error = GetLastError();
        if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) fail(L"Cannot inspect the packs folder: " + windows_error(error));
        if (!CreateDirectoryW(native_path(parent).c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) fail(L"Cannot create the packs folder: " + windows_error());
    }
    parent_guard.directory(parent);
    const auto destination = join(parent, candidate.id + L"-" + candidate.version);
    if (GetFileAttributesW(native_path(destination).c_str()) != INVALID_FILE_ATTRIBUTES) fail(L"This tool pack version is already installed. Existing packs are never overwritten.");
    const auto staging = unique_directory(parent, L"_import");
    bool published = false;
    try {
        CopyBudget budget;
        log_line(log, L"Copying tool pack locally...");
        copy_file_checked(join(candidate.root, L"pack.ini"), join(staging, L"pack.ini"), budget, cancel);
        PathGuard staging_guard; staging_guard.ancestors(staging);
        std::set<std::wstring> made_directories;
        auto copy_declared = [&](const std::wstring& source_path) {
            const auto relative = source_path.substr(candidate.root.size() + 1);
            for (size_t i = 0; i < relative.size(); ++i) if (relative[i] == L'\\') {
                const auto parent = relative.substr(0, i);
                auto key = parent;
                std::transform(key.begin(), key.end(), key.begin(), [](wchar_t c) { return c >= L'A' && c <= L'Z' ? c + L'a' - L'A' : c; });
                if (made_directories.insert(key).second) {
                    if (++budget.files > MAX_PACK_FILES) fail(L"A tool pack import is limited to 2000 files and folders.");
                    create_directory(join(staging, parent));
                    staging_guard.directory(join(staging, parent));
                }
            }
            copy_file_checked(source_path, join(staging, relative), budget, cancel);
        };
        for (const auto& tool : candidate.tools) copy_declared(tool.path);
        for (const auto& asset : candidate.assets) copy_declared(asset.path);
        for (const auto* filename : {L"PACK-README.md", L"PACK-README.txt", L"README.txt"}) {
            const auto readme = join(candidate.root, filename);
            attrs = GetFileAttributesW(native_path(readme).c_str());
            if (attrs != INVALID_FILE_ATTRIBUTES) copy_file_checked(readme, join(staging, filename), budget, cancel);
        }
        const auto licenses = join(candidate.root, L"licenses");
        attrs = GetFileAttributesW(native_path(licenses).c_str());
        if (attrs == INVALID_FILE_ATTRIBUTES) fail(L"A tool pack must include its licenses folder.");
        copy_licenses(licenses, join(staging, L"licenses"), budget, cancel);
        Pack copied = load_pack(staging);
        verify_pack(copied, cancel, log);
        if (copied.id != candidate.id || copied.version != candidate.version ||
            copied.manifest_sha256 != candidate.manifest_sha256)
            fail(L"The source manifest changed during import.");
        check_cancel(cancel);
        staging_guard.handles.clear();
        // Same-volume rename, without MOVEFILE_REPLACE_EXISTING or COPY_ALLOWED.
        if (!MoveFileExW(native_path(staging).c_str(), native_path(destination).c_str(), 0)) fail(L"Cannot publish imported pack (it may already exist): " + windows_error());
        published = true;
        auto installed = load_pack(destination);
        log_line(log, L"Imported " + installed.name + L" " + installed.version + L".");
        return installed;
    } catch (...) {
        if (!published) remove_staging(staging);
        throw;
    }
}
} // namespace bw
