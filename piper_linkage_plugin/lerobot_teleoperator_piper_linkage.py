"""只读的 Piper 主臂遥操作（主从联动拓扑）。

- 只读 CAN 关节反馈，**不使能、不回零、不发指令**；
- 从臂跟随主臂由机械臂固件完成，所以这里只负责把主臂位姿读出来当 action。

模块名以 `lerobot_teleoperator_` 开头，会被 `register_third_party_devices()` 自动导入，
提供 `--teleop.type=piper_linkage_leader`。
"""

from __future__ import annotations

from dataclasses import dataclass

from lerobot.motors.piper.piper import action_pos_dict_from_piper_read
from lerobot.teleoperators import Teleoperator, TeleoperatorConfig

from lerobot_piper_linkage_bus import JOINT_KEYS, get_bus


@TeleoperatorConfig.register_subclass("piper_linkage_leader")
@dataclass
class PiperLinkageLeaderConfig(TeleoperatorConfig):
    can_name: str = "can_follower"


class PiperLinkageLeader(Teleoperator):
    config_class = PiperLinkageLeaderConfig
    name = "piper_linkage_leader"

    def __init__(self, config: PiperLinkageLeaderConfig):
        super().__init__(config)
        self.config = config
        self.bus = get_bus(config.can_name)
        self._is_connected = False

    @property
    def action_features(self) -> dict:
        return {key: float for key in JOINT_KEYS}

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self, **kwargs) -> None:
        pass

    def connect(self, calibrate: bool = True) -> None:
        # 不调用 bus.connect(enable=True)：主臂在联动模式下必须保持可拖动
        self._is_connected = True

    def get_action(self) -> dict[str, float]:
        return action_pos_dict_from_piper_read(self.bus.read())

    def send_feedback(self, feedback: dict) -> None:
        pass

    def disconnect(self) -> None:
        # 不 disable：避免退出时把主/从臂失能
        self._is_connected = False
