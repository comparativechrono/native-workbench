#include "IncludeDefine.h"
#include "SharedMemory.h"
// Workbench uses --genomeLoad NoSharedMemory. Never emulate successful sharing.
SharedMemory::SharedMemory(key_t, bool) { throw SharedMemoryException(EOPENFAILED); }
SharedMemory::~SharedMemory() {}
void SharedMemory::Allocate(size_t) { throw SharedMemoryException(EOPENFAILED); }
void SharedMemory::Clean() { throw SharedMemoryException(EOPENFAILED); }
