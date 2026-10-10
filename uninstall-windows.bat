@echo off
REM uninstall-windows.bat — uninstall boss-hr-agent-toolkit (editable mode)
REM
REM 行为：
REM   - python -m pip uninstall -y boss-hr-agent-toolkit
REM
REM 不：
REM   - 删除源码目录
REM   - 删除 boss-hr-output 或任何业务数据
REM   - 删除 Edge profile / 浏览器数据
REM   - 删除用户简历、评分、报告
REM
REM 如果你想删除整个工具包（包括源码），直接 `rmdir /s /q` 项目根目录即可。

setlocal ENABLEDELAYEDEXPANSION

where python >nul 2>nul
if errorlevel 1 (
    echo [uninstall-windows] ERROR: python not found in PATH.
    exit /b 1
)

echo [uninstall-windows] Running: python -m pip uninstall -y boss-hr-agent-toolkit
python -m pip uninstall -y boss-hr-agent-toolkit
if errorlevel 1 (
    echo [uninstall-windows] ERROR: pip uninstall failed.
    exit /b 1
)

echo.
echo [uninstall-windows] OK. editable install removed.
echo [uninstall-windows] Source code, boss-hr-output/, Edge profile: NOT touched.
echo [uninstall-windows] To fully remove the toolkit, delete the project directory manually.

endlocal
exit /b 0