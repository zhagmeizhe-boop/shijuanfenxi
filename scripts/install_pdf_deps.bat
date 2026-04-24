@echo off
REM PDF生成依赖安装脚本 (Windows)

echo 正在安装PDF生成依赖...

REM 安装Python依赖
pip install -r ..\apps\api\requirements-pdf.txt

REM 安装Playwright浏览器
echo 正在安装Playwright Chromium浏览器...
playwright install chromium

echo ✅ PDF生成依赖安装完成！
pause
