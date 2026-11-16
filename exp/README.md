# 实验记录与数据归档（VLA Light Attack）

本目录存放正式实验的记录表与数据仓库。协议见同目录 `experiment_record_print.pdf`（9 页）。

## 目录结构

```
exp/
├── experiment_record_print.pdf          协议正文（9 页，含登记页 / 条件规则 / 汇总页）
├── rollout_records_100.csv              正式记录表（T001–T100，录入用）
├── rollout_records_100.orig-20261116.csv  改列前的原始副本（仅备份）
└── data/
    ├── light_attack/                    正式试验（T001–T100，对应记录表）
    │   ├── T001/
    │   │   ├── data/  videos/  meta/    lerobot 原生数据集（state/action + 两路视频）
    │   │   ├── T001_cam1.mp4            导出：top 相机
    │   │   ├── T001_cam2.mp4            导出：wrist 相机
    │   │   ├── T001_policy.parquet      导出：state/action 日志
    │   │   └── T001_manifest.json       导出：本试验清单
    │   └── T002/ …
    └── pilot/                           预实验（P001…，**不写入记录表**）
        └── P001/ …
```

`data/` 已在 `exp/.gitignore` 中忽略，记录表 CSV 仍随仓库保留。

## 运行方式

每次试验必须给 `TRIAL_ID`，与记录表的编号一一对应：

```bash
# 正式试验（写入记录表 T001–T100）
TRIAL_ID=T003 bash scripts/deploy_piper.sh

# 预实验（不入记录表，数据进 pilot/，可随意编号）
TRIAL_ID=P001 bash scripts/deploy_piper.sh
```

| 编号格式 | 落盘位置 | 是否进记录表 |
|---|---|---|
| `T` + 3 位数字 | `exp/data/light_attack/<TRIAL_ID>/` | 是 |
| `P` + 3 位数字 | `exp/data/pilot/<TRIAL_ID>/` | 否 |

- 数据写入（`HF_LEROBOT_HOME` 默认指向 `exp/data`）
- 试验目录**已存在时脚本拒绝运行**，避免两次试验混进同一个目录
- 跑完自动调用 `tools/export_trial_assets.py` 导出 `T001_cam1/cam2/policy`
- 导出失败不影响已落盘的数据，手动补跑：
  `python tools/export_trial_assets.py --root exp/data/light_attack/T001 --trial-id T001 --manifest`

## 记录表口径（当前约定）

- 模型：SmolVLA 微调 **15,000 步**，`smolvla_deploy/basket_v2_20261115/policy`
  （协议第 1 页写的是 20,000 步，登记页填写时需更正）
- 恢复与净观测确认按纸面形态**存在同一格**（`recovery_net_obs`）：`Y+` / `N+` / `U?` / `—`
- `failure_reason` 存文字
- 补测（X01–X06）暂不录入

## 待办

- [ ] 协议第 1 页「实验参数登记」各项仍为空白（a、b、δ、Tref、Tmax、批次编号、操作员等）
- [ ] 协议中「20,000 步」更正为 15,000 步并写全 checkpoint 路径
