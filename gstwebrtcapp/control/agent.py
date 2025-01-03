"""
agent.py

Description:
    Base Agent class for the gstreamerwebrtcapp to control the pipeline.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

from abc import ABCMeta, abstractmethod
from enum import Enum
import secrets

from gstwebrtcapp.message.client import MqttConfig, MqttPair, MqttPublisher, MqttSubscriber


class AgentType(Enum):
    ABSTRACT = "ABSTRACT"
    CC = "CC"
    DRL = "DRL"
    DRL_OFFLINE = "DRL_OFFLINE"
    RECORDER = "RECORDER"
    SAFETY_DETECTOR = "SAFETY_DETECTOR"


class Agent(metaclass=ABCMeta):
    def __init__(
        self,
        mqtt_config: MqttConfig,
        id: str = "",
        warmup: float = 0.0,
    ) -> None:
        self.mqtt_config = mqtt_config
        self.mqtts = MqttPair(
            publisher=MqttPublisher(self.mqtt_config),
            subscriber=MqttSubscriber(self.mqtt_config),
        )

        self.id = id or secrets.token_hex(4)
        self.warmup = warmup
        self.type = AgentType.ABSTRACT
        self.is_running = False

    def run(self, *args, **kwargs) -> None:
        self.mqtts.publisher.start()
        self.mqtts.subscriber.start()
        self.init_subscriptions()

    def stop(self) -> None:
        self.is_running = False
        self.mqtts.publisher.stop()
        self.mqtts.subscriber.stop()

    @abstractmethod
    def init_subscriptions(self) -> None:
        pass
