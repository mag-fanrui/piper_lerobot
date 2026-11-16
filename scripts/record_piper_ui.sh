#!/usr/bin/env bash
# 带网页按钮的 Piper 采集：Rerun 保持打开，浏览器点按钮切换 episode。
#
#   bash scripts/record_piper_ui.sh
#   REPO_ID=me/piper_pick_red_block EPISODES=50 bash scripts/record_piper_ui.sh
#   UI_PORT=8099 UI_HOST=0.0.0.0 bash scripts/record_piper_ui.sh   # 允许局域网访问面板
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_DIR="$ROOT/piper_linkage_plugin"

REPO_ID="${REPO_ID:-myuser/piper_pick_blue_red_basket}"
TASK="${TASK:-Pick up the blue block and put it in the red basket.}"
EPISODES="${EPISODES:-50}"
EPISODE_TIME_S="${EPISODE_TIME_S:-30}"
RESET_TIME_S="${RESET_TIME_S:-30}"
TOP_CAM="${TOP_CAM:-/dev/video10}"
WRIST_CAM="${WRIST_CAM:-/dev/video4}"
STATE_DELAY="${STATE_DELAY:-4}"
CAN_NAME="${CAN_NAME:-can_follower}"
UI_PORT="${UI_PORT:-8099}"
UI_HOST="${UI_HOST:-127.0.0.1}"
RESUME="${RESUME:-false}"

cd "$PIPER_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$PLUGIN_DIR:${PYTHONPATH:-}"


# 数据集保存位置（默认 Disk1；可用 HF_LEROBOT_HOME 覆盖）
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-/media/robot204/Disk1/lerobot_data}"
mkdir -p "$HF_LEROBOT_HOME"
DATA_ROOT="$HF_LEROBOT_HOME"

if [ "${RESUME}" != "true" ] && [ -d "$DATA_ROOT/$REPO_ID" ]; then
  echo "错误：数据集已存在: $DATA_ROOT/$REPO_ID" >&2
  echo "  1) 换一个 REPO_ID（推荐，例如 REPO_ID=myuser/piper_pick_blue_block）" >&2
  echo "  2) 或者 RESUME=true 往这个数据集追加（任务/指令必须和原来一致）" >&2
  echo "  3) 或者先手动删掉该目录" >&2
  exit 1
fi

echo "=================================================="
echo " 数据目录: $HF_LEROBOT_HOME"
echo " 控制面板: http://127.0.0.1:$UI_PORT （或 $UI_HOST:$UI_PORT）"
echo " 完成本条 -> 复位 -> 开始下一条；等终端出现 Recording episode N 再动"
echo " 起点位姿: home2（另开终端: python tools/piper_pose.py check home2）"
echo "=================================================="

UI_HOST="$UI_HOST" UI_PORT="$UI_PORT" UI_REPO_ID="$REPO_ID" UI_REPO_ROOT="$DATA_ROOT" python "$ROOT/tools/piper_record_ui.py" \
  --robot.type=piper_linkage \
  --robot.can_name="$CAN_NAME" \
  --robot.state_delay_frames="$STATE_DELAY" \
  --robot.cameras="{
      top:   {type: opencv, index_or_path: $TOP_CAM,  width: 640, height: 480, fps: 30, warmup_s: 3},
      wrist: {type: opencv, index_or_path: $WRIST_CAM, width: 640, height: 480, fps: 30, warmup_s: 3}
    }" \
  --teleop.type=piper_linkage_leader \
  --teleop.can_name="$CAN_NAME" \
  --dataset.repo_id="$REPO_ID" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.fps=30 \
  --dataset.push_to_hub=false \
  --resume="$RESUME" \
  --display_data="${DISPLAY_DATA:-true}" \
  --play_sounds="${PLAY_SOUNDS:-false}"
