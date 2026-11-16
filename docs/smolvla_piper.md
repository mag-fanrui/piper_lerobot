# Piper + SmolVLA 部署手册（基于 piper_lerobot）

> 这台机器上的事实（2026-11-05 实测）：
> - `piper_lerobot` 是 **lerobot 0.4.2 的 fork**，内置 `piper_follower`（CAN + 7 维关节）、`piper_leader`、
>   以及一套针对 Piper 的部署平滑层（EMA / retime / 插值 / 夹爪滤波 / 平滑 home）。
> - 它和本目录的 **lerobot 0.6.1** 环境**不能混装**（0.4.2 要求 `torch<2.8`、`transformers<5`、`draccus==0.10`），
>   必须用一个独立的 Python 3.10 环境。
> - **Piper 是 7 维动作**（6 关节 rad + 夹爪 m），而 `lerobot/smolvla_base` 是 6 维。直接 `--policy.path` 微调会踩坑，
>   正确写法见第 5 节（本机已实测两种写法的差异）。

---

## 0. 用哪个栈跑什么

| 环节 | 用哪个环境 | 命令 |
| --- | --- | --- |
| 采集 / 遥操作 / 真机部署 | `piper_lerobot`（0.4.2，独立 3.10 环境） | `lerobot-record`（0.4.x 支持 `--policy.path`） |
| SmolVLA 微调 | 同上（推荐，单一栈） | `lerobot-train --policy.type=smolvla --policy.pretrained_path=...` |
| 快速验证 / 仿真 / 新特性 | 本目录 0.6.1 环境 | 只用于 SmolVLA 本身的验证，不接 Piper |

> 0.6.1 里 `lerobot-record` 已经不接受 `--policy.path`（拆分成了 `lerobot-rollout`）。两套栈的命令**不能混用**。

---

## 1. 本机硬件现状

| 项 | 现状 |
| --- | --- |
| CAN | **只有一个 USB-CAN 适配器**，接口 `can_follower` 已 UP，1 Mbps |
| CAN 拓扑 | 主臂 + 从臂接在**同一条总线**上，固件主从联动（见 3.2）；不是两路 CAN |
| CAN 命名 | `piper_follower`/`piper_leader` 写死 `can_follower`/`can_master`；单总线请用 3.2 的只读插件 |
| 相机节点 | D435i：`/dev/video10` 是彩色（YUYV），`/dev/video8` 是 IR（GREY，录出来是灰白点阵）；D405：`/dev/video4` 彩色，`/dev/video2` IR |
| 相机别名 | **没有** `/dev/video_top` / `_wrist` / `_down`，要用真实节点或自己写 udev 规则 |
| 相机数量 | 只有 2 台物理相机（D405 + D435i）→ 采 2 路数据微调即可（不要硬凑 3 路） |
| 机械臂 | 两台 Piper（主 + 从）6 轴 + 夹爪，联动已开；当前总线只看到一套 0x2A 关节反馈 |

**一定要选 YUYV 的彩色节点**（`v4l2-ctl -d /dev/videoX --list-formats` 看第一个格式）：
选到 GREY/IR 节点时，画面会是灰白点阵或纯噪声，看起来就像"画面丢了"。
当前可用的彩色节点是 `video10`（D435i，俯视）和 `video4`（D405，腕部），插件脚本已按这个组合设默认值。
`outputs/captured_images/` 里有 4 个节点的截图可以直接对比。

---

## 2. 环境 + CAN

### 2.1 独立环境（Python 3.10）

```bash
cd /media/robot204/Disk1/Projects/piper_lerobot

uv venv --python 3.10 .venv

# GPU 版 torch（先单独装，避免 pip 解析到别的 CUDA 版本）
uv pip install --python .venv/bin/python torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu126

# Piper 驱动 + SmolVLA 依赖
uv pip install --python .venv/bin/python -e ".[piper,smolvla]"

# 自检
.venv/bin/python -c "import lerobot, piper_sdk, torch; print(lerobot.__version__, torch.__version__, torch.cuda.is_available())"
```

一条龙脚本（会创建 `piper_lerobot/.venv`，约 4–6 GB）：
`bash /media/robot204/Disk1/Projects/lerobot/scripts/setup_piper_env.sh`

### 2.2 CAN 接口改名（代码里固定 `can_follower`）

当前系统里只有 `can0`，Piper 驱动连的是 `can_follower`。两种做法：

```bash
# A. 临时改名（重启失效）
sudo ip link set can0 down
sudo ip link set can0 name can_follower
sudo ip link set can_follower type can bitrate 1000000
sudo ip link set can_follower up

# B. 用仓库自带脚本 + udev 规则（长期）
cd /media/robot204/Disk1/Projects/piper_lerobot
bash find_all_can_port.sh      # 看 USB 地址
bash can_activate.sh can_follower 1000000 "<USB地址>"
```

> 有主臂时再加一个适配器，命名为 `can_master`；只有从臂时 `can_follower` 一个就够。

### 2.3 先确认能读状态（不发动作）

```bash
.venv/bin/python - <<'EOF'
from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig
bus = PiperMotorsBus(PiperMotorsBusConfig("can_follower", {f"joint_{i}": (i, "agilex_piper") for i in range(1, 7)} | {"gripper": (7, "agilex_piper")}))
print(bus.read())
EOF
```

---

## 3. 采数据（`lerobot-record`）

> **你的机器是单总线主从联动，请直接跳到 3.2 用只读插件采集。**
> 下面 3.0 这段适用于「主臂 `can_master` + 从臂 `can_follower` 两路独立 CAN」的拓扑。

```bash
.venv/bin/lerobot-record \
  --robot.type=piper_follower \
  --robot.cameras='{
      top:   {type: opencv, index_or_path: /dev/video10,  width: 640, height: 480, fps: 30},
      wrist: {type: opencv, index_or_path: /dev/video4,  width: 640, height: 480, fps: 30}
    }' \
  --robot.deployment.start_from=current \
  --robot.deployment.stop_at=hold \
  --robot.record_action_from_follower=true \
  --teleop.type=piper_leader \
  --dataset.repo_id=myuser/piper_pick_red_block \
  --dataset.single_task="Pick up the red block and put it in the tray." \
  --dataset.num_episodes=50 \
  --dataset.fps=30 \
  --dataset.push_to_hub=false \
  --display_data=true
```

要点：

- **必须有主臂**：`lerobot-record` 要求 `--teleop` 或 `--policy` 至少给一个，纯 `--robot` 会报
  `Choose a policy, a teleoperator or both to control the robot`。Piper 的主臂用 `--teleop.type=piper_leader`，
  它内部固定读 `can_master`（第二个 USB-CAN 适配器 + 第二台 Piper）。只有从臂时无法用这种方式采集。
- `lerobot-record` **没有** `--dataset.video_backend` 这个参数（它是训练/解码侧的参数）。录像用的是 PyAV，不受影响；
  如果 torchcodec 在训练/回放时报 FFmpeg 错误，见 5.2 和排错表。
- `--robot.deployment.start_from=current` / `stop_at=hold`：**不要用默认值**。默认 `start_from=home` 且
  `home_position=(0,0,0,0,0,0,0)`，连接瞬间会把机械臂往全零位姿拉，第一次上电很危险。
- `record_action_from_follower=true`（仓库默认）：数据集里的 `action` 是发指令后从臂读回的关节，训练时保持一致即可。
- 相机 key（top/wrist）在采集和部署时必须一致；换相机/换机位后要重新采。
- `--robot.cameras` 按 YAML 解析：**冒号后必须有空格**（`type: opencv`、`index_or_path: /dev/video10`）。
  写成 `type:opencv` 会被 YAML 当成键名 `"type:opencv"`，报
  `Expected a dict with a 'type' key ... got {'type:opencv': None, ...}`。也可以用 JSON 写法：
  `'{"top": {"type": "opencv", "index_or_path": "/dev/video10", "width": 640, "height": 480, "fps": 30}}'`。
- `--dataset.single_task` 会写进数据集，部署时必须**一字不差**（SmolVLA 用它做语言条件）；base 是英文训练的，
  用英文描述，例如 `"Pick up the red block and put it in the tray."`。
- 只采 2 路也没问题：SmolVLA 的输入特征会从数据集推断（见 5.1）。

### 3.1 采数据时实时看相机画面

两种方式，按场景选：

**A. 采集中看（推荐）——加 `--display_data=true`，用 Rerun**

```bash
source .venv/bin/activate          # 关键：否则 rr.spawn() 找不到 rerun 可执行文件，只会打印 installing-viewer 提示
lerobot-record ... --display_data=true
```

窗口里左侧选 `observation/images/top`、`observation/images/wrist` 就能看到实时画面，关节量和动作曲线也在同一时间轴上。
Rerun 和采集在**同一个进程**里，不会抢占 `/dev/videoX`。

**B. 采集前单独确认机位——`lerobot-find-cameras`**

```bash
.venv/bin/lerobot-find-cameras opencv    # 列出可用节点并把截图存到 outputs/captured_images/
```

注意：

- **不要**在 `lerobot-record` 运行期间另开一个 OpenCV 预览进程读同一个 `/dev/videoX`：V4L2 设备是独占的，
  会打不开或大量掉帧。要看就只用 Rerun。
- Rerun 卡顿/占内存太多时：`export LEROBOT_RERUN_MEMORY_LIMIT=20%`，或直接 `--display_data=false`，
  采完用 `lerobot-dataset-viz --repo-id=... --root=...` 回放检查。
- 无显示器的机器（SSH）：本地窗口方案不可用，用 `rerun --serve-web --bind 0.0.0.0 --port 9876` 起 web viewer，
  或在采集机上关掉显示、拷贝数据集回来回放。

### 3.2 单总线主从联动（你现在这台机器的拓扑）

> 这是本机实际情况：**主臂 + 从臂接在同一个 USB-CAN 适配器上**（只有一个 `can_follower`），
> 从臂跟随主臂由机械臂固件完成，不是靠电脑发指令。
> 这种拓扑下不能用 `piper_follower` / `piper_leader`：它们会打开 `can_follower`/`can_master` 并使能、回零、
> 退出时还会 disable，等于和固件联动打架。

用只读插件 `piper_linkage_plugin/`（在 `lerobot` 项目下）：

| 组件 | 作用 |
| --- | --- |
| `--robot.type=piper_linkage` | 只读关节反馈（0x2Ax）+ 相机；`send_action` 不写 CAN；不使能、不回零 |
| `--teleop.type=piper_linkage_leader` | 只读主臂位姿当 action；不 enable、不 calibrate、退出不 disable |
| `--robot.state_delay_frames` | 总线上只有主臂反馈，用「N 帧前的主臂位姿」当 `observation.state`，近似从臂跟随滞后（默认 4 帧≈133 ms） |

一键采集（脚本会自己 `source .venv/bin/activate` 并设置 `PYTHONPATH`）：

```bash
bash /media/robot204/Disk1/Projects/lerobot/scripts/record_piper_linkage.sh

# 常用覆盖
REPO_ID=me/piper_pick_red_block EPISODES=50 TASK="Pick up the red block and put it in the tray." \
TOP_CAM=/dev/video10 WRIST_CAM=/dev/video4 bash .../record_piper_linkage.sh
```

脚本做的事：`--robot.type=piper_linkage --teleop.type=piper_linkage_leader`，两个相机，30 fps，
`episode_time_s=30`、`reset_time_s=10`，数据集写到 `$HF_LEROBOT_HOME/<repo_id>`；
脚本默认把 `HF_LEROBOT_HOME` 设为 **`/media/robot204/Disk1/lerobot_data`**，可用同名环境变量覆盖。

已经在本机验证过（不动机器人、只读）：注册成功、读到 7 维主臂位姿、录了 90 帧 30fps 数据集
（`observation.state` 7 维、`action` 7 维、`observation.images.top/wrist`），全程没有向 CAN 写一帧运动指令。

注意：

- 采集时你只拖主臂，从臂自己跟；逐条操作见 **3.3**。
- `state_delay_frames` 是这套拓扑的近似：真正理想的是读从臂反馈（`0x2Bx`），但当前总线上只有一套
  0x2A 反馈。如果以后从臂反馈能出来，改成读从臂即可（我可以再改插件）。
- 部署策略时相反：要先把联动关掉（AgileX app 里退出主从/示教模式），让从臂回到默认地址，
  再用第 6 节的 `piper_follower`（它会正常使能并写 CAN）。

### 3.2.1 视频编码（已改为 h264，快约 10 倍）

本机把 `piper_lerobot` 的视频编码从默认的 **SVT-AV1（libsvtav1）** 改成了 **h264（libx264, preset=veryfast, crf=23）**：

- 编码速度约 **10 倍**（实测 300 帧：7.0 s → 0.61 s）；
- 每条 episode 保存等待从 5–15 s 降到 **1–2 s**；
- `delete_episodes` 清理 21→18 条从 10+ 分钟降到 **1 分 07 秒**；
- 代价是文件体积约 **+20%**（对训练无影响）。

改动位置（重装/重新 clone 仓库会丢失，需要重新打）：

| 文件 | 改动 |
| --- | --- |
| `lerobot/datasets/video_utils.py` | `encode_video_frames()` 默认 `vcodec="h264"`, `g=30`, `crf=23`, 并加 `preset=veryfast` |
| `lerobot/datasets/dataset_tools.py` | `_keep_episodes_from_video_with_av()` / `_copy_and_reindex_videos()` 默认 h264 + 同样的 options |

> 注意：codec 必须整个数据集一致（拼接用 stream copy）。不要只改一半，否则 `--resume` 追加会花屏。

### 3.2.2 固定起始位姿（home2）

采集时每条从同一个位姿开始能明显提升数据质量（见第 8 节“初始位姿”说明）。用法：

```bash
# 把主臂拖到目标位姿，记录成 home2
.venv/bin/python tools/piper_pose.py save home2      # 用 piper_lerobot 的 venv 跑

# 采集过程中另开一个终端，实时看偏差；|Δ| ≤ 0.05 rad 显示 OK
.venv/bin/python tools/piper_pose.py check home2

# 查看已保存位姿（会打印可直接复制的 JSON 数组）
.venv/bin/python tools/piper_pose.py list
```

也可以开一个**独立的监控页面**（只读 CAN，可与录制同时跑）：

```bash
bash scripts/pose_monitor.sh                  # http://127.0.0.1:8100
bash scripts/pose_monitor.sh --name home2 --tolerance 0.03 --port 8101
```

页面顶部是大号状态条：绿色 `OK — 已对齐` / 黄色 `接近` / 红色 `偏离较大`，
下面每个关节一条偏差条（蓝→绿/黄/红），并显示最大偏差（rad 与角度）。

位姿保存在 `configs/piper_poses.json`。主从联动模式下机械臂只能靠手拖，
所以这是“对齐提示”，不是自动回位；部署时可以把 `home2` 的 JSON 填进
`HOME_POSITION`，让策略跑完回这个位姿。

### 3.3 逐条录制（按键 + 一跑一条两种用法）

0.4.2 的 `lerobot-record` 只有三个按键（`pynput` 全局监听，焦点在哪个窗口都行）：

| 键 | episode 录制中 | 复位阶段（reset_time_s） |
| --- | --- | --- |
| `→` | 结束当前 episode（提前收工） | 结束复位，**立刻开始录下一条** |
| `←` | 丢弃当前 episode，复位后重录 | 丢弃刚录完的这条，重录 |
| `Esc` | 结束并**保存当前这条（可能是半截的）**，退出 | 保存刚录完的这条，退出 |

> 注意：**录制中按 `Esc` 会把不完整的那条也存进数据集**。想丢掉当前这条，先按 `←`，再在复位阶段按 `Esc`。
> 另外这个版本没有 `r` 键，重录就是 `←`。

#### 用法 A：一次跑完，靠箭头逐条控制（推荐）

```bash
cd ~/Data1/Projects/piper_lerobot
EPISODE_TIME_S=30 RESET_TIME_S=30 bash /media/robot204/Disk1/Projects/lerobot/scripts/record_piper_linkage.sh
```

节奏：

1. 终端出现 `Recording episode N` → 拖主臂把橡皮捡起来 → 完成后按 `→`（不按也行，30 s 到点自动结束）；
2. 进入复位阶段（这期间**不写数据**）：把橡皮放回、主臂回到起始位；
3. 摆好后按 `→` → 下一条立刻开始录；
4. 做坏了：录制中按 `←`，这条丢弃，复位后重录同一条；
5. 全部录完：在复位阶段按 `Esc` 保存并退出（不要在录制中按 Esc）。

`reset_time_s=30` 是上限，摆好了随时按 `→` 提前开始下一条；手慢就调大。

#### 用法 B：一条一跑，逐条检查再追加（更稳，但慢）

```bash
# 第 1 条
EPISODES=1 bash /media/robot204/Disk1/Projects/lerobot/scripts/record_piper_linkage.sh

# 回放检查这一条
.venv/bin/lerobot-dataset-viz --repo-id=myuser/piper_pick_red_block \
  --root /media/robot204/Disk1/lerobot_data/myuser/piper_pick_red_block

# 满意就追加下一条（--resume=true 会往同一个数据集里追加）
EPISODES=1 RESUME=true bash /media/robot204/Disk1/Projects/lerobot/scripts/record_piper_linkage.sh
```

- 每次运行会重新打开相机/Rerun，多花十几秒；
- `--resume` 会校验 robot 类型、特征、fps 与已有数据集一致，所以相机和 `state_delay_frames` 不要中途改；
- 本机已验证「录 1 条 → 再 resume 录 1 条」→ 数据集 `total_episodes=2`。

---

### 3.4 用网页按钮控制（Rerun 保持打开）

Rerun 本身没有可点击的按钮，所以做了一个本地控制面板：它直接改 `lerobot-record` 的事件字典
（不是伪造按键），并实时读取录制阶段。Rerun 窗口可以一直开着。

```bash
cd ~/Data1/Projects/piper_lerobot
bash /media/robot204/Disk1/Projects/lerobot/scripts/record_piper_ui.sh
# 浏览器打开 http://127.0.0.1:8099
```

页面顶部是一条**阶段横幅**，颜色和文案随录制状态变化：

| 阶段 | 显示 | 可点的按钮 |
| --- | --- | --- |
| `recording` | 绿色闪烁「● 录制中 —— 可以开始动作」 | 完成本条 / 重录 / 停止 |
| `reset` | 橙色「◼ 复位中 —— 摆好物体后点开始下一条」 | 开始下一条 / 重录 / 停止 |
| `saving` | 蓝色「⏳ 保存中（编码视频）」 | 停止 |
| `done` | 灰色「✔ 已完成」 | — |

- 「完成本条」和「开始下一条」是**两个独立按钮**，只在对应阶段可点，避免误触；
- 每次切到「录制中」，横幅会闪绿并**响一声**（浏览器音频，需要先点过任意按钮解锁），
  提醒你可以开始动作；
- 面板同时显示 `已录 N 条 / 最近操作`。

局域网内用另一台设备点：`UI_HOST=0.0.0.0 bash scripts/record_piper_ui.sh`，
然后开 `http://<机器人IP>:8099`。

注意：

- 启动后先等横幅从「未就绪」变成「录制中」（约 15 s，相机+模型初始化）；
- `saving` 阶段是在编码上一条视频（2 路 30 s 约 5–15 s），等横幅重新变绿再动；
- 键盘 `→ / ← / Esc` 仍然可用，面板只是多一种输入方式；
- 不要把 `UI_HOST=0.0.0.0` 暴露到公网。

---

## 4. 先做一遍纯软件验证（不接臂）

```bash
cd /media/robot204/Disk1/Projects/piper_lerobot
.venv/bin/python - <<'EOF'
import torch
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors

ck = "/media/robot204/Disk1/Projects/lerobot/models/smolvla_base"
policy = SmolVLAPolicy.from_pretrained(ck).eval()
print("params(M)", sum(p.numel() for p in policy.parameters()) / 1e6)
print("state dims", policy.config.input_features["observation.state"].shape)
print("action dims", policy.config.output_features["action"].shape)
EOF
```

---

## 5. 微调 SmolVLA（关键：6 维 vs 7 维）

### 5.1 两种写法，只有一种对

| 写法 | 结果（本机实测） |
| --- | --- |
| `--policy.path=lerobot/smolvla_base` | 保留 base 的 6 维 `input_features`。训练能跑，但保存的 checkpoint 仍是 6 维，**推理时报 `size of tensor a (6) must match the size of tensor b (7)`** |
| `--policy.type=smolvla --policy.pretrained_path=<base 目录>` | 特征从你的数据集推断（7 维 / 你实际的相机数），权重从 base 加载，**训练 + 推理都正常**（实测动作输出 7 维） |

原因：lerobot 在 `make_policy` 里只用数据集覆盖 `output_features`，`input_features` 非空时保留 checkpoint 里的值。

### 5.2 训练命令（在 piper_lerobot 环境里）

```bash
cd /media/robot204/Disk1/Projects/piper_lerobot
.venv/bin/lerobot-train \
  --policy.type=smolvla \
  --policy.pretrained_path=/media/robot204/Disk1/Projects/lerobot/models/smolvla_base \
  --policy.repo_id=myuser/smolvla_piper_red_block \
  --policy.push_to_hub=false \
  --policy.device=cuda \
  --dataset.repo_id=myuser/piper_pick_red_block \
  --dataset.video_backend=pyav \
  --output_dir=outputs/train/smolvla_piper_red_block \
  --job_name=smolvla_piper_red_block \
  --batch_size=64 \
  --steps=20000 \
  --save_freq=2000 \
  --num_workers=4 \
  --wandb.enable=false
```

- 本机现在是 **2×RTX 2080 Ti 11 GB**：batch 64 峰值显存约 **5.8 GB**，单卡能训；但 Turing 没有原生 bf16，
  update 约 **2.8–3.2 s**（20k 步单卡 ≈15 h），建议 2 卡 DDP（每卡 batch 32）或放服务器训；
- 只训 100M 参数（专家层 + 状态投影），20k 步量级即可；
- 本机已在 `piper_lerobot` 的 0.4.2 环境实测：加载 base → 1 步训练（7 维）→ 保存（config/预处理器均为 7 维）→
  重新加载成功；0.6.1 环境（GPU，2080 Ti）上 7 维 checkpoint 推理 0.38–0.40 s / 50 步。
- `--policy.repo_id` 必须给（base config 里 `push_to_hub=true`），本地训练记得 `--policy.push_to_hub=false`。
- 数据集在 Disk1 时：`export HF_LEROBOT_HOME=/media/robot204/Disk1/lerobot_data`，
  或者显式加 `--dataset.root=/media/robot204/Disk1/lerobot_data/<repo_id>`。

### 5.3 用 0.6.1 环境微调（可选）

本目录 0.6.1 的 SmolVLA 同样支持 7 维，只是采数据和部署必须在 0.4.2 那边，跨栈要手工搬数据集；
不推荐混用，除非你想用 0.6.1 的 `lerobot-rollout`（那还需要把 Piper 驱动移植过去）。

---

## 6. 真机部署（`lerobot-record --policy.path`，0.4.x 写法）

> **前置条件**：策略执行时不能还处在主从联动模式。先在 AgileX app 里退出主从/示教联动，
> 让从臂回到默认 CAN 地址（0x2A），否则 `piper_follower` 的使能/写指令会和固件联动冲突。
> 采集阶段（3.2）则相反，保持联动、只读不写。

### 6.1 第一次：只算不写（dry run）

```bash
cd /media/robot204/Disk1/Projects/piper_lerobot
.venv/bin/lerobot-record \
  --robot.type=piper_follower \
  --robot.cameras='{ top: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30},
                     wrist: {type: opencv, index_or_path: /dev/video4, width: 640, height: 480, fps: 30} }' \
  --robot.deployment.start_from=current \
  --robot.deployment.stop_at=hold \
  --robot.deployment.disable_action_write=true \
  --policy.path=outputs/train/smolvla_piper_red_block/checkpoints/last/pretrained_model \
  --dataset.repo_id=myuser/eval_piper_red_block_dry \
  --dataset.single_task="Pick up the red block and put it in the tray." \
  --display_data=true
```

看日志里的动作维度（7）、数值范围、延迟都正常，再进 6.2。

### 6.2 真实执行

```bash
.venv/bin/lerobot-record \
  --robot.type=piper_follower \
  --robot.cameras='{
      top:   {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30},
      wrist: {type: opencv, index_or_path: /dev/video4, width: 640, height: 480, fps: 30}
    }' \
  --robot.deployment.start_from=current \
  --robot.deployment.stop_at=hold \
  --robot.deployment.max_joint_step_rad=0.05 \
  --robot.deployment.gripper.enabled=true \
  --policy.path=outputs/train/smolvla_piper_red_block/checkpoints/last/pretrained_model \
  --dataset.repo_id=myuser/eval_piper_red_block \
  --dataset.single_task="Pick up the red block and put it in the tray." \
  --display_data=true
```

- 急停可达、先低速（`max_joint_step_rad`）、先空场；
- 默认 `stop_at=home` 会平滑回 `home_position`，确认这个位姿是真的安全位再开；
- 夹爪单位是米（行程量级），`deployment.gripper` 的阈值按实际行程调（仓库 doc 有默认值）。
- 想启用 RTC / 异步 chunk：`--policy.rtc_config.enabled=true`（以及 `--robot.deployment.async_buffer.*`），
  先跑通同步模式再开。

---

## 6.3 把推理放到服务器（可选）

piper_lerobot 自带 gRPC 异步推理：GPU 服务器跑 policy，机器人本地只做「采图 + 采关节 + 执行动作」。

```bash
# A. 服务器（GPU 机器，仓库版本必须和机器人端一致；checkpoint 要放在服务器上）
python -m lerobot.async_inference.policy_server \
  --host=0.0.0.0 --port=8080 --fps=30 --inference_latency=0.10 --obs_queue_timeout=1

# B. 机器人本地（client）
python -m lerobot.async_inference.robot_client \
  --server_address=192.168.1.50:8080 \
  --robot.type=piper_follower --robot.cameras='{...和训练一致...}' \
  --robot.deployment.start_from=current --robot.deployment.stop_at=hold \
  --robot.deployment.async_buffer.enabled=true \
  --robot.deployment.async_buffer.delay=3 \
  --robot.deployment.async_buffer.exec_horizon=40 \
  --task="Pick up the red block and put it in the tray." \
  --policy_type=smolvla \
  --pretrained_name_or_path=/data/models/smolvla_piper_red_block/checkpoints/last/pretrained_model \
  --policy_device=cuda --actions_per_chunk=50 --fps=30 --chunk_size_threshold=0.5
```

关键约束（SmolVLA，30 Hz）：

| 项 | 数值 | 含义 |
| --- | --- | --- |
| 一个 chunk | 50 步 = **1.67 s** | 机器人每次拿到 1.67 s 的动作 |
| 2080 Ti 推理 | **0.40 s** | 本机实测 0.38–0.40 s/chunk（7.5–7.9 ms/步） |
| 剩余余量 | **~1.25 s** | 本地推理余量很足；服务器方案里网络往返 + 排队要小于它 |
| 观测带宽 | 2 路 640×480 原始图 ≈ 1.8 MB/次，约 1 次/秒 | ≈15 Mbps，千兆有线没问题，WiFi 要实测 |

建议：**同一有线 LAN**（RTT < 20 ms）；`--chunk_size_threshold` 调大（如 0.7）可以更早请求下一块；
本地 2080 Ti 已有 1.2 s 余量，服务器方案主要是为了把训练/推理集中管理，不是为了提速。公网/VPN 跨地域不建议做闭环。

注意：

- 推理时必须**退出主从联动**，用 `piper_follower`（要能写 CAN）；3.2 的只读插件只用于采集。
- 断网/服务器挂掉时动作队列会取空抛异常，机器人会停住而不是平滑停下；务必保留急停，并把
  `deployment.stop_at=hold` 配好。
- 不要直接把 8080 暴露到公网，用 SSH 隧道（`ssh -L 8080:127.0.0.1:8080 user@server -N`）或内网。
- 如果机器人这台机器本身就有 2080 Ti，**本地推理更简单也够快**（0.40 s/chunk，无网络）；服务器更适合训练，
  训练完把 checkpoint 同步到本地即可。

---

## 6.4 部署训练好的 checkpoint（本机脚本）

训练产物放到 `/media/robot204/Disk1/Projects/smolvla_deploy/checkpoints/<step>/pretrained_model` 后：

```bash
# 干跑：只算不写（机械臂不动）
bash /media/robot204/Disk1/Projects/lerobot/scripts/deploy_piper.sh

# 真跑：会二次确认
DRY_RUN=false bash /media/robot204/Disk1/Projects/lerobot/scripts/deploy_piper.sh
```

默认参数（都可用环境变量覆盖）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CKPT` | `.../checkpoints/015000/pretrained_model` | 换 010000 直接覆盖 |
| `MAX_STEP_RAD` | **0.1** | 每控制周期最大关节变化（rad） |
| `DRY_RUN` | `true` | `false` 才真正写 CAN |
| `EPISODES` / `EPISODE_TIME_S` | 1 / 60 | eval 录制条数与时长 |
| `START_FROM` | **home** | 连接后先去 `HOME_POSITION`（`current` = 原地开始） |
| `STOP_AT` | **home** | 结束时平滑回 `HOME_POSITION`（`hold` = 原地保持） |
| `POSE_NAME` / `HOME_POSITION` | **home2** | 默认读 `configs/piper_poses.json` 里的 home2；也可直接给 7 个数覆盖 |
| `HOME_STEPS` / `HOME_HZ` | 20 / 10 | 线性插值 20 步、10 Hz，约 2 秒走完 |
| `keep_enabled_on_disconnect` | **true** | 回零后保持使能、**不失能** |

前置条件：AgileX app 里退出主从联动、从臂单臂可控；主臂断电/移开；`top=/dev/video10`、`wrist=/dev/video4`；
任务字符串与训练时一字不差（当前脚本默认 `"Pick up the block and put it in the tray."`）。

> 注意：真跑时连接后会先平滑移动到 home2（约 2 秒），结束再回 home2；干跑不写 CAN，**不会动**。
> 若 `configs/piper_poses.json` 里没有 home2，才退回全零位（伸直姿态，确认不撞桌子/相机）；
> 想用实测安全位姿，把主臂拖到目标位姿后用只读插件读一次关节值，填进 `HOME_POSITION`。
> 干跑（`DRY_RUN=true`）时 `home` 写入也会被 `disable_action_write` 抑制，**不会动**，只有真跑才会回零。

> `keep_enabled_on_disconnect=true` 是本机对 `piper_follower` 打的补丁（`deployment.py` + `piper_follower.py`），
> 重新 clone 仓库会丢失。

---

## 7. 排错

| 现象 | 原因 / 解决 |
| --- | --- |
| `size of tensor a (6) must match ... b (7)` | 用了 `--policy.path` 微调；改成 `--policy.type + --policy.pretrained_path`（5.1） |
| `libavutil.so.57 / .56 not found` | 解码时 torchcodec 和系统 FFmpeg 不匹配。`lerobot-record` 没有这个参数（录像走 PyAV，不受影响）；训练/回放时加 `--dataset.video_backend=pyav`，或 `uv pip uninstall torchcodec` 让它全局回退 PyAV |
| 连不上 CAN / `can_follower` 不存在 | 系统里叫 `can0`，按 2.2 改名 |
| 相机打不开 | 用 `/dev/videoX` 真实节点（先 `lerobot-find-cameras opencv` 确认），或写 udev 规则固定 |
| 一启动机械臂就往零位跑 | `deployment.start_from=home` + `home_position` 全 0 的默认值；改 `current`/`hold` |
| `ImportError: piper_sdk` | 环境没装 `[piper]` extra |
| 训练报 Hub 401 / `RepositoryNotFound` | 本地数据集 `meta/episodes` 缺失，或 repo 不存在；检查采集是否正常结束（dataset 要 finalize） |

---

## 8. 后续可选项

1. **把 Piper 驱动移植到 0.6.1**：这样能用 `lerobot-rollout` + RTC + 新数据集特性；工作量在
   `piper_follower` / `motors/piper` / `piper_leader` 的 API 适配，需要硬件回归。
2. **3 路相机**：补一台相机后重新采数据，SmolVLA 会自动用 3 路特征（不需要改模型）。
3. **EEF 模式**：仓库预留了 8 维 EEF + IK adapter，等接入 Piper URDF 后可用。
