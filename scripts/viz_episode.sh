#!/usr/bin/env bash
# 回放一条已录好的 episode（自动激活 piper 的 venv，避免 rerun 不在 PATH 的问题）。
#
#   bash scripts/viz_episode.sh            # 默认 myuser/piper_pick_red_block 第 0 条
#   bash scripts/viz_episode.sh 1          # 第 1 条
#   REPO_ID=me/piper_xxx bash scripts/viz_episode.sh 2
#   SAVE=1 bash scripts/viz_episode.sh 0   # 不弹窗，导出 .rrd 到 /tmp/rrd
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
REPO_ID="${REPO_ID:-myuser/piper_pick_block_tray}"
EPISODE="${1:-0}"
ROOT="${ROOT:-${HF_LEROBOT_HOME:-/media/robot204/Disk1/lerobot_data}/$REPO_ID}"

cd "$PIPER_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate

if [ "${SAVE:-0}" = "1" ]; then
  out="${OUT_DIR:-/tmp/rrd}"
  mkdir -p "$out"
  lerobot-dataset-viz --repo-id="$REPO_ID" --root "$ROOT" --episode-index "$EPISODE" \
    --save 1 --output-dir "$out"
  echo "已导出: $out"
else
  lerobot-dataset-viz --repo-id="$REPO_ID" --root "$ROOT" --episode-index "$EPISODE"
fi
