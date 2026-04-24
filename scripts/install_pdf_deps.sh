#!/bin/bash
# PDF生成依赖安装脚本

echo "正在安装PDF生成依赖..."

# 安装Python依赖
pip install -r requirements-pdf.txt

# 安装Playwright浏览器
echo "正在安装Playwright Chromium浏览器..."
playwright install chromium

echo "✅ PDF生成依赖安装完成！"
