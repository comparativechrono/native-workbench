#include <filesystem>
#include <string>
void sysRemoveDir(std::string path) {
    std::error_code ec;
    std::filesystem::remove_all(path,ec);
}
