#include "pack_model.h"
#include <algorithm>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>

namespace bw {
namespace {
using Fields = std::map<std::wstring, std::wstring>;
using Sections = std::map<std::wstring, Fields>;
[[noreturn]] void fail(const char *message) {
    throw std::runtime_error(message);
}
void require(bool condition, const char *message) {
    if (!condition)
        fail(message);
}
bool digit(wchar_t c) {
    return c >= L'0' && c <= L'9';
}
bool lower(wchar_t c) {
    return c >= L'a' && c <= L'z';
}
std::wstring fold(std::wstring s) {
    for (auto &c : s)
        if (c >= L'A' && c <= L'Z')
            c += L'a' - L'A';
    return s;
}
std::wstring trim(const std::wstring &s) {
    const auto first = s.find_first_not_of(L" \t");
    return first == s.npos ? L"" : s.substr(first, s.find_last_not_of(L" \t") - first + 1);
}
bool identifier(const std::wstring &s) {
    return !s.empty() && s.size() <= 48 && lower(s.front()) && s.back() != L'-' &&
           std::all_of(s.begin(), s.end(), [](wchar_t c) { return lower(c) || digit(c) || c == L'-'; });
}
bool version(const std::wstring &s) {
    if (s.empty() || s.size() > 32)
        return false;
    size_t start = 0;
    for (int i = 0; i < 3; ++i) {
        size_t end = s.find(L'.', start);
        if (end == s.npos)
            end = s.size();
        if (end == start || end - start > 9 || (end - start > 1 && s[start] == L'0'))
            return false;
        for (size_t j = start; j < end; ++j)
            if (!digit(s[j]))
                return false;
        if ((i < 2 && end == s.size()) || (i == 2 && end != s.size()))
            return false;
        start = end + 1;
    }
    return true;
}
bool clean(const std::wstring &s, size_t maximum, bool empty = false) {
    return (empty || !s.empty()) && s.size() <= maximum &&
           std::all_of(s.begin(), s.end(), [](wchar_t c) { return c >= 32 && c != 127; });
}
std::vector<std::wstring> split(const std::wstring &s, wchar_t separator, bool allow_empty = false) {
    std::vector<std::wstring> result;
    if (s.empty() && allow_empty)
        return result;
    size_t start = 0;
    for (;;) {
        auto end = s.find(separator, start);
        result.push_back(trim(s.substr(start, end == s.npos ? s.npos : end - start)));
        require(!result.back().empty(), "Empty item in a manifest list.");
        if (end == s.npos)
            break;
        start = end + 1;
    }
    return result;
}
std::vector<std::wstring> ids(const std::wstring &s, size_t maximum, bool empty = false) {
    auto result = split(s, L',', empty);
    std::set<std::wstring> seen;
    require(result.size() <= maximum, "Too many IDs in a manifest list.");
    for (const auto &id : result)
        require(identifier(id) && seen.insert(id).second, "Invalid or duplicate ID in a manifest list.");
    return result;
}
const std::wstring &get(const Fields &fields, const wchar_t *key) {
    auto it = fields.find(key);
    require(it != fields.end(), "A required manifest key is missing.");
    return it->second;
}
std::wstring optional(const Fields &f, const wchar_t *key, const wchar_t *fallback = L"") {
    auto it = f.find(key);
    return it == f.end() ? fallback : it->second;
}
void keys(const Fields &fields, std::initializer_list<const wchar_t *> allowed, bool arguments = false) {
    for (const auto &field : fields) {
        bool found = false;
        for (const auto *a : allowed)
            if (field.first == a) {
                found = true;
                break;
            }
        if (arguments && (field.first.rfind(L"arg.", 0) == 0 || field.first.rfind(L"sink-arg.", 0) == 0))
            found = true;
        require(found, "Unknown manifest key.");
    }
}
bool boolean(const std::wstring &s) {
    require(s == L"true" || s == L"false", "Boolean values must be true or false.");
    return s == L"true";
}
long long integer(const std::wstring &s) {
    require(!s.empty() && s.size() <= 20, "Invalid integer.");
    size_t start = s[0] == L'-' ? 1 : 0;
    require(start < s.size(), "Invalid integer.");
    for (size_t i = start; i < s.size(); ++i)
        require(digit(s[i]), "Invalid integer.");
    try {
        size_t used = 0;
        auto value = std::stoll(s, &used);
        require(used == s.size(), "Invalid integer.");
        return value;
    } catch (const std::exception &) {
        fail("Integer is outside the supported range.");
    }
}
bool safe_component(const std::wstring &s) {
    if (!clean(s, 180) || s == L"." || s == L".." || s.back() == L'.' || s.back() == L' ' ||
        s.find_first_of(L"\\/:<>\"|?*{}") != s.npos)
        return false;
    const auto stem = fold(s.substr(0, s.find(L'.')));
    if (stem == L"con" || stem == L"prn" || stem == L"aux" || stem == L"nul" || stem == L"conin$" ||
        stem == L"conout$")
        return false;
    if (stem.size() == 4 && (stem.substr(0, 3) == L"com" || stem.substr(0, 3) == L"lpt") &&
        ((stem[3] >= L'1' && stem[3] <= L'9') || stem[3] == 0xb9 || stem[3] == 0xb2 || stem[3] == 0xb3))
        return false;
    return true;
}
std::wstring relative_path(std::wstring s) {
    require(!s.empty() && s.size() <= 240, "Relative path is empty or too long.");
    std::replace(s.begin(), s.end(), L'\\', L'/');
    size_t start = 0;
    unsigned count = 0;
    for (;;) {
        auto end = s.find(L'/', start);
        require(safe_component(s.substr(start, end == s.npos ? s.npos : end - start)),
                "Unsafe relative path.");
        require(++count <= 12, "Relative path is nested too deeply.");
        if (end == s.npos)
            break;
        start = end + 1;
    }
    return s;
}
Sections parse_sections(std::wstring text) {
    require(text.size() <= 2 * 1024 * 1024, "Manifest exceeds 2 Mi characters.");
    require(text.find(L'\0') == text.npos, "Manifest contains a NUL character.");
    if (!text.empty() && text[0] == 0xfeff)
        text.erase(0, 1);
    Sections sections;
    std::wistringstream stream(text);
    std::wstring line, section;
    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == L'\r')
            line.pop_back();
        require(line.size() <= 8192, "Manifest line exceeds 8192 characters.");
        require(std::all_of(line.begin(), line.end(), [](wchar_t c) { return c >= 32 || c == L'\t'; }),
                "Manifest contains a control character.");
        line = trim(line);
        if (line.empty() || line[0] == L';' || line[0] == L'#')
            continue;
        if (line.front() == L'[' && line.back() == L']') {
            section = line.substr(1, line.size() - 2);
            require(!section.empty() && sections.emplace(section, Fields{}).second,
                    "Empty or duplicate manifest section.");
            require(sections.size() <= 10000, "Too many manifest sections.");
            continue;
        }
        const auto equals = line.find(L'=');
        require(!section.empty() && equals != line.npos, "Expected section and key=value.");
        auto key = trim(line.substr(0, equals));
        auto value = trim(line.substr(equals + 1));
        require(!key.empty() && sections.at(section).emplace(key, value).second,
                "Empty or duplicate manifest key.");
        require(sections.at(section).size() <= 288, "Too many keys in a manifest section.");
    }
    return sections;
}
Tool parse_tool(const std::wstring &id, const Fields &f, bool legacy) {
    keys(f, {L"path", L"version", L"sha256"});
    Tool tool;
    tool.id = id;
    require(identifier(id), "Invalid tool ID.");
    tool.path = relative_path(get(f, L"path"));
    if (legacy)
        require(tool.path == L"bin/" + id + L".exe", "Legacy tool path must be bin/<tool-id>.exe.");
    else
        require(tool.path.size() > 4 && fold(tool.path.substr(tool.path.size() - 4)) == L".exe",
                "A tool must name a relative .exe file.");
    tool.version = get(f, L"version");
    require(clean(tool.version, 64) && std::all_of(tool.version.begin(), tool.version.end(),
                                                   [](wchar_t c) {
                                                       return lower(c) || (c >= L'A' && c <= L'Z') ||
                                                              digit(c) || c == L'.' || c == L'+' ||
                                                              c == L'_' || c == L'-';
                                                   }),
            "Invalid tool version.");
    tool.sha256 = fold(get(f, L"sha256"));
    require(tool.sha256.size() == 64 &&
                std::all_of(tool.sha256.begin(), tool.sha256.end(),
                            [](wchar_t c) { return digit(c) || (c >= L'a' && c <= L'f'); }),
            "Invalid SHA-256.");
    return tool;
}
Asset parse_asset(const std::wstring &id, const Fields &fields) {
    keys(fields, {L"path", L"sha256"});
    require(identifier(id), "Invalid asset ID.");
    Asset asset{id, relative_path(get(fields, L"path")), fold(get(fields, L"sha256"))};
    require(asset.sha256.size() == 64 &&
                std::all_of(asset.sha256.begin(), asset.sha256.end(),
                            [](wchar_t c) { return digit(c) || (c >= L'a' && c <= L'f'); }),
            "Invalid asset SHA-256.");
    return asset;
}
void declare_pack_file(const std::wstring &value, std::set<std::wstring> &paths) {
    const auto path = fold(value);
    require(std::all_of(path.begin(), path.end(), [](wchar_t c) { return c >= 32 && c <= 126; }),
            "Declared pack file paths must use printable ASCII; pack folders may use Unicode.");
    const auto first = path.substr(0, path.find(L'/'));
    require(first != L"pack.ini" && first != L"licenses" && first != L"pack-readme.md" &&
                first != L"pack-readme.txt" && first != L"readme.txt",
            "Declared pack file collides with reserved metadata.");
    require(!paths.count(path), "Declared pack file paths collide.");
    for (size_t i = 0; i < path.size(); ++i)
        if (path[i] == L'/')
            require(!paths.count(path.substr(0, i)), "A declared pack file is another file's parent.");
    const auto descendant = paths.lower_bound(path + L"/");
    require(descendant == paths.end() || descendant->rfind(path + L"/", 0) != 0,
            "A declared pack file is another file's parent.");
    paths.insert(path);
}
struct Placeholder {
    std::wstring kind, id;
};
std::vector<Placeholder> placeholders(const std::wstring &s) {
    std::vector<Placeholder> result;
    size_t start = 0;
    for (;;) {
        auto open = s.find_first_of(L"{}", start);
        if (open == s.npos)
            break;
        require(s[open] == L'{', "Unmatched placeholder brace.");
        auto close = s.find(L'}', open + 1);
        require(close != s.npos, "Unclosed placeholder.");
        auto body = s.substr(open + 1, close - open - 1);
        if (body == L"run")
            result.push_back({L"run", L""});
        else {
            auto colon = body.find(L':');
            require(colon != body.npos, "Unknown placeholder.");
            auto kind = body.substr(0, colon), id = body.substr(colon + 1);
            require((kind == L"input" || kind == L"inputs" || kind == L"output" || kind == L"asset") &&
                        identifier(id),
                    "Unknown or malformed placeholder.");
            require(kind != L"inputs" || (open == 0 && close + 1 == s.size()),
                    "A file-list placeholder must occupy a whole argument.");
            result.push_back({kind, id});
        }
        start = close + 1;
    }
    return result;
}
bool identifier_value(const std::wstring &s) {
    return !s.empty() && s.size() <= 64 && std::all_of(s.begin(), s.end(), [](wchar_t c) {
        return lower(c) || (c >= L'A' && c <= L'Z') || digit(c) || c == L'_' || c == L'.' || c == L'-';
    });
}
void validate_workflow(const Workflow &w, const std::set<std::wstring> &tools,
                       const std::set<std::wstring> &assets) {
    std::map<std::wstring, const Input *> inputs;
    std::set<std::wstring> outputs, paths, available;
    for (const auto &in : w.inputs)
        inputs.emplace(in.id, &in);
    for (const auto &in : w.inputs)
        if (!in.different_from.empty()) {
            auto it = inputs.find(in.different_from);
            require(in.type == L"file" && it != inputs.end() && it->second->type == L"file" &&
                        in.id != in.different_from,
                    "different-from must name another file input.");
        }
    for (const auto &out : w.outputs) {
        outputs.insert(out.id);
        auto path = fold(out.path);
        require(
            std::all_of(path.begin(), path.end(), [](wchar_t c) { return c >= 32 && c <= 126; }),
            "Declared output paths must use printable ASCII; labels and input folders may use Unicode.");
        const auto first = path.substr(0, path.find(L'/'));
        require(first != L"run.json" && first != L"run.json.pending" && first != L"workbench.log" &&
                    first != L"workbench.log.pending" && first != L"logs",
                "Output collides with a reserved workbench file.");
        for (const auto &prior : paths)
            require(path != prior && path.rfind(prior + L"/", 0) != 0 &&
                        prior.rfind(path + L"/", 0) != 0,
                    "Output paths collide.");
        paths.insert(path);
    }
    for (const auto &step : w.steps) {
        std::set<std::wstring> produced;
        auto produce = [&](const std::wstring &id) {
            require(outputs.count(id) && !available.count(id) && produced.insert(id).second,
                    "Unknown or duplicate output producer.");
        };
        if (step.kind == L"copy")
            produce(step.destination);
        else {
            require(tools.count(step.tool), "Step references an unknown tool.");
            if (step.kind == L"pipe")
                require(tools.count(step.sink_tool), "Pipe references an unknown sink tool.");
            if (!step.stdout_id.empty())
                produce(step.stdout_id);
            for (const auto &id : step.produces)
                produce(id);
        }
        auto check = [&](const std::wstring &value, bool copy) {
            const auto refs = placeholders(value);
            if (copy)
                require(refs.size() == 1 && value == L"{" + refs[0].kind + L":" + refs[0].id + L"}" &&
                            (refs[0].kind == L"input" || refs[0].kind == L"output" ||
                             refs[0].kind == L"asset"),
                        "Copy source must be one input, output or asset placeholder.");
            for (const auto &ref : refs) {
                if (ref.kind == L"input" || ref.kind == L"inputs") {
                    auto it = inputs.find(ref.id);
                    require(it != inputs.end(), "Step references an unknown input.");
                    require((ref.kind == L"inputs") == (it->second->type == L"files"),
                            "File lists require the whole-argument inputs placeholder.");
                    if (copy)
                        require(it->second->type == L"file", "Copy source input must have type file.");
                } else if (ref.kind == L"asset") {
                    require(assets.count(ref.id), "Step references an unknown asset.");
                } else if (ref.kind == L"output") {
                    require(outputs.count(ref.id) &&
                                (available.count(ref.id) || (!copy && produced.count(ref.id))),
                            "Output is used before it is produced.");
                }
            }
        };
        if (step.kind == L"copy")
            check(step.source, true);
        else {
            for (const auto &arg : step.args)
                check(arg, false);
            for (const auto &arg : step.sink_args)
                check(arg, false);
        }
        available.insert(produced.begin(), produced.end());
    }
    require(available == outputs, "Every output must have exactly one producer.");
}
Input legacy_file(const wchar_t *id, const wchar_t *label) {
    Input i;
    i.id = id;
    i.label = label;
    return i;
}
Input legacy_threads() {
    Input i;
    i.id = L"threads";
    i.label = L"Threads";
    i.type = L"integer";
    i.default_value = L"2";
    i.minimum = 1;
    i.maximum = 64;
    return i;
}
void legacy_workflows(Pack &p) {
    Workflow stats;
    stats.id = L"statistics";
    stats.name = L"FASTQ statistics";
    stats.description = L"Count reads and bases in an uncompressed FASTQ file.";
    stats.inputs = {legacy_file(L"reads", L"Reads"), legacy_threads()};
    stats.outputs = {{L"statistics", L"FASTQ statistics", L"reads.stats.json", true, true}};
    Step ss;
    ss.id = L"statistics";
    ss.label = L"Calculate FASTQ statistics";
    ss.tool = L"bwfastq";
    ss.stdout_id = L"statistics";
    ss.args = {L"stats", L"--input",   L"{input:reads}",  L"--output",
               L"-",     L"--threads", L"{input:threads}"};
    stats.steps = {ss};
    p.workflows.push_back(stats);
    Workflow reverse;
    reverse.id = L"reverse-complement";
    reverse.name = L"Reverse complement";
    reverse.inputs = {legacy_file(L"reads", L"Reads")};
    reverse.outputs = {{L"reverse", L"Reverse complemented reads", L"reverse.fastq", true, true}};
    Step sr;
    sr.id = L"reverse";
    sr.label = L"Reverse complement";
    sr.tool = L"seqtk";
    sr.stdout_id = L"reverse";
    sr.args = {L"seq", L"-r", L"{input:reads}"};
    reverse.steps = {sr};
    p.workflows.push_back(reverse);
    Workflow align;
    align.id = L"alignment";
    align.name = L"Align reads";
    align.description =
        L"Legacy single-read-file alignment. Use a paired-read workflow for paired FASTQ files.";
    align.inputs = {legacy_file(L"reads", L"Reads"), legacy_file(L"reference", L"Reference genome"),
                    legacy_threads()};
    Input preset;
    preset.id = L"preset";
    preset.label = L"Read type";
    preset.type = L"choice";
    preset.default_value = L"sr";
    preset.choices = {
        {L"sr", L"Short reads"}, {L"map-ont", L"Oxford Nanopore"}, {L"map-hifi", L"PacBio HiFi"}};
    align.inputs.push_back(preset);
    align.outputs = {{L"alignment", L"Alignment SAM", L"alignment.sam", true, true}};
    Step sa;
    sa.id = L"alignment";
    sa.label = L"Align reads";
    sa.tool = L"minimap2";
    sa.stdout_id = L"alignment";
    sa.args = {
        L"-a",           L"-x", L"{input:preset}", L"-t", L"{input:threads}", L"{input:reference}",
        L"{input:reads}"};
    align.steps = {sa};
    p.workflows.push_back(align);
    Workflow combined = align;
    combined.id = L"statistics-and-alignment";
    combined.name = L"Statistics and alignment";
    combined.outputs.insert(combined.outputs.begin(), stats.outputs[0]);
    combined.steps.insert(combined.steps.begin(), ss);
    p.workflows.push_back(combined);
}
} // namespace

bool text_constraint_matches(const std::wstring& constraint, const std::wstring& value) {
    if (constraint.empty()) return true;
    if (constraint == L"identifier") return identifier_value(value);
    if (constraint == L"dna")
        return !value.empty() && value.size() <= 4096 &&
            value.find_first_not_of(L"ACGTRYSWKMBDHVNacgtryswkmbdhvn") == std::wstring::npos;
    return false;
}

Pack parse_pack_text(const std::wstring &text) {
    const auto sections = parse_sections(text);
    auto found = sections.find(L"pack");
    require(found != sections.end(), "Missing pack section.");
    const auto &meta = found->second;
    keys(meta, {L"format", L"id", L"version", L"name", L"platform", L"description", L"color"});
    const auto format = get(meta, L"format");
    require(format == L"1" || format == L"2", "Unsupported pack format.");
    require(get(meta, L"platform") == L"windows-x86_64", "Unsupported pack platform.");
    Pack p;
    p.format = format == L"1" ? 1 : 2;
    p.id = get(meta, L"id");
    p.version = get(meta, L"version");
    p.name = get(meta, L"name");
    p.description = optional(meta, L"description");
    require(identifier(p.id) && version(p.version), "Invalid pack ID or version.");
    require(clean(p.name, 100) && clean(p.description, 2048, true), "Invalid pack name or description.");
    if (meta.count(L"color")) {
        const auto value = get(meta, L"color");
        require(value.size() == 7 && value[0] == L'#', "Color must be #RRGGBB.");
        p.color = 0;
        for (size_t i = 1; i < value.size(); ++i) {
            auto c = fold(value.substr(i, 1))[0];
            require(digit(c) || (c >= L'a' && c <= L'f'), "Invalid pack color.");
            p.color = (p.color << 4) | unsigned(digit(c) ? c - L'0' : c - L'a' + 10);
        }
    }
    if (p.format == 1) {
        require(sections.size() == 4,
                "Legacy pack requires only pack, bwfastq, seqtk and minimap2 sections.");
        for (const auto *id : {L"bwfastq", L"seqtk", L"minimap2"}) {
            auto it = sections.find(id);
            require(it != sections.end(), "Missing legacy tool section.");
            p.tools.push_back(parse_tool(id, it->second, true));
        }
        p.fastq = p.tools[0];
        p.seqtk = p.tools[1];
        p.minimap = p.tools[2];
        legacy_workflows(p);
        return p;
    }
    std::set<std::wstring> used{L"pack"}, tool_ids, asset_ids, pack_paths;
    for (const auto &section : sections)
        if (section.first.rfind(L"tool:", 0) == 0) {
            auto id = section.first.substr(5);
            p.tools.push_back(parse_tool(id, section.second, false));
            declare_pack_file(p.tools.back().path, pack_paths);
            tool_ids.insert(id);
            used.insert(section.first);
        }
    require(!p.tools.empty() && p.tools.size() <= 64, "A pack must declare 1 to 64 tools.");
    for (const auto &section : sections)
        if (section.first.rfind(L"asset:", 0) == 0) {
            const auto id = section.first.substr(6);
            p.assets.push_back(parse_asset(id, section.second));
            declare_pack_file(p.assets.back().path, pack_paths);
            asset_ids.insert(id);
            used.insert(section.first);
        }
    require(p.assets.size() <= 8192, "A pack may declare at most 8192 assets.");
    for (const auto &section : sections)
        if (section.first.rfind(L"workflow:", 0) == 0) {
            Workflow w;
            w.id = section.first.substr(9);
            require(identifier(w.id), "Invalid workflow ID.");
            used.insert(section.first);
            const auto &f = section.second;
            keys(f, {L"name", L"description", L"inputs", L"outputs", L"steps"});
            w.name = get(f, L"name");
            w.description = optional(f, L"description");
            require(clean(w.name, 100) && clean(w.description, 2048, true),
                    "Invalid workflow name or description.");
            auto child = [&](const wchar_t *kind, const std::wstring &id) -> const Fields & {
                auto name = std::wstring(kind) + L":" + w.id + L":" + id;
                auto it = sections.find(name);
                require(it != sections.end(), "Missing workflow child section.");
                require(used.insert(name).second, "Repeated workflow child section.");
                return it->second;
            };
            for (const auto &id : ids(get(f, L"inputs"), 32, true)) {
                const auto &a = child(L"input", id);
                keys(a, {L"label", L"type", L"help", L"filter", L"default", L"required", L"min", L"max",
                         L"choices", L"constraint", L"different-from"});
                Input in;
                in.id = id;
                in.label = get(a, L"label");
                in.type = optional(a, L"type", L"file");
                in.help = optional(a, L"help");
                in.filter = optional(a, L"filter", L"All files|*.*");
                in.default_value = optional(a, L"default");
                in.required = boolean(optional(a, L"required", L"true"));
                require(clean(in.label, 100) && clean(in.help, 2048, true) &&
                            clean(in.default_value, 4096, true),
                        "Invalid input label, help or default.");
                require(in.type == L"file" || in.type == L"files" || in.type == L"directory" ||
                            in.type == L"integer" || in.type == L"choice" || in.type == L"text" ||
                            in.type == L"boolean",
                        "Unknown input type.");
                if (a.count(L"filter"))
                    require(in.type == L"file" || in.type == L"files",
                            "Only file inputs support filters.");
                auto filters = split(in.filter, L'|');
                require(filters.size() % 2 == 0 && filters.size() <= 32,
                        "File filters must have Label|pattern pairs.");
                if (in.type == L"integer") {
                    in.minimum = integer(optional(a, L"min", L"0"));
                    in.maximum = integer(optional(a, L"max", L"2147483647"));
                    require(in.minimum <= in.maximum, "Integer minimum exceeds maximum.");
                    if (!in.default_value.empty()) {
                        auto n = integer(in.default_value);
                        require(n >= in.minimum && n <= in.maximum,
                                "Integer default is outside bounds.");
                    }
                } else
                    require(!a.count(L"min") && !a.count(L"max"),
                            "Only integer inputs support min and max.");
                if (in.type == L"choice") {
                    std::set<std::wstring> seen;
                    for (const auto &item : split(get(a, L"choices"), L'|')) {
                        auto colon = item.find(L':');
                        require(colon != item.npos, "Choices use value:Label.");
                        Choice c{item.substr(0, colon), item.substr(colon + 1)};
                        require(clean(c.value, 128) && clean(c.label, 100) &&
                                    c.value.find_first_of(L"{}") == c.value.npos &&
                                    seen.insert(c.value).second,
                                "Invalid or duplicate choice.");
                        in.choices.push_back(c);
                    }
                    require(in.choices.size() <= 64, "Too many choices.");
                    if (!in.default_value.empty())
                        require(seen.count(in.default_value), "Choice default is not a declared value.");
                } else
                    require(!a.count(L"choices"), "Only choice inputs support choices.");
                if (in.type == L"boolean") {
                    if (in.default_value.empty())
                        in.default_value = L"false";
                    (void)boolean(in.default_value);
                }
                in.constraint = optional(a, L"constraint");
                in.different_from = optional(a, L"different-from");
                if (a.count(L"constraint")) {
                    require(in.type == L"text" && (in.constraint == L"identifier" || in.constraint == L"dna"),
                            "Only text inputs support constraint=identifier or constraint=dna.");
                    if (!in.default_value.empty() || (in.constraint == L"dna" && a.count(L"default")))
                        require(text_constraint_matches(in.constraint, in.default_value),
                            in.constraint == L"dna" ? "DNA default must use 1 to 4096 IUPAC DNA letters." :
                                "Identifier default must use 1 to 64 ASCII letters, digits, underscore, dot or hyphen.");
                }
                if (a.count(L"different-from"))
                    require(in.type == L"file" && identifier(in.different_from),
                            "Only file inputs support different-from=input-id.");
                w.inputs.push_back(in);
            }
            for (const auto &id : ids(get(f, L"outputs"), 64, true)) {
                const auto &a = child(L"output", id);
                keys(a, {L"label", L"path", L"final", L"nonempty"});
                Output out;
                out.id = id;
                out.label = get(a, L"label");
                require(clean(out.label, 100), "Invalid output label.");
                out.path = relative_path(get(a, L"path"));
                out.final = boolean(optional(a, L"final", L"true"));
                out.nonempty = boolean(optional(a, L"nonempty", L"true"));
                w.outputs.push_back(out);
            }
            for (const auto &id : ids(get(f, L"steps"), 64)) {
                const auto &a = child(L"step", id);
                keys(a,
                     {L"label", L"kind", L"tool", L"sink-tool", L"stdout", L"source", L"destination",
                      L"produces"},
                     true);
                Step step;
                step.id = id;
                step.label = get(a, L"label");
                require(clean(step.label, 100), "Invalid step label.");
                step.kind = optional(a, L"kind", L"exec");
                require(step.kind == L"exec" || step.kind == L"copy" || step.kind == L"pipe",
                        "Unknown step kind.");
                auto read_args = [&](const std::wstring &prefix) {
                    std::map<size_t, std::wstring> arguments;
                    for (const auto &field : a)
                        if (field.first.rfind(prefix, 0) == 0) {
                            auto number = field.first.substr(prefix.size());
                            require(
                                !number.empty() && number.size() <= 3 &&
                                    (number.size() == 1 || number[0] != L'0') &&
                                    std::all_of(number.begin(), number.end(), digit),
                                "Argument keys use consecutive arg.0/sink-arg.0, arg.1/sink-arg.1, ...");
                            const size_t n = std::stoul(number);
                            require(n < 128 && clean(field.second, 4096, true),
                                    "Too many or overlong arguments.");
                            arguments.emplace(n, field.second);
                        }
                    std::vector<std::wstring> result;
                    for (size_t n = 0; n < arguments.size(); ++n) {
                        const auto it = arguments.find(n);
                        require(it != arguments.end(), "Argument numbering contains a gap.");
                        result.push_back(it->second);
                    }
                    return result;
                };
                step.args = read_args(L"arg.");
                step.sink_args = read_args(L"sink-arg.");
                if (step.kind == L"pipe")
                    step.sink_tool = get(a, L"sink-tool");
                else
                    require(!a.count(L"sink-tool") && step.sink_args.empty(),
                            "Only pipe steps support sink arguments and tool.");
                if (step.kind == L"exec" || step.kind == L"pipe") {
                    require(!a.count(L"source") && !a.count(L"destination"),
                            "Exec steps do not support source or destination.");
                    step.tool = get(a, L"tool");
                    step.stdout_id = optional(a, L"stdout");
                    step.produces = ids(optional(a, L"produces"), 64, true);
                } else {
                    require(!a.count(L"tool") && !a.count(L"stdout") && !a.count(L"produces") &&
                                step.args.empty(),
                            "Copy steps only support source and destination.");
                    step.source = get(a, L"source");
                    step.destination = get(a, L"destination");
                }
                w.steps.push_back(step);
            }
            validate_workflow(w, tool_ids, asset_ids);
            p.workflows.push_back(std::move(w));
        }
    require(!p.workflows.empty() && p.workflows.size() <= 64, "A pack must declare 1 to 64 workflows.");
    require(used.size() == sections.size(), "Unknown or unreferenced manifest section.");
    return p;
}

std::vector<std::wstring> expand_arguments(const std::vector<std::wstring> &args,
                                           const std::map<std::wstring, std::wstring> &inputs,
                                           const std::map<std::wstring, std::wstring> &outputs,
                                           const std::wstring &run,
                                           const std::map<std::wstring, std::wstring> &assets) {
    std::vector<std::wstring> result;
    size_t characters = 0;
    auto append = [&](std::wstring value) {
        require(value.find(L'\0') == value.npos && value.size() <= 32760,
                "Expanded argument contains NUL or exceeds the command-line limit.");
        characters += value.size() + 1;
        require(result.size() < 1024 && characters <= 32760,
                "Expanded command exceeds Windows command-line limits.");
        result.push_back(std::move(value));
    };
    for (const auto &arg : args) {
        auto refs = placeholders(arg);
        if (refs.size() == 1 && refs[0].kind == L"inputs") {
            auto it = inputs.find(refs[0].id);
            require(it != inputs.end(), "Missing file-list value.");
            if (it->second.empty())
                continue;
            size_t start = 0;
            for (;;) {
                auto end = it->second.find(L'\n', start);
                auto value =
                    it->second.substr(start, end == it->second.npos ? it->second.npos : end - start);
                if (!value.empty() && value.back() == L'\r')
                    value.pop_back();
                require(!value.empty() && value.find(L'\r') == value.npos,
                        "File list contains an empty or malformed filename.");
                append(value);
                if (end == it->second.npos)
                    break;
                start = end + 1;
                if (start == it->second.size())
                    break;
            }
        } else {
            std::wstring expanded;
            size_t start = 0;
            for (const auto &ref : refs) {
                auto open = arg.find(L'{', start);
                auto close = arg.find(L'}', open);
                expanded += arg.substr(start, open - start);
                if (ref.kind == L"run")
                    expanded += run;
                else {
                    const auto &values = ref.kind == L"input"   ? inputs
                                         : ref.kind == L"asset" ? assets
                                                                : outputs;
                    auto it = values.find(ref.id);
                    require(it != values.end(), "Missing placeholder value.");
                    expanded += it->second;
                }
                start = close + 1;
            }
            expanded += arg.substr(start);
            append(std::move(expanded));
        }
    }
    return result;
}
} // namespace bw
