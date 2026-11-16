#!/usr/bin/env python
"""SmolVLA 推理冒烟测试：不接机器人也能确认模型/权重/预处理链路是通的。

用法::

    .venv/bin/python tools/smolvla_smoke_test.py                       # 默认 models/smolvla_base + cuda
    .venv/bin/python tools/smolvla_smoke_test.py --device cpu          # 没有 GPU 时
    .venv/bin/python tools/smolvla_smoke_test.py --model lerobot/smolvla_base

它会：
  1. 加载 policy（本地目录或 Hub repo id 都行）；
  2. 按 checkpoint 自己的 input_features 造一份随机观测（state + camera1..3 + task）；
  3. 走一遍官方的 pre-processor -> select_action -> post-processor 流程；
  4. 打印首帧延迟（一个 50 步 chunk）、排队步延迟、动作范围、显存占用。

随机图像没有任何语义，输出动作也没有意义；这个脚本只验证「链路能跑通 + 延迟/显存」。
"""

from __future__ import annotations

import argparse
import time

import torch

from lerobot.configs import FeatureType
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model",
        default="models/smolvla_base",
        help="本地权重目录或 Hub repo id（默认 models/smolvla_base）",
    )
    parser.add_argument("--device", default="auto", help="cuda / cpu / auto（默认 auto）")
    parser.add_argument(
        "--task",
        default="pick up the lego brick and put it in the box",
        help="语言指令；base 权重是英文训练的，用英文",
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def build_random_batch(policy: SmolVLAPolicy, task: str) -> dict:
    batch: dict = {"task": [task]}
    for key, feat in policy.config.input_features.items():
        shape = tuple(feat.shape)
        if feat.type == FeatureType.VISUAL:
            # (1, C, H, W)，像素范围 [0, 1]
            batch[key] = torch.rand(1, *shape)
        elif feat.type == FeatureType.STATE:
            # 关节角量级，随便给一个 ±1 的范围
            batch[key] = torch.rand(1, *shape) * 2.0 - 1.0
    return batch


def main() -> None:
    args = parse_args()
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)

    print(f"[1/4] 加载 policy: {args.model} -> {device}")
    t0 = time.perf_counter()
    policy = SmolVLAPolicy.from_pretrained(args.model).to(device).eval()
    load_s = time.perf_counter() - t0
    n_params = sum(p.numel() for p in policy.parameters())
    print(f"      完成：{load_s:.1f}s，{n_params / 1e6:.0f}M 参数")

    print("[2/4] 构建预处理/后处理管线")
    preprocess, postprocess = make_pre_post_processors(
        policy.config,
        args.model,
        preprocessor_overrides={"device_processor": {"device": device}},
    )
    batch = preprocess(build_random_batch(policy, args.task))
    print(f"      batch keys: {[k for k in batch if k.startswith('observation')]}")

    print("[3/4] 推理")
    with torch.inference_mode():
        t0 = time.perf_counter()
        action = policy.select_action(batch)  # 第一次会一次性算完 n_action_steps 步
        if device == "cuda":
            torch.cuda.synchronize()
        chunk_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        action2 = policy.select_action(batch)  # 后续从队列里取，几乎不耗算力
        if device == "cuda":
            torch.cuda.synchronize()
        queued_s = time.perf_counter() - t0

    action = postprocess(action)
    n_steps = getattr(policy.config, "n_action_steps", 1)
    print(f"      首帧（chunk {n_steps} 步）: {chunk_s:.2f}s -> 均摊 {chunk_s / n_steps * 1000:.1f} ms/步")
    print(f"      队列取步: {queued_s * 1000:.1f} ms")
    print(f"      动作 shape={tuple(action.shape)} 范围=[{action.min():.3f}, {action.max():.3f}]")

    print("[4/4] 资源")
    if device == "cuda":
        print(f"      显存 allocated={torch.cuda.memory_allocated() / 2**20:.0f} MiB，"
              f"peak={torch.cuda.max_memory_allocated() / 2**20:.0f} MiB")
        print(f"      设备：{torch.cuda.get_device_name(0)}")
    else:
        print("      CPU 推理：能跑通，但每步通常要几百毫秒，真机 30Hz 控制请用 GPU")

    print("\nOK：模型、pre/post-processor、动作输出链路都正常。")


if __name__ == "__main__":
    main()
