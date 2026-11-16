#!/usr/bin/env bash
# 用 lerobot-replay 在真机上重放已采集数据集的某一条 episode。
#
#   bash scripts/replay_piper.sh 0            # 干跑：只走流程，不写 CAN（机械臂不动）
#   DRY_RUN=false bash scripts/replay_piper.sh 0
#   REPO=myuser/piper_pick_blue_block_clean EPISODE=3 ...
#
# 前提：AgileX app 里退出主从联动、从臂单臂可控；工作区清空、急停在手边。
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
REPO="${REPO:-myuser/piper_pick_block_tray}"
LOCAL_ROOT="${LOCAL_ROOT:-/media/robot204/Disk1/lerobot_data}"
EPISODE="${EPISODE:-${1:-0}}"
DRY_RUN="${DRY_RUN:-true}"
MAX_STEP_RAD="${MAX_STEP_RAD:-0.1}"
STOP_AT="${STOP_AT:-hold}"
HOME_POSITION="${HOME_POSITION:-[0,0,0,0,0,0,0]}"

ROOT="${ROOT:-$LOCAL_ROOT/$REPO}"

cd "$PIPER_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-$LOCAL_ROOT}"

[ -d "$ROOT" ] || { echo "找不到数据集: $ROOT" >&2; exit 1; }

echo "============================================================"
echo " 数据集: $REPO"
echo " episode: $EPISODE   fps: 数据集 fps"
echo " 动作写入: $([ "$DRY_RUN" = "true" ] && echo '关闭（只走流程，不动）' || echo '开启！（机械臂会动）')"
echo " 每步限幅: $MAX_STEP_RAD rad"
echo " 退出: $STOP_AT"
echo "============================================================"
if [ "$DRY_RUN" != "true" ]; then
  read -r -p "确认工作区无人、急停在手边，输入 yes 继续: " ans
  [ "$ans" = "yes" ] || { echo "已取消"; exit 1; }
fi

lerobot-replay \
  --robot.type=piper_follower \
  --robot.cameras='{}' \
  --robot.teleop_joint_alpha=1.0 \
  --robot.teleop_gripper_alpha=1.0 \
  --robot.deployment.start_from=current \
  --robot.deployment.stop_at="$STOP_AT" \
  --robot.deployment.home_position="$HOME_POSITION" \
  --robot.deployment.max_joint_step_rad="$MAX_STEP_RAD" \
  --robot.deployment.disable_action_write="$DRY_RUN" \
  --robot.deployment.keep_enabled_on_disconnect=true \
  --dataset.repo_id="$REPO" \
  --dataset.root="$ROOT" \
  --dataset.episode="$EPISODE" \
  --play_sounds=false
