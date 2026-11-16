#!/usr/bin/env bash
# 扫描 CAN 波特率：依次用 1M/500k/250k/125k 监听，看哪个能收到真实数据帧。
# 用法：sudo bash scripts/can_bitrate_scan.sh [接口名]
set -u

IF="${1:-can_follower}"
PY="${PYTHON_BIN:-/media/robot204/Disk1/Projects/piper_lerobot/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

if ! ip link show "$IF" >/dev/null 2>&1; then
  echo "接口 $IF 不存在，先运行 can_follower_up.sh" >&2
  exit 1
fi

for BR in 1000000 500000 250000 125000; do
  ip link set "$IF" down 2>/dev/null
  if ! ip link set "$IF" type can bitrate "$BR" 2>/dev/null; then
    echo "== $BR: 设置失败（接口可能不支持该速率）"
    continue
  fi
  ip link set "$IF" up
  sleep 0.3
  echo -n "== ${BR} bps: "
  "$PY" - "$IF" <<'PY'
import collections
import sys
import time

import can

bus = can.Bus(interface="socketcan", channel=sys.argv[1])
ids = collections.Counter()
errs = 0
t0 = time.time()
while time.time() - t0 < 2.0:
    msg = bus.recv(timeout=0.2)
    if msg is None:
        continue
    if msg.is_error_frame:
        errs += 1
    else:
        ids[msg.arbitration_id] += 1
print(f"data={sum(ids.values())} errors={errs} ids={ {hex(k): v for k, v in sorted(ids.items())[:4]} }")
bus.shutdown()
PY
done

# 恢复默认 1M 并拉起
ip link set "$IF" down 2>/dev/null
ip link set "$IF" type can bitrate 1000000 2>/dev/null || true
ip link set "$IF" up 2>/dev/null || true
echo "== 已恢复 1 Mbps"
ip -details link show "$IF" | sed -n 1,4p
