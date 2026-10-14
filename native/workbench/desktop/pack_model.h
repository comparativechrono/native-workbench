#pragma once
#include <cstdint>
#include <map>
#include <string>
#include <vector>
namespace bw {
struct Tool { std::wstring id, path, version, sha256; };
struct Asset { std::wstring id, path, sha256; };
struct Choice { std::wstring value, label; };
struct Input {
    std::wstring id, label, type = L"file", help, filter = L"All files|*.*", default_value, constraint, different_from;
    bool required = true;
    long long minimum = 0, maximum = 2147483647;
    std::vector<Choice> choices;
};
struct Output {
    std::wstring id, label, path;
    bool final = true, nonempty = true;
};
struct Step {
    std::wstring id, label, kind = L"exec", tool, sink_tool, stdout_id, source, destination;
    std::vector<std::wstring> args, sink_args, produces;
};
struct Workflow {
    std::wstring id, name, description;
    std::vector<Input> inputs;
    std::vector<Output> outputs;
    std::vector<Step> steps;
};
struct Pack {
    std::wstring id, name, version, root, description, manifest_sha256;
    uint32_t color = 0x347E88;
    unsigned format = 1;
    std::vector<Tool> tools;
    std::vector<Asset> assets;
    std::vector<Workflow> workflows;
    // Legacy-format compatibility; the modular engine uses tools/workflows.
    Tool fastq, seqtk, minimap;
};
// Pure text constraints shared by manifest defaults and runtime input checks.
bool text_constraint_matches(const std::wstring& constraint, const std::wstring& value);
// Pure C++ schema parser: paths remain relative until filesystem loading.
Pack parse_pack_text(const std::wstring& text);
// Replace scalar {input:id}, {output:id}, {asset:id}, {run} placeholders. A whole
// {inputs:id} argument expands newline-separated files into separate argv items.
std::vector<std::wstring> expand_arguments(const std::vector<std::wstring>& args,
    const std::map<std::wstring, std::wstring>& inputs,
    const std::map<std::wstring, std::wstring>& outputs, const std::wstring& run,
    const std::map<std::wstring, std::wstring>& assets = {});
}
