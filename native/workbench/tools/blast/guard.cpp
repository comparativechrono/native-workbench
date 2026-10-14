// Workbench BLAST boundary: strict FASTA validation and local, shell-free launch.
// No BLAST scoring, alignment, masking or statistics are implemented here.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif
namespace fs = std::filesystem;
using S = std::string;
static void require(bool ok, const S& why) { if (!ok) throw std::runtime_error(why); }
static void validate(const S& path, const S& kind, const S& report) {
    require(kind=="nucl" || kind=="prot", "Unknown FASTA alphabet");
    std::ifstream in(fs::u8path(path), std::ios::binary);
    require(bool(in), "Cannot open FASTA input");
    S line, id;
    std::set<S> ids;
    uint64_t residues=0, length=0, rows=0;
    const S alphabet = kind=="nucl" ? "ACGTRYSWKMBDHVN" : "ABCDEFGHIKLMNPQRSTVWXYZJUO*";
    while (std::getline(in,line)) {
        ++rows;
        if (!line.empty() && line.back()=='\r') line.pop_back();
        if (line.empty()) continue;
        if (line[0]=='>') {
            require(id.empty() || length>0, "Empty FASTA record before line "+std::to_string(rows));
            const auto space=line.find_first_of(" \t",1);
            id=line.substr(1,space==S::npos ? S::npos : space-1);
            require(!id.empty() && id.size()<=200, "FASTA identifiers must contain 1 to 200 characters");
            for (unsigned char c:id) require(std::isalnum(c) && c<128 || c=='_' || c=='.' || c==':' || c=='-', "FASTA IDs may use ASCII letters, digits, underscore, dot, colon or hyphen; pipes are not accepted");
            for (unsigned char c:line) require(c=='\t' || (c>=32 && c<=126), "FASTA headers must be printable ASCII text");
            require(ids.insert(id).second,"Duplicate FASTA identifier: "+id);
            length=0;
        } else {
            require(!id.empty(), "Sequence text precedes its FASTA header");
            for (unsigned char c:line) {
                require(c<128 && alphabet.find(static_cast<char>(std::toupper(c)))!=S::npos,
                        "Invalid "+kind+" residue or whitespace at FASTA line "+std::to_string(rows));
                ++length; ++residues;
                require(length<=2147483647ULL,"BLAST sequence exceeds the upstream 2,147,483,647 residue limit");
            }
        }
    }
    require(in.eof(),"Cannot read complete FASTA input");
    require(!ids.empty() && length>0,"FASTA has no records or ends with an empty record");
    std::ofstream out(fs::u8path(report),std::ios::binary);
    require(bool(out),"Cannot write FASTA validation report");
    out << "{\n  \"schema\": 1,\n  \"alphabet\": \""<<kind<<"\",\n  \"records\": "<<ids.size()<<",\n  \"residues\": "<<residues<<"\n}\n";
    require(bool(out),"Cannot finish FASTA validation report");
}
#ifdef _WIN32
static std::wstring wide(const S& s) {
    int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),static_cast<int>(s.size()),nullptr,0);
    require(n>0 || s.empty(),"Invalid UTF-8 argument");
    std::wstring w(n,0); if(n) MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s.data(),static_cast<int>(s.size()),w.data(),n); return w;
}
static S utf8(const std::wstring& w) {
    int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,w.data(),static_cast<int>(w.size()),nullptr,0,nullptr,nullptr);
    require(n>0 || w.empty(),"Invalid Unicode argument");
    S s(n,0); if(n) WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,w.data(),static_cast<int>(w.size()),s.data(),n,nullptr,nullptr); return s;
}
static std::wstring quote(const std::wstring& s) {
    std::wstring r=L"\""; size_t slash=0;
    for(wchar_t c:s) { if(c==L'\\') ++slash; else { r.append(c==L'"'?slash*2+1:slash,L'\\');r+=c;slash=0;} }
    r.append(slash*2,L'\\');return r+L"\"";
}
#endif
static int run(std::vector<S> a) {
    if(a.size()==5 && a[1]=="validate") {validate(a[3],a[2],a[4]);return 0;}
    require(a.size()>=3 && a[1]=="run", "Usage: blast-guard validate nucl|prot input report; or run tool args...");
    const std::set<S> allowed={"makeblastdb","blastn","blastp","blastx","tblastn","blast_formatter"};
    require(allowed.count(a[2]),"Unexposed BLAST program");
    for(size_t i=3;i<a.size();++i) require(a[i]!="-remote" && a[i]!="-rid", "Remote BLAST is not permitted in this local pack");
    fs::path exe=fs::absolute(fs::u8path(a[0])).parent_path()/fs::u8path(a[2]);
    // BLAST's database paths are parsed as whitespace-separated lists. Explicit
    // embedded quoting is required by BLAST, independently of process quoting.
    for(size_t i=3;i+1<a.size();++i) if(a[i]=="-db" || (a[2]=="makeblastdb" && a[i]=="-in")) {
        require(a[i+1].find('"')==S::npos,"BLAST database/input list paths cannot contain a double quote");
        a[i+1]='"'+a[i+1]+'"'; ++i;
    }
#ifdef _WIN32
    exe+=L".exe";
    require(SetEnvironmentVariableW(L"BLAST_USAGE_REPORT",L"false") &&
            SetEnvironmentVariableW(L"NCBI_DONT_USE_NCBIRC",L"1") &&
            SetEnvironmentVariableW(L"NCBI_DONT_USE_LOCAL_CONFIG",L"1") &&
            SetEnvironmentVariableW(L"BLASTDB",L"."),"Cannot configure the local BLAST child environment");
    std::wstring command=quote(exe.wstring());
    for(size_t i=3;i<a.size();++i) command+=L" "+quote(wide(a[i]));
    STARTUPINFOW startup{}; startup.cb=sizeof(startup); PROCESS_INFORMATION child{};
    // A hidden Windows child has no console defaults. Forward the parent's
    // redirected handles explicitly so BLAST diagnostics reach the run log.
    startup.dwFlags=STARTF_USESTDHANDLES;
    startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    require(CreateProcessW(exe.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,nullptr,&startup,&child),"Cannot start bundled BLAST executable");
    CloseHandle(child.hThread); WaitForSingleObject(child.hProcess,INFINITE);
    DWORD status=1;GetExitCodeProcess(child.hProcess,&status);CloseHandle(child.hProcess);return static_cast<int>(status);
#else
    require(setenv("BLAST_USAGE_REPORT","false",1)==0 && setenv("NCBI_DONT_USE_NCBIRC","1",1)==0 && setenv("NCBI_DONT_USE_LOCAL_CONFIG","1",1)==0 && setenv("BLASTDB",".",1)==0,"Cannot configure the local BLAST child environment");
    S program=exe.string();std::vector<char*> args{program.data()};
    for(size_t i=3;i<a.size();++i) args.push_back(a[i].data());args.push_back(nullptr);
    execv(program.c_str(),args.data());throw std::runtime_error("Cannot start bundled BLAST executable");
#endif
}
#ifdef _WIN32
int wmain(int argc,wchar_t** argv) {
    try { std::vector<S> a;for(int i=0;i<argc;++i)a.push_back(utf8(argv[i]));return run(a); }
#else
int main(int argc,char** argv) {
    try { return run(std::vector<S>(argv,argv+argc)); }
#endif
    catch(const std::exception& e) {std::cerr<<"BLAST pack: "<<e.what()<<'\n';return 2;}
}
