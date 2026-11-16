#!/usr/bin/env python
"""把数据集中某一条（或全部）episode 的两路相机视频分别导出成独立 mp4。

数据集里每路相机本身是整段 mp4（按 chunk/file 分文件），一个文件里可能连续存了多条
episode；这个脚本按 meta/episodes 里的 from/to_timestamp 精确切出单条。

用法::

    # 导出第 0 条的两路相机
    .venv/bin/python tools/export_episode_video.py \
      --root /media/robot204/Disk1/lerobot_data/myuser/piper_pick_blue_red_basket_v2 \
      --episode 0 --out-dir /tmp/clips

    # 只导出 top
    ... --episode 0 --cams top

    # 全部 episode
    ... --all --out-dir /tmp/clips
"""

from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path

import av
import pandas as pd


def export_one(root: Path, cam: str, chunk: int, file_idx: int, start: float, end: float,
               fps: float, out_path: Path, crf: str = "20") -> int:
    src = root / "videos" / f"observation.images.{cam}" / f"chunk-{chunk:03d}" / f"file-{file_idx:03d}.mp4"
    if not src.is_file():
        raise FileNotFoundError(src)

    in_c = av.open(str(src))
    in_s = in_c.streams.video[0]
    out_c = av.open(str(out_path), "w")
    out_s = out_c.add_stream("h264", rate=Fraction(fps).limit_denominator(1000), options={"preset": "veryfast", "crf": crf})
    out_s.width = in_s.codec_context.width
    out_s.height = in_s.codec_context.height
    out_s.pix_fmt = "yuv420p"

    n = 0
    for frame in in_c.decode(video=0):
        if frame.pts is None:
            continue
        t = float(frame.pts * frame.time_base)
        if t < start - 1e-6:
            continue
        if t >= end - 1e-6:
            break
        frame.pts = n  # 从 0 重新计数，避免导出片段带原始时间偏移
        frame.time_base = Fraction(1, int(round(fps)))
        for packet in out_s.encode(frame):
            out_c.mux(packet)
        n += 1

    for packet in out_s.encode():
        out_c.mux(packet)
    out_c.close()
    in_c.close()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="数据集目录")
    ap.add_argument("--episode", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="导出全部 episode")
    ap.add_argument("--cams", nargs="+", default=None, help="默认导出所有相机，如 top wrist")
    ap.add_argument("--out-dir", default="outputs/clips")
    ap.add_argument("--crf", default="20")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    info = json.loads((root / "meta" / "info.json").read_text())
    fps = float(info["fps"])
    cams = args.cams or [k.split(".")[-1] for k in info["features"] if k.startswith("observation.images.")]

    ep_files = sorted((root / "meta" / "episodes").rglob("*.parquet"))
    if not ep_files:
        raise SystemExit("找不到 meta/episodes/*.parquet")
    df = pd.concat([pd.read_parquet(p) for p in ep_files], ignore_index=True).sort_values("episode_index")

    if args.all:
        episodes = df["episode_index"].astype(int).tolist()
    elif args.episode is not None:
        episodes = [args.episode]
    else:
        raise SystemExit("请给 --episode N 或 --all")

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    for ep in episodes:
        row = df[df["episode_index"] == ep]
        if row.empty:
            print(f"[skip] episode {ep} 不存在")
            continue
        row = row.iloc[0]
        for cam in cams:
            prefix = f"videos/observation.images.{cam}"
            start = float(row[f"{prefix}/from_timestamp"])
            end = float(row[f"{prefix}/to_timestamp"])
            chunk = int(row[f"{prefix}/chunk_index"])
            file_idx = int(row[f"{prefix}/file_index"])
            out_path = out_dir / f"ep{ep:03d}_{cam}.mp4"
            n = export_one(root, cam, chunk, file_idx, start, end, fps, out_path, args.crf)
            print(f"ep{ep:03d} {cam}: {n} frames -> {out_path}")


if __name__ == "__main__":
    main()
