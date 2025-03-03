#!/bin/bash
# ============================================================================
# Bomana 打包脚本 (Linux/macOS)
# ============================================================================
#
# 使用说明：
# 1. 确保已安装 Python 3.7+
# 2. 确保已安装依赖: pip install -r requirements.txt
# 3. 运行此脚本: chmod +x build.sh && ./build.sh
#
# 输出文件将在 dist/ 目录下
# ============================================================================

set -e  # 遇到错误立即退出

echo "========================================"
echo "Bomana 打包脚本"
echo "========================================"
echo ""

# 检查 Python
echo "[1/5] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.7+"
    exit 1
fi
python3 --version
echo ""

# 检查依赖
echo "[2/5] 检查依赖..."
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "[警告] 未安装 PyInstaller，正在安装..."
    pip3 install pyinstaller
fi
echo "PyInstaller 已安装"
echo ""

# 清理旧文件
echo "[3/5] 清理旧的构建文件..."
rm -rf build dist Bomana.spec
echo "清理完成"
echo ""

# 打包
echo "[4/5] 开始打包..."
echo "这可能需要几分钟时间，请耐心等待..."
echo ""

pyinstaller --onefile \
            --windowed \
            --icon=app.ico \
            --name=Bomana \
            --add-data "app.png:." \
            --add-data "sponsor_wechat.png:." \
            Bomana.pyw

echo ""
echo "[5/5] 验证输出..."
if [ -f "dist/Bomana" ]; then
    echo "[成功] 打包完成！"
    echo ""
    echo "输出文件: dist/Bomana"
    echo ""
    ls -lh "dist/Bomana"
    echo ""
    echo "========================================"
    echo "打包成功！"
    echo "========================================"
    echo ""
    echo "你现在可以："
    echo "1. 运行 ./dist/Bomana 测试程序"
    echo "2. 将 dist/Bomana 分发给其他用户"
    echo ""
else
    echo "[错误] 未找到输出文件"
    exit 1
fi
