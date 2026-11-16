#!/usr/bin/env bash
# SmolVLA 环境安装（lerobot 0.6.1 + torch cu130），在项目根目录执行：
#   bash scripts/setup_smolvla_env.sh
# 幂等：venv 已存在时复用，只补装依赖。
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
MODEL_DIR="$ROOT/models/smolvla_base"

# 缓存放项目内，避免和 ~/.cache/huggingface 里已有的权重重复下载
export HF_HOME="${HF_HOME:-$ROOT/.cache/hf}"

echo "== 项目目录: $ROOT"

# 1) Python 3.12（lerobot 0.6.1 要求 >=3.12，且 3.14 目前没有稳定的 torch 轮子）
if [ ! -x .venv/bin/python ]; then
  echo "== 创建 venv (python 3.12)"
  uv venv --python 3.12 .venv
fi

# 2) 依赖。torch/torchvision 已装的话 uv 不会动它们。
echo "== 安装 lerobot[smolvla,dataset,hardware,feetech,intelrealsense]"
uv pip install --python .venv/bin/python \
  "lerobot[smolvla,dataset,hardware,feetech,intelrealsense]==0.6.1"

# 3) 自检
.venv/bin/python - <<'EOF'
import torch, lerobot
print(f"lerobot {lerobot.__version__} | torch {torch.__version__} | cuda {torch.cuda.is_available()} x{torch.cuda.device_count()}")
EOF

# 4) 权重（865MB）+ SmolVLA 的 VLM 底座（首次加载会从 Hub 拉，离线部署需预下载）
if [ ! -f "$MODEL_DIR/model.safetensors" ]; then
  echo "== 下载 smolvla_base -> models/smolvla_base"
  .venv/bin/hf download lerobot/smolvla_base --local-dir models/smolvla_base
fi
echo "== 预下载 SmolVLM2-500M-Video-Instruct（走 HF 缓存）"
.venv/bin/hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct >/dev/null

# 5) 冒烟测试
echo "== 冒烟测试"
.venv/bin/python tools/smolvla_smoke_test.py --model models/smolvla_base --device cuda
