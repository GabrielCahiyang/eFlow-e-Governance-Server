@echo off
rem Match headers to the installed llama-cpp-python 0.3.36 ABI, including all GPU libraries.
call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
set "PATH=%~dp0.speech-venv\Scripts;%PATH%"
cmake -S "%~dp0help_assistant\native" -B "%USERPROFILE%\.cache\eflow-speech\build-compat" -G Ninja -DCMAKE_BUILD_TYPE=Release -DKITTEN_SOURCE="%USERPROFILE%/.cache/eflow-speech/src" -DLLAMA_HEADERS="%USERPROFILE%/.cache/eflow-speech/compat-include" -DLLAMA_LIB="%~dp0.venv/Lib/site-packages/llama_cpp/lib" -DCMAKE_PREFIX_PATH="%~dp0.speech-venv/Lib/site-packages/torch/share/cmake" -DKITTEN_DATA_DIR="%~dp0.speech-venv/Lib/site-packages/kitten_tts_cpp/data"
if errorlevel 1 exit /b 1
cmake --build "%USERPROFILE%\.cache\eflow-speech\build-compat" --parallel 2
exit /b %errorlevel%
