#!/usr/bin/env bash
# 把 USB-CAN 适配器命名成 can_follower 并以 1 Mbps 拉起（需要 sudo）。
# 用法：sudo bash scripts/can_follower_up.sh [当前接口名，默认 can0]
set -euo pipefail

CUR="${1:-can0}"

if ip link show can_follower >/dev/null 2>&1; then
  IF=can_follower
else
  echo "== $CUR -> can_follower"
  ip link set "$CUR" down
  ip link set "$CUR" name can_follower
  IF=can_follower
fi

# 先 down/up 清掉 BUS-OFF 状态；gs_usb 不支持 restart-ms，这里完全不用它
ip link set "$IF" down || true
ip link set "$IF" type can bitrate 1000000 || true
ip link set "$IF" up
echo "== 状态"
ip -details link show "$IF" | head -4

cat <<'EOF'

提示：重启后接口名会恢复成 can0。想固定的话加一个 systemd .link 文件：
  sudo tee /etc/systemd/network/10-can-follower.link <<'LINK'
[Match]
Driver=gs_usb

[Link]
Name=can_follower
LINK
  sudo systemctl restart systemd-udevd
EOF
