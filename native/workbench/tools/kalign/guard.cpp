// SPDX-License-Identifier: MIT
// Bounded FASTA I/O and subprocess boundary. Kalign performs the alignment.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace fs = std::filesystem;
constexpr size_t MAX_INPUT = 64 * 1024 * 1024;
constexpr size_t MAX_OUTPUT = 256 * 1024 * 1024;
constexpr size_t MAX_RESIDUES = 10000000;
static void need(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
static std::string json(const std::string& value) {
    std::string result = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') { result += '\\'; result += char(c); }
        else if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else { need(c >= 32 && c < 127, "ASCII text required"); result += char(c); }
    }
    return result + '"';
}
static void local(const std::string& path) {
    need(!path.empty() && path != "-" && path.find("://") == std::string::npos,
         "Select explicit local paths, not a URL or standard input");
    for (unsigned char c : path)
        need(c >= 32 && c < 127,
             "ASCII installation, input and results paths required; spaces are supported");
}
static std::string read(const fs::path& path, size_t maximum) {
    need(fs::is_regular_file(path), "Cannot read file: " + path.string());
    need(fs::file_size(path) <= maximum, "File exceeds bounded pack size limit: " + path.string());
    std::ifstream input(path, std::ios::binary);
    need(bool(input), "Cannot read file: " + path.string());
    return std::string(std::istreambuf_iterator<char>(input), {});
}
static void write(const fs::path& path, const std::string& content) {
    need(!fs::exists(path), "Refusing to replace existing output: " + path.string());
    std::ofstream output(path, std::ios::binary);
    need(bool(output), "Cannot create output: " + path.string());
    output << content;
    output.close();
    need(bool(output), "Output write failed: " + path.string());
}
static bool id_character(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-';
}
static std::string token(size_t index) {
    std::ostringstream result;
    result << 'S' << std::setw(6) << std::setfill('0') << index + 1;
    return result.str();
}
struct Sequences {
    std::vector<std::string> ids, headers, rows;
    size_t residues = 0, ambiguities = 0;
};
static Sequences fasta(const fs::path& path, bool nucleotide, bool aligned) {
    Sequences result;
    std::istringstream input(read(path, aligned ? MAX_OUTPUT : MAX_INPUT));
    std::set<std::string> ids;
    const std::string allowed = nucleotide ? "ACGTURYSWKMBDHVN" : "ACDEFGHIKLMNPQRSTVWYBXZ";
    const std::string canonical = nucleotide ? "ACGTU" : "ACDEFGHIKLMNPQRSTVWY";
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        if (line.front() == '>') {
            std::string header = line.substr(1), id;
            need(!header.empty() && header.size() <= 1024,
                 "FASTA headers must contain 1..1024 ASCII characters");
            for (unsigned char c : header)
                need((c >= 32 && c < 127) || c == '\t', "FASTA headers must be ASCII text");
            std::istringstream words(header);
            words >> id;
            need(!id.empty() && id.size() <= 128,
                 "FASTA first-word identifiers must contain 1..128 characters");
            for (unsigned char c : id)
                need(id_character(c), "Rename FASTA identifiers using only letters, digits, underscore, dot or hyphen");
            need(ids.insert(id).second, "Duplicate FASTA first-word identifier: " + id);
            need(result.ids.size() < 10000, "At most 10000 sequences are supported by this pack");
            result.ids.push_back(id);
            result.headers.push_back(header);
            result.rows.emplace_back();
        } else {
            need(!result.rows.empty(), "Expected uncompressed FASTA beginning with >; decompress the input first");
            for (unsigned char raw : line) {
                need(raw < 128, "Non-ASCII sequence character; select an uncompressed FASTA file");
                char c = char(std::toupper(raw));
                if (aligned && c == '-') { result.rows.back() += c; continue; }
                need(c != '-' && c != '.', "Input contains alignment gaps; select unaligned homologous sequences");
                need(allowed.find(c) != std::string::npos,
                     nucleotide ? "Unsupported nucleotide symbol; use ungapped DNA/RNA IUPAC letters without sequence whitespace"
                                : "Unsupported protein symbol; use standard amino acids or B/X/Z without gaps or whitespace. Inspect stops before removing appropriate terminal *; J/U/O are unsupported");
                result.rows.back() += c;
                ++result.residues;
                if (canonical.find(c) == std::string::npos) ++result.ambiguities;
                need(result.residues <= MAX_RESIDUES, "At most 10000000 input residues are supported by this pack");
            }
            need(result.rows.back().size() <= (aligned ? MAX_RESIDUES : 15000),
                 "At most 15000 residues per unaligned sequence are supported by this pack");
        }
    }
    need(result.ids.size() >= 2, "At least two nonempty homologous sequences are required");
    for (size_t i = 0; i < result.rows.size(); ++i)
        need(!result.rows[i].empty(), "Empty FASTA sequence: " + result.ids[i]);
    return result;
}
static int child(const std::vector<std::string>& arguments, const fs::path& log) {
#ifdef _WIN32
    std::string command;
    for (const auto& arg : arguments) {
        if (!command.empty()) command += ' ';
        command += '"';
        size_t slashes = 0;
        for (char c : arg) {
            if (c == '\\') { ++slashes; continue; }
            if (c == '"') { command.append(slashes * 2 + 1, '\\'); command += '"'; }
            else { command.append(slashes, '\\'); command += c; }
            slashes = 0;
        }
        command.append(slashes * 2, '\\');
        command += '"';
    }
    SECURITY_ATTRIBUTES security{sizeof(security), nullptr, TRUE};
    HANDLE output = CreateFileA(log.string().c_str(), GENERIC_WRITE, FILE_SHARE_READ,
                                &security, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    need(output != INVALID_HANDLE_VALUE, "Cannot create Kalign execution log");
    HANDLE input = CreateFileA("NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               &security, OPEN_EXISTING, 0, nullptr);
    if (input == INVALID_HANDLE_VALUE) { CloseHandle(output); need(false, "Cannot open null input for Kalign"); }
    STARTUPINFOA startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdOutput = startup.hStdError = output;
    startup.hStdInput = input;
    PROCESS_INFORMATION process{};
    BOOL started = CreateProcessA(arguments[0].c_str(), command.data(), nullptr, nullptr,
                                   TRUE, CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process);
    CloseHandle(output);
    CloseHandle(input);
    need(started, "Cannot start bundled Kalign executable; reinstall this pack");
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return int(code);
#else
    pid_t process = fork();
    need(process >= 0, "Cannot start Kalign subprocess");
    if (process == 0) {
        int output = open(log.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
        int input = open("/dev/null", O_RDONLY);
        if (output < 0 || input < 0) _exit(126);
        dup2(output, STDOUT_FILENO);
        dup2(output, STDERR_FILENO);
        dup2(input, STDIN_FILENO);
        close(output);
        close(input);
        std::vector<char*> argv;
        for (const auto& arg : arguments) argv.push_back(const_cast<char*>(arg.c_str()));
        argv.push_back(nullptr);
        execv(argv[0], argv.data());
        _exit(127);
    }
    int status = 0;
    need(waitpid(process, &status, 0) == process, "Cannot wait for Kalign subprocess");
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
#endif
}
int main(int argc, char** argv) {
    try {
        need(argc == 4, "Usage: kalign-guard sequences run-directory nucleotide|protein");
        local(argv[1]); local(argv[2]);
        const fs::path input = fs::absolute(argv[1]), run = fs::absolute(argv[2]);
        need(fs::is_directory(run), "Run directory does not exist");
        const std::string datatype = argv[3];
        const bool nucleotide = datatype == "nucleotide";
        need(nucleotide || datatype == "protein", "Choose nucleotide or protein explicitly");
        for (const char* name : {"alignment.afa", "alignment-summary.json", "analysis-settings.json", "kalign.log", "kalign-work"})
            need(!fs::exists(run / name), "Choose a fresh output folder; output already exists: " + std::string(name));
        Sequences original = fasta(input, nucleotide, false);
        fs::path self = fs::absolute(argv[0]);
#ifdef _WIN32
        char module[32768];
        DWORD length = GetModuleFileNameA(nullptr, module, sizeof(module));
        need(length > 0 && length < sizeof(module), "Cannot locate installed Kalign");
        self = fs::path(std::string(module, length));
        fs::path binary = self.parent_path() / "kalign.exe";
#else
        fs::path binary = self.parent_path() / "kalign";
#endif
        local(binary.string());
        need(fs::is_regular_file(binary), "Bundled Kalign executable is missing; reinstall this pack");
        const fs::path work = run / "kalign-work";
        fs::create_directory(work);
        std::ostringstream staged;
        for (size_t i = 0; i < original.rows.size(); ++i)
            staged << '>' << token(i) << '\n' << original.rows[i] << '\n';
        write(work / "sequences.fa", staged.str());
        std::vector<std::string> arguments{binary.string(), "-i", (work / "sequences.fa").string(),
            "-o", (work / "alignment.afa").string(), "--type", nucleotide ? "dna" : "protein",
            "-n", "1", "-f", "fasta"};
        std::ostringstream settings;
        settings << "{\n  \"tool\": \"Kalign\", \"version\": \"3.5.1-workbench1\",\n"
                 << "  \"datatype\": " << json(datatype) << ", \"upstreamType\": " << json(nucleotide ? "dna" : "protein")
                 << ", \"mode\": \"default\", \"threads\": 1, \"serial\": true,\n"
                 << "  \"consistencyAnchors\": 5, \"consistencyWeight\": 2.0, \"ensembleRuns\": 0, \"refinement\": \"none\",\n"
                 << "  \"sequenceMapping\": [";
        for (size_t i = 0; i < original.ids.size(); ++i) {
            if (i) settings << ',';
            settings << "{\"stagedId\":" << json(token(i)) << ",\"originalId\":" << json(original.ids[i])
                     << ",\"originalHeader\":" << json(original.headers[i]) << '}';
        }
        settings << "],\n  \"argv\": [";
        for (size_t i = 0; i < arguments.size(); ++i) { if (i) settings << ','; settings << json(arguments[i]); }
        settings << "]\n}\n";
        write(run / "analysis-settings.json", settings.str());
        int code = child(arguments, run / "kalign.log");
        need(code == 0, "Kalign exited with status " + std::to_string(code) + "; inspect kalign.log and verify the input contains homologous sequences");
        Sequences aligned = fasta(work / "alignment.afa", nucleotide, true);
        need(aligned.ids.size() == original.ids.size(), "Kalign output changed the number of sequences; inspect kalign.log");
        std::map<std::string, std::string> by_id;
        for (size_t i = 0; i < aligned.ids.size(); ++i) by_id[aligned.ids[i]] = aligned.rows[i];
        size_t columns = aligned.rows.front().size(), gaps = 0, all_gap_columns = 0;
        std::vector<std::string> ordered;
        std::ostringstream restored;
        for (size_t i = 0; i < original.ids.size(); ++i) {
            need(by_id.count(token(i)) != 0, "Kalign output omitted or changed a sequence identifier");
            const std::string& row = by_id.at(token(i));
            need(row.size() == columns, "Kalign output rows have different lengths");
            std::string residues;
            for (char c : row) { if (c == '-') ++gaps; else residues += c; }
            need(residues == original.rows[i], "Kalign output changed ungapped residues for " + original.ids[i]);
            ordered.push_back(row);
            restored << '>' << original.headers[i] << '\n';
            for (size_t offset = 0; offset < row.size(); offset += 80) restored << row.substr(offset, 80) << '\n';
        }
        for (size_t column = 0; column < columns; ++column) {
            bool all_gap = true;
            for (const auto& row : ordered) if (row[column] != '-') { all_gap = false; break; }
            if (all_gap) ++all_gap_columns;
        }
        size_t minimum = original.rows.front().size(), maximum = minimum;
        for (const auto& row : original.rows) { minimum = std::min(minimum, row.size()); maximum = std::max(maximum, row.size()); }
        std::ostringstream summary;
        summary << "{\n  \"sequences\": " << original.ids.size() << ",\n  \"inputResidues\": " << original.residues
                << ",\n  \"minInputLength\": " << minimum << ",\n  \"maxInputLength\": " << maximum
                << ",\n  \"columns\": " << columns << ",\n  \"gapCharacters\": " << gaps
                << ",\n  \"allGapColumns\": " << all_gap_columns << ",\n  \"ambiguityCharacters\": " << original.ambiguities
                << ",\n  \"preservedUngappedResidues\": true,\n  \"preservedInputOrder\": true,\n"
                << "  \"interpretation\": \"Recorded alignment measurements only; no QC pass thresholds. Alignment does not establish homology, orthology, a gene tree or a species tree.\"\n}\n";
        write(run / "alignment-summary.json", summary.str());
        write(run / "alignment.afa", restored.str());
        std::cout << "Kalign completed; recorded " << original.ids.size() << " sequences and " << columns << " aligned columns.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Kalign pack: " << error.what() << '\n';
        return 2;
    }
}
