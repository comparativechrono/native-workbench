// SPDX-License-Identifier: MIT
// Upstream mosdepth computes per-base depths; this boundary validates inputs and
// aggregates those intervals over complete BAM-dictionary/target denominators.
#include <htslib/sam.h>
#include <htslib/hts.h>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <cstdio>
#include <zlib.h>
#include <iomanip>
#include <algorithm>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static void need(bool v,const std::string& m){if(!v)throw std::runtime_error(m);}
static int64_t number(const std::string&s){need(!s.empty()&&s.find_first_not_of("0123456789")==std::string::npos,"Nonnegative integer BED coordinate required");return std::stoll(s);}
static void local(const std::string&p){need(p.find("://")==std::string::npos&&p.find("##idx##")==std::string::npos&&p!="-","Only explicit local files are supported");for(unsigned char c:p)need(c>=32&&c<127,"ASCII local paths required; spaces are supported");}

struct Stats{uint64_t length=0,sum=0,breadth[3]={0,0,0};};
struct Region{std::string chrom,name;int64_t start,stop;};
static void add(Stats&s,uint64_t length,uint64_t depth,const int*t){s.length+=length;s.sum+=length*depth;for(int i=0;i<3;++i)if(depth>=uint64_t(t[i]))s.breadth[i]+=length;}
static std::vector<std::string> fields(const std::string&line){std::vector<std::string>v;std::stringstream ss(line);std::string f;while(std::getline(ss,f,'\t'))v.push_back(f);return v;}
static int summarize(int argc,char**argv){
 need(argc==9,"Usage: mosdepth-guard summary staged.bam none|normalized.bed per-base.bed.gz full-summary.tsv threshold1 threshold2 threshold3");
 int t[3];for(int i=0;i<3;++i){t[i]=int(number(argv[6+i]));need(t[i]>=1&&t[i]<=1000000&&(i==0||t[i]>t[i-1]),"Coverage thresholds must be strictly increasing integers 1..1000000");}
 samFile*f=sam_open(argv[2],"rb");need(f,"Cannot reopen staged BAM");sam_hdr_t*h=sam_hdr_read(f);need(h,"Cannot read staged BAM dictionary");std::vector<std::string>names;std::vector<int64_t>lengths;std::map<std::string,int>ids;
 for(int i=0;i<sam_hdr_nref(h);++i){names.push_back(sam_hdr_tid2name(h,i));lengths.push_back(sam_hdr_tid2len(h,i));ids[names.back()]=i;}sam_hdr_destroy(h);sam_close(f);
 std::vector<Region>regions;std::string bed=argv[3];if(bed!="none"){std::ifstream in(bed,std::ios::binary);need(bool(in),"Cannot reopen normalized BED");std::string line;while(std::getline(in,line)){auto v=fields(line);need(v.size()==3||v.size()==4,"Invalid private BED");regions.push_back({v[0],v.size()==4?v[3]:"region"+std::to_string(regions.size()+1),number(v[1]),number(v[2])});}}
 std::vector<Stats>chrom(names.size()),selected(regions.size());size_t ri=0;int tid=0;int64_t next=0;gzFile gz=gzopen(argv[4],"rb");need(gz,"Cannot read mosdepth per-base BED");std::string line;char buffer[65536];
 while(gzgets(gz,buffer,sizeof(buffer))){line+=buffer;need(line.size()<=1024*1024,"Per-base BED line too long");if(line.back()!='\n')continue;line.pop_back();if(!line.empty()&&line.back()=='\r')line.pop_back();auto v=fields(line);line.clear();need(v.size()==4,"Malformed mosdepth per-base interval");
  while(tid<int(names.size())&&next==lengths[tid]){++tid;next=0;}need(tid<int(names.size())&&v[0]==names[tid],"Per-base BED differs from BAM dictionary order");auto start=number(v[1]),stop=number(v[2]),depth=number(v[3]);need(start==next&&stop>start&&stop<=lengths[tid]&&depth<=2147483647,"Per-base BED does not partition the complete reference");next=stop;add(chrom[tid],stop-start,depth,t);
  while(ri<regions.size()&&(ids.at(regions[ri].chrom)<tid||(ids.at(regions[ri].chrom)==tid&&regions[ri].stop<=start)))++ri;
  for(size_t j=ri;j<regions.size()&&ids.at(regions[j].chrom)==tid&&regions[j].start<stop;++j){auto a=std::max(start,regions[j].start),b=std::min(stop,regions[j].stop);if(a<b)add(selected[j],b-a,depth,t);}
 }
 int error;gzerror(gz,&error);need((error==Z_OK||error==Z_STREAM_END)&&line.empty(),"Truncated mosdepth per-base BED");need(gzclose(gz)==Z_OK,"Per-base BGZF read failure");while(tid<int(names.size())&&next==lengths[tid]){++tid;next=0;}need(tid==int(names.size()),"Per-base BED omitted reference bases");
 std::ofstream out(argv[5],std::ios::binary);need(bool(out),"Cannot write full-reference summary");out<<"scope\tname\tlength\tdepth_sum\tmean";for(int i=0;i<3;++i)out<<"\tbases_ge_"<<t[i]<<"\tfraction_ge_"<<t[i];out<<'\n'<<std::fixed<<std::setprecision(6);
 auto write=[&](const char*scope,const std::string&name,const Stats&s){out<<scope<<'\t'<<name<<'\t'<<s.length<<'\t'<<s.sum<<'\t'<<(s.length?double(s.sum)/s.length:0);for(int i=0;i<3;++i)out<<'\t'<<s.breadth[i]<<'\t'<<(s.length?double(s.breadth[i])/s.length:0);out<<'\n';};
 auto merge=[](Stats&a,const Stats&b){a.length+=b.length;a.sum+=b.sum;for(int i=0;i<3;++i)a.breadth[i]+=b.breadth[i];};Stats total,target;
 for(size_t i=0;i<names.size();++i){write("reference",names[i],chrom[i]);merge(total,chrom[i]);}write("reference-total","total",total);
 for(size_t i=0;i<regions.size();++i){need(selected[i].length==uint64_t(regions[i].stop-regions[i].start),"Incomplete target-region denominator");write("target",regions[i].name,selected[i]);merge(target,selected[i]);}if(!regions.empty())write("target-total","total",target);need(bool(out),"Summary write failure");return 0;
}

int main(int argc,char**argv){
 try{
#ifdef _WIN32
  _set_fmode(_O_BINARY);_setmode(_fileno(stdout),_O_BINARY);_setmode(_fileno(stderr),_O_BINARY);
#endif
  if(argc>1&&std::string(argv[1])=="summary")return summarize(argc,argv);
  need(argc==8,"Usage: mosdepth-guard input.bam staged.bam none|targets.bed normalized.bed threshold1 threshold2 threshold3");
  for(int n=1;n<5;++n)local(argv[n]);
  int previous=0;for(int n=5;n<8;++n){auto t=number(argv[n]);need(t>previous&&t<=1000000,"Coverage thresholds must be strictly increasing integers 1..1000000");previous=int(t);}
  const std::string input=argv[1],staged=argv[2],bed=argv[3],normalized=argv[4];need(input!=staged,"Refusing to overwrite input BAM");
  {std::ifstream existing(staged,std::ios::binary);need(!existing,"Private staged BAM already exists");}
  {std::ifstream src(input,std::ios::binary);std::ofstream dst(staged,std::ios::binary);need(bool(src)&&bool(dst),"Cannot stage private BAM");std::vector<char>buf(1024*1024);while(src){src.read(buf.data(),buf.size());auto n=src.gcount();if(n)dst.write(buf.data(),n);}need(src.eof()&&bool(dst),"BAM staging failed");}
  samFile* f=sam_open(staged.c_str(),"rb");need(f,"Cannot open local BAM");
  need(hts_get_format(f)->format==bam,"Only binary BAM is supported; SAM and CRAM are not accepted");
  need(hts_check_EOF(f)==1,"BAM must have a valid BGZF EOF marker");
  sam_hdr_t* h=sam_hdr_read(f);need(h,"Cannot read BAM header");
  int nref=sam_hdr_nref(h);need(nref>0,"BAM requires a nonempty reference dictionary");
  kstring_t order={0,0,nullptr};need(sam_hdr_find_tag_hd(h,"SO",&order)==0&&std::string(order.s)=="coordinate","BAM header must declare SO:coordinate");free(order.s);
  std::map<std::string,std::pair<int,int64_t>> refs;
  for(int n=0;n<nref;++n){auto len=sam_hdr_tid2len(h,n);auto name=sam_hdr_tid2name(h,n);need(name&&len>0&&len<=2147483646LL,"BAM contig length must be 1..2147483646");need(refs.emplace(name,std::make_pair(n,len)).second,"Duplicate BAM contig name");}
  uint64_t rows=0;int priorTid=-1;hts_pos_t priorPos=-1;bool noCoordinate=false;int result;
  bam1_t*b=bam_init1();need(b,"Cannot allocate BAM record");
  while((result=sam_read1(f,h,b))>=0){
   ++rows;const auto&c=b->core;
   if(c.tid<0){need(c.flag&BAM_FUNMAP,"Mapped BAM record lacks a reference");noCoordinate=true;continue;}
   need(!noCoordinate,"Coordinate-bearing record follows unmapped tail");
   need(c.tid<nref&&c.pos>=0&&c.pos<sam_hdr_tid2len(h,c.tid),"BAM record coordinate outside reference dictionary");
   need(c.tid>priorTid||(c.tid==priorTid&&c.pos>=priorPos),"BAM records are not coordinate sorted");priorTid=c.tid;priorPos=c.pos;
   if(!(c.flag&BAM_FUNMAP)){
    need(c.n_cigar>0,"Mapped BAM record has no CIGAR");
    int64_t span=0,query=0;auto cig=bam_get_cigar(b);
    for(uint32_t i=0;i<c.n_cigar;++i){int op=bam_cigar_op(cig[i]);int64_t len=bam_cigar_oplen(cig[i]);need(op<=BAM_CDIFF&&len>0,"Unsupported or empty CIGAR operation");if(bam_cigar_type(op)&1)query+=len;if(bam_cigar_type(op)&2)span+=len;}
    need(span>0&&c.pos+span<=sam_hdr_tid2len(h,c.tid),"BAM alignment extends beyond reference");need(query==c.l_qseq,"BAM sequence and CIGAR lengths differ");
   }
  }
  need(result==-1,"Malformed or truncated BAM record stream");bam_destroy1(b);need(sam_close(f)==0,"Failed closing BAM input");sam_hdr_destroy(h);
  uint64_t regions=0,bases=0;
  if(bed!="none"){
   need(bed!=normalized,"Refusing to overwrite BED input");std::ifstream existing(normalized,std::ios::binary);need(!existing,"Private normalized BED already exists");
   std::ifstream in(bed,std::ios::binary);need(bool(in),"Cannot open BED");std::ofstream out(normalized,std::ios::binary);need(bool(out),"Cannot create private BED");std::string line;int tid=-1;int64_t end=-1;
   while(std::getline(in,line)){
    need(line.size()<=1024*1024,"BED line exceeds 1MiB");if(!line.empty()&&line.back()=='\r')line.pop_back();if(line.empty()||line[0]=='#')continue;
    std::vector<std::string> fields;std::stringstream stream(line);std::string field;while(std::getline(stream,field,'\t'))fields.push_back(field);
    need(fields.size()==3||fields.size()==4,"Use uncompressed BED3 or BED4 with tab separators");auto ref=refs.find(fields[0]);need(ref!=refs.end(),"BED contig absent from BAM: "+fields[0]);auto start=number(fields[1]),stop=number(fields[2]);need(start<stop&&stop<=ref->second.second,"BED interval outside BAM reference bounds or empty");
    need(ref->second.first>tid||(ref->second.first==tid&&start>=end),"BED must be coordinate sorted in BAM dictionary order with nonoverlapping intervals");tid=ref->second.first;end=stop;
    if(fields.size()==4){need(!fields[3].empty(),"BED4 name must be nonempty");for(unsigned char c:fields[3])need(c>=32&&c<127,"BED names must be printable ASCII");}
    out<<line<<'\n';++regions;bases+=stop-start;
   }
   need(in.eof()&&bool(out),"BED read/write failure");need(regions>0,"BED must contain at least one nonempty interval");
  }
  need(sam_index_build3(staged.c_str(),nullptr,14,2)==0,"Cannot build private CSI index");
  std::cout<<"{\"valid\":true,\"bam_records\":"<<rows<<",\"contigs\":"<<nref<<",\"target_regions\":"<<regions<<",\"target_bases\":"<<bases<<",\"coordinate_records_checked\":true,\"index\":\"private CSI\",\"coverage_engine\":\"mosdepth 0.3.14-workbench1; unchanged coverage algorithm\"}\n";
  return 0;
 }catch(const std::exception&e){std::cerr<<"mosdepth input validation: "<<e.what()<<'\n';return 2;}
}
