#!/usr/bin/env python
"""记录 / 检查 Piper 的命名位姿（只读 CAN，不发运动指令）。

用法::

    # 把机械臂拖到目标位姿后，记录为 home2
    .venv/bin/python tools/piper_pose.py save home2

    # 持续显示当前位姿与 home2 的偏差（采集前对齐用，Ctrl+C 退出）
    .venv/bin/python tools/piper_pose.py check home2

    # 只看一次
    .venv/bin/python tools/piper_pose.py check home2 --once

    # 列出所有已保存位姿
    .venv/bin/python tools/piper_pose.py list

位姿文件默认：<repo>/configs/piper_poses.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

POSES_PATH = Path("/media/robot204/Disk1/Projects/lerobot/configs/piper_poses.json")
JOINT_KEYS = [f"joint_{i}.pos" for i in range(1, 7)] + ["gripper.pos"]
CAN_NAME = "can_follower"


def get_bus():
    from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig

    motors = {f"joint_{i}": (i, "agilex_piper") for i in range(1, 7)}
    motors["gripper"] = (7, "agilex_piper")
    return PiperMotorsBus(PiperMotorsBusConfig(CAN_NAME, motors))


def read_pose(bus) -> dict[str, float]:
    from lerobot.motors.piper.piper import action_pos_dict_from_piper_read

    return action_pos_dict_from_piper_read(bus.read())


def load_poses() -> dict:
    if POSES_PATH.is_file():
        return json.loads(POSES_PATH.read_text())
    return {}


def cmd_save(name: str) -> None:
    bus = get_bus()
    time.sleep(0.4)  # 等反馈帧
    pose = read_pose(bus)
    poses = load_poses()
    poses[name] = pose
    POSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSES_PATH.write_text(json.dumps(poses, indent=2, ensure_ascii=False))
    print(f"已保存位姿 {name!r} -> {POSES_PATH}")
    for k in JOINT_KEYS:
        print(f"  {k:14s} {pose[k]:+.4f}")


def cmd_list() -> None:
    poses = load_poses()
    if not poses:
        print("还没有保存任何位姿")
        return
    for name, pose in poses.items():
        vals = [round(pose[k], 4) for k in JOINT_KEYS]
        print(f"{name}: {vals}")
        for k in JOINT_KEYS:
            print(f"  {k:14s} {pose[k]:+.4f}")


def cmd_check(name: str, once: bool, tolerance: float) -> None:
    poses = load_poses()
    if name not in poses:
        raise SystemExit(f"没有保存过位姿 {name!r}，先 save")
    target = poses[name]
    bus = get_bus()
    time.sleep(0.3)

    def fmt(delta: dict[str, float]) -> str:
        parts = [f"j{i}={delta[k]:+.3f}" for i, k in enumerate(JOINT_KEYS[:6], 1)]
        return "  ".join(parts) + f"  grip={delta['gripper.pos']:+.3f}"

    try:
        while True:
            cur = read_pose(bus)
            delta = {k: cur[k] - target[k] for k in JOINT_KEYS}
            max_abs = max(abs(v) for k, v in delta.items() if k != "gripper.pos")
            ok = max_abs <= tolerance
            status = "OK  " if ok else "偏离"
            print(f"\r{status} max={max_abs:.3f} rad  {fmt(delta)}   ", end="", flush=True)
            if once:
                print()
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    finally:
        bus = None


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save")
    p_save.add_argument("name")

    p_list = sub.add_parser("list")

    p_check = sub.add_parser("check")
    p_check.add_argument("name")
    p_check.add_argument("--once", action="store_true")
    p_check.add_argument("--tolerance", type=float, default=0.05)

    args = ap.parse_args()
    if args.cmd == "save":
        cmd_save(args.name)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "check":
        cmd_check(args.name, args.once, args.tolerance)


if __name__ == "__main__":
    main()
