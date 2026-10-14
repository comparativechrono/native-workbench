// Copyright (c) 2026 Native Workbench contributors. MIT license.
// CLI plumbing only: kallisto performs all pseudoalignment and estimation.
#include <cerrno>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/wait.h>
#include <unistd.h>
#endif
namespace fs = std::filesystem;

static long long integer(const std::string& value, long long low, long long high) {
    size_t end = 0;
    long long n = std::stoll(value, &end);
    if (end != value.size() || n < low || n > high) throw std::runtime_error("Numeric parameter outside supported range: " + value);
    return n;
}

#ifdef _WIN32
static std::wstring widen(const std::string& value) {
    std::wstring result;
    for (unsigned char c : value) {
        if (c > 127 || c < 32) throw std::runtime_error("This build requires ASCII paths without control characters");
        result += wchar_t(c);
    }
    return result;
}
// Inverse of the Windows CRT command-line parser, including trailing slashes.
static std::wstring quote(const std::wstring& value) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (wchar_t c : value) {
        if (c == L'\\') { ++slashes; continue; }
        result.append(c == L'"' ? slashes * 2 + 1 : slashes, L'\\');
        result += c;
        slashes = 0;
    }
    result.append(slashes * 2, L'\\');
    return result + L"\"";
}
#endif

static int run(const fs::path& executable, const std::vector<std::string>& args) {
#ifdef _WIN32
    std::wstring command = quote(executable.wstring());
    for (const auto& arg : args) command += L" " + quote(widen(arg));
    STARTUPINFOW startup{}; startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, TRUE, 0, nullptr, nullptr, &startup, &process))
        throw std::runtime_error("Cannot start bundled kallisto; Windows error " + std::to_string(GetLastError()));
    CloseHandle(process.hThread);
    DWORD code = 1;
    if (WaitForSingleObject(process.hProcess, INFINITE) == WAIT_OBJECT_0) GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess);
    return int(code);
#else
    std::vector<std::string> values{executable.string()};
    values.insert(values.end(), args.begin(), args.end());
    std::vector<char*> pointers;
    for (auto& value : values) pointers.push_back(value.data());
    pointers.push_back(nullptr);
    pid_t child = fork();
    if (child < 0) throw std::runtime_error("Cannot start bundled kallisto");
    if (!child) { execv(executable.c_str(), pointers.data()); _exit(127); }
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) throw std::runtime_error("Cannot wait for kallisto");
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
#endif
}

int main(int argc, char** argv) {
    try {
        if (argc != 12 || std::string(argv[1]) != "quant")
            throw std::runtime_error("Usage: adapter quant INDEX READ1 READ2-OR-DASH OUTPUT STRAND THREADS BOOTSTRAPS SEED FRAGMENT_MEAN FRAGMENT_SD");
        const std::string index = argv[2], read1 = argv[3], read2 = argv[4], strand = argv[6];
        const fs::path output = argv[5];
        const bool single = read2 == "-";
        integer(argv[7], 1, 64);
        const long long bootstraps = integer(argv[8], 0, 1000);
        integer(argv[9], 0, 2147483647);
        if (single) { integer(argv[10], 1, 10000); integer(argv[11], 1, 10000); }
        if (strand != "unstranded" && strand != "fr" && strand != "rf") throw std::runtime_error("Unknown RNA library strandedness");
        std::ifstream header(index, std::ios::binary);
        uint64_t version = 0;
        if (!header.read(reinterpret_cast<char*>(&version), sizeof(version)) || version != 13)
            throw std::runtime_error("Expected a compatible kallisto index version 13; build an index from the transcriptome FASTA with this pack");
        header.close();
        if (fs::exists(output / "abundance.tsv") || fs::exists(output / "bootstrap-estimates.tsv"))
            throw std::runtime_error("Output contains existing results; select a fresh Workbench run");
        fs::create_directories(output);
        std::vector<std::string> arguments{"quant", "--index", index, "--output-dir", output.string(), "--threads", argv[7], "--bootstrap-samples", argv[8], "--seed", argv[9], "--plaintext"};
        if (single) arguments.insert(arguments.end(), {"--single", "--fragment-length", argv[10], "--sd", argv[11]});
        if (strand == "fr") arguments.push_back("--fr-stranded");
        if (strand == "rf") arguments.push_back("--rf-stranded");
        arguments.push_back(read1);
        if (!single) arguments.push_back(read2);
        fs::path executable = fs::absolute(argv[0]).parent_path() / "kallisto";
#ifdef _WIN32
        executable += ".exe";
#endif
        const int result = run(executable, arguments);
        if (result) return result;
        const std::string columns = "target_id\tlength\teff_length\test_counts\ttpm";
        std::ofstream merged(output / "bootstrap-estimates.tsv", std::ios::binary);
        merged << "bootstrap\t" << columns << '\n';
        for (long long n = 0; n < bootstraps; ++n) {
            std::ifstream input(output / ("bs_abundance_" + std::to_string(n) + ".tsv"), std::ios::binary);
            std::string line;
            if (!std::getline(input, line)) throw std::runtime_error("kallisto did not write requested bootstrap estimates");
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line != columns) throw std::runtime_error("Unexpected kallisto bootstrap table columns");
            while (std::getline(input, line)) {
                if (!line.empty() && line.back() == '\r') line.pop_back();
                merged << n << '\t' << line << '\n';
            }
            if (!input.eof()) throw std::runtime_error("Cannot read bootstrap estimates");
        }
        merged.close();
        if (!merged) throw std::runtime_error("Cannot write combined bootstrap estimates");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "kallisto adapter: " << error.what() << '\n';
        return 1;
    }
}
