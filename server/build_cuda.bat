@echo off
echo ========================================
echo   Building llama-cpp-python with CUDA 12.6
echo ========================================

call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"

set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6
set CudaToolkitDir=%CUDA_PATH%
set PATH=%CUDA_PATH%\bin;%PATH%
set CMAKE_GENERATOR=Ninja
set CMAKE_ARGS=-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=61

echo.
echo [OK] VS2022 + CUDA 12.6 environment ready (GTX 1070 = SM 6.1)
echo.

"%~dp0.venv\Scripts\python.exe" -m pip install "llama-cpp-python==0.3.36" --force-reinstall --no-cache-dir --no-deps

if errorlevel 1 (
    echo [FAIL] Build failed
    exit /b 1
)

echo.
echo ========================================
"%~dp0.venv\Scripts\python.exe" -c "from llama_cpp import llama_supports_gpu_offload; print('GPU offload:', llama_supports_gpu_offload())"
echo ========================================
