// Copyright (c) 2026 Native Workbench contributors. MIT license.
// Standalone portability regression: standard stream semantics, bounded storage,
// recycled shorter input, and seek/tell after output flush and overflow.
#include "WorkbenchBufferStream.h"
#include <cassert>
#include <string>
#include <cstring>

int main() {
    char input[32] = "first second\n";
    WorkbenchInputStream in(input, sizeof input);
    in.inputSize(13);
    std::string word;
    in >> word; assert(word == "first");
    assert(in.tellg() == 5);
    in >> word; assert(word == "second");
    in >> word; assert(in.eof());
    std::memcpy(input, "x\n", 2);
    in.inputSize(2);
    in >> word; assert(word == "x");
    in >> word; assert(in.eof()); // No stale "second" from the old chunk.
    in.clear(); in.seekg(-1, std::ios::end); assert(in.get() == '\n');
    in.clear(); in.seekg(3); assert(in.fail());
    in.inputSize(0); assert(in.peek() == std::char_traits<char>::eof());
    bool threw = false;
    try { in.inputSize(33); } catch (const std::length_error&) { threw = true; }
    assert(threw);

    char output[9]; std::memset(output, '#', sizeof output);
    WorkbenchOutputStream out(output, 8);
    out << "1234"; assert(out.good() && out.tellp() == 4);
    out.seekp(0); out << "xy"; assert(out.tellp() == 2);
    assert(std::string(output, 4) == "xy34");
    out.seekp(-1, std::ios::end); out.put('z'); assert(out.tellp() == 8);
    out.put('!'); assert(out.fail() && output[8] == '#');
    out.clear(); out.seekp(0); out << "abcdefgh";
    assert(out.good() && std::string(output, 8) == "abcdefgh");
    out.write("overflow", 8); assert(out.fail() && output[8] == '#');
    out.clear(); out.seekp(std::numeric_limits<std::streamoff>::max(),std::ios::cur);
    assert(out.fail());
    out.clear(); out.seekp(std::numeric_limits<std::streamoff>::min(),std::ios::cur);
    assert(out.fail());
}
