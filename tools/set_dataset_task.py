#!/usr/bin/env python
"""修改已录数据集的语言指令（只改 meta/tasks.parquet，不动图像/动作）。

用法::

    .venv/bin/python tools/set_dataset_task.py \
      --root ~/.cache/huggingface/lerobot/myuser/piper_pick_red_block \
      --task "Pick up the red block and put it in the green tray."

    --dry-run   只看不写
    --index 0   只改 task_index=0 的那一句（数据集有多条任务时用）

写入前会自动把原文件备份成 meta/tasks.parquet.bak。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="数据集目录")
    ap.add_argument("--task", required=True, help="新的指令文本（和训练/部署时必须一字不差）")
    ap.add_argument("--index", type=int, default=None, help="只替换某个 task_index")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    path = root / "meta" / "tasks.parquet"
    if not path.is_file():
        raise SystemExit(f"找不到 {path}")

    df = pd.read_parquet(path)
    if "task_index" not in df.columns:
        raise SystemExit(f"{path} 里没有 task_index 列，格式不对")

    print("当前:")
    for task, row in df.iterrows():
        print(f"  task_index={int(row['task_index'])}  {task!r}")

    if args.index is None:
        new_index = [args.task] * len(df)
    else:
        if args.index not in set(df["task_index"].astype(int)):
            raise SystemExit(f"task_index={args.index} 不存在")
        new_index = [
            args.task if int(row["task_index"]) == args.index else task
            for task, row in df.iterrows()
        ]

    df.index = pd.Index(new_index)
    print("修改后:")
    for task, row in df.iterrows():
        print(f"  task_index={int(row['task_index'])}  {task!r}")

    if args.dry_run:
        print("dry-run：未写入")
        return

    shutil.copy2(path, path.with_name("tasks.parquet.bak"))
    df.to_parquet(path)
    print(f"已写入 {path}（备份: tasks.parquet.bak）")


if __name__ == "__main__":
    main()
