from dataclasses import dataclass, field, fields
import enum
from typing import Any, Dict, List, Self

from gstwebrtcapp.control.safety.thresholder import Thresholder
from gstwebrtcapp.utils.base import LOGGER

MONITORED_STATS = ["loss", "nack", "pli", "rtt", "jit"]

DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT = {
    "max_bitrate": [700, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 10000],
    "framerate": [10, 15, 20, 25, 30],
    "resolution": ['480x360', '640x480', '1280x720', '1920x1080', '3840x2160'],
    "fec": [0, 10, 20, 50, 75, 100],
    "preset": ['LD', 'SD', 'HD', 'FHD', 'UHD'],
}


class MonitorState(enum.Enum):
    HEALTHY = 0
    RECOVERY = 1
    ALARM = 2


@dataclass
class MonitorConfig:
    type: str = "switcher"  # "switcher" / "callback"
    targets: List[str] = field(default_factory=lambda: ["rtt"])  # check MONITORED_STATS
    window_size: int = 8
    k: float = 0.05
    trend_direction: str = "i"
    trend_agreement_strategy: str = "any"  # "any/all/half"
    warmup_iterations: int = 10
    excesses_allowed: int = 1
    recovery_iterations: int = 1
    max_trends_during_recovery: int | None = None
    failed_recoveries_to_trigger_alarm: int | None = None
    alarm_iterations: int | None = None
    cb_healthy_actions: Dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> Self | None:
        field_dict = {field.name: field.type for field in fields(cls)}
        for key in config_dict.keys():
            if key not in field_dict:
                LOGGER.warning(f"MonitorConfig.from_dict: invalid field name: {key}, ignoring")
                continue

            if key == "type":
                if config_dict["type"] not in ["switcher", "callback"]:
                    LOGGER.error(
                        f"ERROR: MonitorConfig.from_dict: invalid type: {config_dict['type']}, allowed only 'switcher' or 'callback'"
                    )
                    return None
            elif key == "targets":
                if not all([t in MONITORED_STATS for t in config_dict["targets"]]):
                    LOGGER.error(
                        f"ERROR: MonitorConfig.from_dict: invalid targets: {config_dict['targets']}, allowed only {MONITORED_STATS}"
                    )
                    return None
            elif key == "trend_direction":
                if config_dict["trend_direction"] not in ["i", "d"]:
                    LOGGER.warning(
                        f"MonitorConfig.from_dict: invalid trend_direction: {config_dict['trend_direction']}, defaulting to 'i'"
                    )
                    config_dict["trend_direction"] = "i"
                    continue
            elif key == "trend_agreement_strategy":
                if config_dict["trend_agreement_strategy"] not in ["any", "all", "half"]:
                    LOGGER.warning(
                        f"MonitorConfig.from_dict: invalid trend_agreement_strategy: {config_dict['trend_agreement_strategy']}, defaulting to 'any'"
                    )
                    config_dict["trend_agreement_strategy"] = "any"
                    continue
            elif key == "cb_healthy_actions":
                if config_dict["cb_healthy_actions"]:
                    cb_healthy_actions = {}
                    for k, v in config_dict["cb_healthy_actions"].items():
                        if k in DEFAULT_TREND_CALLBACK_ACTIONS_RANGE_DICT:
                            cb_healthy_actions[k] = v
                        else:
                            LOGGER.warning(f"MonitorConfig.from_dict: invalid key in cb_healthy_actions: {k}, ignoring")

                    if not cb_healthy_actions:
                        LOGGER.warning(
                            f"MonitorConfig.from_dict: cb_healthy_actions is empty, no callback will be created"
                        )
                        return None
                    else:
                        config_dict["cb_healthy_actions"] = cb_healthy_actions

        return cls(
            type=config_dict.get("type", cls.type),
            targets=config_dict.get("targets", ["rtt"]),
            window_size=config_dict.get("window_size", cls.window_size),
            k=config_dict.get("k", cls.k),
            trend_direction=config_dict.get("trend_direction", cls.trend_direction),
            trend_agreement_strategy=config_dict.get("trend_agreement_strategy", cls.trend_agreement_strategy),
            warmup_iterations=config_dict.get("warmup_iterations", cls.warmup_iterations),
            excesses_allowed=config_dict.get("excesses_allowed", cls.excesses_allowed),
            recovery_iterations=config_dict.get("recovery_iterations", cls.recovery_iterations),
            max_trends_during_recovery=config_dict.get("max_trends_during_recovery", cls.max_trends_during_recovery),
            failed_recoveries_to_trigger_alarm=config_dict.get(
                "failed_recoveries_to_trigger_alarm", cls.failed_recoveries_to_trigger_alarm
            ),
            alarm_iterations=config_dict.get("alarm_iterations", cls.alarm_iterations),
            cb_healthy_actions=config_dict.get("cb_healthy_actions", cls.cb_healthy_actions),
        )


class Monitor:
    def __init__(
        self,
        config: MonitorConfig = MonitorConfig(),
    ) -> None:

        self.max_window_size = config.window_size

        self.thresholders = {
            target: Thresholder(
                max_window_size=config.window_size,
                k=config.k,
                trend_direction=config.trend_direction,
                warmup_iterations=config.warmup_iterations,
                excesses_allowed=config.excesses_allowed,
            )
            for target in config.targets
        }

        self.state = MonitorState.HEALTHY
        self.is_trend = False

        self.trend_agreement_strategy = config.trend_agreement_strategy

        self.recovery_iterations = 0
        self.max_recovery_iterations = config.recovery_iterations

        self.trends_during_recovery = 0
        self.max_trends_during_recovery = (
            config.max_trends_during_recovery if config.max_trends_during_recovery is not None else -1
        )

        self.failed_recoveries = 0
        self.is_failed_recoveries_increased = False
        self.failed_recoveries_to_trigger_alarm = (
            config.failed_recoveries_to_trigger_alarm if config.failed_recoveries_to_trigger_alarm is not None else -1
        )

        self.alarm_iterations = 0
        self.max_alarm_iterations = config.alarm_iterations or 0

    def act(self, values: Dict[str, Any]) -> Dict[str, Any] | None:
        # NOTE: parent class cannot act
        if not self._is_all_targets_delivered(values):
            LOGGER.warning(
                f"Monitor.act: not all targets delivered, required: {self.thresholders.keys()}, got: {values.keys()}"
            )
            return None
        self.is_trend = self.check_trend(values)
        return None

    def check_trend(self, values: Dict[str, Any]) -> bool:
        trends = [
            self.thresholders[target].check_trend(val) for target, val in values.items() if target in self.thresholders
        ]

        match self.trend_agreement_strategy:
            case "any":
                return any(trends)
            case "all":
                return all(trends)
            case "half":
                return sum(trends) > len(trends) // 2
            case _:
                return False

    def check_state_change(self) -> int:
        # 0 - no change, 1 - change, 2 - no change but worsening
        match self.state:
            case MonitorState.HEALTHY:
                if self.is_trend:
                    self.state = MonitorState.RECOVERY
                    return 1
                return 0

            case MonitorState.RECOVERY:
                if self.is_recovered():
                    self.state = MonitorState.HEALTHY
                    return 1
                else:
                    if self.is_alarm():
                        self.state = MonitorState.ALARM
                        return 1
                    elif self.is_failed_recoveries_increased:
                        self.is_failed_recoveries_increased = False
                        return 2
                    else:
                        return 0

            case MonitorState.ALARM:
                if self.is_alarm_end():
                    self.state = MonitorState.RECOVERY
                    return 1
                else:
                    return 0

            case _:
                return 0

    def is_alarm(self) -> bool:
        if (
            self.failed_recoveries_to_trigger_alarm >= 0
            and self.failed_recoveries >= self.failed_recoveries_to_trigger_alarm
        ):
            self.failed_recoveries = 0
            self.trends_during_recovery = 0
            self.recovery_iterations = 0
            return True
        return False

    def is_alarm_end(self) -> bool:
        self.alarm_iterations += 1
        if self.alarm_iterations >= self.max_alarm_iterations:
            self.alarm_iterations = 0
            return True
        return False

    def is_recovered(self) -> bool:
        self.recovery_iterations += 1

        if self.is_trend:
            self.trends_during_recovery += 1

        if self.max_trends_during_recovery >= 0 and self.trends_during_recovery > self.max_trends_during_recovery:
            self.recovery_iterations = 0
            self.trends_during_recovery = 0
            self.failed_recoveries += 1
            self.is_failed_recoveries_increased = True
            return False
        else:
            if self.recovery_iterations < self.max_recovery_iterations:
                return False
            else:
                self.recovery_iterations = 0
                self.trends_during_recovery = 0
                self.failed_recoveries = 0
                return True

    def _is_all_targets_delivered(self, values: Dict[str, Any]) -> bool:
        return all([target in values for target in self.thresholders])
