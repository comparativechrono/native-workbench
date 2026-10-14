/* Prepared x86-64 computation. No operating-system headers or libc calls. */
#include "bw_api.h"
typedef struct { const bw_host *h; unsigned char *buf; uint64_t at,end; int eof; } reader;
typedef struct { unsigned char *p; uint64_t n,cap; } line;
typedef struct { uint64_t gc,ns,q; int bad_seq,bad_quality; } partial;
typedef struct { const unsigned char *s,*q; uint64_t n; uint32_t nt; partial p[64]; } count_job;
typedef struct { unsigned char *s,*q; uint64_t n; uint32_t nt; } reverse_job;
static uint64_t slen(const char *s) { uint64_t n=0; while(s[n]) ++n; return n; }
static int equal(const char *a,const char *b) { while(*a&&*a==*b){++a;++b;} return *a==*b; }
static int emit(const bw_host *h,uint32_t stream,const void *buf,uint64_t n) {
    const unsigned char *p=buf;
    while(n){ int64_t w=h->write(h->context,stream,p,n); if(w<=0||(uint64_t)w>n)return -1; p+=w;n-=(uint64_t)w; } return 0;
}
static int text(const bw_host *h,uint32_t stream,const char *s){ return emit(h,stream,s,slen(s)); }
static int problem(const bw_host *h,int code,const char *s) { text(h,2,s);text(h,2,"\n"); return code; }
static int reserve(const bw_host *h,line *l,uint64_t need) {
    if(need<=l->cap)return 0; uint64_t cap=l->cap?l->cap:256;
    while(cap<need)cap*=2; if(cap>BW_MAX_LINE+1ull)cap=BW_MAX_LINE+1ull;
    unsigned char *p=h->alloc(h->context,cap);if(!p)return -1;
    for(uint64_t i=0;i<l->n;++i)p[i]=l->p[i];
    if(l->p)h->free(h->context,l->p);l->p=p;l->cap=cap;return 0;
}
/* 1 line; 0 clean EOF; -1 host error; -2 excessive line; -3 cancellation. */
static int next_line(reader *r,line *l) {
    l->n=0;
    for(;;){
        if(r->h->cancelled(r->h->context))return -3;
        if(r->at==r->end){
            if(r->eof)return l->n?1:0;
            int64_t got=r->h->read(r->h->context,r->buf,65536);
            if(got<0||got>65536)return -1;
            r->at=0;r->end=(uint64_t)got;if(!got){r->eof=1;continue;}
        }
        unsigned char c=r->buf[r->at++];
        if(c=='\n'){if(l->n&&l->p[l->n-1]=='\r')--l->n;return l->n>BW_MAX_LINE?-2:1;}
        if(l->n>=BW_MAX_LINE+1ull)return -2;
        if(reserve(r->h,l,l->n+1))return -1;l->p[l->n++]=c;
        if(l->n>BW_MAX_LINE&&c!='\r')return -2;
    }
}
static void BW_ABI count_task(void *v,uint32_t i){
    count_job *j=v;partial *p=&j->p[i];p->gc=p->ns=p->q=0;p->bad_seq=p->bad_quality=0;
    uint64_t lo=j->n*i/j->nt,hi=j->n*(i+1)/j->nt;
    for(uint64_t k=lo;k<hi;++k){unsigned char c=j->s[k];
        if(c=='C'||c=='c'||c=='G'||c=='g')++p->gc;
        else if(c=='N'||c=='n')++p->ns;
        else if(c!='A'&&c!='a'&&c!='T'&&c!='t')p->bad_seq=1;
        unsigned char q=j->q[k]; if(q<33||q>126)p->bad_quality=1;else p->q+=q-33;
    }
}
static unsigned char complement(unsigned char c){
    switch(c){case 'A':return 'T';case 'T':return 'A';case 'G':return 'C';case 'C':return 'G';
    case 'a':return 't';case 't':return 'a';case 'g':return 'c';case 'c':return 'g';default:return c;}
}
static void BW_ABI reverse_task(void *v,uint32_t t){
    reverse_job *j=v;uint64_t half=j->n/2,lo=half*t/j->nt,hi=half*(t+1)/j->nt;
    for(uint64_t i=lo;i<hi;++i){uint64_t k=j->n-1-i;unsigned char a=j->s[i],b=j->q[i];
        j->s[i]=complement(j->s[k]);j->s[k]=complement(a);j->q[i]=j->q[k];j->q[k]=b;}
    if(t==0&&(j->n&1))j->s[half]=complement(j->s[half]);
}
static int metadata(const line *l,int header){
    if(!l->n||l->p[0]!=(header?'@':'+'))return 0;
    if(header&&(l->n<2||l->p[1]<33||l->p[1]>126))return 0;
    for(uint64_t i=1;i<l->n;++i)if(l->p[i]<32||l->p[i]>126)return 0;return 1;
}
static int number(const bw_host *h,uint64_t n){char s[32];uint32_t i=32;do{s[--i]=(char)('0'+n%10);n/=10;}while(n);return emit(h,1,s+i,32-i);}
static int field(const bw_host *h,const char *name,uint64_t n,int last){return text(h,1,name)||number(h,n)||text(h,1,last?"\n}\n":",\n");}
static int add(uint64_t *a,uint64_t b){if(UINT64_MAX-*a<b)return -1;*a+=b;return 0;}
__attribute__((section(".text.entry"),visibility("default")))
int32_t BW_ABI bw_entry(const bw_host *h,uint32_t argc,const char *const *argv){
    if(!h||h->abi_version!=BW_ABI_VERSION||h->struct_size<sizeof(*h)||!h->read||!h->write||!h->alloc||!h->free||!h->cancelled)return 4;
    if(argc!=2||!argv)return problem(h,4,"Expected stats|revcomp and thread count.");
    int reverse=equal(argv[0],"revcomp");if(!reverse&&!equal(argv[0],"stats"))return problem(h,4,"Unsupported command.");
    uint32_t threads=0;for(const char *p=argv[1];*p;++p){if(*p<'0'||*p>'9'||threads>64)return problem(h,4,"Invalid threads.");threads=threads*10+(uint32_t)(*p-'0');}
    if(!threads||threads>64)return problem(h,4,"Threads must be 1..64.");
    if(threads>1&&(!(h->capabilities&BW_CAP_PARALLEL)||!h->parallel_for))return problem(h,4,"Host lacks parallel capability.");
    reader r={h,0,0,0,0};line lines[4];for(int i=0;i<4;++i){lines[i].p=0;lines[i].n=lines[i].cap=0;}
    uint64_t records=0,bases=0,gc=0,ns=0,phred=0,min=UINT64_MAX,max=0;int status=0;
    r.buf=h->alloc(h->context,65536);if(!r.buf){status=problem(h,3,"Unable to allocate read buffer.");goto done;}
    for(;;){
        for(int i=0;i<4;++i){int got=next_line(&r,&lines[i]);
            if(got==0){if(i==0)goto complete;status=problem(h,2,"Incomplete four-line FASTQ record.");goto done;}
            if(got<0){status=problem(h,got==-3?130:got==-2?2:3,got==-3?"Cancelled.":got==-2?"FASTQ line exceeds 16 MiB limit.":"Read or allocation failed.");goto done;}
            if(lines[i].n>BW_MAX_LINE){status=problem(h,2,"FASTQ line exceeds 16 MiB limit.");goto done;}
        }
        if(!metadata(&lines[0],1)||!metadata(&lines[2],0)){status=problem(h,2,"Invalid FASTQ header or separator.");goto done;}
        if(lines[1].n!=lines[3].n){status=problem(h,2,"Sequence and quality lengths differ.");goto done;}
        count_job j;j.s=lines[1].p;j.q=lines[3].p;j.n=lines[1].n;j.nt=j.n>=65536?threads:1;
        if(j.nt==1)count_task(&j,0);else if(h->parallel_for(h->context,j.nt,threads,count_task,&j)){status=problem(h,3,"Parallel operation failed.");goto done;}
        for(uint32_t i=0;i<j.nt;++i){if(j.p[i].bad_seq||j.p[i].bad_quality){status=problem(h,2,j.p[i].bad_seq?"Sequence must contain ACGTN only.":"Quality must be printable Phred+33.");goto done;}
            if(add(&gc,j.p[i].gc)||add(&ns,j.p[i].ns)||add(&phred,j.p[i].q)){status=problem(h,2,"Statistics overflow.");goto done;}}
        if(add(&records,1)||add(&bases,j.n)){status=problem(h,2,"Statistics overflow.");goto done;}
        if(j.n<min)min=j.n;if(j.n>max)max=j.n;
        if(reverse){reverse_job rev={lines[1].p,lines[3].p,j.n,j.nt};
            if(j.nt==1)reverse_task(&rev,0);else if(h->parallel_for(h->context,j.nt,threads,reverse_task,&rev)){status=problem(h,3,"Parallel operation failed.");goto done;}
            for(int i=0;i<4;++i)if(emit(h,1,lines[i].p,lines[i].n)||text(h,1,"\n")){status=problem(h,3,"Output write failed.");goto done;}
        }
    }
complete:
    if(h->cancelled(h->context)){status=problem(h,130,"Cancelled.");goto done;}
    if(!reverse&&(text(h,1,"{\n")||field(h,"  \"records\": ",records,0)||field(h,"  \"bases\": ",bases,0)||field(h,"  \"gc_bases\": ",gc,0)||field(h,"  \"n_bases\": ",ns,0)||field(h,"  \"min_length\": ",records?min:0,0)||field(h,"  \"max_length\": ",max,0)||field(h,"  \"phred33_sum\": ",phred,1)))status=problem(h,3,"Output write failed.");
done:
    for(int i=0;i<4;++i)if(lines[i].p)h->free(h->context,lines[i].p);if(r.buf)h->free(h->context,r.buf);return status;
}
