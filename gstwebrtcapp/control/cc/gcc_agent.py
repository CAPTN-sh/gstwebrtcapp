import json
import time

from gstwebrtcapp.control.agent import Agent, AgentType
from gstwebrtcapp.message.client import MqttConfig
from gstwebrtcapp.utils.base import LOGGER, sleep_until_condition_with_intervals


class GccAgent(Agent):
    def __init__(
        self,
        mqtt_config: MqttConfig,
        id: str = "gcc",
        action_period: float = 1.0,
        is_force_action: bool = True,
        is_enable_actions_on_start: bool = True,
        warmup: float = 0.0,
    ) -> None:
        super().__init__(mqtt_config, id, warmup)
        self.type = AgentType.CC

        self.action_period = action_period
        self.is_force_action = is_force_action
        self.is_actions_enabled = is_enable_actions_on_start

        self.last_action = None

    def run(self, _) -> None:
        super().run()
        time.sleep(self.warmup)
        self.mqtts.subscriber.clean_message_queue(self.mqtts.subscriber.topics.gcc)
        self.is_running = True
        LOGGER.info(f"INFO: GccAgent is starting...")

        while self.is_running:
            bitrate = None
            while not self.mqtts.subscriber.message_queues[self.mqtts.subscriber.topics.gcc].empty():
                gcc_msg = self.mqtts.subscriber.get_message(self.mqtts.subscriber.topics.gcc)
                if gcc_msg is not None:
                    bitrate = float(gcc_msg.msg) / 1e3  # kbps
            if self.is_actions_enabled:
                if bitrate is not None:
                    self.mqtts.publisher.publish(self.mqtts.subscriber.topics.actions, json.dumps({"bitrate": bitrate}))
                    self.last_action = bitrate
                else:
                    if self.is_force_action and self.last_action is not None:
                        self.mqtts.publisher.publish(
                            self.mqtts.subscriber.topics.actions,
                            json.dumps({"bitrate": self.last_action}),
                        )
            sleep_until_condition_with_intervals(10, self.action_period, lambda: not self.is_running)

    def stop(self) -> None:
        super().stop()
        LOGGER.info(f"INFO: GccAgent is stopping...")

    def init_subscriptions(self) -> None:
        self.mqtts.subscriber.subscribe([self.mqtt_config.topics.gcc])

    def enable_actions(self) -> None:
        self.is_actions_enabled = True

    def disable_actions(self) -> None:
        self.is_actions_enabled = False
