from dataclasses import dataclass, fields
import os
import signal
import subprocess
from typing import Any, Dict, Self

from gstwebrtcapp.utils.base import LOGGER


@dataclass
class MqttBrokerConfig:
    broker_host: str = "0.0.0.0"
    broker_port: int = 1883
    keepalive: int = 20
    username: str | None = None
    password: str | None = None
    is_tls: bool = False
    tls_cafile: str | None = None
    protocol: int = 4

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> Self:
        field_dict = {field.name: field.type for field in fields(cls)}
        for key in config_dict.keys():
            if key not in field_dict:
                LOGGER.warning(f"MqttBrokerConfig.from_dict: invalid field name: {key}")
                continue

        return cls(
            broker_host=config_dict.get('broker_host', cls.broker_host),
            broker_port=config_dict.get('broker_port', cls.broker_port),
            keepalive=config_dict.get('keepalive', cls.keepalive),
            username=config_dict.get('username', cls.username),
            password=config_dict.get('password', cls.password),
            is_tls=config_dict.get('is_tls', cls.is_tls),
            tls_cafile=config_dict.get('tls_cafile', cls.tls_cafile),
            protocol=config_dict.get('protocol', cls.protocol),
        )


class MosquittoLocalBroker:
    def __init__(
        self,
        port: int = 1883,
    ):
        self.port = port
        self.process = None
        self.is_running = False

    def run(self) -> None:
        if not os.path.exists("/etc/mosquitto/mosquitto.conf"):
            self._generate_default_conf_file()
        cmd = ["mosquitto", "-c", "/etc/mosquitto/mosquitto.conf", "-p", str(self.port)]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        while self.process.poll() is None:
            if not self.is_running:
                self.is_running = True
                LOGGER.info(f"INFO: Mosquitto broker has been started")

        self.stop()

    def stop(self) -> None:
        if self.process and self.process.returncode is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait()
            except ProcessLookupError:
                pass

    def _generate_default_conf_file(self) -> None:
        with open("/etc/mosquitto/mosquitto.conf", 'w') as config_file:
            config_lines = [
                f"pid_file /run/mosquitto/mosquitto.pid",
                "persistence true",
                f"persistence_location /var/lib/mosquitto/",
                f"log_dest stdout",
                f"connection_messages True",
                f"listener {self.port}",
                f"allow_anonymous True",
                f"log_dest file /var/log/mosquitto/mosquitto.log",
                f"include_dir /etc/mosquitto/conf.d",
            ]
            config_file.write('\n'.join(config_lines))
