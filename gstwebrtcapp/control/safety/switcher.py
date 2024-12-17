from typing import Any, Dict
from gstwebrtcapp.control.safety.monitor import MonitorConfig, Monitor, MonitorState


class SwitchingPair:
    def __init__(self, safe_id: str, unsafe_id: str, switcher_id: str | None = None) -> None:
        self.safe_id = safe_id
        self.unsafe_id = unsafe_id

        self.switcher_id = switcher_id

        self.is_warmups_resetted = False


class Switcher(Monitor):
    def __init__(
        self,
        config: MonitorConfig = MonitorConfig(),
    ) -> None:
        super().__init__(config)

        self.algo = 1  # default "unsafe"

    def act(self, values: Dict[str, Any]) -> Dict[str, int] | None:
        super().act(values)

        _ = self.check_state_change()

        if self.algo == 0:
            if self.state == MonitorState.HEALTHY:
                # if was unsafe and now is healthy, switch to safe
                self.algo = 1
                return {"switch": self.algo}
        else:
            if self.state != MonitorState.HEALTHY:
                # if was safe and now is unhealthy, switch to unsafe
                self.algo = 0
                return {"switch": self.algo}

        return None

    def force_algo(self, algo: int) -> None:
        self.algo = algo
        self.recovery_iterations = 0
        self.trends_during_recovery = 0
        self.failed_recoveries = 0
        if algo == 0:
            self.state = MonitorState.RECOVERY
        else:
            self.state = MonitorState.HEALTHY
