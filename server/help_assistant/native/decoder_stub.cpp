#include "decoder.h"
#include <stdexcept>
namespace kitten {
struct decoder::impl {};
decoder::decoder(const std::string &, int, int) { throw std::runtime_error("Use eFlow's CUDA waveform decoder"); }
decoder::~decoder() = default;
void decoder::seed(int) {}
std::vector<float> decoder::decode(const std::vector<int> &, const std::string &) { throw std::runtime_error("CUDA waveform decoder is required"); }
}
