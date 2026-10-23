// Private JSON-lines adapter. Keep Kitten's model and text normalizer loaded;
// create fresh generation context per turn through the vendor engine API.
#include "engine.h"
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>

int main(int argc, char **argv) try {
    std::map<std::string, std::string> args = {
        {"--tokens-only", "1"}, {"--offline", "1"}, {"--no-mmap", "1"},
        {"--voice", "Bruno"}, {"--max-tokens", "600"},
    };
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("Missing worker option");
        args[argv[i]] = argv[i + 1];
    }
    kitten::engine engine(args);
    std::cout << kitten::json{{"ready", true}}.dump() << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            auto request = kitten::json::parse(line);
            auto text = request.at("text").get<std::string>();
            if (text.empty() || text.size() > 8000) throw std::runtime_error("Invalid speech text");
            auto result = engine.generate({{"--text", text}, {"--seed", std::to_string(std::random_device{}() % 2147483647)}});
            std::ofstream report(request.at("report").get<std::string>());
            report << result.report.dump();
            report.close();
            if (!report) throw std::runtime_error("Cannot write token report");
            std::cout << kitten::json{{"complete", true}}.dump() << std::endl;
        } catch (const std::exception &error) {
            std::cerr << error.what() << std::endl;
            std::cout << kitten::json{{"error", "Speech token generation failed"}}.dump() << std::endl;
        }
    }
    return 0;
} catch (const std::exception &error) {
    std::cerr << error.what() << std::endl;
    return 1;
}
