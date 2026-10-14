#pragma once

#include <cstddef>
#include <functional>
#include <map>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#ifndef DESKTOP_JSON_ONLY
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <memory>
#endif

namespace desktop {

// Protocol values are UTF-8. parse() and dump() reject malformed UTF-8,
// duplicate object names, non-finite numbers, excessive depth and oversized
// messages. Null, unlike an empty string, remains distinguishable throughout.
class Json {
public:
    enum class Type { Null, Bool, Number, String, Array, Object };
    using Array = std::vector<Json>;
    using Object = std::map<std::string, Json>;
    static constexpr std::size_t max_bytes = 8 * 1024 * 1024;

    Json() = default;
    Json(std::nullptr_t) {}
    Json(bool value) : value_(value) {}
    Json(int value) : value_(static_cast<double>(value)) {}
    Json(unsigned value) : value_(static_cast<double>(value)) {}
    Json(long value) : value_(static_cast<double>(value)) {}
    Json(unsigned long value) : value_(static_cast<double>(value)) {}
    Json(long long value) : value_(static_cast<double>(value)) {}
    Json(unsigned long long value) : value_(static_cast<double>(value)) {}
    Json(double value);
    Json(const char* value) : value_(std::string(value ? value : "")) {}
    Json(std::string value) : value_(std::move(value)) {}
    Json(Array value) : value_(std::move(value)) {}
    Json(Object value) : value_(std::move(value)) {}

    static Json array() { return Array{}; }
    static Json object() { return Object{}; }
    static Json parse(const std::string& text);
    std::string dump() const;

    Type type() const noexcept { return static_cast<Type>(value_.index()); }
    bool is_null() const noexcept { return type() == Type::Null; }
    bool is_bool() const noexcept { return type() == Type::Bool; }
    bool is_number() const noexcept { return type() == Type::Number; }
    bool is_string() const noexcept { return type() == Type::String; }
    bool is_array() const noexcept { return type() == Type::Array; }
    bool is_object() const noexcept { return type() == Type::Object; }
    bool contains(const std::string& key) const;
    std::size_t size() const noexcept;
    const Json& get(const std::string& key) const noexcept;
    const Json& operator[](const std::string& key) const noexcept { return get(key); }
    Json& operator[](const std::string& key);
    const Json& operator[](std::size_t index) const;
    Json& operator[](std::size_t index);
    std::string string(const std::string& fallback = {}) const;
    double number(double fallback = 0) const noexcept;
    long long integer(long long fallback = 0) const noexcept;
    bool boolean(bool fallback = false) const noexcept;
    const Array& array_items() const;
    Array& array_items();
    const Object& object_items() const;
    Object& object_items();

private:
    std::variant<std::monostate, bool, double, std::string, Array, Object> value_;
};

// Shared by the Windows reader and portable protocol tests. Chunks may split
// anywhere, including inside UTF-8 characters, escape sequences or newlines.
class JsonLineFramer {
public:
    void feed(const char* bytes, std::size_t size, const std::function<void(std::string)>& emit);
    void finish() const;
private:
    std::string pending_;
};

#ifndef DESKTOP_JSON_ONLY
// One active workspace per installed application root. The mutex name and
// window class share a canonical-root digest, keeping separate installations
// independent while protecting their run history from simultaneous hosts.
class SingleInstance {
public:
    explicit SingleInstance(const std::wstring& app_root);
    ~SingleInstance();
    SingleInstance(const SingleInstance&) = delete;
    SingleInstance& operator=(const SingleInstance&) = delete;
    bool owns() const noexcept { return owned_; }
    std::wstring window_class() const { return window_class_; }
    bool show_existing() const noexcept;
private:
    HANDLE mutex_ = nullptr;
    bool owned_ = false;
    std::wstring window_class_;
};

// The child speaks JSON Lines over anonymous pipes only. No network listener
// or browser is created. All descendants are confined to a kill-on-close job.
// start()/send() throw std::runtime_error; stop() is idempotent.
//
// notification_message: WPARAM=0 -> a raw protocol line; WPARAM=1 -> terminal
// transport event JSON. LPARAM owns a new std::string; the window must delete
// it, including queued messages during teardown. stop() joins reader threads
// before returning, so the window can safely drain its queue and destroy itself.
class HostProcess {
public:
    // DesktopHost's request bound includes the terminating newline.
    static constexpr std::size_t max_request_bytes = 2 * 1024 * 1024;
    HostProcess();
    ~HostProcess();
    HostProcess(const HostProcess&) = delete;
    HostProcess& operator=(const HostProcess&) = delete;
    void start(const std::wstring& app_root, HWND notify_window, UINT notification_message);
    void send(const Json& request);
    void stop() noexcept;
    bool alive() const noexcept;
    DWORD exit_code() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
#endif

} // namespace desktop
