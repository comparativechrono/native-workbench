// MIT; Native Workbench Windows C/C++ library compatibility, 2026-10-04.
#ifndef WORKBENCH_BEDTOOLS_WINDOWS_COMPAT_H
#define WORKBENCH_BEDTOOLS_WINDOWS_COMPAT_H
#include <stdint.h>
#ifdef _WIN32
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <io.h>
#include <fcntl.h>
#include <direct.h>
#ifndef M_SQRT2
#define M_SQRT2 1.41421356237309504880
#endif
static inline int workbench_asprintf(char **destination, const char *format, ...) {
    va_list args, copy;
    va_start(args, format); va_copy(copy, args);
    int n = vsnprintf(NULL, 0, format, copy); va_end(copy);
    if (n < 0) { va_end(args); *destination = NULL; return -1; }
    *destination = (char *)malloc((size_t)n + 1);
    if (!*destination) { va_end(args); return -1; }
    int result = vsnprintf(*destination, (size_t)n + 1, format, args);
    va_end(args); return result;
}
#define asprintf workbench_asprintf
#endif
#endif
