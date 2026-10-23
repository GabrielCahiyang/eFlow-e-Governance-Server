cmake_minimum_required(VERSION 3.24)
project(eflow_kitten LANGUAGES CXX)
foreach(path IN ITEMS KITTEN_SOURCE LLAMA_HEADERS LLAMA_LIB KITTEN_DATA_DIR)
  file(TO_CMAKE_PATH "${${path}}" ${path})
endforeach()
set(CMAKE_CXX_STANDARD 17)
set(KITTEN_BUILD_CLI OFF CACHE BOOL "" FORCE)
add_subdirectory("${KITTEN_SOURCE}/vendor/kitten-text-processing" text-processing)
add_executable(kitten-tts
  "${KITTEN_SOURCE}/tools/kitten-tts/main.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/engine.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/decoder_stub.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/text.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/assets.cpp")
target_include_directories(kitten-tts PRIVATE
  "${LLAMA_HEADERS}" "${CMAKE_CURRENT_SOURCE_DIR}" "${KITTEN_SOURCE}/tools/kitten-tts"
  "${KITTEN_SOURCE}/vendor/nlohmann")
target_compile_definitions(kitten-tts PRIVATE LLAMA_SHARED GGML_SHARED KITTEN_DEFAULT_DATA="${KITTEN_DATA_DIR}")
target_link_libraries(kitten-tts PRIVATE
  "${LLAMA_LIB}/llama.lib" "${LLAMA_LIB}/ggml.lib" "${LLAMA_LIB}/ggml-base.lib"
  KittenTextProcessing::normalizer)

add_executable(eflow-kitten-worker
  "${CMAKE_CURRENT_SOURCE_DIR}/token_worker.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/engine.cpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/decoder_stub.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/text.cpp"
  "${KITTEN_SOURCE}/tools/kitten-tts/assets.cpp")
target_include_directories(eflow-kitten-worker PRIVATE
  "${LLAMA_HEADERS}" "${CMAKE_CURRENT_SOURCE_DIR}" "${KITTEN_SOURCE}/tools/kitten-tts"
  "${KITTEN_SOURCE}/vendor/nlohmann")
target_compile_definitions(eflow-kitten-worker PRIVATE LLAMA_SHARED GGML_SHARED KITTEN_DEFAULT_DATA="${KITTEN_DATA_DIR}")
target_link_libraries(eflow-kitten-worker PRIVATE
  "${LLAMA_LIB}/llama.lib" "${LLAMA_LIB}/ggml.lib" "${LLAMA_LIB}/ggml-base.lib"
  KittenTextProcessing::normalizer)
