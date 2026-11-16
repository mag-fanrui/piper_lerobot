#!/usr/bin/env python
"""按条件分组，连续跑一组正式试验（T###）。

每条试验仍然调用 ``scripts/deploy_piper.sh``（录制 → 导出 → 录入记录表），
本脚本只负责：按记录表的顺序挑出该条件的试验、逐条启动、跑完问下一步。

按键约定：

    每条开始前：  回车 = 开始本条      s = 跳过本条      x = 退出批次
    每条结束后：  回车 = 下一条        r = 重跑本条      x = 退出批次
    （录制过程中：n = 提前结束本条，r = 作废重录，q = 结束录制进程）

用法::

    python tools/run_batch.py --condition A            # A 组 20 条，按表内顺序
    python tools/run_batch.py --condition A --start T013   # 从 T013 开始
    python tools/run_batch.py --condition A B --limit 5    # A、B 两组各跑前 5 条
    python tools/run_batch.py --condition A --dry-run      # 只打印计划，不启动

操作员：默认沿用表里最近一条；也可用环境变量指定，例如::

    OPERATOR=fr python tools/run_batch.py --condition A
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "scripts" / "deploy_piper.sh"
DEFAULT_CSV = ROOT / "exp" / "rollout_records_100.csv"
WAREHOUSE = ROOT / "exp" / "data" / "light_attack"
KEEP = {"trial_id", "layout", "repeat", "position", "condition", "random_u"}
COND_NAME = {"A": "Clean", "B": "Full", "C": "Random", "D": "抓取前", "E": "放置前"}
SMOOTHING_ENV = ROOT / "configs" / "smoothing.env"


def load_smoothing() -> dict[str, str]:
    """读取单一口径的平滑性参数（deploy_piper.sh 也用同一份）。"""
    out: dict[str, str] = {}
    if not SMOOTHING_ENV.is_file():
        return out
    for line in SMOOTHING_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def save_rows(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def clear_row(row: dict) -> None:
    for key in row:
        if key not in KEEP:
            row[key] = ""


def remove_trial_dir(tid: str) -> bool:
    d = (WAREHOUSE / f"eval_{tid}").resolve()
    # 只允许删数据仓库里本条件的试验目录，且名字必须与编号对应
    if d.parent != WAREHOUSE.resolve() or d.name != f"eval_{tid}":
        print(f"  ✗ 拒绝删除可疑路径：{d}", file=sys.stderr)
        return False
    if not d.exists():
        return True
    shutil.rmtree(d)
    print(f"  已删除 {d}")
    return True


def show_card(tid: str, csv_path: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "show_trial.py"),
                    "--trial-id", tid, "--csv", str(csv_path)], check=False)


def ask(prompt: str, allowed: tuple[str, ...]) -> str:
    while True:
        try:
            ans = input(prompt).strip().lower()
        except EOFError:
            return "x"
        if ans in allowed:
            return ans
        print(f"  只能输入 {' / '.join(a or '回车' for a in allowed)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", nargs="+", required=True, help="条件，如 A 或 A B")
    ap.add_argument("--start", help="从该编号开始（含）")
    ap.add_argument("--limit", type=int, help="每组最多跑几条")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不启动")
    ap.add_argument("--deploy", default=str(DEPLOY), help="执行单条试验的脚本（测试时可替换）")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser()
    header, rows = load_rows(csv_path)
    by_id = {r["trial_id"]: r for r in rows}

    plan: list[str] = []
    for cond in args.condition:
        subset = [r["trial_id"] for r in rows if r.get("condition") == cond]
        if args.start:
            subset = [t for t in subset if t >= args.start]
        if args.limit:
            subset = subset[: args.limit]
        if not subset:
            print(f"⚠️  条件 {cond} 没有可跑的试验", file=sys.stderr)
        plan += subset

    print("=" * 62)
    print(f" 批次计划：条件 {'、'.join(f'{c}({COND_NAME.get(c, c)})' for c in args.condition)}"
          f"，共 {len(plan)} 条")
    print("=" * 62)
    for tid in plan:
        r = by_id[tid]
        status = "已录" if (r.get("outcome_S_F_V") or "").strip() else "待跑"
        exists = "⚠️目录已存在" if (WAREHOUSE / f"eval_{tid}").exists() else ""
        print(f"  {tid}  条件 {r['condition']}  {r['layout']} 第 {r['repeat']} 轮 位置 {r['position']}"
              f"  [{status}] {exists}")
    print("=" * 62)

    if args.dry_run:
        print("（--dry-run：只打印计划，未启动任何实验）")
        return

    sm = load_smoothing()
    if sm:
        print(f" 平滑参数：限幅 {sm.get('MAX_STEP_RAD_DEFAULT', '?')} rad/步，"
              f"EMA joint {sm.get('JOINT_ALPHA_DEFAULT', '?')} / gripper {sm.get('GRIPPER_ALPHA_DEFAULT', '?')}，"
              f"n_action_steps {sm.get('N_ACTION_STEPS_DEFAULT', '?')}")

    op = os.environ.get("OPERATOR", "").strip()
    print(f" 操作员：{op or '（沿用上次录入的值）'}")
    print(" 每条开始前：回车开始 / s 跳过 / x 退出")
    print(" 录制中：n 提前结束本条，r 作废重录，q 结束录制")

    done: list[str] = []
    env = dict(os.environ, DRY_RUN="false")
    if op:
        env["OPERATOR"] = op

    idx = 0
    while idx < len(plan):
        tid = plan[idx]
        row = by_id[tid]

        if (WAREHOUSE / f"eval_{tid}").exists():
            print(f"\n⚠️  {tid} 的数据目录已存在，先跳过。要重跑请手动删除或选其它编号。")
            idx += 1
            continue

        print()
        show_card(tid, csv_path)
        act = ask(" 回车=开始本条 / s=跳过 / x=退出 > ", ("", "s", "x"))
        if act == "x":
            break
        if act == "s":
            idx += 1
            continue

        while True:
            env["TRIAL_ID"] = tid
            rc = subprocess.run(["bash", str(Path(args.deploy).expanduser())], cwd=ROOT, env=env).returncode
            if rc != 0:
                print(f"\n⚠️  {tid} 的录制进程退出码 {rc}（可能中途取消）")
            act = ask(" 回车=下一条 / r=重跑本条 / x=退出 > ", ("", "r", "x"))
            if act == "r":
                if remove_trial_dir(tid):
                    clear_row(row)
                    save_rows(csv_path, header, rows)
                    print(f"  {tid} 的数据与记录已清空，重新开始本条")
                    continue
                print("  取消删除，继续下一条")
            break

        if act == "x":
            break
        if (row.get("outcome_S_F_V") or "").strip():
            done.append(tid)
        idx += 1

    print("\n" + "=" * 62)
    print(f" 批次结束：已记录 {len(done)} 条 {done if done else ''}")
    rest = [t for t in plan if t not in done]
    if rest:
        print(f" 未完成：{rest}")
    print("=" * 62)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
