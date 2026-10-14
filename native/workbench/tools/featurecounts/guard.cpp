// SPDX-License-Identifier: MIT
// Native Workbench featureCounts input guard. Does not assign or count reads.
#include <zlib.h>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static void need(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
static uint32_t u32(const unsigned char* p) { return uint32_t(p[0]) | uint32_t(p[1])<<8 | uint32_t(p[2])<<16 | uint32_t(p[3])<<24; }
struct Bam {
    gzFile f;
    explicit Bam(const char* p): f(gzopen(p, "rb")) { need(f, "Cannot open BAM"); }
    ~Bam() { if(f) gzclose(f); }
    bool read(void* p, unsigned n, bool eof=false) {
        int got=gzread(f,p,n);
        if (got==0 && eof) { int code; gzerror(f,&code); need(code==Z_OK || code==Z_STREAM_END,"Damaged/truncated BAM compression"); return false; }
        need(got==int(n),"Truncated BAM stream"); return true;
    }
    uint32_t integer() { unsigned char p[4]; read(p,4); return u32(p); }
};
static uint64_t integer(const std::string& s) { need(!s.empty() && s.find_first_not_of("0123456789")==std::string::npos,"Invalid GTF coordinate"); return std::stoull(s); }
int main(int argc, char** argv) {
    try {
        need(argc==4,"Usage: featurecounts-guard single|paired input.bam annotation.gtf");
        std::string mode=argv[1]; need(mode=="single" || mode=="paired","Invalid read mode");
        Bam bam(argv[2]); unsigned char magic[4]; bam.read(magic,4);
        need(std::string(reinterpret_cast<char*>(magic),4)==std::string("BAM\1",4),"A binary BAM file is required (not SAM or CRAM)");
        uint32_t hlen=bam.integer(); need(hlen<=64*1024*1024,"BAM header exceeds guard limit");
        std::vector<unsigned char> buffer(hlen); if(hlen) bam.read(buffer.data(),hlen);
        uint32_t nref=bam.integer(); need(nref>0 && nref<=10000000,"Invalid BAM reference dictionary");
        std::map<std::string,uint32_t> refs;
        for(uint32_t i=0;i<nref;++i) {
            uint32_t n=bam.integer(); need(n>1 && n<=200,"BAM contig name must contain 1 to 199 bytes");
            buffer.resize(n); bam.read(buffer.data(),n); need(buffer.back()==0,"Unterminated BAM reference name");
            std::string name(reinterpret_cast<char*>(buffer.data()),n-1); need(name.find('\0')==std::string::npos,"Embedded NUL in BAM reference name");
            uint32_t len=bam.integer(); need(len>0 && len<=2147483647,"Invalid BAM reference length");
            need(refs.emplace(name,len).second,"Duplicate BAM reference name");
        }
        uint64_t records=0;
        unsigned char size[4];
        while(bam.read(size,4,true)) {
            uint32_t n=u32(size); need(n>=32 && n<=16*1024*1024,"Invalid/unsupported BAM record size");
            buffer.resize(n); bam.read(buffer.data(),n); ++records;
            unsigned flag=u32(buffer.data()+12)>>16;
            need(bool(flag&1)==(mode=="paired"),"BAM read-pair flags disagree with the selected single/paired operation");
            need(!(flag&0x800),"Supplementary BAM alignments are outside this pack's counting contract; filter flag 0x800 before counting");
            unsigned namelen=buffer[8], cigars=u32(buffer.data()+12)&65535, seq=u32(buffer.data()+16);
            need(namelen>=2 && 32ULL+namelen+4ULL*cigars+(seq+1ULL)/2+seq<=n,"Malformed BAM record lengths");
            need(buffer[32+namelen-1]==0,"Unterminated BAM read name");
            if(mode=="paired") need(bool(flag&0x40)!=bool(flag&0x80),"Paired BAM must mark each record as exactly one of read 1 or read 2");
        }
        std::ifstream annotation(argv[3],std::ios::binary); need(bool(annotation),"Cannot open GTF");
        std::string line; uint64_t exons=0, lineno=0;
        std::regex gene("(^|;)\\s*gene_id\\s+\"([^\"]+)\"\\s*(;|$)");
        while(std::getline(annotation,line)) {
            ++lineno; need(line.size()<=1024*1024,"GTF line exceeds guard limit");
            if(!line.empty() && line.back()=='\r') line.pop_back();
            if(line.empty() || line[0]=='#') continue;
            std::vector<std::string> fields; std::istringstream s(line); std::string f;
            while(std::getline(s,f,'\t')) fields.push_back(f);
            need(fields.size()==9,"GTF must have exactly nine tab-separated columns (line "+std::to_string(lineno)+")");
            if(fields[2]!="exon") continue;
            auto ref=refs.find(fields[0]); need(ref!=refs.end(),"GTF exon contig absent from BAM reference dictionary: "+fields[0]);
            auto start=integer(fields[3]), end=integer(fields[4]);
            need(start>=1 && start<=end && end<=ref->second,"GTF exon coordinates outside BAM reference bounds");
            need(fields[6]=="+" || fields[6]=="-","GTF exon strand must be + or -");
            std::smatch match; need(std::regex_search(fields[8],match,gene),"Every GTF exon requires a quoted nonempty gene_id attribute");
            ++exons;
        }
        need(annotation.eof(),"Failed while reading GTF"); need(exons>0,"GTF contains no exon features with gene_id");
        std::cout<<"{\"valid\":true,\"bam_records\":"<<records<<",\"gtf_exons\":"<<exons<<",\"paired\":"<<(mode=="paired"?"true":"false")<<"}\n";
        return 0;
    } catch(const std::exception& e) { std::cerr<<"featureCounts input validation: "<<e.what()<<"\n"; return 2; }
}
