// MIT; implements the upstream MMapFile interface with Win32 file mappings.
#include "mmap_file.h"
namespace kraken2 {
MMapFile::MMapFile():valid_(false),fd_(-1),fptr_(nullptr),filesize_(0) {}
MMapFile::~MMapFile(){CloseFile();}
void MMapFile::OpenFile(const std::string &name,int mode,int a,int b,size_t size){OpenFile(name.c_str(),mode,a,b,size);}
void MMapFile::OpenFile(const char *name,int mode,int,int,size_t size){
 if(mode&O_APPEND || (mode&O_ACCMODE)==O_WRONLY) errx(EX_SOFTWARE,"unsupported mapping mode");
 fd_=wb_open(name,mode,0666);if(fd_<0)err(EX_OSERR,"cannot open %s",name);
 HANDLE file=(HANDLE)_get_osfhandle(fd_);LARGE_INTEGER length;
 if(mode&O_CREAT){length.QuadPart=size;if(!SetFilePointerEx(file,length,nullptr,FILE_BEGIN)||!SetEndOfFile(file))errx(EX_OSERR,"cannot extend %s",name);}
 if(!GetFileSizeEx(file,&length)||length.QuadPart<=0)errx(EX_DATAERR,"empty or unreadable mapping %s",name);
 filesize_=(size_t)length.QuadPart;bool writable=(mode&O_ACCMODE)==O_RDWR;
 HANDLE map=CreateFileMappingW(file,nullptr,writable?PAGE_READWRITE:PAGE_READONLY,0,0,nullptr);
 if(!map)errx(EX_OSERR,"CreateFileMapping failed (%lu): %s",GetLastError(),name);
 fptr_=(char*)MapViewOfFile(map,writable?FILE_MAP_WRITE:FILE_MAP_READ,0,0,0);CloseHandle(map);
 if(!fptr_)errx(EX_OSERR,"MapViewOfFile failed (%lu): %s",GetLastError(),name);valid_=true;
}
char *MMapFile::fptr(){return valid_?fptr_:nullptr;}
size_t MMapFile::filesize(){return valid_?filesize_:0;}
void MMapFile::LoadFile(){if(valid_){volatile char touched=0;for(size_t i=0;i<filesize_;i+=4096)touched^=fptr_[i];(void)touched;}}
void MMapFile::SyncFile(){if(valid_)FlushViewOfFile(fptr_,0);}
void MMapFile::CloseFile(){if(!valid_)return;UnmapViewOfFile(fptr_);_close(fd_);valid_=false;fptr_=nullptr;filesize_=0;fd_=-1;}
}
