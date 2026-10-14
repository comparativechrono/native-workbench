#define _POSIX_C_SOURCE 200809L
#include "bw_api.h"
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <poll.h>
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <sys/stat.h>
#ifndef BW_MODULE_SHA256
#define BW_MODULE_SHA256 "not-recorded"
#endif
extern const unsigned char bw_module_start[], bw_module_end[];
#ifdef BW_DIRECT
extern int32_t BW_ABI bw_entry(const bw_host *,uint32_t,const char *const *);
#endif
static volatile sig_atomic_t interrupted;
typedef struct {int in,out;} io_context;
static void on_signal(int n){(void)n;interrupted=1;}
static int ready(int fd,short events){
    struct pollfd p={fd,events,0};
    while(!interrupted){int k=poll(&p,1,100);if(k>0)return 1;if(k<0&&errno!=EINTR)return 0;}
    errno=EINTR;return 0;
}
static int64_t BW_ABI host_read(void *v,void *p,uint64_t n){
    io_context *c=v;if(!ready(c->in,POLLIN)||interrupted)return -1;
    ssize_t k;do{k=read(c->in,p,(size_t)n);}while(k<0&&errno==EINTR&&!interrupted);return k;
}
static int64_t BW_ABI host_write(void *v,uint32_t stream,const void *p,uint64_t n){
    io_context *c=v;int fd=stream==1?c->out:STDERR_FILENO;
    if(stream==1&&(!ready(fd,POLLOUT)||interrupted))return -1;
    /* Bound pipe writes so a writable pipe does not wait for an entire large buffer. */
    if(n>4096)n=4096;
    ssize_t k;do{k=write(fd,p,(size_t)n);}while(k<0&&errno==EINTR&&!interrupted);return k;
}
static void *BW_ABI host_alloc(void *v,uint64_t n){(void)v;if(n>SIZE_MAX)return NULL;return malloc((size_t)n);}
static void BW_ABI host_free(void *v,void *p){(void)v;free(p);}
static int32_t BW_ABI host_cancelled(void *v){(void)v;return interrupted?1:0;}
typedef struct {atomic_uint next;uint32_t count;bw_task task;void *context;} work;
static void *worker(void *v){work *w=v;for(;;){unsigned i=atomic_fetch_add(&w->next,1);if(i>=w->count||interrupted)break;w->task(w->context,i);}return NULL;}
static int32_t BW_ABI host_parallel(void *v,uint32_t count,uint32_t max,bw_task task,void *ctx){
    (void)v;if(!count||!max||max>64||!task)return -1;uint32_t n=count<max?count:max;
    work w;atomic_init(&w.next,0);w.count=count;w.task=task;w.context=ctx;
    pthread_t th[63];uint32_t started=0;for(uint32_t i=1;i<n;++i){if(pthread_create(&th[started],NULL,worker,&w))break;++started;}
    worker(&w);for(uint32_t i=0;i<started;++i)pthread_join(th[i],NULL);return interrupted?-1:0;
}
static void usage(void){fputs("bwfastq stats|revcomp --input FILE|- --output FILE|- [--threads 1..64]\nStrict four-line FASTQ, ACGTN only, Phred+33. Output files must not exist.\n",stderr);}
int main(int argc,char **argv){
    if(argc==2&&!strcmp(argv[1],"--version")){printf("bwfastq 0.1.0 / prepared SysV x86-64 ABI 1 / module sha256 %s\n",BW_MODULE_SHA256);return 0;}
    if(argc<2||(strcmp(argv[1],"stats")&&strcmp(argv[1],"revcomp"))){usage();return 4;}
    const char *input=NULL,*output=NULL,*threads="1";
    for(int i=2;i<argc;++i){if(i+1>=argc){usage();return 4;}
        if(!strcmp(argv[i],"--input")&&!input)input=argv[++i];
        else if(!strcmp(argv[i],"--output")&&!output)output=argv[++i];
        else if(!strcmp(argv[i],"--threads"))threads=argv[++i];else{usage();return 4;}}
    char *end;long nt=strtol(threads,&end,10);if(!*threads||*end||nt<1||nt>64||!input||!output){usage();return 4;}
    io_context c={STDIN_FILENO,STDOUT_FILENO};int own_in=strcmp(input,"-")!=0,own_out=strcmp(output,"-")!=0;
    if(own_in){c.in=open(input,O_RDONLY);if(c.in<0){perror("input");return 3;}struct stat st;if(fstat(c.in,&st)||!S_ISREG(st.st_mode)){fputs("Input must be a regular file, or use stdin.\n",stderr);close(c.in);return 3;}}
    char *temporary=NULL;
    if(own_out){
        struct stat st;if(lstat(output,&st)==0||errno!=ENOENT){fputs("Output must be a new file.\n",stderr);if(own_in)close(c.in);return 3;}
        size_t n=strlen(output)+24;temporary=malloc(n);if(!temporary){if(own_in)close(c.in);return 3;}
        snprintf(temporary,n,"%s.partial.XXXXXX",output);c.out=mkstemp(temporary);
        if(c.out<0){perror("temporary output");free(temporary);if(own_in)close(c.in);return 3;}
    }
    struct sigaction sa;memset(&sa,0,sizeof(sa));sa.sa_handler=on_signal;sigemptyset(&sa.sa_mask);sigaction(SIGINT,&sa,NULL);sigaction(SIGTERM,&sa,NULL);signal(SIGPIPE,SIG_IGN);
    bw_host h={BW_ABI_VERSION,sizeof(bw_host),BW_CAP_PARALLEL,&c,host_read,host_write,host_alloc,host_free,host_parallel,host_cancelled};
    const char *args[2]={argv[1],threads};
#ifdef BW_DIRECT
    int status=bw_entry(&h,2,args);
#else
    bw_entry_fn entry=(bw_entry_fn)(const void *)bw_module_start;int status=entry(&h,2,args);
#endif
    if(interrupted)status=130;if(own_in)close(c.in);
    if(own_out){
        if(!status&&fsync(c.out))status=3;if(close(c.out)&&!status)status=3;
        /* link() is an atomic no-replace publication in the same directory. */
        if(!status&&link(temporary,output)){perror("publish output");status=3;}
        unlink(temporary);free(temporary);
    }
    return status;
}
