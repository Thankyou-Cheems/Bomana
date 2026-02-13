#!/bin/bash
# ============================================================================
# Bomana 打包脚本 (Linux/macOS)
# ============================================================================
#
# 使用说明：
# 1. 确保已安装 uv
# 2. 同步依赖: uv sync --extra build
# 3. 运行此脚本: chmod +x build.sh && ./build.sh [Enhanced|Standard|Lite]
#
# 输出文件将在 dist/ 目录下
# ============================================================================

set -e  # 遇到错误立即退出

echo "========================================"
echo "Bomana 打包脚本"
echo "========================================"
echo ""

# 检查 uv
echo "[1/6] 检查 uv 环境..."
if command -v uv &> /dev/null; then
    UV_CMD=(uv)
elif python3 -m uv --version >/dev/null 2>&1; then
    UV_CMD=(python3 -m uv)
else
    echo "[错误] 未找到 uv，请先安装 uv: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi
"${UV_CMD[@]}" --version
echo ""

# 检查依赖
echo "[2/6] 检查依赖..."
if ! "${UV_CMD[@]}" sync --extra build; then
    echo "[错误] 依赖同步失败"
    exit 1
fi
echo "依赖同步完成"
echo ""

# 解析版本类型
VARIANT="${1:-Enhanced}"
case "$VARIANT" in
  Enhanced|Standard|Lite) ;;
  *)
    echo "[错误] 版本类型无效: $VARIANT"
    echo "用法: ./build.sh [Enhanced|Standard|Lite]"
    exit 1
    ;;
esac
echo "[3/6] 构建版本: $VARIANT"
echo ""

# 根据版本注入编译开关（备份后修改 config.py）
echo "[4/6] 注入编译开关..."
CONFIG_FILE="bomana/config.py"
CONFIG_BAK="bomana/config.py.bak"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[错误] 未找到 $CONFIG_FILE"
    exit 1
fi
cp "$CONFIG_FILE" "$CONFIG_BAK"
trap 'if [ -f "$CONFIG_BAK" ]; then mv "$CONFIG_BAK" "$CONFIG_FILE"; fi' EXIT

if [ "$VARIANT" = "Enhanced" ]; then
    ENABLE_CCRP="True"
    ENABLE_ZONES="True"
    ENABLE_FUEL="True"
elif [ "$VARIANT" = "Standard" ]; then
    ENABLE_CCRP="False"
    ENABLE_ZONES="True"
    ENABLE_FUEL="True"
else
    ENABLE_CCRP="False"
    ENABLE_ZONES="False"
    ENABLE_FUEL="False"
fi
ENABLE_ADVANCED_SETTINGS="True"
ENABLE_AIRFIELDS="$ENABLE_ZONES"
ENABLE_CHECKLIST="$ENABLE_ZONES"
export ENABLE_CCRP ENABLE_ZONES ENABLE_AIRFIELDS ENABLE_FUEL ENABLE_CHECKLIST ENABLE_ADVANCED_SETTINGS

"${UV_CMD[@]}" run python - <<'PY'
from pathlib import Path
import os
import re

path = Path("bomana/config.py")
code = path.read_text(encoding="utf-8")
switches = {
    "ENABLE_CCRP": os.environ["ENABLE_CCRP"],
    "ENABLE_ZONES": os.environ["ENABLE_ZONES"],
    "ENABLE_AIRFIELDS": os.environ["ENABLE_AIRFIELDS"],
    "ENABLE_FUEL": os.environ["ENABLE_FUEL"],
    "ENABLE_CHECKLIST": os.environ["ENABLE_CHECKLIST"],
    "ENABLE_ADVANCED_SETTINGS": os.environ["ENABLE_ADVANCED_SETTINGS"],
}
for key, value in switches.items():
    code = re.sub(rf"(?m)^{key}\\s*=.*", f"{key} = {value}", code)
path.write_text(code, encoding="utf-8")
PY

# 清理旧文件
echo "[5/6] 清理旧的构建文件..."
rm -rf build dist Bomana.spec
echo "清理完成"
echo ""

# 打包
echo "[6/6] 开始打包..."
echo "这可能需要几分钟时间，请耐心等待..."
echo ""

EXEC_NAME="Bomana_${VARIANT}"
ADD_DATA_ARGS=(
  "--add-data" "app.png:."
  "--add-data" "sponsor_wechat.png:."
)
if [ "$VARIANT" = "Enhanced" ]; then
  if [ -f "ccrp_bomb_params.json" ]; then
    ADD_DATA_ARGS+=("--add-data" "ccrp_bomb_params.json:.")
  elif [ -f "ccrp_bomb_params.py" ]; then
    ADD_DATA_ARGS+=("--add-data" "ccrp_bomb_params.py:.")
  fi
fi

"${UV_CMD[@]}" run pyinstaller --onefile \
            --noconsole \
            --icon=app.ico \
            --name="$EXEC_NAME" \
            "${ADD_DATA_ARGS[@]}" \
            --hidden-import "pystray._win32" \
            --collect-submodules "PIL" \
            --clean Bomana.pyw

echo ""
echo "[验证] 检查输出..."
if [ -f "dist/$EXEC_NAME" ]; then
    echo "[成功] 打包完成！"
    echo ""
    echo "输出文件: dist/$EXEC_NAME"
    echo ""
    ls -lh "dist/$EXEC_NAME"
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
