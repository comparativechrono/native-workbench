// MIT; OS boundary only. Kraken2 scientific routines remain upstream.
#ifndef WORKBENCH_KRAKEN2_WINDOWS_COMPAT_H
#define WORKBENCH_KRAKEN2_WINDOWS_COMPAT_H
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <cstdlib>
#include <cstdio>
#include <cerrno>
#include <cstdarg>
#include <cstring>
#include <algorithm>
#include <getopt.h>
static inline void wb_message(bool with_errno, const char *fmt, va_list a) {
 int saved=errno; vfprintf(stderr,fmt,a); if(with_errno) fprintf(stderr,": %s",strerror(saved)); fputc('\n',stderr);
}
[[noreturn]] static inline void err(int status,const char *fmt,...) {va_list a;va_start(a,fmt);wb_message(true,fmt,a);va_end(a);exit(status);}
[[noreturn]] static inline void errx(int status,const char *fmt,...) {va_list a;va_start(a,fmt);wb_message(false,fmt,a);va_end(a);exit(status);}
static inline void warnx(const char *fmt,...) {va_list a;va_start(a,fmt);wb_message(false,fmt,a);va_end(a);}
static inline void warn(const char *fmt,...) {va_list a;va_start(a,fmt);wb_message(true,fmt,a);va_end(a);}
// No transparent huge-page facility is requested on Windows. Ordinary malloc
// gives the alignment required by the upstream POD table, paired with free.
static inline int wb_posix_memalign(void **p,size_t,size_t n) {*p=malloc(n);return *p?0:ENOMEM;}
#define posix_memalign wb_posix_memalign
static inline int wb_open(const char *p,int flags, int permissions=0666) {return _open(p,flags|_O_BINARY,permissions);}
static inline int wb_read(int fd,void *p,size_t n) {return _read(fd,p,(unsigned)std::min(n,(size_t)0x40000000));}
#define lseek _lseeki64
#define EX_OK 0
#define EX_USAGE 64
#define EX_DATAERR 65
#define EX_NOINPUT 66
#define EX_SOFTWARE 70
#define EX_OSERR 71
#define EX_CANTCREAT 73
#define EX_IOERR 74
#define EX_CONFIG 78
#endif
#endif
