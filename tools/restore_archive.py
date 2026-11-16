#!/usr/bin/env python
"""把归档的实验批次恢复回来（数据目录 + 记录行）。

配合 ``exp/data/_archive_*`` 使用：归档时会把该批次的试验目录移走，
并把对应的记录行另存为 ``<归档目录>/<批次>_records.csv``。
本脚本做反向操作：把目录移回 ``exp/data/light_attack/``，把记录行合并回主表。

用法::

    # 先看会做什么
    python tools/restore_archive.py --archive exp/data/_archive_A_v1_20261116_2123 --dry-run

    # 真正恢复
    python tools/restore_archive.py --archive exp/data/_archive_A_v1_20261116_2123

安全措施：
- 目标目录已存在则拒绝（除非 --force，且会先备份主表）
- 记录行按 trial_id 覆盖式合并，未涉及的行走样保留
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "exp" / "data" / "light_attack"
DEFAULT_CSV = ROOT / "exp" / "rollout_records_100.csv"


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def save_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, help="归档目录，如 exp/data/_archive_A_v1_20261116_2123")
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="主记录表路径")
    ap.add_argument("--records", default=None, help="归档里的记录行 CSV（默认自动找 *_records.csv）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不改动")
    ap.add_argument("--force", action="store_true", help="目标目录已存在时也覆盖（先备份主表）")
    args = ap.parse_args()

    arch = Path(args.archive).expanduser().resolve()
    if not arch.is_dir():
        raise SystemExit(f"归档目录不存在：{arch}")

    csv_path = Path(args.csv).expanduser()
    rec_path = Path(args.records) if args.records else next(iter(sorted(arch.glob("*_records.csv"))), None)
    dirs = sorted(arch.glob("eval_*"))

    print(f"归档目录：{arch}")
    print(f"  数据目录：{len(dirs)} 个" + (f"（{', '.join(d.name for d in dirs)}）" if dirs else ""))
    print(f"  记录行  ：{rec_path.name if rec_path else '（未找到 *_records.csv）'}")

    clashes = [d for d in dirs if (WAREHOUSE / d.name).exists()]
    if clashes and not args.force:
        print(f"\n✗ 目标已存在，拒绝恢复：{[d.name for d in clashes]}\n  加 --force 可覆盖", file=sys.stderr)
        return

    if args.dry_run:
        print("\n[dry-run] 将要执行：")
        for d in dirs:
            print(f"  mv {d}  ->  {WAREHOUSE / d.name}")
        if rec_path:
            print(f"  合并 {rec_path.name} 的记录行到 {csv_path.name}")
        return

    if args.force and csv_path.exists():
        backup = csv_path.with_suffix(csv_path.suffix + ".before-restore")
        shutil.copy2(csv_path, backup)
        print(f"  已备份主表：{backup}")

    WAREHOUSE.mkdir(parents=True, exist_ok=True)
    moved = 0
    for d in dirs:
        target = WAREHOUSE / d.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(d), str(target))
        moved += 1
    print(f"\n✓ 已恢复数据目录 {moved} 个")

    if rec_path and rec_path.is_file():
        header, rows = load_csv(csv_path)
        r_header, r_rows = load_csv(rec_path)
        missing = set(r_header) - set(header)
        if missing:
            raise SystemExit(f"记录表缺少这些列：{sorted(missing)}")
        by_id = {r["trial_id"]: r for r in rows}
        merged = 0
        for rr in r_rows:
            tid = rr["trial_id"]
            if tid in by_id:
                by_id[tid].update({k: v for k, v in rr.items() if k in header})
            else:
                new_row = {k: rr.get(k, "") for k in header}
                rows.append(new_row)
                by_id[tid] = new_row
            merged += 1
        save_csv(csv_path, header, rows)
        filled = sum(1 for r in rows if (r.get("outcome_S_F_V") or "").strip())
        print(f"✓ 已合并记录 {merged} 行；主表已填 {filled}/100")


if __name__ == "__main__":
    main()
