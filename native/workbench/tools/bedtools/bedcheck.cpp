// MIT; Native Workbench bounded BED input validator and result counter.
// This helper performs no genomic interval arithmetic; BEDTools owns it.
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <cctype>
#include <cstring>
#include <limits>
#include <set>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static uint64_t coordinate(const std::string &value) {
    if (value.empty()) throw std::runtime_error("Empty BED coordinate");
    uint64_t n=0;
    for (unsigned char c:value) {
        if (c<'0'||c>'9'||n>(uint64_t(INT64_MAX)-(c-'0'))/10)
            throw std::runtime_error("BED coordinates must be nonnegative 64-bit integers");
        n=n*10+c-'0';
    }
    return n;
}
int main(int argc,char **argv) {
#ifdef _WIN32
    _set_fmode(_O_BINARY); _setmode(_fileno(stdout),_O_BINARY);
#endif
    try {
        if(argc==3 && std::string(argv[1])=="reference") {
            std::ifstream in(argv[2],std::ios::binary);if(!in)throw std::runtime_error("Cannot open reference FASTA");
            std::string line,id;std::set<std::string> names;uint64_t length=0;
            while(std::getline(in,line)) {
                if(!line.empty()&&line.back()=='\r')line.pop_back();
                if(line.empty())continue;
                if(line[0]=='>') {
                    if(!id.empty()&&!length)throw std::runtime_error("Empty reference sequence");
                    id=line.substr(1,line.find_first_of(" \t",1)-1);length=0;
                    if(id.empty()||!names.insert(id).second)throw std::runtime_error("Missing or duplicate reference contig ID");
                } else {
                    if(id.empty())throw std::runtime_error("Reference sequence before FASTA header");
                    for(unsigned char c:line) {
                        if(!std::strchr("ACGTRYSWKMBDHVNacgtryswkmbdhvn",c) || c==0)throw std::runtime_error("Reference must contain uncompressed nucleotide FASTA");
                        if(++length>2147483647ULL)throw std::runtime_error("BEDTools bundled faidx supports reference contigs of at most 2,147,483,647 bases");
                    }
                }
            }
            if(in.bad()||names.empty()||!length)throw std::runtime_error("Empty or unreadable reference FASTA");
            std::cout<<"{\"referenceContigs\":"<<names.size()<<"}\n";return 0;
        }
        if (argc!=3 || (std::string(argv[1])!="plain" && std::string(argv[1])!="strand" && std::string(argv[1])!="summary"))
            throw std::runtime_error("Usage: bedcheck plain|strand|summary BED");
        bool strand=std::string(argv[1])=="strand",summary=std::string(argv[1])=="summary";
        std::ifstream in(argv[2],std::ios::binary);
        if (!in) throw std::runtime_error("Cannot open BED file");
        uint64_t records=0;std::string line;size_t columns=0;
        while(std::getline(in,line)) {
            if (line.size()>1024*1024) throw std::runtime_error("BED line exceeds 1 MiB");
            if(!line.empty()&&line.back()=='\r') line.pop_back();
            if(line.empty()||line[0]=='#'||line.rfind("track ",0)==0||line.rfind("browser ",0)==0) continue;
            std::vector<std::string> fields;size_t begin=0;
            for(;;) {size_t end=line.find('\t',begin);fields.push_back(line.substr(begin,end==std::string::npos?end:end-begin));if(end==std::string::npos)break;begin=end+1;}
            if(fields.size()<3||fields.size()>6||(!summary&&columns&&columns!=fields.size()))
                throw std::runtime_error("Use a consistent, tab-separated BED3 through BED6 file; BED12 and other formats are not supported by this pack");
            columns=fields.size();
            if(fields[0].empty())throw std::runtime_error("Missing BED contig");
            for(unsigned char c:fields[0])if(std::isspace(c)||c>=128||c<32)throw std::runtime_error("BED contig IDs must be ASCII without whitespace");
            uint64_t start=coordinate(fields[1]),end=coordinate(fields[2]);
            if(start>=end)throw std::runtime_error("BED coordinates are zero-based half-open and require end greater than start");
            if(fields.size()>=4&&fields[3].empty())throw std::runtime_error("BED name cannot be empty");
            if(fields.size()>=5&&fields[4]!=".") {uint64_t score=coordinate(fields[4]);if(score>1000)throw std::runtime_error("BED score must be 0..1000 or a dot");}
            if(fields.size()==6&&fields[5]!="+"&&fields[5]!="-"&&fields[5]!=".")throw std::runtime_error("BED strand must be +, - or dot");
            if(strand&&(fields.size()!=6||(fields[5]!="+"&&fields[5]!="-")))throw std::runtime_error("Stranded operations require BED6 with an explicit + or - on every record");
            ++records;
        }
        if(in.bad())throw std::runtime_error("Cannot read BED file");
        if(!records&&!summary)throw std::runtime_error("Input BED contains no intervals");
        std::cout << "{\"records\":" << records << ",\"coordinateSystem\":\"zero-based-half-open\"}\n";
        return 0;
    }catch(const std::exception &e){std::cerr<<"BED input error: "<<e.what()<<"\n";return 2;}
}
