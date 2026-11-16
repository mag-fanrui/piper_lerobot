#!/usr/bin/env python
"""包装 lerobot-record：在录制进程内额外监听 k/g，记录开灯/关灯时刻。

为什么不用改上游代码：`piper_lerobot` 不在本仓库里，跨进程用 pynput 抓键盘也不可靠。
这里在**录制同一个进程内**再起一个键盘监听（pynput 是全局被动监听，不影响原监听器），
然后把参数原样交给 `lerobot.scripts.lerobot_record.main`。

环境变量：
    LEROBOT_KEYLOG   记录文件路径（JSONL）。不设则不记录，行为与原 CLI 完全一致。

事件格式：``{"key": "start"|"k"|"g", "t": <perf_counter 秒>}``

- ``start``：第一帧写入的时刻，即 episode 的 t=0 锚点
- ``k`` / ``g``：操作员按下的开灯 / 关灯时刻

四者同进程同一时钟，所以 ``k - start``、``g - start`` 就是相对秒数。
"""

from __future__ import annotations

import json
import os
import sys
import time


def _log(path: str, key: str, t: float | None = None) -> None:
    try:
        with open(path, "a") as f:
            f.write(json.dumps({"key": key, "t": round(t if t is not None else time.perf_counter(), 3)}) + "\n")
    except Exception:
        pass


def main() -> None:
    log_path = os.environ.get("LEROBOT_KEYLOG")
    if log_path:
        from pynput import keyboard

        def on_press(key):
            ch = getattr(key, "char", None)
            if ch and ch.lower() in ("k", "g"):
                _log(log_path, ch.lower())

        keyboard.Listener(on_press=on_press).start()

        # 以「第一帧写入」作为 episode 的 t=0 锚点（与按键共用同一时钟）
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        _orig_add_frame = LeRobotDataset.add_frame
        _state = {"logged": False}

        def _add_frame(self, frame):
            if not _state["logged"]:
                _state["logged"] = True
                _log(log_path, "start")
            return _orig_add_frame(self, frame)

        LeRobotDataset.add_frame = _add_frame

    from lerobot.scripts.lerobot_record import main as record_main

    sys.argv = ["lerobot-record", *sys.argv[1:]]
    record_main()


if __name__ == "__main__":
    main()
