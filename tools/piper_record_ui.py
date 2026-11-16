#!/usr/bin/env python
"""给 lerobot-record 加一个网页控制面板（按钮驱动 episode 切换，带阶段反馈）。

Rerun 窗口保持打开，操作者在浏览器里操作：

    [完成本条]   只在「录制中」可用 -> 结束当前 episode
    [开始下一条] 只在「复位中」可用 -> 结束复位，开始下一条
    [重录本条]   录制中/复位中可用  -> 丢弃当前条
    [停止录制]   任何阶段可用       -> 保存并退出

页面顶部大字显示当前阶段（录制中 / 复位中 / 保存中 / 完成），
每次切到「录制中」会闪一下并响一声，提示可以开始动作了。

用法（其余参数原样传给 lerobot-record）：

    UI_PORT=8099 python tools/piper_record_ui.py \
      --robot.type=piper_linkage ... --teleop.type=piper_linkage_leader ...

浏览器打开 http://127.0.0.1:8099 。想从别的机器点，用 UI_HOST=0.0.0.0。
键盘方向键仍然可用（原监听保留）。
"""

from __future__ import annotations

import http.server
import json
import os
import threading
import time
from pathlib import Path

import lerobot.scripts.lerobot_record as record_module

EVENTS: dict = {}
READY = False
PHASE = "not_ready"  # not_ready | recording | reset | saving | done
PHASE_TS = 0.0
LOCK = threading.Lock()
HISTORY: list[tuple[float, str]] = []

PHASE_TEXT = {
    "not_ready": "未就绪（等待录制器启动）",
    "recording": "● 录制中 —— 可以开始动作",
    "reset": "◼ 复位中 —— 摆好物体后点「开始下一条」",
    "saving": "⏳ 保存中（编码视频，稍等）",
    "done": "✔ 已完成",
}

ROOT_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piper 采集控制台</title>
<style>
  :root { --green:#16a34a; --amber:#d97706; --blue:#2563eb; --gray:#4b5563; }
  body { font-family: system-ui, sans-serif; background:#0f1115; color:#e5e7eb; margin:0; padding:20px; }
  h1 { font-size:18px; font-weight:600; color:#9ca3af; margin:0 0 12px; }
  #banner { font-size:26px; font-weight:700; padding:22px 16px; border-radius:14px;
            background:var(--gray); text-align:center; transition:background .2s; }
  #banner.recording { background:var(--green); animation:pulse 1.2s ease-in-out infinite; }
  #banner.reset { background:var(--amber); }
  #banner.saving { background:var(--blue); }
  #banner.done { background:var(--gray); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.72} }
  .stats { margin:12px 0 16px; font-size:14px; color:#9ca3af; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; max-width:680px; }
  button { font-size:20px; padding:28px 10px; border-radius:14px; border:0; cursor:pointer;
           color:#fff; font-weight:600; }
  button:disabled { background:#374151 !important; color:#6b7280; cursor:not-allowed; }
  #finish { background:var(--green); }
  #next { background:var(--amber); }
  #redo { background:#7c3aed; }
  #stop { background:#b91c1c; }
  button:not(:disabled):active { transform:scale(.98); }
  #last { color:#e5e7eb; }
  .hint { margin-top:14px; font-size:13px; color:#6b7280; line-height:1.6; }
</style>
</head>
<body>
  <h1>Piper 采集控制台</h1>
  <div id="banner">未就绪</div>
  <div class="stats">已录 <b id="eps">-</b> 条 · 最近操作 <span id="last">无</span></div>
  <div class="grid">
    <button id="finish">完成本条</button>
    <button id="next">开始下一条</button>
    <button id="redo">重录本条</button>
    <button id="stop">停止录制</button>
  </div>
  <div class="hint">
    录制中只有「完成本条」可点；复位阶段只有「开始下一条」可点。<br>
    看到顶部变绿并听到提示音，说明已经开始录下一条了。
  </div>
<script>
let audioCtx = null;
let lastPhase = null;
function beep() {
  try {
    if (!audioCtx) return;
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = 880; g.gain.value = 0.12;
    o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.12);
  } catch (e) {}
}
function ensureAudio() {
  if (!audioCtx) { try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
}
function act(a) {
  ensureAudio();
  fetch('/' + a, {method:'POST'}).then(refresh);
}
document.getElementById('finish').onclick = () => act('finish');
document.getElementById('next').onclick = () => act('next');
document.getElementById('redo').onclick = () => act('redo');
document.getElementById('stop').onclick = () => act('stop');

function setDisabled(id, disabled) { document.getElementById(id).disabled = disabled; }

async function refresh() {
  try {
    const r = await fetch('/status');
    const s = await r.json();
    const banner = document.getElementById('banner');
    const phase = s.phase || 'not_ready';
    banner.className = phase;
    banner.textContent = s.phase_text;
    document.getElementById('eps').textContent = (s.episodes === null ? '-' : s.episodes);
    document.getElementById('last').textContent =
      (s.history.length ? s.history[s.history.length-1][1] : '无');

    setDisabled('finish', phase !== 'recording');
    setDisabled('next', phase !== 'reset');
    setDisabled('redo', !(phase === 'recording' || phase === 'reset'));
    setDisabled('stop', !(phase === 'recording' || phase === 'reset'));

    if (lastPhase !== phase && phase === 'recording' && lastPhase !== null) beep();
    lastPhase = phase;
  } catch (e) {
    const b = document.getElementById('banner');
    b.className = 'not_ready'; b.textContent = '控制服务未就绪';
  }
}
setInterval(refresh, 500); refresh();
</script>
</body>
</html>
"""


def _episode_count():
    repo = os.getenv("UI_REPO_ID")
    if not repo:
        return None
    root = os.getenv("UI_REPO_ROOT")
    if not root:
        hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache/huggingface"))
        root = str(hf_home / "lerobot")
    info = Path(root) / repo / "meta" / "info.json"
    try:
        return int(json.loads(info.read_text())["total_episodes"])
    except Exception:
        return None


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
            with LOCK:
                payload = {
                    "ready": READY,
                    "phase": PHASE,
                    "phase_text": PHASE_TEXT.get(PHASE, PHASE),
                    "episodes": _episode_count(),
                    "events": dict(EVENTS),
                    "history": [[time.strftime("%H:%M:%S", time.localtime(t)), a] for t, a in HISTORY[-10:]],
                }
            self._reply(200, json.dumps(payload).encode(), "application/json")
        else:
            self._reply(200, ROOT_HTML.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        action = self.path.strip("/")
        with LOCK:
            if not READY:
                self._reply(503, b"recorder not ready yet", "text/plain")
                return
            phase = PHASE
            if action == "finish":
                if phase != "recording":
                    self._reply(409, b"not recording", "text/plain")
                    return
                EVENTS["exit_early"] = True
            elif action == "next":
                if phase != "reset":
                    self._reply(409, b"not in reset phase", "text/plain")
                    return
                EVENTS["exit_early"] = True
            elif action == "redo":
                if phase not in ("recording", "reset"):
                    self._reply(409, b"not recording/reset", "text/plain")
                    return
                EVENTS["rerecord_episode"] = True
                EVENTS["exit_early"] = True
            elif action == "stop":
                EVENTS["stop_recording"] = True
                EVENTS["exit_early"] = True
            else:
                self._reply(404, b"unknown action", "text/plain")
                return
            HISTORY.append((time.time(), action))
        self._reply(200, b"ok", "text/plain")


def start_ui_server(host: str, port: int) -> None:
    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[ui] 控制面板: http://{host}:{port}", flush=True)


def main() -> None:
    host = os.getenv("UI_HOST", "127.0.0.1")
    port = int(os.getenv("UI_PORT", "8099"))
    start_ui_server(host, port)

    global PHASE, PHASE_TS

    def on_phase(phase: str) -> None:
        global PHASE, PHASE_TS
        with LOCK:
            PHASE = phase
            PHASE_TS = time.time()
        print(f"[ui] phase -> {phase}", flush=True)

    original_init = record_module.init_keyboard_listener

    def patched_init(*args, **kwargs):
        listener, events = original_init(*args, **kwargs)
        global EVENTS, READY
        with LOCK:
            EVENTS = events
            READY = True
        print("[ui] 已接管 episode 事件字典，按钮可用", flush=True)
        return listener, events

    record_module.init_keyboard_listener = patched_init
    if hasattr(record_module, "set_phase_callback"):
        record_module.set_phase_callback(on_phase)
    else:
        print(
            "[ui] 警告：当前 lerobot 没有阶段回调（piper_lerobot 未打补丁），"
            "按钮会一直不可用。",
            flush=True,
        )
    record_module.main()


if __name__ == "__main__":
    main()
