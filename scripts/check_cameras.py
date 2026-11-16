#!/usr/bin/env python
"""相机机位自检：抓一帧、存图、打印亮度，方便边调边看。

用法::

    .venv/bin/python scripts/check_cameras.py
    .venv/bin/python scripts/check_cameras.py --cams top=/dev/video10 wrist=/dev/video4

亮度参考：mean < 30 基本是黑的（镜头被挡/对着暗处）；30–60 偏暗；> 60 正常。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--cams",
        nargs="+",
        default=["top=/dev/video10", "wrist=/dev/video4"],
        help="name=path 列表",
    )
    p.add_argument("--out", default="outputs/camera_check")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for item in args.cams:
        name, _, path = item.partition("=")
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            print(f"[{name}] {path}: 打不开（被别的进程占用？）")
            continue
        # 丢前几帧，等自动曝光稳定
        for _ in range(10):
            cap.read()
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print(f"[{name}] {path}: 读帧失败")
            continue
        mean = float(frame.mean())
        dst = out / f"check_{name}.png"
        cv2.imwrite(str(dst), frame)
        flag = "太黑！检查镜头盖/遮挡/朝向" if mean < 30 else ("偏暗" if mean < 60 else "OK")
        print(f"[{name}] {path}: mean={mean:.1f} -> {flag} | 已存 {dst}")


if __name__ == "__main__":
    main()
