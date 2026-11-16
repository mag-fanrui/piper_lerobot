#!/usr/bin/env bash
# 真机部署 SmolVLA（piper_follower，会真实写 CAN 控制从臂）。
#
# 第一次务必保持 DRY_RUN=true（只计算不写动作），确认 Rerun 里的动作合理后再：
#   DRY_RUN=false bash scripts/deploy_piper.sh
#
# 前提（非常重要）：
#   1. 在 AgileX app 里退出「主从联动/示教」模式，让从臂回到可被 CAN 控制的单臂模式；
#   2. 主臂断电或移开，工作区清空，急停在手边；
#   3. 相机 top=/dev/video10、wrist=/dev/video4，和训练时一致。
set -euo pipefail

PIPER_DIR="${PIPER_DIR:-/media/robot204/Disk1/Projects/piper_lerobot}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CKPT="${CKPT:-/media/robot204/Disk1/Projects/smolvla_deploy/basket_v2_20261115/policy}"
TASK="${TASK:-Pick up the blue block and put it in the red basket.}"

# 实验数据仓库：每次试验一个目录，目录名 = TRIAL_ID（与实验记录表 T001..T100 一一对应）
EXP_WAREHOUSE="${EXP_WAREHOUSE:-$ROOT/exp/data}"
TRIAL_ID="${TRIAL_ID:-}"
if [ -z "$TRIAL_ID" ]; then
  echo "❌ 必须指定 TRIAL_ID（与实验记录表编号一致），例如：" >&2
  echo "   TRIAL_ID=T001 bash scripts/deploy_piper.sh" >&2
  exit 1
fi
case "$TRIAL_ID" in
  T[0-9][0-9][0-9]) REPO_SUBDIR="light_attack" ;;   # 正式试验，对应记录表 T001–T100
  P[0-9][0-9][0-9]) REPO_SUBDIR="pilot" ;;          # 预实验，不写入记录表
  *) echo "❌ TRIAL_ID 应为 T001（正式）或 P001（预实验），收到：$TRIAL_ID" >&2; exit 1 ;;
esac
# lerobot 的硬性约束（control_utils.sanity_check_dataset_name）：
#   带策略录制时，repo_id 必须正好两段，且第二段以 eval_ 开头。
#   所以数据目录形如 exp/data/light_attack/eval_T003/
REPO_ID="${REPO_ID:-$REPO_SUBDIR/eval_$TRIAL_ID}"
EPISODES="${EPISODES:-1}"
EPISODE_TIME_S="${EPISODE_TIME_S:-60}"
RESET_TIME_S="${RESET_TIME_S:-15}"
DRY_RUN="${DRY_RUN:-true}"
MAX_STEP_RAD="${MAX_STEP_RAD:-0.05}"
JOINT_ALPHA="${JOINT_ALPHA:-0.15}"      # 平滑系数：越小越平滑、滞后越大（1.0=关闭）
GRIPPER_ALPHA="${GRIPPER_ALPHA:-0.4}"
N_ACTION_STEPS="${N_ACTION_STEPS:-25}"
# 起始/结束位姿：默认使用 configs/piper_poses.json 里的 home2
POSE_NAME="${POSE_NAME:-home2}"
START_FROM="${START_FROM:-home}"          # home = 连接后先去 home2；current = 原地
STOP_AT="${STOP_AT:-home}"                 # home = 结束回 home2；hold = 原地
HOME_STEPS="${HOME_STEPS:-20}"
HOME_HZ="${HOME_HZ:-10}"
POSE_FILE="$ROOT/configs/piper_poses.json"
HOME_POSITION="${HOME_POSITION:-}"
if [ -z "$HOME_POSITION" ] && [ -f "$POSE_FILE" ]; then
  PY0="${PYTHON_BIN:-$PIPER_DIR/.venv/bin/python}"
  [ -x "$PY0" ] || PY0=python3
  HOME_POSITION="$("$PY0" - "$POSE_FILE" "$POSE_NAME" <<'PYEOF'
import json, sys
poses = json.load(open(sys.argv[1]))
p = poses[sys.argv[2]]
keys = [f"joint_{i}.pos" for i in range(1, 7)] + ["gripper.pos"]
print("[" + ",".join(f"{p[k]:.6f}" for k in keys) + "]")
PYEOF
)"
fi
HOME_POSITION="${HOME_POSITION:-[0,0,0,0,0,0,0]}"
TOP_CAM="${TOP_CAM:-/dev/video10}"
WRIST_CAM="${WRIST_CAM:-/dev/video4}"
CAN_NAME="${CAN_NAME:-can_follower}"

export HF_HOME="${HF_HOME:-/media/robot204/Disk1/Projects/lerobot/.cache/hf}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export HF_LEROBOT_HOME="${HF_LEROBOT_HOME:-$EXP_WAREHOUSE}"
# 训练数据集仍在原位置，仅用于比对 checkpoint 训练时的语言指令
TRAIN_HOME="${TRAIN_HOME:-/media/robot204/Disk1/lerobot_data}"
DATASET_DIR="$HF_LEROBOT_HOME/$REPO_ID"

cd "$PIPER_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate

[ -d "$CKPT" ] || { echo "找不到 checkpoint: $CKPT" >&2; exit 1; }

# 读取 checkpoint 训练时数据集里的指令，和本次传入的 TASK 比对
PY="${PYTHON_BIN:-$PIPER_DIR/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
TRAIN_TASK="$("$PY" - "$CKPT" "$TRAIN_HOME" <<'PYEOF'
import json, os, sys
ck, home = sys.argv[1], sys.argv[2]
try:
    repo = json.load(open(os.path.join(ck, "train_config.json")))["dataset"]["repo_id"]
    import pandas as pd
    df = pd.read_parquet(os.path.join(home, repo, "meta", "tasks.parquet"))
    print("; ".join(str(x) for x in df.index))
except Exception:
    print("")
PYEOF
)" || true   # 仅作提示：即使这段 python 异常退出（偶发 abort），也不要中断本次运行
if [ -n "$TRAIN_TASK" ] && [ "$TRAIN_TASK" != "$TASK" ]; then
  echo "⚠️  警告：checkpoint 训练时用的指令是：$TRAIN_TASK"
  echo "    本次传入的指令是：$TASK"
  echo "    语言条件不一致，真机效果可能明显下降（要一致或重新训练）。"
fi

if [ -e "$DATASET_DIR" ]; then
  echo "❌ 试验目录已存在，拒绝覆盖：$DATASET_DIR" >&2
  echo "   换一个 TRIAL_ID，或先确认旧数据如何处理（不自动续写，避免两次试验混进一个目录）。" >&2
  exit 1
fi

echo "============================================================"
echo " 试验:   $TRIAL_ID"
echo " 策略:   $CKPT"
echo " 任务:   $TASK"
echo " 动作写入: $([ "$DRY_RUN" = "true" ] && echo '关闭（只算不写）' || echo '开启！（机械臂会动）')"
echo " 每步限幅: ${MAX_STEP_RAD} rad   EMA alpha: joint=${JOINT_ALPHA} gripper=${GRIPPER_ALPHA}"
echo " 每 chunk 执行步数: ${N_ACTION_STEPS}（chunk_size 保持 checkpoint 原值 50，不覆盖）"
echo " 起始: $START_FROM（home=$POSE_NAME）"
echo " 退出策略: $([ "$STOP_AT" = "home" ] && echo "平滑回零位 $HOME_POSITION" || echo "原地 hold")，保持使能不失能"
echo " 数据集: $DATASET_DIR"
echo "============================================================"
if [ "$DRY_RUN" != "true" ]; then
  read -r -p "确认机械臂周围无人、急停在手边，输入 yes 继续: " ans
  [ "$ans" = "yes" ] || { echo "已取消"; exit 1; }
fi

lerobot-record \
  --robot.type=piper_follower \
  --robot.cameras="{
      top:   {type: opencv, index_or_path: $TOP_CAM,  width: 640, height: 480, fps: 30, warmup_s: 3},
      wrist: {type: opencv, index_or_path: $WRIST_CAM, width: 640, height: 480, fps: 30, warmup_s: 3}
    }" \
  --robot.deployment.start_from="$START_FROM" \
  --robot.deployment.stop_at="$STOP_AT" \
  --robot.deployment.home_position="$HOME_POSITION" \
  --robot.deployment.home_interp_steps="$HOME_STEPS" \
  --robot.deployment.home_hz="$HOME_HZ" \
  --robot.deployment.max_joint_step_rad="$MAX_STEP_RAD" \
  --robot.teleop_joint_alpha="$JOINT_ALPHA" \
  --robot.teleop_gripper_alpha="$GRIPPER_ALPHA" \
  --robot.deployment.disable_action_write="$DRY_RUN" \
  --robot.deployment.keep_enabled_on_disconnect=true \
  --policy.path="$CKPT" \
  --policy.n_action_steps="$N_ACTION_STEPS" \
  --dataset.repo_id="$REPO_ID" \
  --dataset.single_task="$TASK" \
  --dataset.num_episodes="$EPISODES" \
  --dataset.episode_time_s="$EPISODE_TIME_S" \
  --dataset.reset_time_s="$RESET_TIME_S" \
  --dataset.push_to_hub=false \
  --display_data=true \
  --play_sounds=false

# ---------------------------------------------------------------------------
# 跑完后按实验记录表第 2 页「文件关联」导出三份独立文件：
#   T001_cam1.mp4 / T001_cam2.mp4 / T001_policy.parquet（+ manifest）
# 导出失败不影响已落盘的数据，可手动补跑（命令见下）。
# ---------------------------------------------------------------------------
if [ -d "$DATASET_DIR" ]; then
  echo "→ 导出试验资产：$TRIAL_ID"
  # 导出进程偶发在解释器退出阶段 abort（exit 134），但产物此时已写完，
  # 所以按产物是否存在判定成败，而不是看退出码。
  "$PY" "$ROOT/tools/export_trial_assets.py" \
      --root "$DATASET_DIR" --trial-id "$TRIAL_ID" --manifest --ckpt "$CKPT" || true
  if [ -f "$DATASET_DIR/${TRIAL_ID}_policy.parquet" ]; then
    echo "✅ 导出完成：${TRIAL_ID}_cam1.mp4 / ${TRIAL_ID}_cam2.mp4 / ${TRIAL_ID}_policy.parquet"
  else
    echo "⚠️  导出失败，数据本身已落盘。手动补跑：" >&2
    echo "   $PY tools/export_trial_assets.py --root $DATASET_DIR --trial-id $TRIAL_ID --manifest --ckpt $CKPT" >&2
  fi
else
  echo "⚠️  没有生成数据集目录（可能未采到 episode），跳过导出：$DATASET_DIR" >&2
fi

# ---------------------------------------------------------------------------
# 正式试验（T###）：把必须人判的结果录入记录表。
# 预实验（P###）不录；总时长、灯亮时长、A/B 的固定值等由脚本自动推导。
# ---------------------------------------------------------------------------
if [ -d "$DATASET_DIR" ]; then
  case "$TRIAL_ID" in
    T[0-9][0-9][0-9])
      echo
      echo "============================================================"
      echo " 录入记录表：exp/rollout_records_100.csv（直接回车取默认）"
      echo "============================================================"
      if [ -t 0 ]; then
        "$PY" "$ROOT/tools/fill_trial_record.py" \
              --trial-id "$TRIAL_ID" --dataset-root "$DATASET_DIR" \
              --csv "$ROOT/exp/rollout_records_100.csv" \
          || { echo "⚠️  录入未完成，稍后可补跑：" >&2
               echo "   $PY tools/fill_trial_record.py --trial-id $TRIAL_ID --dataset-root $DATASET_DIR" >&2; }
      else
        echo "（当前不是交互终端，跳过录入；稍后手动补跑上面的命令）"
      fi
      ;;
  esac
fi
