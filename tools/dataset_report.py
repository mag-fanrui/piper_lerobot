#!/usr/bin/env python
"""数据集体检：条数/帧数/任务/每条时长，并标出「全程无运动」的空录。

用法::

    .venv/bin/python tools/dataset_report.py --root /media/robot204/Disk1/lerobot_data/myuser/piper_pick_blue_block_clean
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="数据集目录")
    ap.add_argument("--motion-threshold", type=float, default=0.004, help="判定有运动的关节变化阈值(rad/帧)")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    info = json.loads((root / "meta" / "info.json").read_text())
    print(f"数据集: {root}")
    print(f"  episodes={info['total_episodes']} frames={info['total_frames']} fps={info['fps']} "
          f"duration={info['total_frames'] / info['fps']:.0f}s")
    print(f"  features={list(info['features'])}")

    tasks_path = root / "meta" / "tasks.parquet"
    if tasks_path.is_file():
        import pandas as pd

        df = pd.read_parquet(tasks_path)
        print("  tasks=")
        for task, row in df.iterrows():
            print(f"    [{int(row['task_index'])}] {task!r}")

    rows = []
    for f in glob.glob(str(root / "data" / "**" / "*.parquet"), recursive=True):
        t = pq.read_table(f).to_pydict()
        rows += list(zip(t["episode_index"], t["observation.state"]))
    if not rows:
        print("  (没有 data parquet)")
        return

    eps: dict[int, list] = defaultdict(list)
    for e, s in rows:
        eps[e].append(np.asarray(s, dtype=float))

    empty = []
    print(f"\n  {'ep':>4} {'dur_s':>6} {'idle_tail_s':>12}")
    for e in sorted(eps):
        a = np.array(eps[e])
        d = np.abs(np.diff(a, axis=0)).mean(1) if len(a) > 1 else np.array([0.0])
        active = np.where(d > args.motion_threshold)[0]
        last = active[-1] if len(active) else 0
        dur = len(a) / info["fps"]
        tail = (len(a) - last) / info["fps"]
        flag = ""
        if len(active) == 0:
            flag = "  <-- 全程无运动"
            empty.append(int(e))
        print(f"  {e:4d} {dur:6.1f} {tail:12.1f}{flag}")

    print(f"\n空录 episode: {empty if empty else '无'}")

    # 初始位姿一致性：每条 episode 第一帧的关节值
    firsts = np.array([np.array(eps[e][0]) for e in sorted(eps)])
    mean = firsts.mean(axis=0)
    std = firsts.std(axis=0)
    print("\n初始位姿（每条第一帧）:")
    print("  mean:", np.round(mean, 3).tolist())
    print("  std :", np.round(std, 3).tolist())
    print(f"  各关节最大 std = {std.max():.3f} rad"
          + ("  <-- 起始位姿差异较大" if std.max() > 0.15 else "  （较一致）"))



if __name__ == "__main__":
    main()
