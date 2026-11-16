#!/usr/bin/env python
"""独立的位姿偏差监控页面：实时显示当前 Piper 关节角与某个已保存位姿（默认 home2）的偏差。

只读 CAN，不发运动指令。

    .venv/bin/python tools/pose_monitor.py            # 默认 home2，端口 8100
    .venv/bin/python tools/pose_monitor.py --name home2 --port 8100 --tolerance 0.05

浏览器打开 http://127.0.0.1:8100 ，采集时把它放在副屏，对齐到绿色 OK 再开始录。
"""

from __future__ import annotations

import argparse
import http.server
import json
import threading
import time
import traceback
from pathlib import Path

POSES_PATH = Path("/media/robot204/Disk1/Projects/lerobot/configs/piper_poses.json")
JOINT_KEYS = [f"joint_{i}.pos" for i in range(1, 7)] + ["gripper.pos"]
JOINT_LABELS = [f"j{i}" for i in range(1, 7)] + ["grip"]

STATE_LOCK = threading.Lock()
STATE: dict = {
    "ready": False,
    "error": "",
    "name": "home2",
    "tolerance": 0.05,
    "target": None,
    "current": None,
    "deltas": None,
    "max_abs": None,
    "updated": 0.0,
}

HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piper 位姿对齐</title>
<style>
  :root { --ok:#16a34a; --warn:#d97706; --bad:#b91c1c; }
  body { font-family: system-ui, sans-serif; background:#0f1115; color:#e5e7eb; margin:0; padding:22px; }
  h1 { font-size:16px; color:#9ca3af; font-weight:600; margin:0 0 14px; }
  #banner { font-size:34px; font-weight:800; text-align:center; padding:30px 12px; border-radius:16px;
            background:#374151; transition:background .15s; }
  #banner.ok { background:var(--ok); }
  #banner.warn { background:var(--warn); }
  #banner.bad { background:var(--bad); }
  #sub { text-align:center; color:#9ca3af; font-size:15px; margin:10px 0 18px; }
  .row { display:grid; grid-template-columns:52px 1fr 110px; gap:10px; align-items:center;
         padding:7px 0; border-bottom:1px solid #1f2937; font-variant-numeric:tabular-nums; }
  .bar { height:10px; background:#1f2937; border-radius:5px; position:relative; overflow:hidden; }
  .bar > i { position:absolute; top:0; bottom:0; left:50%; background:#3b82f6; border-radius:5px; }
  .val { text-align:right; color:#9ca3af; font-size:14px; }
  .label { color:#6b7280; }
  .foot { margin-top:16px; color:#6b7280; font-size:13px; line-height:1.7; }
  #err { color:#fca5a5; margin-top:10px; font-size:13px; white-space:pre-wrap; }
</style>
</head>
<body>
  <h1>Piper 位姿对齐 · <span id="name">home2</span></h1>
  <div id="banner">等待 CAN…</div>
  <div id="sub">—</div>
  <div id="rows"></div>
  <div id="err"></div>
  <div class="foot">
    绿色 = 所有关节偏差 ≤ 容差，可以开始录下一条。<br>
    黄色 = 接近；红色 = 偏离较大。停止录制/开始下一条前对齐到位。
  </div>
<script>
const LABELS = ["j1","j2","j3","j4","j5","j6","grip"];
let rowsBuilt = false;
function buildRows() {
  const box = document.getElementById('rows');
  box.innerHTML = LABELS.map(l => `
    <div class="row">
      <div class="label">${l}</div>
      <div class="bar"><i id="bar_${l}"></i></div>
      <div class="val" id="val_${l}">—</div>
    </div>`).join('');
  rowsBuilt = true;
}
async function refresh() {
  try {
    const s = await (await fetch('/status')).json();
    const banner = document.getElementById('banner');
    if (!s.ready) {
      banner.className = ''; banner.textContent = '等待 CAN…';
      document.getElementById('sub').textContent = s.error || '';
      return;
    }
    document.getElementById('name').textContent = s.name;
    if (!rowsBuilt) buildRows();
    const m = s.max_abs;
    const tol = s.tolerance;
    let cls = 'ok', text = 'OK — 已对齐';
    if (m > tol * 2) { cls = 'bad'; text = '偏离较大'; }
    else if (m > tol) { cls = 'warn'; text = '接近，继续对齐'; }
    banner.className = cls;
    banner.textContent = text;
    document.getElementById('sub').textContent =
      '最大偏差 ' + m.toFixed(3) + ' rad (' + (m*180/Math.PI).toFixed(1) + '°)   容差 ' + tol.toFixed(3) + ' rad';

    const maxScale = 0.5; // rad，对应满格
    LABELS.forEach((l, i) => {
      const d = s.deltas[i];
      const pct = Math.min(Math.abs(d) / maxScale, 1) * 50;
      const el = document.getElementById('bar_' + l);
      el.style.width = pct + '%';
      el.style.left = d >= 0 ? '50%' : (50 - pct) + '%';
      el.style.background = Math.abs(d) <= tol ? '#22c55e' : (Math.abs(d) <= tol*2 ? '#f59e0b' : '#ef4444');
      document.getElementById('val_' + l).textContent = d.toFixed(3);
    });
    document.getElementById('err').textContent = s.error || '';
  } catch (e) {
    document.getElementById('banner').className = '';
    document.getElementById('banner').textContent = '监控服务未就绪';
  }
}
setInterval(refresh, 200); refresh();
</script>
</body>
</html>
"""


def read_pose(bus) -> dict[str, float]:
    from lerobot.motors.piper.piper import action_pos_dict_from_piper_read

    return action_pos_dict_from_piper_read(bus.read())


def reader_loop(name: str, target: dict[str, float], hz: float) -> None:
    while True:
        try:
            from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig

            motors = {f"joint_{i}": (i, "agilex_piper") for i in range(1, 7)}
            motors["gripper"] = (7, "agilex_piper")
            bus = PiperMotorsBus(PiperMotorsBusConfig("can_follower", motors))
            time.sleep(0.3)
            with STATE_LOCK:
                STATE["ready"] = True
                STATE["error"] = ""
            while True:
                pose = read_pose(bus)
                deltas = [pose[k] - target[k] for k in JOINT_KEYS]
                max_abs = max(abs(d) for d, k in zip(deltas, JOINT_KEYS) if k != "gripper.pos")
                with STATE_LOCK:
                    STATE["current"] = [pose[k] for k in JOINT_KEYS]
                    STATE["deltas"] = deltas
                    STATE["max_abs"] = max_abs
                    STATE["updated"] = time.time()
                time.sleep(1.0 / hz)
        except Exception:
            with STATE_LOCK:
                STATE["ready"] = False
                STATE["error"] = traceback.format_exc(limit=2)
            time.sleep(2.0)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/status"):
            with STATE_LOCK:
                payload = {k: v for k, v in STATE.items()}
            self._reply(200, json.dumps(payload).encode(), "application/json")
        else:
            self._reply(200, HTML.encode(), "text/html; charset=utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="home2")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--hz", type=float, default=5.0)
    args = ap.parse_args()

    poses = json.loads(POSES_PATH.read_text()) if POSES_PATH.is_file() else {}
    if args.name not in poses:
        raise SystemExit(f"没有保存过位姿 {args.name!r}，先跑 tools/piper_pose.py save {args.name}")
    target = poses[args.name]

    with STATE_LOCK:
        STATE["name"] = args.name
        STATE["tolerance"] = args.tolerance
        STATE["target"] = [target[k] for k in JOINT_KEYS]

    threading.Thread(target=reader_loop, args=(args.name, target, args.hz), daemon=True).start()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[pose] 监控页面: http://{args.host}:{args.port}  位姿={args.name} 容差={args.tolerance} rad", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
