@echo off
REM QuickPythonIDE 一键打包脚本（生成 QuickPythonIDE.exe）
REM 界面外置，ui/ 不打包，发布时把 exe 与 ui/ 放在同一目录即可。
REM 首次使用前请先安装依赖： pip install -r requirements.txt pyinstaller

pyinstaller --onefile --windowed --name QuickPythonIDE --collect-all webview main.py

echo.
echo 打包完成，生成的 exe 在 dist\QuickPythonIDE.exe
echo 发布时把 QuickPythonIDE.exe 和 ui\ 文件夹放在同一目录即可。
pause
