# SmolVLA 部署手册（本机：2×RTX 2080 Ti / lerobot 0.6.1）

> 结论：这台机器的环境、权重、推理、微调链路都已经跑通（下文的命令都在本机实测过）。
> 真正要做的只剩两件事：**① 把你的机械臂接上并校准；② 用自己的数据微调，再用 `lerobot-rollout` 部署。**
>
> 实测数据：450M 参数，显存占用 ~1 GB，一个 50 步动作 chunk 推理 **0.38–0.40 s**（≈7.5 ms/步），
> 30 Hz 控制够用；微调 batch=64 峰值显存 **5.8 GB**，单卡 2080 Ti（11 GB）可以训练（bf16 在 Turing 上偏慢）。

---

## 0. 先看这条：网上教程会踩的坑

从 lerobot **0.6.x** 开始：

| 旧写法（0.5.x 及更早） | 0.6.1 的正确写法 |
| --- | --- |
| `lerobot-record --policy.path=...` 跑策略 | **`lerobot-rollout --policy.path=...`** |
| `lerobot-record` 既采数据又跑策略 | `lerobot-record` **只采数据**，`lerobot-rollout` 负责部署，`lerobot-eval` 负责仿真评测 |

`lerobot-record --policy.path` 在 0.6.1 会直接报错并提示改用 `lerobot-rollout`。
本手册按 0.6.1 的 API 编写。

---

## 1. 本机现状（已安装 / 已验证）

| 项目 | 值 |
| --- | --- |
| GPU | 2 × RTX 2080 Ti 11 GB（Turing, sm_75），驱动 595.112.07，CUDA 13.2 |
| Python | 3.12.15（`/media/robot204/Disk1/Projects/lerobot/.venv`） |
| lerobot | **0.6.1**（PyPI），含 smolvla / dataset / hardware / feetech / intelrealsense extras |
| torch | 2.11.0+cu130，torchvision 0.26.0 |
| transformers | 5.5.4 |
| 权重 | `models/smolvla_base/`（865 MB，450M 参数） |
| 相机 | RealSense D435I `254522072269`、D405 `262422272748`（`pyrealsense2` 已装） |
| 机械臂 | 当前**未连接**（没有 `/dev/ttyACM*`），需插上后再校准 |

实测（`tools/smolvla_smoke_test.py`，RTX 2080 Ti）：

```
加载（权重已缓存） 11.3 s，450M 参数
chunk（50 步，稳态） 0.38–0.40 s -> 7.5–7.9 ms/步
队列取步            2.9 ms
显存 peak 1035 MiB
```

微调实测（`lerobot-train`，合成数据集）：

| batch_size | 峰值显存 | 单次 update |
| --- | --- | --- |
| 2 | 1.86 GB | 0.98 s |
| 64 | 5.83 GB | 2.8–3.2 s（bf16 无原生支持，偏慢） |

---

## 2. 环境（已装好；重装时照抄）

```bash
cd /media/robot204/Disk1/Projects/lerobot
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  "lerobot[smolvla,dataset,hardware,feetech,intelrealsense]==0.6.1"
```

**不要**在本项目里执行 `uv sync` / `uv run`：根目录 `pyproject.toml` 还是 `uv init` 的空壳
（`requires-python = ">=3.14"`、`dependencies = []`），`uv sync` 会把上面装好的 lerobot 全部删掉。
要固定解释器就用 `.venv/bin/python` 或 `source .venv/bin/activate`。
（想让它可复现的话，正确做法是把 `requires-python` 改成 `>=3.12`、把依赖写进 `pyproject.toml`，
再用 `uv sync --inexact`——`--inexact` 保证不会删掉别的包。目前先别动，以免破坏可用环境。）

权重下载：

```bash
# 本机验证时把 HF 缓存放在项目内（约 7 GB，含 SmolVLM2 多份权重）；
# 不设的话会落到默认的 ~/.cache/huggingface，等于重新下一遍。
export HF_HOME=$PWD/.cache/hf

# 主权重 865 MB
.venv/bin/hf download lerobot/smolvla_base --local-dir models/smolvla_base

# SmolVLA 的视觉语言底座：首次 from_pretrained 会从 Hub 拉（约 1 GB），
# 内网/离线部署必须提前缓存；不会自动从 smolvla_base 目录里读。
.venv/bin/hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct
```

国内网络慢就加 `export HF_ENDPOINT=https://hf-mirror.com`；离线运行加 `export HF_HUB_OFFLINE=1`。

一条龙脚本：`bash scripts/setup_smolvla_env.sh`。

**验证**：

```bash
.venv/bin/python tools/smolvla_smoke_test.py --model models/smolvla_base --device cuda
```

看到 `OK：模型、pre/post-processor、动作输出链路都正常` 就说明环境没问题。

---

## 3. SmolVLA 的输入输出契约（决定 base 能不能直接用）

`lerobot/smolvla_base` 是在 SO-100/101 社区数据上训的，配置写死在权重里：

| 项 | 要求 |
| --- | --- |
| 状态 | `observation.state`，**6 维**（5 关节 + 夹爪） |
| 动作 | **6 维**，一次出 `chunk_size=50` 步，10 步去噪 |
| 相机 | `observation.images.camera1/2/3`，各 3×256×256（内部会 resize+pad 到 512×512） |
| 语言 | 一句任务描述（base 用英文训的，部署时也用英文） |

几个直接后果：

- **6 自由度以外的机械臂不能零样本跑**。Piper 7 维、ALOHA 14 维、双臂等都必须先微调；
  lerobot 0.6.1 内置机型里也**没有 Piper**（只有 so100/so101/koch/lekiwi/openarm 等）。
  Piper 的完整方案见 **[docs/smolvla_piper.md](smolvla_piper.md)**（用 `piper_lerobot` fork，7 维数据 + 正确微调写法）。
- 相机只有 2 路也能跑（缺的那路会被 mask 掉），但零样本效果会下降。
- 相机名字不必叫 `camera1/2/3`，用 `--rename_map` 映射即可（见 4.3）。
- **零样本基本不可用**：base 只在 SO-100 社区任务/场景上有效，换了桌高、相机位置、物体就要微调。
  正确路径是「采 30–50 条数据 → 微调 20k 步 → 部署」，见第 5 节。

---

## 4. 真机部署：`lerobot-rollout`

### 4.1 接线上电 + 校准

```bash
ls /dev/ttyACM*                              # 机械臂串口，插上才有
.venv/bin/lerobot-find-cameras realsense     # 列出 RealSense 序列号并抓图确认视角
.venv/bin/lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_arm
```

- 新机械臂第一次用还要跑 `lerobot-setup-motors`（写电机 ID/波特率）。
- `--robot.id` 是标定文件名，后续 rollout 必须用同一个 id。
- 串口权限：`sudo usermod -aG dialout $USER`，重新登录生效。

### 4.2 最小可跑命令（先架空、先别放物体）

```bash
.venv/bin/lerobot-rollout \
  --strategy.type=base \
  --policy.path=models/smolvla_base \
  --device=cuda \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 \
  --robot.id=my_arm \
  --robot.max_relative_target=5 \
  --robot.cameras='{
      camera1: {type: intelrealsense, serial_number_or_name: "254522072269", width: 640, height: 480, fps: 30},
      camera2: {type: intelrealsense, serial_number_or_name: "262422272748", width: 640, height: 480, fps: 30}
    }' \
  --task="pick up the cube and put it in the box" \
  --fps=30 \
  --duration=30 \
  --display_data=true
```

说明：

- `--strategy.type=base`：只跑策略、不录像。要录像/采数据换成 `episodic`（按 episode 存）或 `sentry`（持续录）。
- `--robot.max_relative_target=5`：限制每个控制周期最多动 5°，**第一次跑务必加**，防止模型输出乱飞。
- `--display_data=true` 会开 Rerun 看相机画面和动作（需要本机有显示）。
- `--duration` 秒后自动停，并且默认会平滑回到启动位姿（`--return_to_initial_position=true`）。
- 上面只给了 **2 路**相机（本机现在确实只有 D435i + D405）。base 期望 3 路，缺的那路会被
  mask 掉、能跑但效果打折；要正式部署请补第三路，或直接用自己的 2 路数据微调。

### 4.3 相机名不一致：`rename_map`

rollout 启动时会校验「策略要的视觉 key」和「机器人提供的 key」是否对得上，对不上会报
`Visual feature mismatch between policy and robot hardware`。两种解法：

1. 直接把相机命名成 `camera1/2/3`（推荐，上面就是这么写的）；
2. 保持你的硬件命名（`top`/`wrist`），加映射（**左边是机器人的 key，右边是策略的 key**）：

```bash
--rename_map='{"observation.images.top": "observation.images.camera1",
               "observation.images.wrist": "observation.images.camera2"}'
```

### 4.4 VLA 推理慢 → 开 RTC / torch.compile

SmolVLA 一次算 50 步、10 步去噪，稳态 0.40 s。开环执行 50 步期间机器人看不到新画面，
动作快了会「冲过头」。官方给慢 VLA 的解法是 Real-Time Chunking：

```bash
--inference.type=rtc --inference.rtc.execution_horizon=10
```

还可以加 `--use_torch_compile=true`（首次编译要几十秒到几分钟，之后更快；调试阶段先别开）。

### 4.5 跑微调后的策略

```bash
--policy.path=outputs/train/smolvla_so101_pick/checkpoints/last/pretrained_model
```

`lerobot-train` 的 checkpoint 目录结构：`checkpoints/<step>/pretrained_model`，`last` 是最新的软链接。

---

## 5. 微调（几乎必做）

### 5.1 采数据（`lerobot-record` 现在只干这个）

```bash
.venv/bin/lerobot-record \
  --robot.type=so101_follower --robot.port=/dev/ttyACM0 --robot.id=my_arm \
  --robot.cameras='{ ...和 4.2 完全一致，包括序列号和分辨率... }' \
  --teleop.type=so101_leader --teleop.port=/dev/ttyACM1 --teleop.id=my_leader \
  --dataset.repo_id=myuser/so101_pick_cube \
  --dataset.single_task="Pick up the blue cube and put it in the box" \
  --dataset.num_episodes=50 \
  --dataset.fps=30 \
  --dataset.push_to_hub=false
```

采集要求（直接决定微调效果）：

- **相机 key、顺序、安装位置**在采集和部署时必须完全一致；
- 每条 episode 从**同一个初始位姿**开始，任务描述**一字不差**；
- 30–50 条起步，场景/物体/光照要有变化，别只在一个位置重复；
- 采集结束必须 `finalize`（CLI 会自动做；自己写脚本采集时**必须调用 `dataset.finalize()`**，
  否则 `meta/episodes/` 缺失，训练时会去 Hub 找一个不存在的 repo 然后报 401）。

### 5.2 训练

```bash
.venv/bin/lerobot-train \
  --policy.path=lerobot/smolvla_base \
  --policy.repo_id=myuser/smolvla_so101_pick \
  --policy.push_to_hub=false \
  --policy.device=cuda \
  --dataset.repo_id=myuser/so101_pick_cube \
  --output_dir=outputs/train/smolvla_so101_pick \
  --job_name=smolvla_so101_pick \
  --batch_size=64 \
  --steps=20000 \
  --save_freq=2000 \
  --num_workers=4 \
  --wandb.enable=false
```

要点：

- `--policy.repo_id` **必须给**（base 的 config 里 `push_to_hub=true`，不给会报
  `'repo_id' argument missing`）；本地训练加 `--policy.push_to_hub=false`。
- 默认 `freeze_vision_encoder=true`、`train_expert_only=true`，只训 100M 参数，24 GB 显存很宽裕；
  数据量上万条再考虑解冻视觉塔。
- 学习率/调度器沿用 base 的预设（1e-4、cosine），一般不用动。
- 数据在本机：加 `--dataset.root=<本地数据集目录>`；repo_id 用 `local/xxx` 也可以。

### 5.3 部署

```bash
.venv/bin/lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/train/smolvla_so101_pick/checkpoints/last/pretrained_model \
  ...（同 4.2 的机器人参数）...
```

---

## 6. 性能与调参

| 场景 | 实测 | 建议 |
| --- | --- | --- |
| 推理（50 步 chunk） | 0.38–0.40 s / 7.5 ms 每步 | 30 Hz 余量很足；开 RTC 更稳 |
| 推理显存 | <1 GB | 单卡可跑；第二张卡可留给训练/其他服务 |
| 微调 batch=64 | 5.83 GB / 2.8–3.2 s 每 update | 11 GB 够用；慢是 Turing bf16 的问题，可用 2 卡 DDP |
| 权重加载 | 11.3 s（已缓存） | 首次要下 VLM（约 2 GB），网速慢时可能十几分钟 |

其它可调项：

- `--policy.n_action_steps` 调到 10–20：执行更短、闭环更频繁，但 GPU 调用次数增加（每次仍是 0.40 s）。
- `--fps`：采集和部署必须一致（数据集 fps 写死在 meta 里）。
- `--use_torch_compile=true`：延迟可再降，但首次编译慢，且改代码后要重新编译。

---

## 7. 排错表

| 现象 | 原因 / 解法 |
| --- | --- |
| `ImportError: 'datasets' is required` | 没装 extra：`uv pip install "lerobot[dataset]==0.6.1"`（本机已装） |
| `ImportError: 'feetech-servo-sdk' is required` | SO-101 电机 SDK 不在 `hardware` extra 里：`uv pip install "lerobot[feetech]==0.6.1"`（本机已装） |
| `Could not load ... libtorchcodec_core4.so` / `libavutil.so.56` | torchcodec 需要 FFmpeg 4，系统是 FFmpeg 6。lerobot 会自动回退 `pyav`，**不影响使用**，可忽略；想彻底消掉得装 FFmpeg 4（不推荐折腾） |
| 训练报 `RepositoryNotFoundError: ... /refs` (401) | 本地数据集 `meta/episodes/` 没写出来：采集脚本漏了 `dataset.finalize()` |
| 训练报 `'repo_id' argument missing` | 补 `--policy.repo_id=...`，本地训练加 `--policy.push_to_hub=false` |
| `Visual feature mismatch between policy and robot hardware` | 相机 key 对不上，改相机名或加 `--rename_map` |
| 动作维度不对 / 机械臂抖 | 机械臂不是 6 维 SO-100 构型 → 必须微调；临时先加 `--robot.max_relative_target` |
| `lerobot-record` 不认 `--policy.path` | 0.6.1 已拆分，用 `lerobot-rollout` |
| CUDA 不可用（只有在我这个 agent 沙箱里 `nvidia-smi` 会失败） | 你自己的终端里 `nvidia-smi` 正常即可；本机实测 2×2080 Ti 可用 |
| 串口 `Permission denied` | `sudo usermod -aG dialout $USER` 后重新登录 |
| 相机打不开 | `lerobot-find-cameras realsense` 确认序列号；D435i 是 USB2 口时带宽不够，换 USB3 |

---

## 8. 下一步（需要你确认）

1. **机械臂到底是哪一款？** 当前机器上没有 `/dev/ttyACM*`，只有 CAN 适配器和两台 RealSense。
   - 是 SO-101 → 上面命令可直接用，插上校准即可；
   - 是 Agilex Piper（CAN）→ 用 `piper_lerobot` fork，见 **[docs/smolvla_piper.md](smolvla_piper.md)**（已写好完整命令与 7 维踩坑说明）；
   - 是别的臂 → 告诉我自由度、关节顺序、控制接口。
2. **有没有已采好的数据集 / 已微调的 checkpoint？** 有的话直接进 5.3 部署，把路径给我。
3. **相机怎么装？** 现在 D435i + D405 两个，SmolVLA base 期望 3 路；要么补第三路，要么用 2 路微调。

---

## 附：文件

- `tools/smolvla_smoke_test.py` — 不接硬件的推理自检（加载 → 预处理 → 动作 → 延迟/显存）
- `scripts/setup_smolvla_env.sh` — 环境 + 权重一键安装
- `models/smolvla_base/` — 已下载的 base 权重
