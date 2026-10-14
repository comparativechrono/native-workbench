// Portable tests for the exact JSON parser and line framer used by the native
// Windows UI. These do not claim to test Windows process/Job Object behavior.
// From the source root:
// c++ -std=c++17 -O2 -Wall -Wextra -Werror -DDESKTOP_JSON_ONLY -Idesktop tests/test_desktop_json.cpp desktop/desktop_ipc.cpp -o build/test_desktop_json
// build/test_desktop_json
#include "desktop_ipc.h"
#include "record_list.h"
#include <algorithm>
#include <cassert>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

using desktop::Json;
using desktop::JsonLineFramer;

template<class Function> void rejects(Function function) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    assert(rejected);
}

int main() {
    auto value = Json::parse("{\"name\":\"C:\\\\a b\\u00e9\\ud83d\\ude00\",\"none\":null,\"a\":[true,false,1,-2.5,1e3,\"\\u0000\"]}");
    assert(value["name"].string() == "C:\\a b\xc3\xa9\xf0\x9f\x98\x80");
    assert(value["a"][0].boolean());
    assert(value["a"][3].number() == -2.5);
    assert(value["a"][4].integer() == 1000);
    assert(value["a"][5].string().size() == 1);
    assert(value["none"].is_null() && value["absent"].is_null());
    assert(Json::parse(value.dump()).dump() == value.dump());
    assert(Json(9223372036854775808.0).integer(7) == 7);
    assert(Json(-9223372036854775808.0).integer() == std::numeric_limits<long long>::min());
    assert(Json(1.5).integer(7) == 7);
    rejects([] { Json number(std::numeric_limits<double>::infinity()); });
    rejects([] { Json number(std::numeric_limits<double>::quiet_NaN()); });

    // Native catalogue/results callbacks run before their first async reply.
    // They also retain a briefly stale selection when a new search has no
    // matches. Exercise the exact shared selector used by both Windows views.
    for (const char* key : {"workflows", "runs"}) {
        for (const auto& before_reply : {Json(), Json::object(), Json::parse("{\"notice\":\"loading\"}")}) {
            assert(desktop::selected_record(before_reply, key, -1).is_object());
            assert(desktop::selected_record(before_reply, key, 0).get("id").is_null());
        }
        Json records = Json::Object{{key, Json::array()}};
        assert(!desktop::selected_record(records, key, -1).get("available").boolean());
        assert(desktop::selected_record(records, key, 0).get("id").is_null());
        records[key] = Json::Array{Json::Object{{"id", "first"}, {"available", true}},
                                  Json::Object{{"id", "second"}, {"available", false}}};
        assert(desktop::selected_record(records, key, 0).get("id").string() == "first");
        assert(desktop::selected_record(records, key, 1).get("id").string() == "second");
        assert(desktop::selected_record(records, key, -1).get("id").is_null());
        assert(desktop::selected_record(records, key, 2).get("id").is_null());
        assert(desktop::selected_record(records, key, std::numeric_limits<int>::max()).get("id").is_null());
        records[key] = Json::array(); // An empty search after the second row was selected.
        assert(desktop::selected_record(records, key, 1).get("id").is_null());
        for (const auto& invalid_rows : {Json(), Json("invalid"), Json::object(), Json(Json::Array{Json("invalid")})}) {
            records[key] = invalid_rows;
            assert(desktop::selected_record(records, key, 0).get("id").is_null());
        }
    }

    const std::vector<std::string> invalid = {
        "", "{}x", "NaN", "Infinity", "01", "1.", ".1", "1e", "1e+", "-", "+1",
        "[1,]", "{\"a\":1,}", "{\"a\":1,\"a\":2}", "{\"a\":null,\"\\u0061\":2}",
        "\"\\ud800\"", "\"\\udfff\"", "\"\\ud800\\u0061\"", "\"\\z\"", "\"raw\nline\"",
        "1e999", "truefalse", "\"\xc0\xaf\"", "\"\xed\xa0\x80\"", "\"\xf4\x90\x80\x80\"",
        "\"\xe2\x82\"", "\xef\xbb\xbf{}"
    };
    for (const auto& input : invalid) rejects([&] { Json::parse(input); });
    rejects([] { Json::parse(std::string(66, '[') + "0" + std::string(66, ']')); });
    rejects([] { Json::parse(std::string(Json::max_bytes + 1, ' ')); });
    std::string many = "[0";
    for (unsigned i = 0; i < 200000; ++i) many += ",0";
    many += ']';
    rejects([&] { Json::parse(many); });
    rejects([] { Json(std::string("\xc0\xaf")).dump(); });

    // Realistic multi-megabyte response with Unicode labels and a long Windows
    // path. JSON's character escapes must not become protocol delimiters.
    const std::string path = "\\\\?\\C:\\" + std::string(4000, 'd') + "\\reads \xc3\xa9\xf0\x9f\x98\x80.fastq";
    Json snapshot = Json::Object{{"id", 17}, {"ok", true}, {"result", Json::Object{
        {"path", path}, {"text", std::string(3 * 1024 * 1024, 'x') + "\n\"\\\xc3\xa9"}}}};
    const auto encoded = snapshot.dump();
    const auto final = Json(Json::Object{{"id", 18}, {"ok", true}}).dump();
    const std::string wire = encoded + "\r\n" + final + "\n";
    for (const std::size_t chunk : {std::size_t(1), std::size_t(16384), std::size_t(65537)}) {
        JsonLineFramer frames;
        std::vector<std::string> received;
        for (std::size_t p = 0; p < wire.size(); p += chunk)
            frames.feed(wire.data() + p, std::min(chunk, wire.size() - p), [&](std::string line) { received.push_back(std::move(line)); });
        frames.finish();
        assert(received.size() == 2 && received[0] == encoded && received[1] == final);
        assert(Json::parse(received[0])["result"]["path"].string() == path);
    }
    for (const auto& incomplete : {std::string("{}"), std::string("{\"x\":")}) {
        JsonLineFramer frames;
        frames.feed(incomplete.data(), incomplete.size(), [](std::string) {});
        rejects([&] { frames.finish(); });
    }
    for (const auto& bad_line : {std::string("\n"), std::string("\r\n"), std::string("\xc0\xaf\n")}) {
        JsonLineFramer frames;
        rejects([&] { frames.feed(bad_line.data(), bad_line.size(), [](std::string) {}); });
    }
    // Every possible chunk boundary in a UTF-8 character sequence is valid
    // until the complete line is available; validation happens after assembly.
    const std::string unicode_line = "\"\xf0\x9f\x98\x80\xc3\xa9\"\n";
    for (std::size_t split = 1; split < unicode_line.size(); ++split) {
        JsonLineFramer frames;
        unsigned emitted = 0;
        const auto emit = [&](std::string line) { ++emitted; assert(Json::parse(line).string() == "\xf0\x9f\x98\x80\xc3\xa9"); };
        frames.feed(unicode_line.data(), split, emit);
        frames.feed(unicode_line.data() + split, unicode_line.size() - split, emit);
        frames.finish();
        assert(emitted == 1);
    }
    JsonLineFramer oversized;
    const std::string block(Json::max_bytes, 'x');
    oversized.feed(block.data(), block.size(), [](std::string) {});
    rejects([&] { oversized.feed("x\n", 2, [](std::string) {}); });

    std::cout << "Desktop JSON, record selection and pipe framing tests passed (portable; Windows lifecycle not executed).\n";
}
