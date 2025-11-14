@echo off
:: === Visual Studio Compiler ===
set PATH=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.29.30133\bin\Hostx64\x64;%PATH%

:: === CUDA Toolkit ===
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin;%PATH%

:: === Conda environment ===
call C:\ProgramData\miniconda3\Scripts\activate.bat vamtoolbox

:: === Show environment confirmation ===
where nvcc
where cl
where python
cmd