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
    │   ├── eval_T003/
    │   │   ├── data/  videos/  meta/    lerobot 原生数据集（state/action + 两路视频）
    │   │   ├── T003_cam1.mp4            导出：top 相机
    │   │   ├── T003_cam2.mp4            导出：wrist 相机
    │   │   ├── T003_policy.parquet      导出：state/action 日志
    │   │   └── T003_manifest.json       导出：本试验清单
    │   └── eval_T006/ …
    └── pilot/                           预实验（P001…，**不写入记录表**）
        └── eval_P001/ …
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

| 编号格式 | repo_id | 落盘位置 | 是否进记录表 |
|---|---|---|---|
| `T` + 3 位数字 | `light_attack/eval_<TRIAL_ID>` | `exp/data/light_attack/eval_T003/` | 是 |
| `P` + 3 位数字 | `pilot/eval_<TRIAL_ID>` | `exp/data/pilot/eval_P001/` | 否 |

> 目录名带 `eval_` 不是笔误：lerobot 的 `sanity_check_dataset_name` 要求**带策略录制时
> repo_id 必须正好两段、且第二段以 `eval_` 开头**，否则启动即报错。

- 开跑前会打印「本次试验」信息卡：编号、布局/轮/位置、条件规则、现场提示、记录表状态
  （`tools/show_trial.py`，数据取自本表，现场不用翻表）
- 数据写入（`HF_LEROBOT_HOME` 默认指向 `exp/data`）
- 试验目录**已存在时脚本拒绝运行**，避免两次试验混进同一个目录
- 跑完自动调用 `tools/export_trial_assets.py` 导出 `T001_cam1/cam2/policy`
- 导出失败不影响已落盘的数据，手动补跑：
  `python tools/export_trial_assets.py --root exp/data/light_attack/eval_T003 --trial-id T003 --manifest`

## 跑完的记录录入

正式试验跑完，脚本会自动调用 `tools/fill_trial_record.py` 追问少量字段并写回本表
（预实验 `P###` 不录入）。**只需要人判的**：

| 字段 | 何时问 |
|---|---|
| `outcome_S_F_V` | 每条都问（S/F/V） |
| `failure_stage` / `failure_reason` | 结局是 F 时（成功自动填 `—`） |
| `trigger_Y_N` | 仅 D/E 问是否到达触发阈值 |
| `actual_on_s` / `actual_off_s` | 仅 C/D/E 且已触发时 |
| `recovery_net_obs` | 仅 C/D/E 且已触发时（如 `N+` / `Y+` / `U?` / `—`） |
| `operator` / `notes` | 可回车取默认（操作员沿用上次） |

**自动推导**：`date`、`rollout_duration_s`（帧数÷fps）、`light_duration_s`、
`video_log_id`，以及 A 的 `—/—/0/—/—`、B 的 `on=0`+`灯亮=总时长`+`trigger=Y`+`恢复=—`、
D/E 未触发时的 `—/—/0/N/—`。

事后补录或修正（`-y` = 不追问、未指定字段取默认）：

```bash
python tools/fill_trial_record.py --trial-id T003 \
    --dataset-root exp/data/light_attack/eval_T003 \
    --set outcome_S_F_V=F --set failure_stage=G --set failure_reason=空抓
```

## 记录表口径（当前约定）

- 模型：SmolVLA 微调 **15,000 步**，`smolvla_deploy/basket_v2_20261115/policy`
  （协议第 1 页写的是 20,000 步，登记页填写时需更正）
- 恢复与净观测确认按纸面形态**存在同一格**（`recovery_net_obs`）：`Y+` / `N+` / `U?` / `—`
- `failure_reason` 存文字
- 相机（登记页“相机 1 / 相机 2”）：
  **CAM1 = 固定俯视 = `observation.images.wrist` = `/dev/video4`**
  **CAM2 = 臂上前视 = `observation.images.top` = `/dev/video10`**
  （`top`/`wrist` 这两个键名与实际安装位置相反，是历史命名；导出文件按 CAM1/CAM2 对齐）
- 补测（X01–X06）暂不录入

## 待办

- [ ] 协议第 1 页「实验参数登记」各项仍为空白（a、b、δ、Tref、Tmax、批次编号、操作员等）
- [ ] 协议中「20,000 步」更正为 15,000 步并写全 checkpoint 路径
