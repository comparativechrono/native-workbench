// Native Workbench, MIT. Input validation and shell-free Prodigal invocation only.
// Scientific prediction is performed by the pinned upstream executable.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#else
#include <sys/wait.h>
#include <unistd.h>
#include <cerrno>
#endif
static void require(bool ok,const std::string &message) { if(!ok) throw std::runtime_error(message); }
static bool line(std::istream &in,std::string &value) {
    value.clear(); char c;
    while(in.get(c)) { if(c=='\n') return true; require(value.size()<8192,"FASTA lines must be at most 8192 characters; rewrap the sequence"); value+=c; }
    require(!in.bad(),"Cannot read FASTA input"); return !value.empty();
}
struct Input { uint64_t bases=0, contigs=0, ambiguous=0; };
static Input validate(const std::string &path,const std::string &mode) {
    std::ifstream in(path,std::ios::binary); require(bool(in),"Cannot open nucleotide FASTA; select a readable local file");
    std::string text,id; std::set<std::string> ids; Input result; uint64_t length=0,runs=0,total_runs=0; bool in_n=false;
    while(line(in,text)) {
        if(!text.empty()&&text.back()=='\r')text.pop_back();
        if(text.empty())continue;
        if(text[0]=='>') {
            require(id.empty()||length>0,"A FASTA record has no sequence; remove empty records");
            require(text.size()<=1024,"FASTA headers must be at most 1024 ASCII characters");
            for(unsigned char c:text)require(c>=32&&c<127&&c!='"',"FASTA headers must be printable ASCII without quote characters");
            id=text.substr(1,text.find_first_of(" \t",1)-1);
            require(!id.empty()&&id.size()<=200,"Use a nonempty FASTA identifier of at most 200 characters");
            for(unsigned char c:id) require(std::isalnum(c)||c=='_'||c=='.'||c=='-'||c==':',"FASTA identifiers may contain letters, digits, underscore, dot, hyphen or colon");
            require(ids.insert(id).second,"Duplicate FASTA first-word identifier; make every contig identifier unique");
            require(++result.contigs<=1000000,"This pack supports at most one million contigs per input");
            length=0;runs=0;in_n=false;
        } else {
            require(!id.empty(),"Expected uncompressed nucleotide FASTA beginning with >; gzip, reads and protein files are not accepted");
            for(unsigned char c:text) {
                c=static_cast<unsigned char>(std::toupper(c));
                require(c=='A'||c=='C'||c=='G'||c=='T'||c=='N',"Use unaligned DNA FASTA containing A/C/G/T/N only; resolve other ambiguity codes explicitly");
                if(c=='N') {++result.ambiguous;if(!in_n){++runs;++total_runs;}in_n=true;}else in_n=false;
                require(++length<=30000000,"A contig exceeds the supported 30 million bases; upstream has a fixed 32-million-base buffer");
                require(++result.bases<=1000000000ULL,"This pack supports at most one billion total input bases");
                require(runs<=4000&&(mode!="single"||total_runs<=4000),"Too many N-runs for the upstream fixed masking buffer; split the input or resolve ambiguous sequence");
            }
        }
    }
    require(result.contigs&&length,"Input contains no nonempty FASTA sequence");
    if(mode=="single") {
        require(result.bases>=20000,"Single-genome training requires at least 20,000 bases; use metagenome mode for short contigs or supply the complete assembly");
        require(result.bases+(result.contigs>1?result.contigs*12:0)<=30000000,"Single-genome training is limited to 30 million bases including contig separators in this pack; upstream otherwise truncates its training input");
        require(result.bases-result.ambiguous>=20000,"Single-genome training needs at least 20,000 non-N bases in this pack; supply more resolved assembly sequence");
    }
    return result;
}
static std::string json_string(const std::string &s) {
    std::string result="\"";for(unsigned char c:s) {if(c=='\\'||c=='"')result+='\\';require(c>=32,"Control character in process argument");result+=static_cast<char>(c);}return result+'"';
}
static bool parse_boolean(const std::string &s) {require(s=="true"||s=="false","Boolean parameter must be true or false");return s=="true";}
#ifdef _WIN32
static std::string quote(const std::string &s) {
    std::string result="\""; size_t slashes=0;
    for(char c:s) {if(c=='\\'){++slashes;continue;}if(c=='"')result.append(slashes*2+1,'\\');else result.append(slashes,'\\');slashes=0;result+=c;}
    result.append(slashes*2,'\\');return result+'"';
}
#endif
static int run(const std::vector<std::string> &args) {
#ifdef _WIN32
    std::string command;for(const auto &arg:args){if(!command.empty())command+=' ';command+=quote(arg);}
    std::vector<char> buffer(command.begin(),command.end());buffer.push_back(0);
    STARTUPINFOA si{};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES;si.hStdInput=GetStdHandle(STD_INPUT_HANDLE);si.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);si.hStdError=GetStdHandle(STD_ERROR_HANDLE);PROCESS_INFORMATION pi{};
    require(CreateProcessA(args[0].c_str(),buffer.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,nullptr,&si,&pi)!=0,"Cannot start bundled Prodigal; check installation integrity and executable approval");
    CloseHandle(pi.hThread);DWORD wait=WaitForSingleObject(pi.hProcess,INFINITE),code=1;
    bool okay=wait==WAIT_OBJECT_0&&GetExitCodeProcess(pi.hProcess,&code);CloseHandle(pi.hProcess);require(okay,"Cannot obtain Prodigal completion status");return static_cast<int>(code);
#else
    pid_t child=fork();require(child>=0,"Cannot start Prodigal process");
    if(child==0) {std::vector<char*> values;for(const auto &arg:args)values.push_back(const_cast<char*>(arg.c_str()));values.push_back(nullptr);execv(values[0],values.data());_exit(127);}
    int status=0;pid_t got;do{got=waitpid(child,&status,0);}while(got<0&&errno==EINTR);require(got==child,"Cannot obtain Prodigal completion status");return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
#endif
}
static uint64_t count_fasta(const std::string &path) {
    std::ifstream in(path,std::ios::binary);require(bool(in),"Prodigal did not write a declared sequence output");
    uint64_t n=0;std::string text;while(line(in,text))if(!text.empty()&&text[0]=='>')++n;return n;
}
int main(int argc,char **argv) {
#ifdef _WIN32
    _setmode(_fileno(stdout),_O_BINARY);
#endif
    try {
        require(argc==12,"Usage: prodigal-guard EXECUTABLE single|meta FASTA GFF PROTEINS CDS CODE auto|nonsd CLOSED MASK report-v1");
        std::string mode=argv[2],code=argv[7],model=argv[8];require(mode=="single"||mode=="meta","Unknown prediction mode");
        require(std::string(argv[11])=="report-v1","Unsupported report contract");bool closed=parse_boolean(argv[9]),mask=parse_boolean(argv[10]);
        if(mode=="single") {require(code=="11"||code=="4"||code=="25","Select supported prokaryotic translation table 11, 4 or 25");require(model=="auto"||model=="nonsd","Choose automatic or forced non-Shine-Dalgarno model");}
        else require(code=="auto"&&model=="auto","Metagenome mode uses upstream preset models and their translation tables; overrides are unsupported");
        Input input=validate(argv[3],mode);
        std::string executable=argv[1];
        if(executable=="bundled") {
#ifdef _WIN32
            executable=(std::filesystem::absolute(argv[0]).parent_path()/"prodigal.exe").string();
#else
            executable=(std::filesystem::absolute(argv[0]).parent_path()/"prodigal").string();
#endif
        }
        std::vector<std::string> args={executable,"-p",mode,"-i",argv[3],"-f","gff","-o",argv[4],"-a",argv[5],"-d",argv[6]};
        if(mode=="single"){args.insert(args.end(),{"-g",code});if(model=="nonsd")args.push_back("-n");}
        if(closed)args.push_back("-c");
        if(mask)args.push_back("-m");
        int status=run(args);require(status==0,"Prodigal failed (exit "+std::to_string(status)+"); review its preceding error log, selected mode and available memory");
        uint64_t proteins=count_fasta(argv[5]),cds=count_fasta(argv[6]);require(proteins==cds,"Prodigal protein/CDS counts disagree");
        std::ifstream gff(argv[4],std::ios::binary);require(bool(gff),"Prodigal did not write GFF annotations");
        uint64_t annotations=0;std::string text;while(line(gff,text))if(!text.empty()&&text[0]!='#'&&text!="\r")++annotations;
        require(annotations==cds,"Prodigal GFF and sequence counts disagree");
        std::cout<<"{\"schema\":1,\"tool\":\"Prodigal\",\"version\":\"2.6.3-workbench1\",\"mode\":\""<<mode<<"\",\"geneticCode\":\""<<code<<"\",\"startModel\":\""<<model<<"\",\"closedEnds\":"<<(closed?"true":"false")<<",\"maskN\":"<<(mask?"true":"false")<<",\"inputContigs\":"<<input.contigs<<",\"inputBases\":"<<input.bases<<",\"ambiguousBases\":"<<input.ambiguous<<",\"predictedGenes\":"<<cds<<",\"proteinRecords\":"<<proteins<<",\"cdsRecords\":"<<cds<<",\"command\":[";
        for(size_t i=0;i<args.size();++i){if(i)std::cout<<',';std::cout<<json_string(args[i]);}std::cout<<"]}\n";
        return 0;
    }catch(const std::exception &e){std::cerr<<"Prodigal input/run error: "<<e.what()<<"\n";return 2;}
}
