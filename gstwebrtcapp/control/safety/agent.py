import json
import time
from typing import Any, Dict, List

from gstwebrtcapp.control.agent import Agent, AgentType
from gstwebrtcapp.control.safety.callbacks import TrendCallback, TrendCallbackFactory
from gstwebrtcapp.control.safety.monitor import MonitorConfig, MonitorState
from gstwebrtcapp.control.safety.switcher import Switcher
from gstwebrtcapp.message.client import MqttConfig, MqttMessage
from gstwebrtcapp.utils.base import LOGGER, sleep_until_condition_with_intervals
from gstwebrtcapp.utils.gst import GstWebRTCStatsType, find_stat, is_same_rtcp
from gstwebrtcapp.utils.webrtc import clock_units_to_seconds, ntp_short_format_to_seconds


class SafetyDetectorAgent(Agent):
    def __init__(
        self,
        mqtt_config: MqttConfig,
        id: str = "safety_detector",
        is_start_inactive: bool = False,
        monitor_configs: Dict[str, MonitorConfig] | None = None,
        update_interval: float = 0.2,
        max_inactivity_time: float = 60.0,
        warmup: float = 10.0,
    ) -> None:
        super().__init__(mqtt_config, id, warmup)
        self.type = AgentType.SAFETY_DETECTOR

        self.last_gst_stats = None
        self.first_ssrc = None

        # is_inactive is True if there is no auto switcher/callback configs or they are falsly configured
        # this agent serves then as a tunnel for manual switch commands in the connector class
        self.switchers: Dict[str, Switcher] = {}
        self.callbacks: Dict[str, TrendCallback] = {}
        self.is_inactive = False
        if not monitor_configs:
            LOGGER.warning("WARNING: SafetyDetectorAgent: monitor config dict is empty. Inactive agent is created.")
            self.is_inactive = True
        else:
            self._set_monitors(monitor_configs)
            if not self.switchers and not self.callbacks:
                LOGGER.warning(
                    "WARNING: SafetyDetectorAgent: No switchers/callbacks were created. False keys in a config dict?"
                )
                self.is_inactive = True
            else:
                self.is_inactive = is_start_inactive

        self.update_interval = update_interval
        self.max_inactivity_time = max_inactivity_time

    def run(self, _) -> None:
        super().run()
        time.sleep(self.warmup)
        self.mqtts.subscriber.clean_message_queue(self.mqtts.subscriber.topics.stats)
        self.is_running = True
        break_func = lambda: not self.is_running or self.is_inactive
        LOGGER.info(f"INFO: SafetyDetectorAgent is starting...")

        while self.is_running:
            if not self.is_inactive:
                if not sleep_until_condition_with_intervals(1, self.update_interval, break_func):
                    # checkif not inactive or turned off while waiting
                    gst_stats_collected = self._fetch_stats()
                    if gst_stats_collected:
                        stats = []
                        for gst_stats_mqtt in gst_stats_collected:
                            p_stats = self._process_stats(gst_stats_mqtt)
                            if p_stats:
                                stats.append(p_stats)
                        if stats:
                            # take the latest
                            self._decide(stats[-1])

    def change_status(self, is_inactive: bool) -> None:
        if is_inactive:
            self.is_inactive = True
        else:
            if self.switchers:
                self.is_inactive = False
                self._publish_action({"switch": 1})

    def init_subscriptions(self) -> None:
        self.mqtts.subscriber.subscribe([self.mqtt_config.topics.stats])
        self.mqtts.subscriber.subscribe([self.mqtt_config.topics.state])

    def _fetch_stats(self) -> List[MqttMessage] | None:
        time_inactivity_starts = time.time()
        stats = []
        while not self.mqtts.subscriber.message_queues[self.mqtts.subscriber.topics.stats].empty():
            gst_stats = self.mqtts.subscriber.get_message(self.mqtts.subscriber.topics.stats)
            if gst_stats is None:
                if time.time() - time_inactivity_starts > self.max_inactivity_time:
                    LOGGER.warning(
                        "WARNING: SafetyDetector agent: No stats were pulled from the observation queue after"
                        f" {self.max_inactivity_time} sec"
                    )
                    return None
            else:
                stats.append(gst_stats)
        return stats or None

    def _process_stats(self, gst_stats_mqtt: MqttMessage) -> Dict[str, Any]:
        gst_stats = json.loads(gst_stats_mqtt.msg)
        rtp_outbound = find_stat(gst_stats, GstWebRTCStatsType.RTP_OUTBOUND_STREAM)
        rtp_inbound = find_stat(gst_stats, GstWebRTCStatsType.RTP_REMOTE_INBOUND_STREAM)
        if not rtp_outbound or not rtp_inbound:
            LOGGER.info("WARNING: SafetyDetectorAgent: no stats were found...")
            return None

        # last stats
        last_rtp_outbound = (
            find_stat(self.last_gst_stats, GstWebRTCStatsType.RTP_OUTBOUND_STREAM)
            if self.last_gst_stats is not None
            else None
        )
        last_rtp_inbound = (
            find_stat(self.last_gst_stats, GstWebRTCStatsType.RTP_REMOTE_INBOUND_STREAM)
            if self.last_gst_stats is not None
            else None
        )
        if last_rtp_outbound is None or last_rtp_inbound is None:
            self.last_gst_stats = gst_stats
            return None

        if self.first_ssrc is None:
            self.first_ssrc = rtp_inbound[0]["ssrc"]

        # len(rtp_inbound) = number of viewers. Iterate by their ssrc
        # outbound stats are the same for all viewers
        final_stats = {}
        for i, rtp_inbound_ssrc in enumerate(rtp_inbound):
            if rtp_inbound_ssrc["ssrc"] == self.first_ssrc:
                if 0 <= i < len(last_rtp_inbound) and is_same_rtcp(rtp_inbound_ssrc, last_rtp_inbound[i]):
                    continue

                # loss rate
                loss_rate = (
                    float(rtp_inbound_ssrc["rb-packetslost"])
                    / (rtp_outbound[0]["packets-sent"] + rtp_inbound_ssrc["rb-packetslost"])
                    if rtp_outbound[0]["packets-sent"] + rtp_inbound_ssrc["rb-packetslost"] > 0
                    else 0.0
                )

                # nack rate
                nack_rate = (
                    float(rtp_outbound[0]["nack-count"]) / (rtp_outbound[0]["packets-received"])
                    if rtp_outbound[0]["packets-received"] > 0
                    else 0.0
                )

                # pli rate
                pli_rate = (
                    float(rtp_outbound[0]["pli-count"]) / (rtp_outbound[0]["packets-received"])
                    if rtp_outbound[0]["packets-received"] > 0
                    else 0.0
                )

                # rtt
                rtt = ntp_short_format_to_seconds(rtp_inbound_ssrc["rb-round-trip"])

                # jitter
                jitter = clock_units_to_seconds(rtp_inbound_ssrc["rb-jitter"], rtp_outbound[0]["clock-rate"])

                # form the final state with the keys defined for switchers
                final_stats = {
                    "loss": loss_rate,
                    "nack": nack_rate,
                    "pli": pli_rate,
                    "rtt": rtt,
                    "jit": jitter,
                }

                self.last_gst_stats = gst_stats
                return final_stats

        return None

    def _decide(self, new_stats: Dict[str, float]) -> None:
        if self.switchers:
            switch_action_to_safe = 0
            switch_action_to_unsafe = 0
            alarm_state = None
            for switcher in self.switchers.values():
                sa = switcher.act(new_stats)
                if sa:
                    if sa["switch"] == 0:
                        switch_action_to_safe += 1
                    elif sa["switch"] == 1:
                        switch_action_to_unsafe += 1
                ast = switcher.state if switcher.state == MonitorState.ALARM else None
                if not alarm_state and ast:
                    alarm_state = ast

            if switch_action_to_safe > 0 and not alarm_state:
                # at least one switch to safe and no alarm
                algo = 0
                for switcher in self.switchers.values():
                    if switcher.algo != algo:
                        # make algos consistent
                        switcher.force_algo(0)
                self._publish_action({"switch": 0})
                self.reset()
            elif switch_action_to_unsafe == len(self.switchers) and not alarm_state:
                # all switch to unsafe and no alarm
                algo = 1
                for switcher in self.switchers.values():
                    if switcher.algo != algo:
                        # make algos consistent
                        switcher.force_algo(algo)
                self._publish_action({"switch": 1})
                self.reset()

        if self.callbacks:
            for cb in self.callbacks.values():
                action = cb.act(new_stats)
                if action:
                    self._publish_action(action)

    def _publish_action(self, action: Dict[str, int]) -> None:
        if self.mqtts.publisher.topics.controller:
            topic = self.mqtts.publisher.topics.controller
            payload = {self.mqtts.publisher.id_init: action}
        else:
            topic = self.mqtts.publisher.topics.actions
            payload = action
        self.mqtts.publisher.publish(topic, json.dumps(payload))

    def _set_monitors(self, monitor_configs: Dict[str, MonitorConfig]) -> None:
        for name, config in monitor_configs.items():
            if config.type == "switcher":
                self.switchers[name] = Switcher(config)
            elif config.type == "callback":
                callback = TrendCallbackFactory.create(name, config)
                if callback:
                    self.callbacks[name] = callback

    def reset(self) -> None:
        self.last_gst_stats = None

    def stop(self) -> None:
        super().stop()
        LOGGER.info(f"INFO: SafetyDetectorAgent is stopping...")
