#pragma once
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#include <direct.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <signal.h>
#include <pthread.h>
#include <cerrno>
#include <cstdio>
#include <cstdint>
typedef int key_t;
#ifndef S_IRGRP
#define S_IRGRP 0
#define S_IWGRP 0
#define S_IXGRP 0
#define S_IROTH 0
#define S_IWOTH 0
#define S_IXOTH 0
#endif
#ifndef S_IRWXU
#define S_IRWXU (_S_IREAD|_S_IWRITE|_S_IEXEC)
#endif
#ifndef SIGKILL
#define SIGKILL 9
#endif
inline int wb_mkdir(const char *path, int) { return _mkdir(path); }
#define mkdir wb_mkdir
inline int mkfifo(const char *, int) { errno=ENOSYS; return -1; }
inline int vfork() { errno=ENOSYS; return -1; }
inline int kill(int, int) { errno=ENOSYS; return -1; }
inline int symlink(const char *, const char *) { errno=ENOSYS; return -1; }
#endif
