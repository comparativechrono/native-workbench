#include "child_environment.h"
#include <iostream>
#include <stdexcept>

static void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

int main() {
    const std::vector<std::wstring> source{
        L"=C:=C:\\Users\\Scientist", L"CLASSPATH=unrelated.jar",
        L"JAVA_TOOL_OPTIONS=-javaagent:unexpected.jar", L"JDK_JAVA_OPTIONS=-Xmx64m",
        L"MY_JAVA_TOOL_OPTIONS=retain=this", L"PATH=C:\\Windows;C:\\Tools",
        L"PERL5LIB=C:\\OtherPerl", L"PERL5OPT=-MUnexpected", L"PERL5SHELL=other.exe",
        L"PERLLIB=C:\\OtherModules", L"PERL_UNICODE=SDA", L"SystemRoot=C:\\Windows",
        L"TEMP=C:\\Users\\Zo\u00eb\\Temp", L"_java_options=-Xmx64m",
        L"java_tool_options=-Xmx128m", L"perlio=:encoding(UTF-16)", L"PERLIO_DEBUG=C:\\unexpected.log"
    };
    const auto original = source;
    const auto block = bw::pack_environment_block(source);
    check(block.size() >= 2 && block[block.size()-1] == 0 && block[block.size()-2] == 0,
          "Windows environment must terminate with two NUL characters");
    std::vector<std::wstring> kept;
    for (const wchar_t* p = block.data(); *p;) {
        std::wstring entry(p); p += entry.size()+1; kept.push_back(entry);
    }
    check(kept == std::vector<std::wstring>{source[0],source[4],source[5],source[11],source[12]},
          "Remove startup overrides while preserving Windows paths, Unicode and similarly named variables");
    check(source == original, "Never mutate the parent environment entries");
    check(bw::pack_environment_block({}) == std::vector<wchar_t>{0,0}, "Empty environment format");
    check(bw::pack_environment_block({L"JAVA_TOOL_OPTIONS="}) == std::vector<wchar_t>{0,0},
          "All-filtered environment format");
    for (const auto& bad : {std::wstring{}, std::wstring(L"A=x\0B=y",7)}) {
        bool rejected = false;
        try { bw::pack_environment_block({bad}); } catch (const std::runtime_error&) { rejected=true; }
        check(rejected, "Reject malformed environment entries");
    }
    std::cout << "7 child-environment contract checks passed; Windows process execution not tested here.\n";
}
