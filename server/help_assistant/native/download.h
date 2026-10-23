#pragma once
#include <string>
#include <filesystem>
#include <stdexcept>
// eFlow provisions and verifies assets separately. The runtime is offline.
struct common_download_opts {
    bool offline = true;
    std::string bearer_token;
    std::string ca_cert_file;
};
inline int common_download_file_single(const std::string &, const std::string & path, const common_download_opts &) {
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("Missing provisioned speech asset");
    return 304;
}
