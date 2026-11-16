#!/usr/bin/env python
"""把一次试验的结果录入记录表（exp/rollout_records_100.csv）。

只问「必须人判」的字段，其余按协议自动推导：

  自动：date、rollout_duration_s（帧数÷fps）、light_duration_s、
        A 的 开/关=—、灯亮=0、触发=—、恢复=—；
        B 的 开灯=0、灯亮=总时长、触发=Y、恢复=—；
        D/E 未触发时的 开/关=—、灯亮=0、触发=N、恢复=—；
        video_log_id（=试验编号）

  追问：outcome（S/F/V）；F 时问失败阶段/主因；
        C/D/E 问是否触发、开灯秒、关灯秒、恢复+净观测确认；
        备注（可空）；操作员（默认沿用上次）。

用法::

    # 交互录入（跑完自动调用）
    python tools/fill_trial_record.py --trial-id T003 --dataset-root exp/data/light_attack/eval_T003

    # 非交互（事后补录或批量修正）
    python tools/fill_trial_record.py --trial-id T003 --dataset-root ... \
        --set outcome=F --set failure_stage=G --set failure_reason=空抓

预实验（P###）不要录入本表，脚本会拒绝。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date as _date
from pathlib import Path

DASH = "—"
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "exp" / "rollout_records_100.csv"
OUTCOMES = ("S", "F", "V")
STAGES = ("A", "G", "T", "P", "U")


def ask(prompt: str, default: str = "", allowed: tuple[str, ...] | None = None) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        val = raw or default
        if allowed and val not in allowed:
            print(f"  ✗ 只能是 {allowed} 之一", file=sys.stderr)
            continue
        return val


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        header = list(rows[0].keys()) if rows else []
    return header, rows


def save_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def rollout_duration(dataset_root: Path) -> float | None:
    info = dataset_root / "meta" / "info.json"
    if not info.is_file():
        return None
    meta = json.loads(info.read_text())
    frames, fps = meta.get("total_frames"), meta.get("fps")
    if not frames or not fps:
        return None
    return round(float(frames) / float(fps), 1)


def last_operator(rows: list[dict]) -> str:
    for row in reversed(rows):
        if (row.get("operator") or "").strip():
            return row["operator"].strip()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial-id", required=True)
    ap.add_argument("--dataset-root", required=True, help="本次试验的数据集目录（用于算总时长）")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="指定字段，可重复；给了就不追问该字段")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="不追问：未指定字段直接取默认值（非交互补录用）")
    args = ap.parse_args()

    if not args.trial_id.startswith("T"):
        raise SystemExit(f"{args.trial_id} 是预实验编号，不录入正式记录表")

    csv_path = Path(args.csv).expanduser()
    header, rows = load_csv(csv_path)
    row = next((r for r in rows if r.get("trial_id") == args.trial_id), None)
    if row is None:
        raise SystemExit(f"记录表里没有 {args.trial_id}")

    overrides = {}
    for item in args.set:
        k, _, v = item.partition("=")
        overrides[k.strip()] = v.strip()
    unknown = set(overrides) - set(header)
    if unknown:
        raise SystemExit(f"记录表没有这些列：{sorted(unknown)}")

    cond = row["condition"].strip()
    duration = rollout_duration(Path(args.dataset_root).expanduser())

    # ---------- 自动字段：按条件推导 ----------
    if cond == "A":
        auto = {"actual_on_s": DASH, "actual_off_s": DASH, "light_duration_s": "0",
                "trigger_Y_N": DASH, "recovery_net_obs": DASH}
    elif cond == "B":
        d = "" if duration is None else f"{duration:.1f}"
        auto = {"actual_on_s": "0.0", "actual_off_s": d, "light_duration_s": d,
                "trigger_Y_N": "Y", "recovery_net_obs": DASH}
    else:
        auto = {}  # C/D/E 依赖是否触发，下面追问

    manual: dict[str, str] = {}

    def put(key: str, prompt: str, default: str = "", allowed: tuple[str, ...] | None = None) -> str:
        if key in overrides:
            val = overrides[key]
        elif args.yes:
            val = default
        else:
            val = ask(prompt, default, allowed)
        if allowed and val not in allowed:
            raise SystemExit(f"{key}={val!r} 非法，只能取 {allowed}")
        manual[key] = val
        return val

    print(f"\n录入 {args.trial_id}（布局 {row['layout']} 第 {row['repeat']} 轮 位置 {row['position']} 条件 {cond}"
          + (f" u={row['random_u']}" if cond == "C" else "") + "）")
    if duration is not None:
        print(f"  总时长（自动，帧数÷fps）= {duration:.1f} s")

    # ---------- 人判字段 ----------
    if cond in ("C", "D", "E"):
        if cond == "C":
            triggered = "Y"
            manual["trigger_Y_N"] = "Y"   # C 为随机触发，触发栏固定 Y
            print("  C 为随机触发，触发栏固定 Y")
        else:
            triggered = put("trigger_Y_N", "是否触发（Y/N）", "Y", ("Y", "N"))
        if triggered == "Y":
            on = put("actual_on_s", "实际开灯时刻 / 秒")
            off = put("actual_off_s", "实际关灯时刻 / 秒")
            try:
                dur_light = float(off) - float(on)
                if dur_light < 0:
                    print(f"  ⚠️  关灯 {off}s 早于开灯 {on}s，请核对", file=sys.stderr)
                auto["light_duration_s"] = f"{dur_light:.1f}"
            except ValueError:
                print("  ⚠️  开/关灯不是数字，灯亮时长留空", file=sys.stderr)
                auto["light_duration_s"] = ""
            put("recovery_net_obs", "恢复+净观测确认（如 N+ / Y+ / U? / —）", DASH)
        else:
            auto.update({"actual_on_s": DASH, "actual_off_s": DASH, "light_duration_s": "0",
                         "recovery_net_obs": DASH})
            manual["trigger_Y_N"] = "N"

    outcome = put("outcome_S_F_V", "结局（S=成功 / F=失败 / V=设备无效）", "", OUTCOMES)
    if outcome == "S":
        manual["failure_stage"] = DASH   # 协议：成功填 —
        manual["failure_reason"] = DASH
    elif outcome == "F":
        put("failure_stage", "失败阶段（A接近/G抓取/T搬运/P放置/U不明）", "", STAGES)
        put("failure_reason", "失败主因（文字）", "")
    else:  # V
        put("failure_stage", "失败阶段", DASH)
        put("failure_reason", "设备无效原因", "")

    put("date", "日期", _date.today().isoformat())
    put("operator", "操作员", last_operator(rows))
    put("notes", "备注（可空）", "")
    if "video_log_id" not in overrides:
        manual["video_log_id"] = args.trial_id
    if duration is not None and "rollout_duration_s" not in overrides:
        manual["rollout_duration_s"] = f"{duration:.1f}"

    # ---------- 写回 ----------
    for key, val in {**auto, **manual}.items():
        if key in header:
            row[key] = val
    save_csv(csv_path, header, rows)

    print(f"\n✅ 已写入 {csv_path.name} 的 {args.trial_id}")
    for key in ("date", "operator", "actual_on_s", "actual_off_s", "light_duration_s",
                "rollout_duration_s", "outcome_S_F_V", "trigger_Y_N", "failure_stage",
                "failure_reason", "recovery_net_obs", "video_log_id", "notes"):
        print(f"   {key:20s} = {row.get(key, '')!r}")


if __name__ == "__main__":
    main()
