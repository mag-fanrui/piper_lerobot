#!/usr/bin/env python
"""把一组试验的关键帧拼成一张总览图，便于逐条判定成功/失败。

默认取每条试验「末帧」（俯视相机，即 CAM1），因为抓放任务的成败在末帧最直观。
需要看过程时用 ``--frame all``（首/中/末三帧并排）。

用法::

    python tools/trial_review_sheet.py --condition A --out outputs/review_A.png
    python tools/trial_review_sheet.py --trials T003 T006 --frame all
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "exp" / "data" / "light_attack"
DEFAULT_CSV = ROOT / "exp" / "rollout_records_100.csv"


def grab_frames(mp4: Path, mode: str, n: int = 3) -> list[Image.Image]:
    with av.open(str(mp4)) as c:
        frames = [f.to_image() for f in c.decode(video=0)]
    if not frames:
        return []
    if mode == "first":
        return [frames[0]]
    if mode == "mid":
        return [frames[len(frames) // 2]]
    if mode == "last":
        return [frames[-1]]
    idx = [0, len(frames) // 2, len(frames) - 1][:n]
    return [frames[i] for i in idx]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", nargs="+", help="按条件筛选，如 A")
    ap.add_argument("--trials", nargs="+", help="直接指定编号")
    ap.add_argument("--frame", default="last", choices=("last", "first", "mid", "all"))
    ap.add_argument("--cell", type=int, default=400, help="单格宽度（高度按 4:3）")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "review_sheet.png"))
    args = ap.parse_args()

    cond_of = {}
    rows = list(csv.DictReader(Path(args.csv).open(newline="", encoding="utf-8-sig")))
    for r in rows:
        cond_of[r["trial_id"]] = (r.get("condition") or "").strip()

    dirs = sorted(WAREHOUSE.glob("eval_T*"))
    if args.trials:
        want = set(args.trials)
        dirs = [d for d in dirs if d.name[5:] in want]
    if args.condition:
        dirs = [d for d in dirs if cond_of.get(d.name[5:]) in args.condition]
    if not dirs:
        raise SystemExit("没有匹配的试验目录")

    cw, ch = args.cell, int(args.cell * 3 / 4)
    label_h = 26
    tiles: list[tuple[str, list[Image.Image]]] = []
    for d in dirs:
        tid = d.name[5:]
        try:
            info = json.loads((d / "meta" / "info.json").read_text())
            dur = info["total_frames"] / info["fps"]
        except Exception:
            dur = float("nan")
        mp4 = d / f"{tid}_cam1.mp4"
        if not mp4.is_file():
            cand = sorted((d / "videos" / "observation.images.wrist").rglob("*.mp4"))
            mp4 = cand[0] if cand else None
        if mp4 is None or not mp4.is_file():
            print(f"[skip] {tid} 没有可用的俯视视频", file=sys.stderr)
            continue
        tiles.append((f"{tid}  {dur:.1f}s", grab_frames(mp4, args.frame)))
        print(f"  {tid}: {dur:.1f}s, {len(tiles[-1][1])} 帧")

    per_row = max(len(t[1]) for t in tiles)
    cols = args.cols if args.frame != "all" else max(1, args.cols // per_row)
    rows_n = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows_n * (ch + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()

    for i, (label, frames) in enumerate(tiles):
        cx = (i % cols) * cw
        cy = (i // cols) * (ch + label_h)
        draw.text((cx + 6, cy + 3), label, fill="black", font=font)
        for j, fr in enumerate(frames[:per_row]):
            sheet.paste(fr.resize((cw // per_row, ch)), (cx + j * (cw // per_row), cy + label_h))

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"\n总览图：{out}  ({sheet.width}×{sheet.height}, {len(tiles)} 条)")


if __name__ == "__main__":
    main()
