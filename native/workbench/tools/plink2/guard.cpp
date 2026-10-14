// SPDX-License-Identifier: MIT
// Bounded VCF I/O and subprocess boundary. PLINK2 calculates the statistics.
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
    need(output != INVALID_HANDLE_VALUE, "Cannot create PLINK2 execution log");
    HANDLE input = CreateFileA("NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               &security, OPEN_EXISTING, 0, nullptr);
    if (input == INVALID_HANDLE_VALUE) { CloseHandle(output); need(false, "Cannot open null input for PLINK2"); }
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
    need(started, "Cannot start bundled PLINK2 executable; reinstall this pack");
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return int(code);
#else
    pid_t process = fork();
    need(process >= 0, "Cannot start PLINK2 subprocess");
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
    need(waitpid(process, &status, 0) == process, "Cannot wait for PLINK2 subprocess");
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
#endif
}
static std::vector<std::string> split(const std::string& value, char delimiter) {
    std::vector<std::string> result;
    size_t start = 0;
    do {
        size_t end = value.find(delimiter, start);
        result.push_back(value.substr(start, end == std::string::npos ? end : end - start));
        if (end == std::string::npos) break;
        start = end + 1;
    } while (true);
    return result;
}
static size_t integer(const std::string& value, size_t maximum) {
    need(!value.empty() && value.size() <= 10, "Expected a bounded nonnegative integer");
    size_t result = 0;
    for (char c : value) {
        need(c >= '0' && c <= '9', "Expected an integer, not: " + value);
        result = result * 10 + size_t(c - '0');
        need(result <= maximum, "Integer exceeds supported bound: " + value);
    }
    return result;
}
static void identifier(const std::string& value, bool sample) {
    need(!value.empty() && value.size() <= 128 && value != "." && (!sample || value != "0"),
         "Use nonmissing 1..128-character identifiers; sample ID 0 and identifier . are unsupported");
    for (unsigned char c : value)
        need(id_character(c), "Rename sample and variant identifiers using letters, digits, underscore, dot or hyphen");
}
struct Variant {
    std::string id, chromosome, position, ref, alt;
    size_t homref = 0, het = 0, homalt = 0, missing = 0;
};
struct Data {
    std::string bytes;
    std::vector<std::string> samples;
    std::vector<size_t> sample_missing;
    std::vector<Variant> variants;
    size_t missing = 0, alternate = 0;
};
static Data vcf(const fs::path& path) {
    Data result;
    result.bytes = read(path, MAX_INPUT);
    need(!result.bytes.empty() && result.bytes.rfind("##fileformat=VCFv4.", 0) == 0,
         "Select a plain uncompressed VCF 4.2 or 4.3 file; decompress gzip/BCF inputs first");
    for (unsigned char c : result.bytes)
        need((c >= 32 && c < 127) || c == '\t' || c == '\n' || c == '\r', "VCF must contain plain ASCII text");
    std::istringstream stream(result.bytes);
    std::string line;
    bool header = false, gt_header = false;
    std::set<std::string> sample_ids, variant_ids;
    size_t line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        need(!line.empty() && line.size() <= 2 * 1024 * 1024, "Empty or oversized VCF line; repair the input");
        need(line.find('\r') == std::string::npos, "Invalid embedded carriage return in VCF line");
        if (line_number == 1) {
            need(line == "##fileformat=VCFv4.2" || line == "##fileformat=VCFv4.3", "Only VCF 4.2 and 4.3 are supported");
            continue;
        }
        if (line.rfind("##", 0) == 0) {
            need(!header, "VCF metadata must precede the column header");
            if (line.rfind("##FORMAT=<ID=GT,", 0) == 0) {
                need(!gt_header && line.find("Number=1,") != std::string::npos && line.find("Type=String,") != std::string::npos,
                     "Provide one standard GT FORMAT declaration (Number=1, Type=String)");
                gt_header = true;
            }
            continue;
        }
        auto fields = split(line, '\t');
        if (line[0] == '#') {
            need(!header && gt_header, "Provide one VCF column header and standard GT FORMAT declaration");
            const std::vector<std::string> expected{"#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"};
            need(fields.size() >= 11 && fields.size() <= 1009, "The summary pack supports 2..1000 samples");
            need(std::equal(expected.begin(), expected.end(), fields.begin()), "Invalid VCF column header; use tab delimiters");
            for (size_t i = 9; i < fields.size(); ++i) {
                identifier(fields[i], true);
                need(sample_ids.insert(fields[i]).second, "Duplicate sample identifier: " + fields[i]);
                result.samples.push_back(fields[i]);
            }
            result.sample_missing.resize(result.samples.size());
            header = true;
            continue;
        }
        need(header, "Expected VCF column header before variant records");
        need(fields.size() == result.samples.size() + 9, "VCF record has the wrong number of tab-delimited sample columns");
        size_t chromosome = integer(fields[0], 22);
        need(chromosome >= 1 && fields[0] == std::to_string(chromosome), "Use human autosomes 1..22 only; sex, mitochondrial and other chromosomes require separate workflows");
        need(integer(fields[1], 2147483646) >= 1, "VCF positions must be positive");
        identifier(fields[2], false);
        need(variant_ids.insert(fields[2]).second, "Duplicate variant identifier: " + fields[2]);
        need(fields[3].size() == 1 && fields[4].size() == 1 && fields[3] != fields[4] &&
             std::string("ACGT").find(fields[3]) != std::string::npos && std::string("ACGT").find(fields[4]) != std::string::npos,
             "Only biallelic SNPs with distinct uppercase A/C/G/T REF and ALT are supported; select the intended SNPs explicitly");
        need(!fields[5].empty() && !fields[6].empty() && !fields[7].empty(), "Empty QUAL, FILTER or INFO field; use . for missing values");
        need(fields[8] == "GT", "Only GT-only hardcalls are supported; dosage, likelihood, depth and other FORMAT fields must not be silently discarded. Export a reviewed GT-only VCF");
        Variant variant{fields[2], fields[0], fields[1], fields[3], fields[4]};
        for (size_t i = 0; i < result.samples.size(); ++i) {
            const auto& gt = fields[i + 9];
            need(gt.size() == 3 && (gt[1] == '/' || gt[1] == '|'), "Use diploid GT calls 0/0, 0/1, 1/1 or ./. (phased equivalents accepted); haploid and polyploid calls are unsupported");
            if (gt[0] == '.' || gt[2] == '.') {
                need(gt[0] == '.' && gt[2] == '.', "Half-missing genotype is ambiguous; review it explicitly before analysis");
                ++variant.missing; ++result.missing; ++result.sample_missing[i];
            } else {
                need((gt[0] == '0' || gt[0] == '1') && (gt[2] == '0' || gt[2] == '1'), "GT allele index must be 0 or 1 for biallelic SNPs");
                size_t alt = size_t(gt[0] - '0' + gt[2] - '0');
                result.alternate += alt;
                if (alt == 0) ++variant.homref;
                else if (alt == 1) ++variant.het;
                else ++variant.homalt;
            }
        }
        result.variants.push_back(variant);
        need(result.variants.size() <= 100000 && result.variants.size() * result.samples.size() <= 10000000,
             "Pack bounds are 100000 variants and 10000000 genotypes; select a smaller reviewed dataset");
    }
    need(header && !result.variants.empty(), "VCF contains no variant records; select at least one biallelic SNP");
    return result;
}
using Row = std::map<std::string, std::string>;
static std::vector<Row> table(const fs::path& path) {
    std::istringstream stream(read(path, MAX_INPUT));
    std::string line;
    need(bool(std::getline(stream, line)), "PLINK2 output is empty: " + path.string());
    if (!line.empty() && line.back() == '\r') line.pop_back();
    auto headers = split(line, '\t');
    std::vector<Row> rows;
    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto fields = split(line, '\t');
        need(fields.size() == headers.size(), "Malformed PLINK2 output table");
        Row row;
        for (size_t i = 0; i < fields.size(); ++i) row[headers[i]] = fields[i];
        rows.push_back(row);
    }
    return rows;
}
static void equal_count(const Row& row, const std::string& key, size_t expected) {
    auto value = row.find(key);
    need(value != row.end() && integer(value->second, 20000000) == expected,
         "PLINK2 output did not preserve recorded genotype counts: " + key);
}
int main(int argc, char** argv) {
    try {
        need(argc == 3, "Usage: plink2-guard input.vcf run-directory");
        local(argv[1]); local(argv[2]);
        fs::path input = fs::absolute(argv[1]), run = fs::absolute(argv[2]);
        need(fs::is_directory(run), "Run directory does not exist");
        for (const char* name : {"plink.afreq", "plink.gcount", "plink.smiss", "plink.vmiss", "summary.json", "settings.json", "plink.log", "adapter.log", "plink-work"})
            need(!fs::exists(run / name), "Choose a fresh output folder; output already exists: " + std::string(name));
        Data data = vcf(input);
        fs::path self = fs::absolute(argv[0]);
#ifdef _WIN32
        char module[32768];
        DWORD length = GetModuleFileNameA(nullptr, module, sizeof(module));
        need(length > 0 && length < sizeof(module), "Cannot locate installed PLINK2");
        self = fs::path(std::string(module, length));
        fs::path binary = self.parent_path() / "plink2.exe";
#else
        fs::path binary = self.parent_path() / "plink2";
#endif
        local(binary.string());
        need(fs::is_regular_file(binary), "Bundled PLINK2 executable is missing; reinstall this pack");
        fs::path work = run / "plink-work";
        fs::create_directory(work);
        write(work / "input.vcf", data.bytes);
        std::vector<std::string> args{binary.string(), "--vcf", (work / "input.vcf").string(), "--const-fid", "0", "--nonfounders", "--threads", "1", "--memory", "640", "require", "--freq", "cols=chrom,pos,ref,alt,altfreq,nobs", "--geno-counts", "cols=chrom,pos,ref,alt,homref,refalt,homalt1,missing", "--missing", "scols=nmiss,nobs,fmiss", "vcols=chrom,pos,ref,alt,nmiss,nobs,fmiss", "--out", (work / "plink").string()};
        std::ostringstream settings;
        settings << "{\n  \"schema\": 1, \"tool\": \"PLINK2\", \"version\": \"2.0.0-a.7.12\",\n"
                 << "  \"inputMode\": \"VCF GT-only diploid biallelic autosomal SNPs\",\n"
                 << "  \"threads\": 1, \"memoryMiB\": 640, \"memoryIsWholeProcessLimit\": false,\n"
                 << "  \"filtersApplied\": false, \"allSamplesIncluded\": true, \"phaseUsed\": false,\n"
                 << "  \"args\": [";
        for (size_t i = 0; i < args.size(); ++i) settings << (i ? ", " : "") << json(args[i]);
        settings << "]\n}\n";
        write(run / "settings.json", settings.str());
        int code = child(args, run / "adapter.log");
        if (fs::is_regular_file(work / "plink.log")) write(run / "plink.log", read(work / "plink.log", MAX_INPUT));
        need(code == 0, "PLINK2 failed (exit " + std::to_string(code) + "). Read adapter.log and plink.log; verify the local VCF, available memory and writable output folder");
        auto freq = table(work / "plink.afreq"), geno = table(work / "plink.gcount"), vm = table(work / "plink.vmiss"), sm = table(work / "plink.smiss");
        need(freq.size() == data.variants.size() && geno.size() == data.variants.size() && vm.size() == data.variants.size() && sm.size() == data.samples.size(), "Unexpected PLINK2 output record count");
        for (size_t i = 0; i < data.variants.size(); ++i) {
            auto& variant = data.variants[i];
            need(freq[i].at("ID") == variant.id && geno[i].at("ID") == variant.id && vm[i].at("ID") == variant.id,
                 "PLINK2 changed variant identifiers or order");
            equal_count(freq[i], "OBS_CT", 2 * (data.samples.size() - variant.missing));
            equal_count(geno[i], "HOM_REF_CT", variant.homref);
            equal_count(geno[i], "HET_REF_ALT_CTS", variant.het);
            equal_count(geno[i], "HOM_ALT1_CT", variant.homalt);
            equal_count(geno[i], "MISSING_CT", variant.missing);
            equal_count(vm[i], "MISSING_CT", variant.missing);
            equal_count(vm[i], "OBS_CT", data.samples.size());
        }
        for (size_t i = 0; i < data.samples.size(); ++i) {
            need(sm[i].at("#IID") == data.samples[i], "PLINK2 changed sample identifiers or order");
            equal_count(sm[i], "MISSING_CT", data.sample_missing[i]);
            equal_count(sm[i], "OBS_CT", data.variants.size());
        }
        for (const char* name : {"plink.afreq", "plink.gcount", "plink.smiss", "plink.vmiss"}) write(run / name, read(work / name, MAX_INPUT));
        size_t total = data.samples.size() * data.variants.size();
        std::ostringstream summary;
        summary << "{\n  \"schema\": 1, \"tool\": \"PLINK2\", \"version\": \"2.0.0-a.7.12\",\n"
                << "  \"samples\": " << data.samples.size() << ", \"variants\": " << data.variants.size() << ",\n"
                << "  \"totalGenotypes\": " << total << ", \"calledGenotypes\": " << total - data.missing << ",\n"
                << "  \"missingGenotypes\": " << data.missing << ", \"observedAlleles\": " << 2 * (total - data.missing) << ",\n"
                << "  \"alternateAlleles\": " << data.alternate << ", \"missingFraction\": " << std::setprecision(12) << double(data.missing) / double(total) << ",\n"
                << "  \"interpretation\": \"Recorded hardcall measurements; no QC pass thresholds. All samples and variants included regardless of FILTER. ALT frequency is not minor allele frequency; all-missing allele frequencies remain undefined. No ancestry or clinical interpretation.\"\n}\n";
        write(run / "summary.json", summary.str());
        std::cout << "Recorded PLINK2 summaries for " << data.samples.size() << " samples and " << data.variants.size() << " variants.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "PLINK2 pack: " << error.what() << '\n';
        return 2;
    }
}
