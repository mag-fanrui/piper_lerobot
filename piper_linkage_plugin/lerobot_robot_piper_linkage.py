"""只读的 Piper 观测机器人（用于主从联动拓扑）。

- 只读 CAN 关节反馈 + 相机，**不向 CAN 写任何运动指令**；
- send_action 原样返回动作，供 dataset 记录；
- 从臂的跟随由机械臂固件（主从联动）完成。

因为模块名以 `lerobot_robot_` 开头，`lerobot-record` 启动时的
`register_third_party_devices()` 会自动导入并注册 `--robot.type=piper_linkage`。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig
from lerobot.cameras.utils import make_cameras_from_configs
from lerobot.motors.piper.piper import action_pos_dict_from_piper_read
from lerobot.robots import Robot, RobotConfig
from lerobot.utils.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError

from lerobot_piper_linkage_bus import JOINT_KEYS, get_bus


@RobotConfig.register_subclass("piper_linkage")
@dataclass
class PiperLinkageConfig(RobotConfig):
    can_name: str = "can_follower"
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    # 总线上只有主臂反馈，state 用「N 帧之前」的主臂位姿来近似从臂的跟随滞后。
    # 0 = 不做延迟（此时 state 和 action 几乎相同，训练容易退化成恒等映射）。
    state_delay_frames: int = 4


class PiperLinkage(Robot):
    """只读观测 + 相机；动作不落 CAN。"""

    config_class = PiperLinkageConfig
    name = "piper_linkage"

    def __init__(self, config: PiperLinkageConfig):
        super().__init__(config)
        self.config = config
        self.bus = get_bus(config.can_name)
        self.cameras = make_cameras_from_configs(config.cameras)
        self._is_connected = False
        self._state_buffer: deque = deque(maxlen=max(1, config.state_delay_frames + 1))

    # ---------- features ----------
    @property
    def _motors_ft(self) -> dict[str, type]:
        return {key: float for key in JOINT_KEYS}

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {name: (cam.height, cam.width, 3) for name, cam in self.cameras.items()}

    @property
    def action_features(self) -> dict:
        return self._motors_ft

    @property
    def observation_features(self) -> dict:
        return {**self._motors_ft, **self._cameras_ft}

    @property
    def is_connected(self) -> bool:
        return self._is_connected and all(cam.is_connected for cam in self.cameras.values())

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self, **kwargs) -> None:
        pass

    # ---------- lifecycle ----------
    def connect(self, calibrate: bool = True) -> None:
        if self._is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")
        connected = []
        try:
            for name, cam in self.cameras.items():
                cam.connect()
                connected.append(cam)
        except Exception:
            for cam in reversed(connected):
                cam.disconnect()
            raise
        self._is_connected = True

    def disconnect(self) -> None:
        for cam in self.cameras.values():
            if cam.is_connected:
                cam.disconnect()
        self._is_connected = False

    # ---------- io ----------
    def get_observation(self) -> dict:
        if not self.is_connected:
            raise DeviceNotConnectedError("PiperLinkage is not connected. Run `robot.connect()` first.")
        pose = action_pos_dict_from_piper_read(self.bus.read())
        self._state_buffer.append(pose)
        # 队列装满后取最早的一帧当 observation.state（模拟从臂滞后）
        state = self._state_buffer[0] if len(self._state_buffer) == self._state_buffer.maxlen else pose
        obs = dict(state)
        for name, cam in self.cameras.items():
            obs[name] = cam.async_read()
        return obs

    def send_action(self, action: dict[str, float]) -> dict[str, float]:
        # 只读模式：不写 CAN。主臂→从臂的跟随由固件联动完成。
        return dict(action)
