import csv
from datetime import datetime
import enum
import json
import os
import time
from typing import List

from gstwebrtcapp.control.agent import Agent, AgentType
from gstwebrtcapp.message.client import MqttConfig, MqttMessage
from gstwebrtcapp.utils.base import LOGGER
from gstwebrtcapp.utils.gst import GstWebRTCStatsType, find_stat, get_stat_diff, is_same_rtcp
from gstwebrtcapp.utils.webrtc import clock_units_to_seconds, ntp_short_format_to_seconds


class RecorderAgentMode(enum.Enum):
    NULL = 0
    MQTT = 1
    CSV = 2
    DC = 3


class RecorderAgent(Agent):
    def __init__(
        self,
        mqtt_config: MqttConfig,
        id: str = "recorder",
        max_inactivity_time: float = 5.0,
        log_path: str | None = "./logs",
        stats_publish_topic: str | None = None,
        external_data_channel: str | None = None,
        verbose: bool = False,
        warmup: float = 3.0,
    ) -> None:
        super().__init__(mqtt_config, id, warmup)
        self.max_inactivity_time = max_inactivity_time
        self.log_path = log_path
        self.stats_publish_topic = stats_publish_topic
        self.external_data_channel = external_data_channel
        self.verbose = verbose
        self.type = AgentType.RECORDER

        # cooked stats
        self.ready_stats = []
        # raw gst stats
        self.last_stats = None
        self.inbetween_burst_loss_packets = 0

        self.csv_file = None
        self.csv_handler = None
        self.csv_writer = None

    def run(self, _) -> None:
        super().run()
        time.sleep(self.warmup)
        # clean the queue from the messages obtained before warmup
        self.mqtts.subscriber.clean_message_queue(self.mqtts.subscriber.topics.stats)
        self.is_running = True
        LOGGER.info(f"INFO: Recorder agent warmup {self.warmup} sec is finished, starting...")

        while self.is_running:
            time.sleep(0.1)
            gst_stats_collected = self._fetch_stats()
            if gst_stats_collected is not None:
                for gst_stats in gst_stats_collected:
                    self._process_stats(gst_stats)
                if self.ready_stats:
                    if self.log_path:
                        self._save_stats_to_csv()
                    if self.stats_publish_topic:
                        self._publish_to_topic()
                    if self.external_data_channel:
                        self._relay_to_external_data_channel()
                    if self.verbose:
                        LOGGER.info(f"INFO: Recorder agent {self.id} stats:\n {self.ready_stats[-1]}")
                self.ready_stats = []

    def _fetch_stats(self) -> List[MqttMessage] | None:
        time_inactivity_starts = time.time()
        stats = []
        while not self.mqtts.subscriber.message_queues[self.mqtts.subscriber.topics.stats].empty():
            gst_stats = self.mqtts.subscriber.get_message(self.mqtts.subscriber.topics.stats)
            if gst_stats is None:
                if time.time() - time_inactivity_starts > self.max_inactivity_time:
                    LOGGER.warning(
                        "WARNING: Recorder agent: No stats were pulled from the observation queue after"
                        f" {self.max_inactivity_time} sec"
                    )
                    return None
            else:
                stats.append(gst_stats)
        return stats or None

    def _process_stats(self, gst_stats_mqtt: MqttMessage) -> None:
        gst_stats = json.loads(gst_stats_mqtt.msg)
        rtp_outbound = find_stat(gst_stats, GstWebRTCStatsType.RTP_OUTBOUND_STREAM)
        rtp_inbound = find_stat(gst_stats, GstWebRTCStatsType.RTP_REMOTE_INBOUND_STREAM)
        ice_candidate_pair = find_stat(gst_stats, GstWebRTCStatsType.ICE_CANDIDATE_PAIR)
        if not rtp_outbound or not rtp_inbound or not ice_candidate_pair:
            LOGGER.info("WARNING: Recorder agent: no stats were found...")
            return

        # last stats
        last_rtp_outbound = (
            find_stat(self.last_stats, GstWebRTCStatsType.RTP_OUTBOUND_STREAM) if self.last_stats is not None else None
        )
        last_rtp_inbound = (
            find_stat(self.last_stats, GstWebRTCStatsType.RTP_REMOTE_INBOUND_STREAM)
            if self.last_stats is not None
            else None
        )
        if last_rtp_outbound is None or last_rtp_inbound is None:
            self.last_stats = gst_stats
            return

        # len(rtp_inbound) = number of viewers. Iterate by their ssrc
        # outbound stats are the same for all viewers
        for i, rtp_inbound_ssrc in enumerate(rtp_inbound):
            if 0 <= i < len(last_rtp_inbound) and is_same_rtcp(rtp_inbound_ssrc, last_rtp_inbound[i]):
                # NOTE: the current iteration is skipped to save only unique rtt and jitter values
                # but the burst loss packets appeared in-between need to be accumulated
                self.inbetween_burst_loss_packets += rtp_inbound_ssrc["rb-fractionlost"]
                continue

            # ssrc
            ssrc = rtp_inbound_ssrc["ssrc"]

            # burst loss packets
            burst_loss_packets = rtp_inbound_ssrc["rb-fractionlost"] + self.inbetween_burst_loss_packets
            self.inbetween_burst_loss_packets = 0

            # loss rate
            loss_rate = (
                float(rtp_inbound_ssrc["rb-packetslost"])
                / (rtp_outbound[0]["packets-sent"] + rtp_inbound_ssrc["rb-packetslost"])
                if rtp_outbound[0]["packets-sent"] + rtp_inbound_ssrc["rb-packetslost"] > 0
                else 0.0
            )

            # fraction loss rate
            packets_sent_diff = get_stat_diff(rtp_outbound[0], last_rtp_outbound[0], "packets-sent")
            rb_packetslost_diff = get_stat_diff(rtp_inbound[i], last_rtp_inbound[i], "rb-packetslost")
            fraction_loss_rate = (
                rb_packetslost_diff / (packets_sent_diff + rb_packetslost_diff)
                if packets_sent_diff + rb_packetslost_diff > 0
                else 0.0
            )

            ts_diff_sec = get_stat_diff(rtp_outbound[0], last_rtp_outbound[0], "timestamp") / 1000

            # fraction tx rate in Mbits
            try:
                bitrate_sent = ice_candidate_pair[0]["bitrate-sent"]
                tx_rate = bitrate_sent / 1000000
            except KeyError:
                tx_bytes_diff = get_stat_diff(rtp_outbound[0], last_rtp_outbound[0], "bytes-sent")
                tx_mbits_diff = tx_bytes_diff * 8 / 1000000
                tx_rate = tx_mbits_diff / ts_diff_sec if ts_diff_sec > 0 else 0.0

            # fraction rx rate in Mbits
            try:
                bitrate_recv = ice_candidate_pair[0]["bitrate-recv"]
                rx_rate = bitrate_recv / 1000000
            except KeyError:
                rx_bytes_diff = get_stat_diff(rtp_outbound[0], last_rtp_outbound[0], "bytes-received")
                rx_mbits_diff = rx_bytes_diff * 8 / 1000000
                rx_rate = rx_mbits_diff / ts_diff_sec if ts_diff_sec > 0 else 0.0

            # rtts / jitter
            rtt_ms = ntp_short_format_to_seconds(rtp_inbound_ssrc["rb-round-trip"]) * 1000.0
            jitter_ms = clock_units_to_seconds(rtp_inbound_ssrc["rb-jitter"], rtp_outbound[0]["clock-rate"]) * 1000.0

            # opened to extensions
            final_stats = {
                "timestamp": gst_stats_mqtt.timestamp,
                "ssrc": ssrc,
                "burst_lost_packets": burst_loss_packets,
                "lost_packets": rtp_inbound_ssrc["rb-packetslost"],
                "fraction_loss_rate": fraction_loss_rate,
                "loss_rate": loss_rate,
                "ext_highest_seq": rtp_inbound_ssrc["rb-exthighestseq"],
                "rtt_ms": rtt_ms,
                "jitter_ms": jitter_ms,
                "nack_count": rtp_outbound[0]["recv-nack-count"],
                "pli_count": rtp_outbound[0]["recv-pli-count"],
                "rx_packets": rtp_outbound[0]["packets-received"],
                "rx_mbytes": rtp_outbound[0]["bytes-received"] / 1000000.0,
                "tx_rate_mbits": tx_rate,
                "rx_rate_mbits": rx_rate,
            }
            self.ready_stats.append(final_stats)
            self.last_stats = gst_stats

    def _save_stats_to_csv(self) -> None:
        if self.csv_handler is None:
            datetime_now = datetime.now().strftime("%Y-%m-%d-%H_%M_%S_%f")[:-3]
            os.makedirs(self.log_path, exist_ok=True)
            if self.csv_file is None:
                self.csv_file = os.path.join(self.log_path, f"{self.id}_{datetime_now}.csv")
            header = self.ready_stats[-1].keys()
            self.csv_handler = open(self.csv_file, mode="a", newline="\n")
            self.csv_writer = csv.DictWriter(self.csv_handler, fieldnames=header)
            if os.stat(self.csv_file).st_size == 0:
                self.csv_writer.writeheader()
            self.csv_handler.flush()
        else:
            for stat in self.ready_stats:
                self.csv_writer.writerow(stat)

    def _publish_to_topic(self) -> None:
        for stat in self.ready_stats:
            self.mqtts.publisher.publish(
                topic=self.stats_publish_topic,
                msg=json.dumps(stat),
                id="recorder",
            )

    def _relay_to_external_data_channel(self) -> None:
        if self.mqtt_config.topics.controller:
            topic = self.mqtt_config.topics.controller
        else:
            topic = self.mqtt_config.topics.actions

        for stat in self.ready_stats:
            self.mqtts.publisher.publish(
                topic=topic,
                msg=json.dumps(
                    {
                        self.mqtts.publisher.id_init: {
                            "send_dc": {
                                "name": self.external_data_channel,
                                "msg": {"stats": stat},
                            },
                        },
                    },
                ),
                id="recorder",
            )

    def init_subscriptions(self) -> None:
        self.mqtts.subscriber.subscribe([self.mqtt_config.topics.stats])

    def stop(self) -> None:
        super().stop()
        LOGGER.info("INFO: stopping Recorder agent...")
        if self.csv_handler is not None:
            self.csv_handler.close()
            self.csv_handler = None
            self.csv_writer = None
