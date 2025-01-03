"""
app.py

Description: An abstract class that provides an interface for the applications that use GStreamer's webrtc plugins to stream the video source
and to control the QoE parameters of the video stream.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

from abc import ABCMeta, abstractmethod
import asyncio
from dataclasses import dataclass, field, fields
import json
import logging
import re
from typing import Any, Callable, Dict, List, Self

import gi

gi.require_version("Gst", "1.0")
gi.require_version('GstWebRTC', '1.0')
from gi.repository import Gst
from gi.repository import GstWebRTC

from gstwebrtcapp.apps.pipelines import BIN_H264_IN_H264_OUT_PIPELINE
from gstwebrtcapp.media.preset import VideoPreset
from gstwebrtcapp.utils.base import LOGGER, GSTWEBRTCAPP_EXCEPTION, async_wait_for_condition, wait_for_condition
from gstwebrtcapp.utils.gst import DEFAULT_GCC_SETTINGS, DEFAULT_TRANSCEIVER_SETTINGS, get_gst_encoder_name


@dataclass
class GstWebRTCAppConfig:
    """
    Configuration class for GstWebRTCApp.

    :param str pipeline_str: GStreamer pipeline string. Default is the default h264 in-out pipeline string for webrtcbin.
    :param str video_url: URL of the video source (RTSP, RTMP, FILE, etc.). Default is None.
    :param str codec: Name of the src video codec (encoder). Possible options are "h264", "h265", "vp8", "vp9", "av1".
        Default is "h264".
    :param int bitrate: Bitrate of the video in Kbps. Default is 2000.
    :param Dict[str, int] resolution: Dictionary containing width and height of the video resolution.
        Default is {"width": 1280, "height": 720}.
    :param int framerate: Frame rate of the video. Default is 20.
    :param int fec_percentage: Forward error correction percentage. Default is 0.
    :param bool is_preset_tuning: Flag indicating whether to use the video preset tuning. Default is False.
    :param Dict[str, int] | None gcc_settings: Dictionary containing GCC settings. If None, gcc will not be used.
        Default is {"min-bitrate": 400000, "max-bitrate": 20000000}.
    :param Dict[str, Any] | None transceiver_settings: Dictionary containing transceiver settings for NACK and FEC. Default both are True.
    :param List[Dict[str, Any]] data_channels_cfgs: List of dictionaries containing data channel configurations.
    :param int priority: priority (DSCP marking) for the sender RTP stream (from 1 to 4). Default is 2 (DSCP 0).
    :param int max_timeout: Maximum timeout for operations in seconds. Default is 60.
    :param bool is_debug: Flag indicating whether debugging GStreamer logs are enabled. Default is False.
    :param bool is_graph: Flag indicating whether to generate the pipeline graph. Default is False.
    """

    pipeline_str: str = BIN_H264_IN_H264_OUT_PIPELINE
    video_url: str | None = None
    codec: str = "h264"
    bitrate: int = 2000
    resolution: Dict[str, int] = field(default_factory=lambda: {"width": 1280, "height": 720})
    framerate: int = 20
    fec_percentage: int = 0
    is_preset_tuning: bool = False
    gcc_settings: Dict[str, int] | None = field(default_factory=lambda: DEFAULT_GCC_SETTINGS)
    transceiver_settings: Dict[str, Any] | None = field(default_factory=lambda: DEFAULT_TRANSCEIVER_SETTINGS)
    data_channels_cfgs: List[Dict[str, Any]] = field(default_factory=lambda: [])
    priority: int = 2
    max_timeout: int = 60
    is_debug: bool = False
    is_graph: bool = False

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> Self:
        field_dict = {field.name: field.type for field in fields(cls)}
        for key in config_dict.keys():
            if key not in field_dict:
                LOGGER.warning(f"GstWebRTCAppConfig.from_dict: invalid field name: {key}")
                continue
        return cls(
            pipeline_str=config_dict.get('pipeline_str', cls.pipeline_str),
            video_url=config_dict.get('video_url', cls.video_url),
            codec=config_dict.get('codec', cls.codec),
            bitrate=config_dict.get('bitrate', cls.bitrate),
            resolution=config_dict.get('resolution', {"width": 1280, "height": 720}),
            framerate=config_dict.get('framerate', cls.framerate),
            fec_percentage=config_dict.get('fec_percentage', cls.fec_percentage),
            is_preset_tuning=config_dict.get('is_preset_tuning', cls.is_preset_tuning),
            gcc_settings=config_dict.get('gcc_settings', DEFAULT_GCC_SETTINGS),
            transceiver_settings=config_dict.get('transceiver_settings', DEFAULT_TRANSCEIVER_SETTINGS),
            data_channels_cfgs=config_dict.get('data_channels_cfgs', []),
            priority=config_dict.get('priority', cls.priority),
            max_timeout=config_dict.get('max_timeout', cls.max_timeout),
            is_debug=config_dict.get('is_debug', cls.is_debug),
            is_graph=config_dict.get('is_graph', cls.is_graph),
        )


class GstWebRTCApp(metaclass=ABCMeta):
    """
    Abstract GstWebRTCApp class that defines set of actions to establish and control the pipeline
    """

    def __init__(self, config: GstWebRTCAppConfig, **kwargs) -> None:
        # NOTE: call super().__init__() in the derived classes AFTER declaring their GST instance variables
        self.pipeline_str = config.pipeline_str
        self.video_url = config.video_url
        self.encoder_gst_name = get_gst_encoder_name(
            config.codec,
            bool(re.search(r'\b(nvh264dec|nvh265dec|nvh264enc|nvh265enc|nvav1enc)\b', self.pipeline_str)),
        )

        self.bitrate = config.bitrate
        self.resolution = config.resolution
        self.framerate = config.framerate
        self.fec_percentage = config.fec_percentage
        self.is_preset_tuning = config.is_preset_tuning
        self.gcc_settings = config.gcc_settings
        self.transceiver_settings = config.transceiver_settings
        self.scaling_elements = []
        self.data_channels_cfgs = config.data_channels_cfgs
        self.data_channels = {}
        self.data_channels_data = {}
        self.priority = config.priority
        self.max_timeout = config.max_timeout
        self.is_graph = config.is_graph
        self.is_running = False

        Gst.init(None)
        if config.is_debug:
            Gst.debug_set_default_threshold(Gst.DebugLevel.WARNING)
            Gst.debug_set_active(True)
            LOGGER.setLevel(logging.DEBUG)

        self._init_pipeline()

    @abstractmethod
    def _init_pipeline(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def _post_init_pipeline(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_bitrate(self, bitrate: int) -> bool:
        """
        Set the bitrate of the video stream.

        :param int bitrate: Bitrate of the video in Kbps.
        :return: True if the bitrate is set successfully, False otherwise.
        """
        pass

    @abstractmethod
    def set_resolution(self, width: int, height: int) -> bool:
        """
        Set the resolution of the video stream.

        :param int width: Width of the video.
        :param int height: Height of the video.
        :return: True if the resolution is set successfully, False otherwise.
        """
        pass

    @abstractmethod
    def set_framerate(self, framerate: int) -> bool:
        """
        Set the framerate of the video stream.

        :param int framerate: Framerate of the video.
        :return: True if the framerate is set successfully, False otherwise.
        """
        pass

    @abstractmethod
    def set_fec_percentage(self, percentage: int) -> bool:
        """
        Set the FEC percentage of the video stream.

        :param int percentage: FEC percentage of the video.
        :return: True if the FEC percentage is set successfully, False otherwise.
        """
        pass

    def set_preset(self, preset: VideoPreset, is_set_bitrate: bool = True) -> bool:
        """
        Set the video preset.

        :param VideoPreset preset: Video preset.
        :param bool is_set_bitrate: Flag indicating whether to set the bitrate. Default is True.
        :return: True if at least one of the preset parameters is set, False otherwise.
        """
        ok = False
        if preset.width != self.resolution["width"] or preset.height != self.resolution["height"]:
            if self.set_resolution(preset.width, preset.height):
                ok = True
        if preset.framerate != self.framerate:
            if self.set_framerate(preset.framerate):
                ok = True
        if is_set_bitrate and preset.bitrate != self.bitrate:
            if self.set_bitrate(preset.bitrate):
                ok = True
        return ok

    def set_app_transceiver_properties(
        self,
        transceiver: GstWebRTC.WebRTCRTPTransceiver,
        props_dict: Dict[str, Any],
    ) -> bool:
        """
        Set the properties of the transceiver collected in self.transceivers.

        :param GstWebRTCTransceiver transceiver: Transceiver object.
        :param Dict[str, Any] props_dict: Dictionary containing the properties to be set.
        :param int index: Index of the transceiver. Default is -1 (the last).
        :return: True if the properties are set successfully, False otherwise.
        """
        for key in props_dict:
            old_prop = transceiver.get_property(key)
            if old_prop is not None:
                transceiver.set_property(key, props_dict[key])
                LOGGER.info(f"ACTION: changed {key} for {transceiver.get_name()} from {old_prop} to {props_dict[key]}")
            else:
                LOGGER.error(f"ERROR: can't set {key} for {transceiver.get_name()}, property not found")
                return False
        return True

    def maybe_set_letterboxes(self, border: Dict[str, int] = {"width": 1024, "height": 768}) -> bool:
        """
        Set the letterboxes for the video rendering if resolution is below the border

        :param Dict[str, int] border: Dictionary containing the border resolution.
        :return: True if the letterboxes properties are succesfully tweaked, False otherwise.
        """
        do_set = False
        if self.scaling_elements:
            if not "width" in self.resolution or not "height" in self.resolution:
                LOGGER.error("ERROR: can't decide on letterboxes, border value should contain 'width' and 'height'")
                return False
            if self.resolution["width"] < border["width"] or self.resolution["height"] < border["height"]:
                do_set = True
            for scaling_element in self.scaling_elements:
                scaling_element.set_property("add-borders", do_set)
            return True
        return False

    def is_webrtc_ready(self) -> bool:
        return self.webrtcbin is not None

    def create_data_channel(
        self,
        name: str,
        options: Gst.Structure = None,
        callbacks: Dict[str, Callable[[Dict], Any]] | None = None,
    ) -> None:
        wait_for_condition(lambda: self.is_webrtc_ready(), self.max_timeout)
        if options is None:
            # default dc options which I found good to have
            dc_options = Gst.Structure.new_from_string("application/data-channel")
            dc_options.set_value("ordered", True)
            dc_options.set_value("max-retransmits", 2)
        else:
            dc_options = options

        data_channel = self.webrtcbin.emit('create-data-channel', name, options)
        if not data_channel:
            raise GSTWEBRTCAPP_EXCEPTION(f"Can't create data channel {name}")

        self.data_channels_data[name] = asyncio.Queue()

        # with false you may override them on your own
        if callbacks is None:
            data_channel.connect('on-open', lambda _: LOGGER.info(f"OK: data channel {name} is opened"))
            data_channel.connect('on-close', lambda _: LOGGER.info(f"OK: data channel {name} is closed"))
            data_channel.connect('on-error', lambda _: LOGGER.info(f"ERROR: data channel {name} met an error"))
            data_channel.connect(
                'on-message-string',
                lambda _, message: self.data_channels_data[name].put_nowait(json.loads(message)),
            )
        else:
            for event in callbacks:
                try:
                    data_channel.connect(event, callbacks[event])
                except Exception as e:
                    raise GSTWEBRTCAPP_EXCEPTION(f"Can't attach callback for event {event} to data channel {name}: {e}")

        self.data_channels[name] = data_channel
        LOGGER.info(f"OK: created data channel {name}")

    def set_data_channels(self) -> None:
        if self.data_channels_cfgs:
            for dc_cfg in self.data_channels_cfgs:
                name = dc_cfg.get("name", None)
                if name is not None:
                    self.create_data_channel(
                        name,
                        dc_cfg.get("options", None),
                        dc_cfg.get("callbacks", None),
                    )
                else:
                    LOGGER.error("ERROR: can't create data channel, 'name' is not found in the config")

    def is_data_channel_ready(self, data_channel_name: str) -> bool:
        dc = self.data_channels[data_channel_name]
        return dc and dc.get_property("ready-state") == GstWebRTC.WebRTCDataChannelState.OPEN

    def send_data_channel_message(self, data_channel_name: str, data: Dict[str, Any]) -> bool:
        if not self.is_data_channel_ready(data_channel_name):
            LOGGER.debug(f"dropping message, data channel {data_channel_name} is not ready")
            return False
        self.data_channels[data_channel_name].emit("send-string", json.dumps(data))
        return True

    async def handle_pipeline(self) -> None:
        # run the loop to fetch messages from the bus
        LOGGER.info("OK: PIPELINE HANDLER IS ON -- ready to read pipeline bus messages")
        self.bus = self.pipeline.get_bus()
        try:
            while True:
                message = self.bus.timed_pop_filtered(
                    0.1 * Gst.SECOND,
                    Gst.MessageType.APPLICATION
                    | Gst.MessageType.EOS
                    | Gst.MessageType.ERROR
                    | Gst.MessageType.LATENCY
                    | Gst.MessageType.STATE_CHANGED,
                )
                if message:
                    message_type = message.type
                    if message_type == Gst.MessageType.APPLICATION:
                        if message.get_structure().get_name() == "termination":
                            LOGGER.info("INFO: received termination message, preparing to terminate the pipeline...")
                            break
                        elif message.get_structure().get_name() == "post-init":
                            LOGGER.info(
                                "INFO: received post-init message, preparing to continue initializing the pipeline"
                            )
                            self._post_init_pipeline()
                    elif message_type == Gst.MessageType.EOS:
                        LOGGER.info("INFO: got EOS message, preparing to terminate the pipeline...")
                        break
                    elif message_type == Gst.MessageType.ERROR:
                        err, _ = message.parse_error()
                        LOGGER.error(f"ERROR: Pipeline error")
                        self.is_running = False
                        raise GSTWEBRTCAPP_EXCEPTION(err.message)
                    elif message_type == Gst.MessageType.LATENCY:
                        try:
                            self.pipeline.recalculate_latency()
                            LOGGER.debug("INFO: latency is recalculated")
                        except Exception as e:
                            raise GSTWEBRTCAPP_EXCEPTION(f"can't recalculate latency, reason: {e}")
                    elif message_type == Gst.MessageType.STATE_CHANGED:
                        if message.src == self.pipeline:
                            old, new, _ = message.parse_state_changed()
                            LOGGER.info(
                                "INFO: Pipeline state changed from "
                                f"{Gst.Element.state_get_name(old)} to "
                                f"{Gst.Element.state_get_name(new)}"
                            )
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            LOGGER.info("ERROR: handle_pipeline, KeyboardInterrupt received, exiting...")

        LOGGER.info("OK: PIPELINE HANDLER IS OFF")
        self.is_running = False
        self.terminate_pipeline()

    def terminate_pipeline(self) -> None:
        LOGGER.info("OK: terminating pipeline...")
        for data_channel_name in self.data_channels.keys():
            self.data_channels[data_channel_name].emit('close')
            LOGGER.info(f"OK: data channel {data_channel_name} is closed")
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            LOGGER.info("OK: set pipeline state to NULL")
        if self.webrtcbin:
            self.webrtcbin.set_state(Gst.State.NULL)
            self.webrtcbin = None
            LOGGER.info("OK: set webrtcbin state to NULL")
        self.source = None
        self.encoder = None
        self.raw_caps = None
        self.raw_capsfilter = None
        self.pay_capsfilter = None
        self.transceivers = []
        self.data_channels = {}
        LOGGER.info("OK: pipeline is terminated!")

    def send_termination_message_to_bus(self) -> None:
        if self.bus is not None:
            LOGGER.info("OK: sending termination message to the pipeline's bus")
            self.bus.post(Gst.Message.new_application(None, Gst.Structure.new_empty("termination")))
        else:
            LOGGER.error("ERROR: can't send termination message to the pipeline's bus, bus is None")

    def send_post_init_message_to_bus(self) -> None:
        if self.bus is not None:
            LOGGER.info("OK: sending post-init message to the pipeline's bus")
            self.bus.post(Gst.Message.new_application(None, Gst.Structure.new_empty("post-init")))
        else:
            LOGGER.error("ERROR: can't send post-init message to the pipeline's bus, bus is None")

    async def async_connect_signal(
        self,
        attribute_name: str,
        signal: str,
        callback: Callable,
        condition: Callable | None = None,
        timeout: int | None = None,
    ) -> None:
        if condition is not None:
            await async_wait_for_condition(condition, timeout or self.max_timeout)
        attr = getattr(self, attribute_name, None)
        if attr is None:
            LOGGER.error(
                f"ERROR: can't connect signal {signal} to callback {callback.__name__}, {attribute_name} is None"
            )
            return
        attr.connect(signal, callback)
