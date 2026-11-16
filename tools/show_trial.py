#!/usr/bin/env python
"""开跑前打印「本次试验」信息：编号、布局/轮/位置、条件与固定操作规则、记录表状态。

数据来自 exp/rollout_records_100.csv（试验编号的设计字段已预填），
所以现场只需看屏幕对照，不用翻表。

用法::

    python tools/show_trial.py --trial-id T003
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "exp" / "rollout_records_100.csv"

COND_NAME = {"A": "Clean", "B": "Full", "C": "Random", "D": "抓取前", "E": "放置前"}
COND_RULE = {
    "A": "全程关灯；开/关时刻填「—」，灯亮时长填 0；触发与恢复填「—」",
    "B": "从任务启动持续照射至任务结束；记录实际开/关时刻；恢复填「—」",
    "C": "按本条 u 计算起始时间，照射 δ 秒；计划开灯时刻 = a + u(b−a)",
    "D": "按 k 开灯、按 g 关灯；两个时刻均按按键实测记录（不设默认值）",
    "E": "按 k 开灯、按 g 关灯；两个时刻均按按键实测记录（不设默认值）",
}
SITE_TIP = {
    "A": "现场：确认聚光灯全程关闭（这是 A 唯一的操作变量）",
    "B": "现场：确认聚光灯已打开，并保持到任务结束",
    "C": "现场：按 u 算出的时刻开灯，照射 δ 秒后关灯，掐表计时",
    "D": "现场：开灯时按 k、关灯时按 g（g 的时刻即恢复判定时刻）",
    "E": "现场：开灯时按 k、任务结束关灯时按 g",
}
AUTO_FIELDS = {
    "A": "跑完自动：date、总时长、开/关=—、灯亮=0、触发=—、恢复=—",
    "B": "跑完自动：date、总时长、开灯=0、灯亮=总时长、触发=Y、恢复=—",
    "C": "跑完自动：date、总时长、灯亮=关灯−开灯；追问：开/关时刻、恢复+净观测",
    "D": "跑完自动：date、总时长、开灯/关灯=按键实测；追问：恢复+净观测",
    "E": "跑完自动：date、总时长、开灯/关灯=按键实测；追问：恢复+净观测",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial-id", required=True)
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    args = ap.parse_args()

    tid = args.trial_id
    line = "─" * 58
    print(line)

    if tid.startswith("P"):
        print(f" 预实验 {tid}　（不录入记录表，数据进 exp/data/pilot/）")
        print(line)
        return

    path = Path(args.csv).expanduser()
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8-sig"))) if path.is_file() else []
    row = next((r for r in rows if r.get("trial_id") == tid), None)
    if row is None:
        print(f" ⚠️  记录表里没有 {tid}（{path}）")
        print(line)
        return

    cond = row["condition"].strip()
    print(f" 本次试验 {tid}　条件 {cond}・{COND_NAME.get(cond, '?')}")
    print(f" 布局 {row['layout']}　第 {row['repeat']} 轮　位置 {row['position']}")
    if cond == "C":
        u = row.get("random_u") or "?"
        print(f" C 的 u = {u}　（开灯时刻 = a + u(b−a)，a/b 见登记页）")
    print(f" 规则：{COND_RULE.get(cond, '')}")
    print(f" {AUTO_FIELDS.get(cond, '')}")
    print(f" {SITE_TIP.get(cond, '')}")

    done = (row.get("outcome_S_F_V") or "").strip()
    if done:
        print(f" ⚠️  该行已有结局 {done}，重跑会覆盖已有记录")
    else:
        print(" 记录表状态：未填写")
    print(line)


if __name__ == "__main__":
    main()
