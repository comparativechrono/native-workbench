/* Native Workbench Windows I/O compatibility for pinned Kalign 3.5.1.
 * This is a forced build include, not an alignment implementation.
 * Keep the complete file with corresponding sources and build provenance.
 */
#ifndef WORKBENCH_KALIGN_WINDOWS_COMPAT_H
#define WORKBENCH_KALIGN_WINDOWS_COMPAT_H
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
/* Kalign uses ERROR as a local cleanup label. */
#ifdef ERROR
#undef ERROR
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <time.h>
#include <sys/types.h>

static inline struct tm *workbench_localtime_r(const time_t *value,
                                               struct tm *result)
{
    return localtime_s(result, value) == 0 ? result : NULL;
}

/* POSIX getline semantics: retain the newline, NUL terminate, return the
 * number of bytes read, and retain caller-owned allocated storage at EOF.
 * The pack boundary separately bounds inputs before the scientific process.
 */
static inline ssize_t workbench_getline(char **line, size_t *capacity, FILE *stream)
{
    size_t used = 0;
    int ch;
    if (!line || !capacity || !stream) { errno = EINVAL; return -1; }
    if (!*line || *capacity == 0) {
        char *next = (char *)realloc(*line, 256);
        if (!next) { errno = ENOMEM; return -1; }
        *line = next;
        *capacity = 256;
    }
    while ((ch = fgetc(stream)) != EOF) {
        if (used + 1 >= *capacity) {
            if (*capacity > (size_t)PTRDIFF_MAX / 2) { errno = EOVERFLOW; return -1; }
            size_t next_capacity = *capacity * 2;
            char *next = (char *)realloc(*line, next_capacity);
            if (!next) { errno = ENOMEM; return -1; }
            *line = next;
            *capacity = next_capacity;
        }
        (*line)[used++] = (char)ch;
        if (ch == '\n') break;
    }
    (*line)[used] = '\0';
    if (ferror(stream) || (used == 0 && ch == EOF)) return -1;
    return (ssize_t)used;
}
#define localtime_r workbench_localtime_r
#define getline workbench_getline
#endif
#endif
