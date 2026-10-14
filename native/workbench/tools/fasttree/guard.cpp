// SPDX-License-Identifier: MIT
// Validation/normalization and subprocess boundary only; FastTree infers the tree.
#include <algorithm>
#include <cmath>
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
namespace fs=std::filesystem;
static void need(bool ok,const std::string& message){if(!ok)throw std::runtime_error(message);}
static std::string json(const std::string&s){std::string o="\"";for(unsigned char c:s){if(c=='"'||c=='\\'){o+='\\';o+=char(c);}else if(c=='\n')o+="\\n";else if(c=='\r')o+="\\r";else if(c=='\t')o+="\\t";else{need(c>=32&&c<127,"ASCII text required");o+=char(c);}}return o+'"';}
static void local(const std::string&s){need(!s.empty()&&s!="-"&&s.find("://")==std::string::npos,"Select explicit local paths");for(unsigned char c:s)need(c>=32&&c<127,"ASCII installation, input and results paths required; spaces are supported");}
static std::string read(const fs::path&p,size_t max){std::ifstream f(p,std::ios::binary);need(bool(f),"Cannot read "+p.string());need(fs::file_size(p)<=max,"Input exceeds bounded pack size limit");return std::string(std::istreambuf_iterator<char>(f),{});}
static void write(const fs::path&p,const std::string&s){need(!fs::exists(p),"Refusing to replace existing output: "+p.string());std::ofstream f(p,std::ios::binary);need(bool(f),"Cannot create "+p.string());f<<s;f.close();need(bool(f),"Output write failed: "+p.string());}
static int integer(const std::string&s){need(!s.empty()&&s.find_first_not_of("0123456789")==std::string::npos,"Seed must be an integer 1..2147483647");auto n=std::stoll(s);need(n>=1&&n<=2147483647,"Seed must be 1..2147483647");return int(n);}
struct Alignment{std::vector<std::string> ids,seqs;size_t columns=0,variable=0,informative=0,ambiguous=0,gaps=0;};
static Alignment alignment(const fs::path&p,bool nt){
 Alignment a;std::istringstream in(read(p,256*1024*1024));std::string line;std::set<std::string> ids;size_t bytes=0;
 const std::string canonical=nt?"ACGT":"ACDEFGHIKLMNPQRSTVWY",allowed=nt?"ACGTURYSWKMBDHVN-.":"ACDEFGHIKLMNPQRSTVWYBXZ-.";
 while(std::getline(in,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();if(line.empty())continue;
  if(line[0]=='>'){std::istringstream header(line.substr(1));std::string id;header>>id;need(!id.empty()&&id.size()<=128,"FASTA identifiers must contain 1..128 ASCII characters");for(unsigned char c:id)need(std::isalnum(c)||c=='_'||c=='.'||c=='-',"Rename FASTA identifiers using only letters, digits, underscore, dot or hyphen");need(ids.insert(id).second,"Duplicate FASTA first-word identifier: "+id);need(a.ids.size()<10000,"At most 10000 taxa supported");a.ids.push_back(id);a.seqs.emplace_back();}
  else{need(!a.seqs.empty(),"Expected uncompressed aligned FASTA beginning with >");for(unsigned char raw:line){need(raw<128,"Non-ASCII alignment character");char c=char(std::toupper(raw));need(allowed.find(c)!=std::string::npos,"Unsupported alignment symbol; use DNA IUPAC or protein standard residues/B/X/Z and gaps, without stops or sequence whitespace");if(nt&&c=='U')c='T';if(c=='.')c='-';if(c=='-')++a.gaps;else if(canonical.find(c)==std::string::npos){++a.ambiguous;c='-';}a.seqs.back()+=c;need(++bytes<=256*1024*1024,"Alignment exceeds 256 MiB");}need(a.seqs.back().size()<=1000000,"At most 1000000 alignment columns supported");}
 }
 need(a.ids.size()>=4,"At least four aligned taxa are required for this tree operation");a.columns=a.seqs[0].size();need(a.columns>=20,"At least 20 alignment columns required");
 for(const auto&s:a.seqs){need(s.size()==a.columns,"Alignment rows have different lengths; align the homologous sequences first");need(s.find_first_not_of('-')!=std::string::npos,"Every taxon needs at least one recognized residue; unknown symbols are treated as missing data");}
 for(size_t i=0;i<a.columns;++i){std::map<char,size_t> counts;for(const auto&s:a.seqs)if(s[i]!='-')++counts[s[i]];if(counts.size()>1)++a.variable;size_t repeated=0;for(auto x:counts)if(x.second>=2)++repeated;if(repeated>=2)++a.informative;}
 return a;
}
static std::string token(size_t i){std::ostringstream s;s<<'T'<<std::setw(6)<<std::setfill('0')<<(i+1);return s.str();}
static int child(const std::vector<std::string>&args,const fs::path&report,const fs::path&log){
#ifdef _WIN32
 std::string cmd;for(auto a:args){if(!cmd.empty())cmd+=' ';cmd+='"';size_t slashes=0;for(char c:a){if(c=='\\'){++slashes;continue;}if(c=='"'){cmd.append(slashes*2+1,'\\');cmd+='"';}else{cmd.append(slashes,'\\');cmd+=c;}slashes=0;}cmd.append(slashes*2,'\\');cmd+='"';}
 SECURITY_ATTRIBUTES sa{sizeof(sa),nullptr,TRUE};HANDLE out=CreateFileA(report.string().c_str(),GENERIC_WRITE,FILE_SHARE_READ,&sa,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);HANDLE err=CreateFileA(log.string().c_str(),GENERIC_WRITE,FILE_SHARE_READ,&sa,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);need(out!=INVALID_HANDLE_VALUE&&err!=INVALID_HANDLE_VALUE,"Cannot create FastTree execution logs");HANDLE input=CreateFileA("NUL",GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,nullptr);STARTUPINFOA si{};si.cb=sizeof(si);si.dwFlags=STARTF_USESTDHANDLES;si.hStdOutput=out;si.hStdError=err;si.hStdInput=input;PROCESS_INFORMATION pi{};BOOL ok=CreateProcessA(args[0].c_str(),cmd.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW,nullptr,nullptr,&si,&pi);CloseHandle(out);CloseHandle(err);CloseHandle(input);need(ok,"Cannot start bundled FastTree executable");WaitForSingleObject(pi.hProcess,INFINITE);DWORD code=1;GetExitCodeProcess(pi.hProcess,&code);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return int(code);
#else
 pid_t pid=fork();need(pid>=0,"Cannot fork FastTree");if(pid==0){int out=open(report.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600),err=open(log.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);if(out<0||err<0)_exit(126);dup2(out,STDOUT_FILENO);dup2(err,STDERR_FILENO);close(out);close(err);std::vector<char*> argv;for(const auto&s:args)argv.push_back(const_cast<char*>(s.c_str()));argv.push_back(nullptr);execv(argv[0],argv.data());_exit(127);}int status=0;need(waitpid(pid,&status,0)==pid,"Cannot wait for FastTree");return WIFEXITED(status)?WEXITSTATUS(status):128;
#endif
}
struct Tree{std::string restored;size_t leaves=0,branches=0,supports=0;};
static Tree tree(const std::string&s,const Alignment&a,bool support){
 Tree t;std::map<std::string,std::string> names;for(size_t i=0;i<a.ids.size();++i)names[token(i)]=a.ids[i];std::set<std::string> seen;std::vector<size_t> children;size_t i=0;bool expect=true,closed=false,done=false;
 auto skip=[&](){while(i<s.size()&&std::isspace(static_cast<unsigned char>(s[i])))++i;};
 auto numeric=[&](){size_t start=i;while(i<s.size()&&std::string("0123456789eE+-.").find(s[i])!=std::string::npos)++i;need(i>start,"Missing numeric Newick branch/support");size_t used=0;auto v=std::stod(s.substr(start,i-start),&used);need(used==i-start&&std::isfinite(v)&&v>=0,"Invalid negative/nonfinite Newick branch/support");t.restored+=s.substr(start,i-start);return v;};
 while(i<s.size()){skip();if(i==s.size())break;char c=s[i];if(expect){if(c=='('){children.push_back(0);t.restored+='('; ++i;continue;}size_t start=i;while(i<s.size()&&std::string("(),:; \t\r\n").find(s[i])==std::string::npos)++i;std::string name=s.substr(start,i-start);need(names.count(name)&&seen.insert(name).second,"FastTree output changed, omitted or duplicated a taxon identifier");t.restored+=names[name];++t.leaves;expect=false;closed=false;}
  else{if(closed&&c!=':'&&c!=','&&c!=')'&&c!=';'){double v=numeric();need(support&&v<=1,"Unexpected local support outside 0..1");++t.supports;closed=false;continue;}if(c==':'){t.restored+=':';++i;numeric();++t.branches;closed=false;skip();c=i<s.size()?s[i]:0;need(c==','||c==')'||c==';',"Unexpected Newick content after branch length");continue;}if(c==','){need(!children.empty(),"Malformed Newick comma");++children.back();t.restored+=c;++i;expect=true;closed=false;}else if(c==')'){need(!children.empty()&&++children.back()>=2,"Malformed Newick internal node");children.pop_back();t.restored+=c;++i;closed=true;}else if(c==';'){need(children.empty(),"Unclosed Newick internal node");t.restored+=';';++i;skip();need(i==s.size(),"Trailing Newick content");done=true;break;}else need(false,"Malformed Newick output");}
 }
 need(done&&!expect&&seen.size()==a.ids.size(),"Incomplete Newick tree or missing taxa");need(t.branches>=a.ids.size(),"Missing Newick branch lengths");need(support?t.supports<=t.branches-t.leaves:t.supports==0,"Unexpected branch support count");t.restored+='\n';return t;
}
int main(int argc,char**argv){try{
 need(argc==8,"Usage: fasttree-guard alignment run-directory nucleotide|protein JC|GTR|JTT|LG|WAG cat|gamma none|sh seed");
 for(int i=1;i<=2;++i){local(argv[i]);}
 fs::path input=fs::absolute(argv[1]),run=fs::absolute(argv[2]);need(fs::is_directory(run),"Run directory does not exist");
 std::string datatype=argv[3],model=argv[4],rates=argv[5],support=argv[6];bool nt=datatype=="nucleotide";need(nt||datatype=="protein","Datatype must be nucleotide or protein");need(nt?(model=="JC"||model=="GTR"):(model=="JTT"||model=="LG"||model=="WAG"),"Choose a substitution model valid for the selected datatype");need(rates=="cat"||rates=="gamma","Rates must be CAT20 or Gamma20 branch-length rescaling");need(support=="none"||support=="sh","Support must be none or SH-like local support");int seed=integer(argv[7]);
 for(const char*name:{"inferred-tree.nwk","alignment-summary.json","analysis-settings.json","fasttree.log","fasttree-model.log","fasttree.stdout","fasttree-work"})need(!fs::exists(run/name),"Choose a fresh output folder; output already exists: "+std::string(name));
 Alignment a=alignment(input,nt);fs::path work=run/"fasttree-work";fs::create_directory(work);std::ostringstream staged;for(size_t i=0;i<a.ids.size();++i)staged<<'>'<<token(i)<<'\n'<<a.seqs[i]<<'\n';write(work/"alignment.fa",staged.str());
 fs::path self=fs::absolute(argv[0]);
#ifdef _WIN32
 char module[32768];DWORD len=GetModuleFileNameA(nullptr,module,sizeof(module));need(len>0&&len<sizeof(module),"Cannot locate installed FastTree");self=fs::path(std::string(module,len));
#endif
 fs::path binary=self.parent_path()/
#ifdef _WIN32
 "fasttree.exe";
#else
 "fasttree";
#endif
 local(binary.string());need(fs::is_regular_file(binary),"Bundled FastTree executable is missing; reinstall this pack");
 std::vector<std::string> cmd{binary.string(),"-nopr","-cat","20","-seed",std::to_string(seed),"-boot",support=="sh"?"1000":"0","-log",(run/"fasttree-model.log").string(),"-out",(work/"raw-tree.nwk").string()};if(nt)cmd.push_back("-nt");if(model=="GTR")cmd.push_back("-gtr");if(model=="LG")cmd.push_back("-lg");if(model=="WAG")cmd.push_back("-wag");if(rates=="gamma")cmd.push_back("-gamma");cmd.push_back((work/"alignment.fa").string());
 std::ostringstream settings;settings<<"{\n  \"tool\": \"FastTree\", \"version\": \"2.2.0\", \"serial\": true, \"precision\": \"double\",\n  \"datatype\": "<<json(datatype)<<", \"model\": "<<json(model)<<", \"rates\": "<<json(rates)<<", \"support\": "<<json(support)<<", \"supportResamples\": "<<(support=="sh"?1000:0)<<", \"seed\": "<<seed<<",\n  \"taxonMapping\": [";for(size_t i=0;i<a.ids.size();++i){if(i)settings<<',';settings<<"{\"stagedId\":"<<json(token(i))<<",\"originalId\":"<<json(a.ids[i])<<'}';}settings<<"],\n  \"argv\": [";for(size_t i=0;i<cmd.size();++i){if(i)settings<<',';settings<<json(cmd[i]);}settings<<"]\n}\n";write(run/"analysis-settings.json",settings.str());
 int code=child(cmd,run/"fasttree.stdout",run/"fasttree.log");need(code==0,"FastTree exited with status "+std::to_string(code)+"; inspect fasttree.log, input alignment and selected model");Tree result=tree(read(work/"raw-tree.nwk",16*1024*1024),a,support=="sh");
 std::ostringstream summary;summary<<"{\n  \"taxa\": "<<a.ids.size()<<",\n  \"columns\": "<<a.columns<<",\n  \"variableColumnsIgnoringMissing\": "<<a.variable<<",\n  \"parsimonyInformativeColumnsIgnoringMissing\": "<<a.informative<<",\n  \"gapCharacters\": "<<a.gaps<<",\n  \"ambiguityCharactersTreatedAsMissing\": "<<a.ambiguous<<",\n  \"treeTaxa\": "<<result.leaves<<",\n  \"branchLengths\": "<<result.branches<<",\n  \"localSupportValues\": "<<result.supports<<",\n  \"interpretation\": \"Unrooted approximate maximum-likelihood gene tree. SH-like local support is not global bootstrap or posterior probability. CAT20 search; optional Gamma20 rescales lengths without a new topology search. Measurements only; no QC pass thresholds.\"\n}\n";
 write(run/"alignment-summary.json",summary.str());write(run/"inferred-tree.nwk",result.restored);std::cout<<"FastTree completed; recorded "<<a.ids.size()<<" taxa and "<<a.columns<<" aligned columns.\n";return 0;
 }catch(const std::exception&e){std::cerr<<"FastTree pack: "<<e.what()<<'\n';return 2;}}
