"""共享的 Piper CAN 读取总线（只读，不使能、不发运动指令）。

用于「主从联动」拓扑：主臂和从臂接在同一个 USB-CAN 适配器（同一个 can 接口）上，
由机械臂固件完成 主臂→从臂 的跟随。上层只需要读 0x2Ax 的关节反馈，
绝不能在这个总线上发 EnablePiper / DisableArm / JointCtrl。
"""

from __future__ import annotations

import threading

from lerobot.motors.piper.piper import PiperMotorsBus, PiperMotorsBusConfig

JOINT_KEYS = [f"joint_{index}.pos" for index in range(1, 7)] + ["gripper.pos"]

_MOTORS = {
    **{f"joint_{index}": (index, "agilex_piper") for index in range(1, 7)},
    "gripper": (7, "agilex_piper"),
}

_BUSES: dict[str, PiperMotorsBus] = {}
_LOCK = threading.Lock()


def get_bus(can_name: str = "can_follower") -> PiperMotorsBus:
    """同一个 can 接口只创建一个 SDK 实例，robot 和 teleop 共用。"""
    with _LOCK:
        if can_name not in _BUSES:
            _BUSES[can_name] = PiperMotorsBus(PiperMotorsBusConfig(can_name, dict(_MOTORS)))
        return _BUSES[can_name]
