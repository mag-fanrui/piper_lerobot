#!/usr/bin/env bash
# 启动独立的位姿偏差监控页面（只读 CAN，可与采集同时运行）。
#
#   bash scripts/pose_monitor.sh                 # home2, 端口 8100
#   bash scripts/pose_monitor.sh --name home1 --port 8101 --tolerance 0.03
#   UI_HOST=0.0.0.0 bash scripts/pose_monitor.sh # 允许局域网访问
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PIPER_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate

# 兼容 --name/--port 透传；UI_HOST 环境变量控制监听地址
HOST_ARG=()
[ -n "${UI_HOST:-}" ] && HOST_ARG=(--host "$UI_HOST")
exec python "$ROOT/tools/pose_monitor.py" "${HOST_ARG[@]}" "$@"
