#pragma once
#include <windows.h>
#include <string>
struct statvfs { unsigned long long f_bavail, f_bsize; };
inline int statvfs(const char *path, struct statvfs *value) {
    value->f_bavail=0; value->f_bsize=1;
    std::string parent(path); auto slash=parent.find_last_of("/\\");
    parent=slash==std::string::npos ? "." : parent.substr(0,slash+1);
    ULARGE_INTEGER available,total,free;
    if (!GetDiskFreeSpaceExA(parent.c_str(),&available,&total,&free)) return -1;
    value->f_bavail=available.QuadPart; return 0;
}
