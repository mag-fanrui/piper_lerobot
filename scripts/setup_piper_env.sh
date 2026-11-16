#!/usr/bin/env bash
# 为 piper_lerobot（lerobot 0.4.2 fork）创建独立的 Python 3.10 环境。
# 用法：bash scripts/setup_piper_env.sh [piper_lerobot 路径]
# 默认路径：/media/robot204/Disk1/Projects/piper_lerobot
set -euo pipefail

PIPER_DIR="${1:-${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}}"
if [ ! -d "$PIPER_DIR/lerobot" ] && [ ! -d "$PIPER_DIR/src/lerobot" ]; then
  echo "找不到 piper_lerobot：$PIPER_DIR" >&2
  exit 1
fi
cd "$PIPER_DIR"

export UV_CACHE_DIR="${UV_CACHE_DIR:-$PIPER_DIR/.cache/uv}"
export HF_HOME="${HF_HOME:-/media/robot204/Disk1/Projects/lerobot/.cache/hf}"

# 1) Python 3.10（0.4.2 要求 torch<2.8 / transformers<5，不能用本目录的 3.12 venv）
if [ ! -x .venv/bin/python ]; then
  echo "== 创建 venv (python 3.10)"
  uv venv --python 3.10 .venv
fi

# 2) GPU 版 torch（单独装，避免解析到不匹配的 CUDA 版本）
if ! .venv/bin/python -c "import torch" >/dev/null 2>&1; then
  echo "== 安装 torch 2.7.1 + torchvision (cu126)"
  uv pip install --python .venv/bin/python torch==2.7.1 torchvision==0.22.1 \
    --index-url https://download.pytorch.org/whl/cu126
fi

# 3) 以 editable 方式安装 piper_lerobot（含 Piper SDK 与 SmolVLA 依赖）
echo "== 安装 piper_lerobot[piper,smolvla]"
uv pip install --python .venv/bin/python -e ".[piper,smolvla]"

# 4) 自检（不碰硬件）
.venv/bin/python - <<'EOF'
import lerobot, piper_sdk, torch
print(f"lerobot {lerobot.__version__} | torch {torch.__version__} | cuda {torch.cuda.is_available()} x{torch.cuda.device_count()}")
from lerobot.robots.piper_follower.piper_follower import PIPERFollower  # noqa: F401
from lerobot.teleoperators.piper_leader.piper_leader import PIPERLeader  # noqa: F401
print("piper_follower / piper_leader 导入正常")
EOF

echo
echo "完成。CAN 名称如果是 can0，先改名："
echo "  sudo ip link set can0 down && sudo ip link set can0 name can_follower && sudo ip link set can_follower type can bitrate 1000000 up"
