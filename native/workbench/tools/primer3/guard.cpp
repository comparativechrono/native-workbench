// SPDX-License-Identifier: MIT
// Bounded FASTA I/O and subprocess boundary. Primer3 performs primer design.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cmath>
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
    need(output != INVALID_HANDLE_VALUE, "Cannot create Primer3 execution log");
    HANDLE input = CreateFileA("NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               &security, OPEN_EXISTING, 0, nullptr);
    if (input == INVALID_HANDLE_VALUE) { CloseHandle(output); need(false, "Cannot open null input for Primer3"); }
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
    need(started, "Cannot start bundled Primer3 executable; reinstall this pack");
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return int(code);
#else
    pid_t process = fork();
    need(process >= 0, "Cannot start Primer3 subprocess");
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
    need(waitpid(process, &status, 0) == process, "Cannot wait for Primer3 subprocess");
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
#endif
}
static double decimal(const std::string& text, double low, double high, const std::string& name) {
    need(!text.empty() && text.size() <= 24, name + ": enter a finite decimal number");
    for (unsigned char c : text) need((c >= '0' && c <= '9') || c == '.', name + ": use a positive decimal number without units");
    size_t used = 0;
    double value;
    try { value = std::stod(text, &used); } catch (...) { throw std::runtime_error(name + ": enter a finite decimal number"); }
    need(used == text.size() && std::isfinite(value) && value >= low && value <= high,
         name + ": value outside supported range " + std::to_string(low) + ".." + std::to_string(high));
    return value;
}
static int integer(const std::string& text, int low, int high, const std::string& name) {
    for (unsigned char c : text) need(c >= '0' && c <= '9', name + ": enter a whole number");
    return int(decimal(text, low, high, name));
}
struct Template { std::string id, sequence; };
static Template fasta(const fs::path& path) {
    Template result;
    std::istringstream input(read(path, 2 * 1024 * 1024));
    std::string line;
    bool header = false;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        if (line.front() == '>') {
            need(!header, "Select exactly one template FASTA record; split multi-record files before designing primers");
            header = true;
            need(line.size() <= 1025, "FASTA header exceeds 1024 characters");
            for (unsigned char c : line) need(c >= 32 && c < 127, "Use an ASCII FASTA header");
            std::istringstream words(line.substr(1)); words >> result.id;
            need(!result.id.empty() && result.id.size() <= 128, "FASTA first-word identifier must contain 1..128 characters");
            for (unsigned char c : result.id) need(std::isalnum(c) || c == '_' || c == '.' || c == '-', "Rename the FASTA identifier using letters, digits, underscore, dot or hyphen");
        } else {
            need(header, "Select an uncompressed FASTA file beginning with a > header; gzip and raw Boulder input are unsupported");
            for (unsigned char c : line) {
                c = static_cast<unsigned char>(std::toupper(c));
                need(std::string("ACGTN").find(c) != std::string::npos, "Template must use A/C/G/T/N only; remove gaps and resolve other ambiguity codes explicitly");
                result.sequence += char(c);
            }
            need(result.sequence.size() <= 100000, "Template exceeds the 100000-base pack limit; select a local target region");
        }
    }
    need(result.sequence.size() >= 60, "Template requires at least 60 bases; select a longer target region");
    return result;
}
static std::string reverse_complement(std::string text) {
    std::reverse(text.begin(), text.end());
    for (char& c : text) {
        auto p = std::string("ACGTN").find(c);
        need(p != std::string::npos, "Invalid primer sequence reported by upstream");
        c = "TGCAN"[p];
    }
    return text;
}
static std::map<std::string, std::string> boulder(const fs::path& path) {
    std::map<std::string, std::string> result;
    std::istringstream input(read(path, 8 * 1024 * 1024));
    std::string line; int ends = 0;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line == "=") { ++ends; continue; }
        if (line.empty()) continue;
        auto split = line.find('=');
        need(split != std::string::npos && ends == 0, "Malformed Primer3 Boulder output");
        need(result.emplace(line.substr(0, split), line.substr(split + 1)).second, "Duplicate Primer3 result tag");
    }
    need(ends == 1, "Primer3 did not complete one Boulder result record");
    return result;
}
static std::string required(const std::map<std::string, std::string>& record, const std::string& key) {
    auto entry = record.find(key);
    need(entry != record.end(), "Primer3 output is missing " + key);
    return entry->second;
}
static std::pair<int,int> position(const std::string& text) {
    auto comma = text.find(',');
    need(comma != std::string::npos, "Malformed Primer3 binding position");
    return {integer(text.substr(0, comma), 0, 100000, "Binding start"), integer(text.substr(comma + 1), 12, 36, "Primer length")};
}
int main(int argc, char** argv) {
    try {
        need(argc == 16, "Usage: primer3-guard template.fa run-directory product-min product-max pairs size-min size-opt size-max tm-min tm-opt tm-max monovalent-mM divalent-mM dNTP-mM effective-oligo-nM");
        local(argv[1]); local(argv[2]);
        const fs::path input = fs::absolute(argv[1]), run = fs::absolute(argv[2]);
        need(fs::is_directory(run), "Run directory does not exist");
        const int product_min = integer(argv[3], 40, 10000, "Product minimum"), product_max = integer(argv[4], 40, 10000, "Product maximum");
        const int pairs = integer(argv[5], 1, 20, "Pairs requested");
        const int size_min = integer(argv[6], 12, 36, "Primer minimum length"), size_opt = integer(argv[7], 12, 36, "Primer optimum length"), size_max = integer(argv[8], 12, 36, "Primer maximum length");
        const double tm_min = decimal(argv[9], 0, 100, "Minimum Tm"), tm_opt = decimal(argv[10], 0, 100, "Optimum Tm"), tm_max = decimal(argv[11], 0, 100, "Maximum Tm");
        const double mono = decimal(argv[12], 0.01, 1000, "Monovalent salt (mM)"), div = decimal(argv[13], 0, 100, "Divalent salt (mM)"), dntp = decimal(argv[14], 0, 100, "Total dNTP (mM)"), oligo = decimal(argv[15], 0.01, 100000, "Effective annealing oligo concentration (nM)");
        need(product_min <= product_max, "Product minimum must not exceed product maximum");
        need(size_min <= size_opt && size_opt <= size_max, "Primer lengths must satisfy minimum <= optimum <= maximum");
        need(tm_min <= tm_opt && tm_opt <= tm_max, "Tm values must satisfy minimum <= optimum <= maximum");
        need(product_min >= size_max, "Product minimum must be at least the maximum primer length");
        const Template sequence = fasta(input);
        need(product_min <= int(sequence.sequence.size()), "Product minimum exceeds template length; choose a longer template or a smaller product range");
        for (const char* name : {"primers.tsv", "primer3-result.boulder", "primer3-input.boulder", "primer3-summary.json", "analysis-settings.json", "primer3.log"})
            need(!fs::exists(run / name), "Choose a fresh output folder; refusing to replace " + std::string(name));
        fs::path self = fs::absolute(argv[0]);
#ifdef _WIN32
        char module[32768];
        DWORD length = GetModuleFileNameA(nullptr, module, sizeof(module));
        need(length > 0 && length < sizeof(module), "Cannot locate installed Primer3");
        self = fs::path(std::string(module, length));
        const fs::path binary = self.parent_path() / "primer3_core.exe";
#else
        const fs::path binary = self.parent_path() / "primer3_core";
#endif
        const fs::path config = self.parent_path() / "primer3_config";
        local(binary.string()); local(config.string());
        need(fs::is_regular_file(binary), "Bundled primer3_core executable is missing; reinstall this pack");
        need(fs::is_directory(config), "Bundled thermodynamic configuration is missing; reinstall this pack");
        for (const char* name : {"dangle.dh", "dangle.ds", "loops.dh", "loops.ds", "stack.dh", "stack.ds", "stackmm.dh", "stackmm.ds", "tetraloop.dh", "tetraloop.ds", "triloop.dh", "triloop.ds", "tstack.dh", "tstack_tm_inf.ds", "tstack2.dh", "tstack2.ds"})
            need(fs::is_regular_file(config / name), "Bundled thermodynamic file is missing; reinstall this pack: " + std::string(name));
        std::map<std::string, std::string> settings = {
            {"PRIMER_TASK", "generic"}, {"PRIMER_PICK_LEFT_PRIMER", "1"}, {"PRIMER_PICK_RIGHT_PRIMER", "1"}, {"PRIMER_PICK_INTERNAL_OLIGO", "0"},
            {"PRIMER_FIRST_BASE_INDEX", "0"}, {"PRIMER_NUM_RETURN", argv[5]}, {"PRIMER_PRODUCT_SIZE_RANGE", std::string(argv[3]) + "-" + argv[4]},
            {"PRIMER_MIN_SIZE", argv[6]}, {"PRIMER_OPT_SIZE", argv[7]}, {"PRIMER_MAX_SIZE", argv[8]},
            {"PRIMER_MIN_TM", argv[9]}, {"PRIMER_OPT_TM", argv[10]}, {"PRIMER_MAX_TM", argv[11]},
            {"PRIMER_SALT_MONOVALENT", argv[12]}, {"PRIMER_SALT_DIVALENT", argv[13]}, {"PRIMER_DNTP_CONC", argv[14]}, {"PRIMER_DNA_CONC", argv[15]},
            {"PRIMER_TM_FORMULA", "1"}, {"PRIMER_SALT_CORRECTIONS", "1"}, {"PRIMER_THERMODYNAMIC_OLIGO_ALIGNMENT", "1"}, {"PRIMER_THERMODYNAMIC_TEMPLATE_ALIGNMENT", "0"},
            {"PRIMER_EXPLAIN_FLAG", "1"}, {"PRIMER_MAX_NS_ACCEPTED", "0"}, {"PRIMER_LIBERAL_BASE", "0"}, {"PRIMER_LOWERCASE_MASKING", "0"}, {"PRIMER_MASK_TEMPLATE", "0"},
            {"PRIMER_THERMODYNAMIC_PARAMETERS_PATH", config.generic_string() + "/"}
        };
        std::ostringstream request;
        request << "SEQUENCE_ID=" << sequence.id << "\nSEQUENCE_TEMPLATE=" << sequence.sequence << '\n';
        for (const auto& setting : settings) request << setting.first << '=' << setting.second << '\n';
        request << "=\n";
        write(run / "primer3-input.boulder", request.str());
        int code = child({binary.string(), "--default_version=2", "--io_version=4", "--strict_tags", "--output=" + (run / "primer3-result.boulder").string(), (run / "primer3-input.boulder").string()}, run / "primer3.log");
        need(code == 0, "Primer3 failed with exit " + std::to_string(code) + "; inspect primer3.log and primer3-result.boulder, confirm parameters and reinstall the pack if configuration is missing");
        const auto result = boulder(run / "primer3-result.boulder");
        auto error = result.find("PRIMER_ERROR");
        need(error == result.end() || error->second.empty(), "Primer3 rejected the request: " + (error == result.end() ? "unknown error" : error->second));
        int count = integer(required(result, "PRIMER_PAIR_NUM_RETURNED"), 0, pairs, "Returned pair count");
        std::ostringstream table, summary;
        table << "pair_rank\tleft_sequence_5to3\tright_sequence_5to3\tleft_start0\tleft_end0_exclusive\tright_start0\tright_end0_exclusive\tproduct_bp\tleft_tm_C\tright_tm_C\tleft_gc_percent\tright_gc_percent\tpair_penalty\n";
        summary << "{\n  \"tool\": \"Primer3\",\n  \"version\": \"2.6.1\",\n  \"templateId\": " << json(sequence.id) << ",\n  \"templateBases\": " << sequence.sequence.size() << ",\n  \"pairsRequested\": " << pairs << ",\n  \"pairsReturned\": " << count << ",\n  \"coordinateSystem\": \"zero-based half-open template intervals\",\n  \"specificityEvaluated\": false,\n  \"guidance\": " << json(count ? "Candidate primers require independent specificity and experimental assessment." : "No candidate pair satisfies the selected settings. Review PRIMER_LEFT_EXPLAIN, PRIMER_RIGHT_EXPLAIN and PRIMER_PAIR_EXPLAIN in the Boulder output; reconsider template, product range or design constraints.") << ",\n  \"pairs\": [";
        for (int i = 0; i < count; ++i) {
            std::string n = std::to_string(i), left = required(result, "PRIMER_LEFT_" + n + "_SEQUENCE"), right = required(result, "PRIMER_RIGHT_" + n + "_SEQUENCE");
            auto l = position(required(result, "PRIMER_LEFT_" + n)), r = position(required(result, "PRIMER_RIGHT_" + n));
            const int right_begin = r.first - r.second + 1, right_end = r.first + 1;
            need(l.first + l.second <= int(sequence.sequence.size()) && right_begin >= 0 && right_end <= int(sequence.sequence.size()), "Primer3 reported binding outside the template");
            need(left.size() == size_t(l.second) && right.size() == size_t(r.second) && sequence.sequence.substr(l.first, l.second) == left && reverse_complement(sequence.sequence.substr(right_begin, r.second)) == right, "Primer3 binding sequences do not match template coordinates");
            const std::string product = required(result, "PRIMER_PAIR_" + n + "_PRODUCT_SIZE");
            need(integer(product, product_min, product_max, "Reported product size") == right_end - l.first, "Primer3 product length is inconsistent with binding positions");
            const std::string ltm = required(result, "PRIMER_LEFT_" + n + "_TM"), rtm = required(result, "PRIMER_RIGHT_" + n + "_TM"), lgc = required(result, "PRIMER_LEFT_" + n + "_GC_PERCENT"), rgc = required(result, "PRIMER_RIGHT_" + n + "_GC_PERCENT"), penalty = required(result, "PRIMER_PAIR_" + n + "_PENALTY");
            decimal(ltm, 0, 100, "Reported left Tm"); decimal(rtm, 0, 100, "Reported right Tm"); decimal(lgc, 0, 100, "Reported GC"); decimal(rgc, 0, 100, "Reported GC"); decimal(penalty, 0, 100000, "Reported penalty");
            table << i + 1 << '\t' << left << '\t' << right << '\t' << l.first << '\t' << l.first + l.second << '\t' << right_begin << '\t' << right_end << '\t' << product << '\t' << ltm << '\t' << rtm << '\t' << lgc << '\t' << rgc << '\t' << penalty << '\n';
            if (i) summary << ',';
            summary << "\n    {\"rank\": " << i + 1 << ", \"productBases\": " << product << ", \"leftTmC\": " << ltm << ", \"rightTmC\": " << rtm << ", \"leftGcPercent\": " << lgc << ", \"rightGcPercent\": " << rgc << ", \"pairPenalty\": " << penalty << '}';
        }
        summary << "\n  ]\n}\n";
        write(run / "primers.tsv", table.str());
        write(run / "primer3-summary.json", summary.str());
        std::ostringstream recorded;
        recorded << "{\n  \"tool\": \"Primer3\",\n  \"version\": \"2.6.1\",\n  \"defaultVersion\": 2,\n  \"threads\": 1,\n  \"templateId\": " << json(sequence.id) << ",\n  \"templateInput\": " << json(input.string()) << ",\n  \"settings\": {";
        bool first = true;
        for (const auto& setting : settings) { if (!first) recorded << ','; first = false; recorded << "\n    " << json(setting.first) << ": " << json(setting.second); }
        recorded << "\n  },\n  \"model\": \"SantaLucia 1998 nearest-neighbor Tm and salt correction (formula 1, correction 1); concentrations are user settings, not measurements\",\n  \"specificityEvaluated\": false\n}\n";
        write(run / "analysis-settings.json", recorded.str());
        // Names clarify units; retain validated variables to catch unused validation regressions.
        (void)mono; (void)div; (void)dntp; (void)oligo;
        std::cout << "Primer3 returned " << count << " candidate pairs. Inspect primers.tsv and primer3-result.boulder; no specificity or experimental success is established.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Primer3 pack: " << error.what() << '\n';
        return 2;
    }
}
