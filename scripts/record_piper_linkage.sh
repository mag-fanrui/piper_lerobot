#!/usr/bin/env bash
# 单总线主从联动拓扑下采集数据：主臂+从臂共用一个 USB-CAN，从臂由固件联动跟随。
# 本脚本只读 CAN（不发使能/回零/运动指令），主臂可以放心拖动。
#
# 用法：
#   bash scripts/record_piper_linkage.sh
#   REPO_ID=me/piper_eraser EPISODES=2 bash scripts/record_piper_linkage.sh
#   TOP_CAM=/dev/video10 WRIST_CAM=/dev/video4 bash scripts/record_piper_linkage.sh
#   DISPLAY_DATA=false bash scripts/record_piper_linkage.sh   # 无显示器/远程时关掉 Rerun 窗口
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)/piper_linkage_plugin"

REPO_ID="${REPO_ID:-myuser/piper_pick_blue_red_basket}"
TASK="${TASK:-Pick up the blue block and put it in the red basket.}"
EPISODES="${EPISODES:-50}"
EPISODE_TIME_S="${EPISODE_TIME_S:-30}"
RESET_TIME_S="${RESET_TIME_S:-30}"
TOP_CAM="${TOP_CAM:-/dev/video10}"
WRIST_CAM="${WRIST_CAM:-/dev/video4}"
STATE_DELAY="${STATE_DELAY:-4}"
CAN_NAME="${CAN_NAME:-can_follower}"
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


python - <<'EOF'
import lerobot_robot_piper_linkage, lerobot_teleoperator_piper_linkage
print("piper_linkage plugin loaded: --robot.type=piper_linkage --teleop.type=piper_linkage_leader")
EOF

lerobot-record \
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
