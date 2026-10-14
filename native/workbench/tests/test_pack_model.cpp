#include "../desktop/pack_model.h"
#include <codecvt>
#include <fstream>
#include <iostream>
#include <locale>
#include <stdexcept>
#include <string>
using namespace bw;
namespace {
int checks = 0;
void check(bool ok, const char *what) {
    if (!ok)
        throw std::runtime_error(what);
    ++checks;
}
std::wstring replace(std::wstring text, const std::wstring &from, const std::wstring &to) {
    auto at = text.find(from);
    if (at == text.npos)
        throw std::runtime_error("Bad test mutation");
    text.replace(at, from.size(), to);
    return text;
}
void reject(const std::wstring &text) {
    bool rejected = false;
    try {
        (void)parse_pack_text(text);
    } catch (const std::exception &) {
        rejected = true;
    }
    check(rejected, "Malformed manifest was accepted");
}
const std::wstring manifest = LR"([pack]
format=2
id=variant-calling
version=0.3.0
name=Variant calling
platform=windows-x86_64
description=A two-stage pipeline
color=#28AcE4
[tool:align]
path=bin/align.exe
version=1.0
sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
[workflow:paired]
name=Paired reads
inputs=reads,reference,threads,mode,flag
outputs=reference,sam,bam
steps=copy,align,sort
[input:paired:reads]
label=Read pairs
type=files
filter=FASTQ files|*.fq;*.fastq|All files|*.*
[input:paired:reference]
label=Reference
type=file
[input:paired:threads]
label=Threads
type=integer
min=1
max=64
default=2
[input:paired:mode]
label=Mode
type=choice
choices=sr:Short reads|map-ont:Oxford Nanopore
default=sr
[input:paired:flag]
label=Flag
type=boolean
default=false
[output:paired:reference]
label=Reference copy
path=reference/ref.fa
final=false
[output:paired:sam]
label=SAM
path=alignment.sam
final=false
[output:paired:bam]
label=Sorted BAM
path=sorted.bam
[step:paired:copy]
label=Copy reference
kind=copy
source={input:reference}
destination=reference
[step:paired:align]
label=Align
kind=exec
tool=align
stdout=sam
arg.0=-t
arg.1={input:threads}
arg.2={output:reference}
arg.3={inputs:reads}
[step:paired:sort]
label=Sort
kind=exec
tool=align
produces=bam
arg.0=sort
arg.1=-o
arg.2={output:bam}
arg.3={output:sam}
)";
} // namespace
int main(int argc, char **argv) {
    try {
        const Pack pack = parse_pack_text(manifest);
        check(pack.format == 2 && pack.id == L"variant-calling" && pack.color == 0x28ace4,
              "Pack metadata");
        check(pack.tools.size() == 1 && pack.workflows.size() == 1, "Dynamic tools/workflows");
        const auto &w = pack.workflows[0];
        check(w.inputs.size() == 5 && w.steps.size() == 3 && w.outputs.size() == 3, "Workflow model");
        check(w.inputs[2].minimum == 1 && w.inputs[2].maximum == 64 && w.inputs[2].default_value == L"2",
              "Integer bounds");
        check(w.inputs[3].choices[1].value == L"map-ont", "Choice values");
        auto unicode = replace(manifest, L"name=Variant calling", L"name=分析 — naïve");
        check(parse_pack_text(unicode).name == L"分析 — naïve", "Unicode label");
        auto crlf = manifest;
        for (size_t at = 0; (at = crlf.find(L'\n', at)) != crlf.npos; at += 2)
            crlf.replace(at, 1, L"\r\n");
        check(parse_pack_text(L"\ufeff" + crlf).format == 2, "BOM and CRLF");
        check(parse_pack_text(replace(manifest, L"bin/align.exe", L"bin\\align.exe")).tools[0].path ==
                  L"bin/align.exe",
              "Path normalization");
        const std::pair<std::wstring, std::wstring> negatives[] = {
            {L"format=2", L"format=3"},
            {L"platform=windows-x86_64", L"platform=linux"},
            {L"id=variant-calling", L"id=variant-calling\nid=second"},
            {L"id=variant-calling", L"id=variant-calling\nunknown=value"},
            {L"id=variant-calling", L"id=Variant"},
            {L"version=0.3.0", L"version=0.03.0"},
            {L"color=#28AcE4", L"color=#12345g"},
            {L"[tool:align]", L"[tool:align]\n[tool:align]"},
            {L"bin/align.exe", L"../align.exe"},
            {L"bin/align.exe", L"C:/align.exe"},
            {L"bin/align.exe", L"bin/other.cmd"},
            {L"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", L"aaa"},
            {L"inputs=reads,reference,threads,mode,flag", L"inputs=reads,reads"},
            {L"steps=copy,align,sort", L"steps=align,copy,sort"},
            {L"steps=copy,align,sort", L"steps=copy,align"},
            {L"outputs=reference,sam,bam", L"outputs=reference,sam,bam,missing"},
            {L"type=files", L"type=unknown"},
            {L"min=1", L"min=65"},
            {L"default=2", L"default=0"},
            {L"max=64", L"max=9223372036854775808"},
            {L"min=1", L"min=1x"},
            {L"default=sr", L"default=bad"},
            {L"choices=sr:Short reads|map-ont:Oxford Nanopore", L"choices=sr:Short reads|sr:Duplicate"},
            {L"default=false", L"default=0"},
            {L"type=files", L"type=files\nmin=1"},
            {L"filter=FASTQ files|*.fq;*.fastq|All files|*.*", L"filter=Missing pair"},
            {L"path=sorted.bam", L"path=../sorted.bam"},
            {L"path=sorted.bam", L"path=/sorted.bam"},
            {L"path=sorted.bam", L"path=folder//sorted.bam"},
            {L"path=sorted.bam", L"path=folder/../sorted.bam"},
            {L"path=sorted.bam", L"path=CON.txt"},
            {L"path=sorted.bam", L"path=COM¹.txt"},
            {L"path=sorted.bam", L"path=stream:ads"},
            {L"path=sorted.bam", L"path=trailing./file"},
            {L"path=sorted.bam", L"path=Alignment.SAM"},
            {L"path=sorted.bam", L"path=alignment.sam/nested"},
            {L"path=sorted.bam", L"path=run.json"},
            {L"path=sorted.bam", L"path=LOGS/x"},
            {L"path=sorted.bam", L"path=workbench.log"},
            {L"kind=copy", L"kind=shell"},
            {L"tool=align", L"tool=absent"},
            {L"stdout=sam", L"stdout=sam\nproduces=sam"},
            {L"produces=bam", L"produces=sam"},
            {L"arg.0=-t", L"arg.8=-t"},
            {L"arg.0=-t", L"arg.00=-t"},
            {L"arg.0=-t", L"arg.-1=-t"},
            {L"arg.0=-t", L"arg.128=-t"},
            {L"arg.0=-t", L"arg.0=-t\narg.0=-a"},
            {L"{input:threads}", L"{input:missing}"},
            {L"{output:reference}", L"{output:bam}"},
            {L"{inputs:reads}", L"{input:reads}"},
            {L"{input:threads}", L"{inputs:threads}"},
            {L"{inputs:reads}", L"prefix{inputs:reads}"},
            {L"{input:threads}", L"{input:threads"},
            {L"{input:threads}", L"{bad:threads}"},
            {L"{input:threads}", L"literal}"},
            {L"source={input:reference}", L"source={input:reference}.fa"},
            {L"source={input:reference}", L"source={output:reference}"},
            {L"source={input:reference}", L"source={input:threads}"},
            {L"kind=copy", L"kind=copy\narg.0=anything"},
        };
        for (const auto &n : negatives)
            reject(replace(manifest, n.first, n.second));
        reject(manifest + L"\n[unknown]\nkey=value\n");
        reject(manifest + L"\n[input:paired:unused]\nlabel=Unused\n");
        reject(replace(manifest, L"path=sorted.bam", L"path=run.json.pending"));
        reject(replace(manifest, L"path=sorted.bam", L"path=workbench.log/file"));
        reject(replace(manifest, L"path=sorted.bam", L"path=分析.bam"));
        auto asset_section = [](const std::wstring &id, const std::wstring &path) {
            return L"\n[asset:" + id + L"]\npath=" + path + L"\nsha256=" + std::wstring(64, L'b') +
                   L"\n";
        };
        const auto with_assets = manifest + asset_section(L"adapters", L"data/adapters.fa") +
                                 asset_section(L"python-dll", L"runtime/python/python313.dll");
        const auto parsed_assets = parse_pack_text(with_assets);
        check(parsed_assets.assets.size() == 2 && parsed_assets.assets[0].id == L"adapters",
              "Hashed assets loaded");
        check(parse_pack_text(replace(with_assets, L"bin/align.exe", L"runtime/python/python.exe"))
                      .tools[0]
                      .path == L"runtime/python/python.exe",
              "Nested runtime executable");
        check(parse_pack_text(replace(with_assets, L"{input:threads}", L"--adapters={asset:adapters}"))
                      .workflows[0]
                      .steps[1]
                      .args[1] == L"--adapters={asset:adapters}",
              "Asset argument");
        check(parse_pack_text(
                  replace(with_assets, L"source={input:reference}", L"source={asset:adapters}"))
                      .workflows[0]
                      .steps[0]
                      .source == L"{asset:adapters}",
              "Asset copy source");
        reject(replace(with_assets, L"{input:threads}", L"{asset:missing}"));
        reject(replace(with_assets, L"source={input:reference}", L"source={asset:missing}"));
        reject(replace(with_assets, L"source={input:reference}", L"source={asset:adapters}.extra"));
        reject(replace(with_assets, L"[asset:adapters]", L"[asset:Invalid]"));
        reject(replace(with_assets, L"[asset:adapters]", L"[asset:adapters]\nversion=1"));
        reject(replace(with_assets, std::wstring(64, L'b'), L"not-a-hash"));
        for (const auto *path :
             {L"../adapters.fa", L"C:/adapters.fa", L"//host/share/a", L"data//a", L"data/CON.fa",
              L"data/a:stream", L"licenses/a", L"PACK.ini/a", L"PACK-README.md", L"Readme.txt",
              L"data/分析.fa", L"BIN/ALIGN.EXE", L"bin/align.exe/data", L"bin"})
            reject(replace(with_assets, L"data/adapters.fa", path));
        reject(with_assets + asset_section(L"third", L"DATA/ADAPTERS.FA"));
        reject(with_assets + asset_section(L"third", L"data/adapters.fa/child"));
        reject(with_assets + asset_section(L"third", L"data"));
        reject(with_assets + asset_section(L"adapters", L"data/second.fa"));
        reject(replace(with_assets, L"bin/align.exe", L"licenses/align.exe"));
        reject(replace(with_assets, L"bin/align.exe", L"runtime/../align.exe"));
        auto runtime_asset_args =
            expand_arguments({L"--adapters={asset:adapters}", L"{asset:python-dll}"}, {}, {}, L"C:\\run",
                             {{L"adapters", L"C:\\pack α\\data\\adapters.fa"},
                              {L"python-dll", L"C:\\pack α\\runtime\\python\\python313.dll"}});
        check(runtime_asset_args.size() == 2 &&
                  runtime_asset_args[0] == L"--adapters=C:\\pack α\\data\\adapters.fa",
              "Asset expansion preserves Unicode path and argument boundaries");
        bool missing_asset = false;
        try {
            (void)expand_arguments({L"{asset:missing}"}, {}, {}, L"run");
        } catch (const std::exception &) {
            missing_asset = true;
        }
        check(missing_asset, "Unknown expansion asset rejected");
        auto large_runtime = manifest;
        for (int i = 0; i < 1100; ++i)
            large_runtime += asset_section(L"module-" + std::to_wstring(i),
                                           L"runtime/python/lib/module" + std::to_wstring(i) + L".py");
        check(parse_pack_text(large_runtime).assets.size() == 1100, "Large private runtime manifest");
        const auto piped =
            replace(manifest, L"kind=exec\ntool=align\nstdout=sam",
                    L"kind=pipe\ntool=align\nsink-tool=align\nstdout=sam\nsink-arg.0=-u\nsink-arg.1=-");
        const auto parsed_pipe = parse_pack_text(piped);
        check(parsed_pipe.workflows[0].steps[1].kind == L"pipe" &&
                  parsed_pipe.workflows[0].steps[1].sink_tool == L"align" &&
                  parsed_pipe.workflows[0].steps[1].sink_args == std::vector<std::wstring>{L"-u", L"-"},
              "Two-process pipe keeps producer and sink arguments separate");
        for (const auto &mutation : std::vector<std::pair<std::wstring, std::wstring>>{
                 {L"sink-tool=align", L"sink-tool=missing"},
                 {L"sink-tool=align", L""},
                 {L"kind=pipe", L"kind=exec"},
                 {L"sink-arg.0=-u", L"sink-arg.3=-u"},
                 {L"sink-arg.0=-u", L"sink-arg.00=-u"},
                 {L"sink-arg.0=-u", L"sink-arg.128=-u"},
                 {L"sink-arg.0=-u", L"sink-arg.0={input:missing}"},
                 {L"sink-arg.0=-u", L"sink-arg.0={asset:missing}"},
                 {L"sink-arg.0=-u", L"sink-arg.0={output:bam}"},
                 {L"sink-arg.0=-u", L"sink-arg.0=prefix{inputs:reads}"},
                 {L"sink-arg.0=-u", L"sink-arg.0=-u\nsink-arg.0=-a"}})
            reject(replace(piped, mutation.first, mutation.second));
        reject(replace(manifest, L"kind=copy", L"kind=copy\nsink-tool=align"));
        reject(replace(manifest, L"kind=copy", L"kind=copy\nsink-arg.0=-u"));
        auto many_args = piped;
        std::wstring extras;
        for (int i = 4; i < 128; ++i)
            extras += L"arg." + std::to_wstring(i) + L"=literal\n";
        for (int i = 2; i < 128; ++i)
            extras += L"sink-arg." + std::to_wstring(i) + L"=literal\n";
        many_args = replace(many_args, L"[step:paired:sort]", extras + L"[step:paired:sort]");
        check(parse_pack_text(many_args).workflows[0].steps[1].args.size() == 128 &&
                  parse_pack_text(many_args).workflows[0].steps[1].sink_args.size() == 128,
              "Per-child argument limits support two full argument vectors");
        auto constrained = replace(manifest, L"type=boolean\ndefault=false",
                                   L"type=text\nconstraint=identifier\ndefault=Sample_1-A.2");
        check(parse_pack_text(constrained).workflows[0].inputs[4].constraint == L"identifier",
              "Identifier constraint");
        reject(replace(constrained, L"Sample_1-A.2", L"bad\\tSM:sample"));
        reject(replace(constrained, L"Sample_1-A.2", std::wstring(65, L'a')));
        reject(replace(constrained, L"constraint=identifier", L"constraint=anything"));
        reject(replace(constrained, L"type=text", L"type=file"));
        const auto dna = replace(replace(constrained, L"constraint=identifier", L"constraint=dna"),
            L"default=Sample_1-A.2", L"default=AcgTrySwkMbDhVn");
        check(parse_pack_text(dna).workflows[0].inputs[4].constraint == L"dna", "IUPAC DNA default");
        check(text_constraint_matches(L"dna", L"AcgTrySwkMbDhVn"), "Runtime mixed-case IUPAC DNA");
        check(text_constraint_matches(L"dna", std::wstring(4096, L'N')), "DNA upper length boundary");
        for (const auto& invalid : std::vector<std::wstring>{L"", L"file:adapters.fa", L"C:\\adapters.fa",
            L"/data/adapters.fa", L"--option", L"ACGT;max_error_rate=0.2", L"ACGT N", L"ACGU", L"A{3}", L"ACGT$", std::wstring(4097, L'A')}) {
            check(!text_constraint_matches(L"dna", invalid), "Invalid runtime DNA rejected");
            reject(replace(dna, L"default=AcgTrySwkMbDhVn", L"default=" + invalid));
        }
        reject(replace(dna, L"type=text", L"type=file"));
        check(parse_pack_text(replace(dna, L"default=AcgTrySwkMbDhVn", L"; no default"))
            .workflows[0].inputs[4].default_value.empty(), "DNA may require the user to supply its value");
        auto different = replace(manifest, L"type=files\nfilter=FASTQ",
                                 L"type=file\ndifferent-from=reference\nfilter=FASTQ");
        different = replace(different, L"{inputs:reads}", L"{input:reads}");
        check(parse_pack_text(different).workflows[0].inputs[0].different_from == L"reference",
              "Distinct file constraint");
        reject(replace(different, L"different-from=reference", L"different-from=reads"));
        reject(replace(different, L"different-from=reference", L"different-from=missing"));
        reject(replace(different, L"different-from=reference", L"different-from=threads"));
        reject(replace(different, L"type=file\ndifferent-from", L"type=files\ndifferent-from"));
        auto nul = manifest;
        nul.push_back(0);
        reject(nul);
        reject(replace(manifest, L"name=Variant calling", L"name=" + std::wstring(101, L'x')));
        auto args = expand_arguments(
            {L"--prefix={input:name}", L"{inputs:reads}", L"{output:bam}", L"{run}", L""},
            {{L"name", L"α {run} & \"quoted\""},
             {L"reads", L"C:\\reads one.fq\nC:\\reads & two.fq\r\n"}},
            {{L"bam", L"C:\\output folder\\sorted.bam"}}, L"C:\\run folder");
        check(args.size() == 6, "File list expands argv count");
        check(args[0] == L"--prefix=α {run} & \"quoted\"",
              "Scalar substitution is single pass and literal");
        check(args[1] == L"C:\\reads one.fq" && args[2] == L"C:\\reads & two.fq",
              "Filename boundaries and metacharacters");
        check(args[3] == L"C:\\output folder\\sorted.bam" && args[4] == L"C:\\run folder" &&
                  args[5].empty(),
              "Output/run/empty argument");
        check(expand_arguments({L"{inputs:reads}"}, {{L"reads", L""}}, {}, L"x").empty(),
              "Optional empty file list");
        auto expansion_reject = [&](const std::vector<std::wstring> &a,
                                    const std::map<std::wstring, std::wstring> &i) {
            bool caught = false;
            try {
                expand_arguments(a, i, {}, L"run");
            } catch (const std::exception &) {
                caught = true;
            }
            check(caught, "Unsafe expansion accepted");
        };
        expansion_reject({L"{input:missing}"}, {});
        expansion_reject({L"{inputs:reads}"}, {{L"reads", L"a\n\nb"}});
        expansion_reject({L"{input:value}"}, {{L"value", std::wstring(L"a\0b", 3)}});
        expansion_reject({L"{input:value}"}, {{L"value", std::wstring(32761, L'x')}});
        std::wstring legacy = LR"([pack]
format=1
id=core-bio
version=0.2.0
name=Essentials
platform=windows-x86_64
)";
        for (const auto *id : {L"bwfastq", L"seqtk", L"minimap2"})
            legacy += L"[" + std::wstring(id) + L"]\npath=bin\\" + id + L".exe\nversion=1.0\nsha256=" +
                      std::wstring(64, L'a') + L"\n";
        const auto old = parse_pack_text(legacy);
        check(old.tools.size() == 3 && old.workflows.size() == 4 && old.assets.empty(),
              "Legacy conversion");
        reject(replace(legacy, L"bin\\seqtk.exe", L"runtime/seqtk.exe"));
        reject(legacy + asset_section(L"unexpected", L"data/file"));
        check(old.fastq.id == L"bwfastq" && old.minimap.path == L"bin/minimap2.exe",
              "Legacy fixed tool aliases");
        check(old.workflows[3].steps.size() == 2 && old.workflows[3].inputs.size() == 4,
              "Legacy combined workflow preserves behavior");
        for (int i = 1; i < argc; ++i) {
            std::ifstream file(argv[i], std::ios::binary);
            check(bool(file), "Cannot open requested manifest");
            std::string bytes((std::istreambuf_iterator<char>(file)), {});
            auto parsed =
                parse_pack_text(std::wstring_convert<std::codecvt_utf8<wchar_t>>{}.from_bytes(bytes));
            check(!parsed.workflows.empty(), "Requested manifest has no workflows");
            std::cout << argv[i] << ": " << parsed.tools.size() << " tools, " << parsed.workflows.size()
                      << " workflows\n";
        }
        std::cout << "PASS: " << checks << " pack-model checks\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "FAIL: " << e.what() << " (after " << checks << " checks)\n";
        return 1;
    }
}
