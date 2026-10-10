@echo off
REM install-windows.bat — editable install boss-hr-agent-toolkit
REM
REM 要求：
REM   - Windows + Python 3.10+
REM   - 从脚本所在目录运行（不硬编码用户/桌面路径）
REM
REM 行为：
REM   - 检查 Python >= 3.10
REM   - python -m pip install -e .
REM   - 执行 boss-hr --help 验证
REM   - 安装失败时返回非零退出码
REM
REM 不：
REM   - 启动 Edge
REM   - 连接 BOSS
REM   - 创建真实输出目录
REM   - 修改用户业务数据

setlocal ENABLEDELAYEDEXPANSION

REM 切到脚本所在目录
pushd "%~dp0"

REM 1. 检查 Python
where python >nul 2>nul
if errorlevel 1 (
    echo [install-windows] ERROR: python not found in PATH.
    popd
    exit /b 1
)

REM 2. 检查 Python 版本 >= 3.10
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VERSION=%%v
echo [install-windows] Detected Python %PY_VERSION%

REM 解析 major.minor
for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if %PY_MAJOR% LSS 3 (
    echo [install-windows] ERROR: Python >= 3.10 required, got %PY_VERSION%.
    popd
    exit /b 1
)
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo [install-windows] ERROR: Python >= 3.10 required, got %PY_VERSION%.
    popd
    exit /b 1
)

REM 3. editable install
echo [install-windows] Running: python -m pip install -e .
python -m pip install -e .
if errorlevel 1 (
    echo [install-windows] ERROR: pip install failed.
    popd
    exit /b 1
)

REM 4. 验证 boss-hr --help
echo [install-windows] Verifying: boss-hr --help
where boss-hr >nul 2>nul
if errorlevel 1 (
    echo [install-windows] WARN: boss-hr not in PATH after install.
    echo [install-windows] Try: python -m boss_hr --help
    python -m boss_hr --help
    if errorlevel 1 (
        echo [install-windows] ERROR: boss-hr verification failed.
        popd
        exit /b 1
    )
) else (
    boss-hr --help
    if errorlevel 1 (
        echo [install-windows] ERROR: boss-hr --help returned non-zero.
        popd
        exit /b 1
    )
)

echo.
echo [install-windows] OK. Run 'boss-hr --help' to confirm.
echo [install-windows] Source must remain at: %CD%
echo [install-windows] If you move the source directory, run this script again.

popd
endlocal
exit /b 0