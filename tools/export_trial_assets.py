#!/usr/bin/env python
"""把一次试验的 lerobot 数据集导出成实验记录表约定的三份独立文件。

约定（实验记录表第 2 页「文件关联」）：
    T001_cam1.mp4        ← observation.images.wrist（固定俯视，CAM1）
    T001_cam2.mp4        ← observation.images.top  （臂上前视，CAM2）
    T001_policy.parquet  ← data/**/*.parquet（state / action 日志）

产物写回数据集目录本身，即一次试验一个文件夹。

用法::

    .venv/bin/python tools/export_trial_assets.py \
      --root exp/data/light_attack/T001 --trial-id T001

    # 相机与编号的对应关系不是 top/wrist 时可改
    # 实物对应（本机）：CAM1 = 固定俯视 = observation.images.wrist = /dev/video4
    #                   CAM2 = 臂上前视 = observation.images.top  = /dev/video10
    ... --cam1 wrist --cam2 top
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_episode_video import export_one  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="试验数据集目录，如 exp/data/light_attack/T001")
    ap.add_argument("--trial-id", required=True, help="试验编号，如 T001")
    ap.add_argument("--cam1", default="wrist", help="CAM1 对应的相机键；本机 CAM1=固定俯视=wrist")
    ap.add_argument("--cam2", default="top", help="CAM2 对应的相机键；本机 CAM2=臂上前视=top")
    ap.add_argument("--crf", default="20")
    ap.add_argument("--manifest", action="store_true", help="额外写 <trial>_manifest.json")
    ap.add_argument("--ckpt", default="", help="写入 manifest 的 checkpoint 路径")
    ap.add_argument("--params", default="", help="写入 manifest 的运行参数，形如 k=v,k=v")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not (root / "meta" / "info.json").is_file():
        raise SystemExit(f"不是 lerobot 数据集目录: {root}")

    info = json.loads((root / "meta" / "info.json").read_text())
    fps = float(info["fps"])

    ep_files = sorted((root / "meta" / "episodes").rglob("*.parquet"))
    if not ep_files:
        print(f"试验 {args.trial_id}: 没有 meta/episodes（空试验），无可导出内容 → 跳过")
        return
    df = pd.concat([pd.read_parquet(p) for p in ep_files], ignore_index=True).sort_values("episode_index")
    episodes = df["episode_index"].astype(int).tolist()

    print(f"试验 {args.trial_id}: {root}")
    print(f"  episodes={episodes}  fps={fps:g}")

    # ---- 两路相机 ----
    for tag, cam in (("cam1", args.cam1), ("cam2", args.cam2)):
        prefix = f"videos/observation.images.{cam}"
        if f"{prefix}/from_timestamp" not in df.columns:
            print(f"  [skip] 数据集中没有相机 {cam}")
            continue
        for ep in episodes:
            row = df[df["episode_index"] == ep].iloc[0]
            suffix = "" if len(episodes) == 1 else f"_ep{ep:03d}"
            out = root / f"{args.trial_id}_{tag}{suffix}.mp4"
            n = export_one(
                root, cam,
                int(row[f"{prefix}/chunk_index"]), int(row[f"{prefix}/file_index"]),
                float(row[f"{prefix}/from_timestamp"]), float(row[f"{prefix}/to_timestamp"]),
                fps, out, args.crf,
            )
            print(f"  {out.name}: {n} frames")

    # ---- 动作 / 状态日志 ----
    data_files = sorted((root / "data").rglob("*.parquet"))
    if not data_files:
        raise SystemExit("找不到 data/**/*.parquet")
    out_parquet = root / f"{args.trial_id}_policy.parquet"
    if len(data_files) == 1:
        shutil.copy2(data_files[0], out_parquet)
    else:  # 跨多个 file-XXX.parquet 时合并
        pd.concat([pd.read_parquet(p) for p in data_files], ignore_index=True).to_parquet(out_parquet, index=False)
    n_frames = len(pd.read_parquet(out_parquet))
    print(f"  {out_parquet.name}: {n_frames} frames（源 {len(data_files)} 个文件）")

    # ---- 可选清单 ----
    if args.manifest:
        manifest = {
            "trial_id": args.trial_id,
            "dataset_root": str(root),
            "total_episodes": info.get("total_episodes"),
            "total_frames": info.get("total_frames"),
            "fps": info.get("fps"),
            "checkpoint": args.ckpt,
            "params": dict(kv.split("=", 1) for kv in args.params.split(",") if "=" in kv),
            "files": sorted(p.name for p in root.glob(f"{args.trial_id}_*")),
        }
        (root / f"{args.trial_id}_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        print(f"  {args.trial_id}_manifest.json")


if __name__ == "__main__":
    main()
