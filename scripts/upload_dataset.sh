#!/usr/bin/env bash
# 把录制好的数据集同步到训练服务器。
#
#   SERVER=user@10.0.0.5 PORT=65002 DEST=/data/lerobot_data \
#     bash scripts/upload_dataset.sh
#
#   REPO=myuser/piper_pick_blue_block_clean LOCAL_ROOT=/media/robot204/Disk1/lerobot_data ...
set -euo pipefail

REPO="${REPO:-myuser/piper_pick_blue_red_basket_v2}"
LOCAL_ROOT="${LOCAL_ROOT:-/media/robot204/Disk1/lerobot_data}"
SERVER="${SERVER:?请设置 SERVER=user@host}"
DEST="${DEST:-/data/lerobot_data}"
PORT="${PORT:-}"
SSH_PORT_ARGS=()
RSYNC_SSH="ssh"
if [ -n "$PORT" ]; then
  SSH_PORT_ARGS=(-p "$PORT")
  RSYNC_SSH="ssh -p $PORT"
fi

SRC="$LOCAL_ROOT/$REPO"
[ -d "$SRC" ] || { echo "找不到本地数据集: $SRC" >&2; exit 1; }

PY="${PYTHON_BIN:-/media/robot204/Disk1/Projects/lerobot/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

echo "== 数据集: $REPO  ($(du -sh "$SRC" | cut -f1))"
"$PY" - "$SRC" <<'PYEOF' || true
import json, os, sys
root = sys.argv[1]
info = json.load(open(os.path.join(root, "meta", "info.json")))
print(f"   episodes={info['total_episodes']} frames={info['total_frames']} fps={info['fps']}")
try:
    import pandas as pd
    df = pd.read_parquet(os.path.join(root, "meta", "tasks.parquet"))
    print(f"   task={list(df.index)}")
except Exception:
    pass
PYEOF

echo "== 同步 $SRC -> $SERVER:$DEST/$REPO${PORT:+（SSH 端口 $PORT）}"
ssh "${SSH_PORT_ARGS[@]}" "$SERVER" "mkdir -p '$DEST/$(dirname "$REPO")'"
rsync -avP --partial --info=progress2 -e "$RSYNC_SSH" \
  "$SRC" "$SERVER:$DEST/$(dirname "$REPO")/"

echo "== 远端校验"
ssh "${SSH_PORT_ARGS[@]}" "$SERVER" "du -sh '$DEST/$REPO'; ls '$DEST/$REPO/meta'; python3 -c \"
import json,sys
i=json.load(open('$DEST/$REPO/meta/info.json'))
print('episodes', i['total_episodes'], 'frames', i['total_frames'], 'fps', i['fps'])
\" 2>/dev/null || true"

echo
echo "完成。服务器上训练时用："
echo "  --dataset.repo_id=$REPO --dataset.root=$DEST/$REPO"
