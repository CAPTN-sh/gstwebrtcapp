from typing import Any, Dict, List
from gstwebrtcapp.control.safety.monitor import (
    MonitorConfig,
    Monitor,
    MonitorState,
    DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT,
)
from gstwebrtcapp.utils.base import LOGGER


class TrendCallback(Monitor):
    def __init__(
        self,
        config: MonitorConfig = MonitorConfig(),
    ) -> None:
        super().__init__(config)

        self.healthy_actions = config.cb_healthy_actions

        self.init_factor = 1.0
        self.factor = 1.0

    def act(self, values: Dict[str, Any]) -> Dict[str, Any] | None:
        super().act(values)

        res = self.check_state_change()
        if res > 0:
            match self.state:
                case MonitorState.HEALTHY:
                    return self.on_healthy()
                case MonitorState.RECOVERY:
                    return self.on_recovery()
                case MonitorState.ALARM:
                    return self.on_alarm()
        else:
            return None

    def on_healthy(self) -> Dict[str, Any] | None:
        return None

    def on_recovery(self) -> Dict[str, Any] | None:
        return None

    def on_alarm(self) -> Dict[str, Any] | None:
        return None

    def to_action(self, key: str, value: float | int | str | None) -> Dict[str, Any] | None:
        if value is None:
            return None

        value = TrendCallback.find_closest_action_value(key, value)
        if value is None:
            return None

        if key == "resolution":
            value = value.split('x')
            return {key: {"width": int(value[0]), "height": int(value[1])}}
        else:
            return {key: value}

    def to_actions(self, values: Dict[str, Any]) -> Dict[str, Any] | None:
        actions = {}
        for key, value in values.items():
            action = self.to_action(key, value)
            if action is not None:
                actions.update(action)
        return actions

    @staticmethod
    def find_closest_action_value(key: str, value: Any) -> Any:
        if key not in DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT:
            return None

        value_type = type(value)
        right_type = type(DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT[key][0])
        if value_type != right_type:
            if value_type == int and right_type == float:
                value = float(value)
            elif value_type == float and right_type == int:
                value = int(value)
            else:
                LOGGER.warning(
                    f"find_closest_action_value: value {value} type does not match the range type for key {key}"
                )
                return None

        vals = DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT[key]

        if isinstance(vals[0], str):
            return min(vals, key=lambda x: abs(int(x.split("x")[0]) - int(value.split("x")[0])))

        return min(vals, key=lambda x: abs(x - value))


class LossTrendCallback(TrendCallback):
    def __init__(self, config: MonitorConfig = MonitorConfig()) -> None:
        super().__init__(config)

        self.init_factor = 0.75
        self.factor = 0.75

    def on_healthy(self) -> Dict[str, Any] | None:
        return self.to_actions(self.healthy_actions)

    def on_recovery(self) -> Dict[str, Any] | None:
        new_factor = pow(self.init_factor, self.failed_recoveries + 1)
        if new_factor == self.factor and self.failed_recoveries > 0:
            # on the same iteration of the failed recovery attempt; do not change the factor
            return None
        else:
            self.factor = new_factor

        actions = {}
        for key, value in self.healthy_actions.items():
            if isinstance(value, int) or isinstance(value, float):
                actions[key] = value * self.factor
            elif isinstance(value, str):
                value = value.split('x')
                new_width = str(int(float(value[0]) * self.factor))
                new_height = str(int(float(value[1]) * self.factor))
                actions[key] = f"{new_width}x{new_height}"
        return self.to_actions(actions)

    def on_alarm(self) -> Dict[str, Any] | None:
        actions = {}
        if "max_bitrate" in self.healthy_actions:
            actions["max_bitrate"] = 1000
        if "framerate" in self.healthy_actions:
            actions["framerate"] = 10
        if "resolution" in self.healthy_actions:
            actions["resolution"] = "640x480"
        if "fec" in self.healthy_actions:
            actions["fec"] = 0
        if "preset" in self.healthy_actions:
            actions["preset"] = "SD"
        return self.to_actions(actions)


class TrendCallbackFactory:
    @staticmethod
    def create(name: str, config: MonitorConfig) -> TrendCallback | None:
        if not name:
            LOGGER.warning("TrendCallbackFactory.create: no name provided, no callback will be created")
            return None
        if not config.cb_healthy_actions:
            LOGGER.warning("TrendCallbackFactory.create: no healthy_actions provided, no callback will be created")
            return None

        if name == "loss_cb":
            return LossTrendCallback(config)
        else:
            return None

    @staticmethod
    def get_available_callbacks() -> List[str]:
        return ["loss_cb"]
