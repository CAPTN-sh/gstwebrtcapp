"""
app.py

Description: An application that controls the GStreamer pipeline with webrtcsink as WebRTC producer.
Requires browser js client as well as websocket signalling server to connect to the pipeline and control it.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

import asyncio
from collections import OrderedDict
import re
import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstRtp', '1.0')
gi.require_version('GstWebRTC', '1.0')
from gi.repository import Gst
from gi.repository import GstRtp
from gi.repository import GstWebRTC

from gstwebrtcapp.apps.app import GstWebRTCApp, GstWebRTCAppConfig
from gstwebrtcapp.apps.pipelines import SINK_H264_IN_H264_OUT_PIPELINE
from gstwebrtcapp.utils.base import GSTWEBRTCAPP_EXCEPTION, LOGGER, wait_for_condition
from gstwebrtcapp.utils.gst import DEFAULT_GCC_SETTINGS, dump_to_dot
from gstwebrtcapp.utils.webrtc import TWCC_URI


class SinkApp(GstWebRTCApp):
    """
    An application that uses GStreamer's WEBRTCSINK plugin to stream the video source to the Google Chrome API Client.
    """

    def __init__(
        self,
        config: GstWebRTCAppConfig = GstWebRTCAppConfig(pipeline_str=SINK_H264_IN_H264_OUT_PIPELINE),
    ) -> None:
        self.pipeline = None
        self.webrtcsink = None
        self.webrtcsink_pipeline = None
        self.webrtcsink_elements = OrderedDict()
        self.webrtcbin = None
        self.source = None
        self.signaller = None
        self.gcc = None
        self.gcc_estimated_bitrates = asyncio.Queue()
        self.encoder = None
        self.encoder_caps = None
        self.encoder_capsfilter = None
        self.payloader = None
        self.twcc_id = None
        self.transceivers = []
        self.bus = None

        super().__init__(config)

    def _init_pipeline(self) -> None:
        # pipeline
        if self.video_url is not None:
            self.pipeline_str, _ = re.subn(r'(location=)[^ ]*', f'\\1{self.video_url}', self.pipeline_str)
        LOGGER.info(f"OK: initializing pipeline from a string {self.pipeline_str}...")
        self.pipeline = Gst.parse_launch(self.pipeline_str)
        if not self.pipeline:
            raise GSTWEBRTCAPP_EXCEPTION(f"can't create pipeline from {self.pipeline_str}")
        if self.is_graph:
            dump_to_dot(self.pipeline, Gst.DebugGraphDetails.ALL, "sinkapp")

        # webrtcsink
        self.webrtcsink = self.pipeline.get_by_name("ws")
        if not self.webrtcsink:
            raise GSTWEBRTCAPP_EXCEPTION(f"Can't get webrtcsink from the pipeline {self.pipeline_str}")
        LOGGER.info("OK: webrtcsink is found in the pipeline")
        self.log_file = None

        # get signaller
        self.signaller = self.webrtcsink.get_property("signaller")
        if not self.signaller:
            raise GSTWEBRTCAPP_EXCEPTION("Can't get signaller from the webrtcsink")

        # get webrtcsink pipeline and collect its mutable elements
        self.webrtcsink.connect(
            'consumer-pipeline-created',
            self._cb_webrtcsink_pipeline_created,
        )

        # get webrtcbin to create data channels and set up the WebRTC connection
        self.webrtcsink.connect(
            'consumer-added',
            self._cb_webrtcbin_created,
        )

        # get all encoders to tweak their properties later
        self.webrtcsink.connect(
            'encoder-setup',
            self._cb_encoder_setup,
        )

        self.webrtcsink.connect(
            'payloader-setup',
            self._cb_payloader_setup,
        )

        # assign video caps directly to the encoder selecting therefore the target encoder
        # NOTE: it can only be done for the encoder thanks to video-caps property, others require to tweak their capsfilters
        enc_caps = self.get_caps(is_only_header=True)
        enc_caps.set_value("stream-format", "byte-stream")
        self.webrtcsink.set_property("video-caps", enc_caps)
        LOGGER.info(f"OK: set target video caps to webrtcsink")

        # create gcc estimator
        self.gcc = Gst.ElementFactory.make("rtpgccbwe")
        if not self.gcc:
            raise GSTWEBRTCAPP_EXCEPTION("Can't create rtpgccbwe")
        LOGGER.info("OK: rtpgccbwe is created")

        # switch to playing state
        r = self.pipeline.set_state(Gst.State.PLAYING)
        if r == Gst.StateChangeReturn.FAILURE:
            # NOTE: unlike the webrtcbin, webrtcsink pipeline returns GST_STATE_ASYNC so that we should check it has not failed
            raise GSTWEBRTCAPP_EXCEPTION("unable to set the pipeline to the playing state")
        else:
            self.is_running = True

    def _post_init_pipeline(self) -> None:
        LOGGER.info("OK: start post init pipeline actions after starting the bus...")
        if not self.webrtcsink_elements:
            raise GSTWEBRTCAPP_EXCEPTION("WebRTCSink elements are not collected")

        # wait until the target encoder is found and raise an exception if it is not found
        wait_for_condition(lambda: self.encoder is not None, self.max_timeout)

        # HACK: you can't tweak caps of enc src pad, they are not writable, but you can tweak its following capsfilter
        try:
            elements_key_list = list(self.webrtcsink_elements.keys())
            encoder_index = elements_key_list.index(self.encoder.get_name())
            self.encoder_capsfilter = self.webrtcsink_elements[elements_key_list[encoder_index + 1]]
        except ValueError:
            raise GSTWEBRTCAPP_EXCEPTION("Can't find encoder in the webrtcsink pipeline")

        # set priority to the rtp sender
        self.set_priority(self.priority)

        # set initial values
        self.set_bitrate(self.bitrate)
        self.set_resolution(self.resolution["width"], self.resolution["height"])
        self.set_framerate(self.framerate)
        self.set_fec_percentage(self.fec_percentage)

        # ok!
        LOGGER.info("OK: WebRTCSink is fully ready!")

    def get_caps(self, is_only_header: bool = False) -> Gst.Caps:
        enc_part = ""
        match self.encoder_gst_name:
            case "vp8enc":
                enc_part = "video/x-vp8"
            case "vp9enc":
                enc_part = "video/x-vp9"
            case "x264enc" | "nvh264enc":
                enc_part = "video/x-h264"
            case "x265enc" | "nvh265enc":
                enc_part = "video/x-h265"
            case "av1enc" | "nvav1enc":
                enc_part = "video/x-av1"
            case _:
                raise GSTWEBRTCAPP_EXCEPTION(f"unknown codec {self.encoder_gst_name}")
        if is_only_header:
            return Gst.Caps.from_string(enc_part)
        else:
            return Gst.Caps.from_string(
                f"{enc_part},width={self.resolution['width']},height={self.resolution['height']},framerate={self.framerate}/1,"
            )

    def set_priority(self, priority: int) -> None:
        # set priority to the sender. Corresponds to 8, 0, 36, 38 DSCP values.
        match priority:
            case 1:
                wrtc_priority_type = GstWebRTC.WebRTCPriorityType.VERY_LOW
            case 2:
                wrtc_priority_type = GstWebRTC.WebRTCPriorityType.LOW
            case 3:
                wrtc_priority_type = GstWebRTC.WebRTCPriorityType.MEDIUM
            case 4:
                wrtc_priority_type = GstWebRTC.WebRTCPriorityType.HIGH
            case _:
                wrtc_priority_type = GstWebRTC.WebRTCPriorityType.LOW
        sender = self.transceivers[0].get_property("sender")
        if sender is not None:
            sender.set_priority(wrtc_priority_type)
            LOGGER.info(f"OK: set priority (DSCP marking) to {priority}, min 1, max 4")
        else:
            LOGGER.error("ERROR: can't set priority to the sender")

    def set_bitrate(self, bitrate_kbps: int) -> bool:
        if not self.encoder:
            return False
        if self.encoder_gst_name.startswith("nv") or self.encoder_gst_name.startswith("x26"):
            self.encoder.set_property("bitrate", bitrate_kbps)
        elif self.encoder_gst_name.startswith("vp") or self.encoder_gst_name.startswith("av"):
            self.encoder.set_property("target-bitrate", bitrate_kbps * 1000)
        else:
            raise GSTWEBRTCAPP_EXCEPTION(f"encoder {self.encoder_gst_name} is not supported")
        self.bitrate = bitrate_kbps
        return True

    def set_resolution(self, width: int, height: int) -> bool:
        if not self.encoder_capsfilter:
            return False
        self.resolution = {"width": width, "height": height}
        self.encoder_caps = self.get_caps()
        self.encoder_capsfilter.set_property("caps", self.encoder_caps)
        self.maybe_set_letterboxes()
        return True

    def set_framerate(self, framerate: int) -> bool:
        # FIXME: 60 is hardcoded in a default pipeline. That is reasonable for 99% of streams, make configurable later
        if not self.encoder_capsfilter:
            return False
        self.framerate = min(60, framerate)
        self.encoder_caps = self.get_caps()
        self.encoder_capsfilter.set_property("caps", self.encoder_caps)
        return True

    def set_fec_percentage(self, percentage: int, index: int = -1) -> bool:
        percentage = min(100, max(0, percentage))
        if not self.transceivers:
            LOGGER.error("ERROR: there is no transceivers in the pipeline")
            return False
        if index > 0:
            try:
                transceiver = self.transceivers[index]
                transceiver.set_property("fec-percentage", percentage)
            except IndexError:
                LOGGER.error(f"ERROR: can't find tranceiver with index {index}")
                return False
        else:
            for transceiver in self.transceivers:
                transceiver.set_property("fec-percentage", percentage)
        self.fec_percentage = percentage
        return True

    # additional setter to set fully custom encoder caps
    def set_encoder_caps(self, caps_dict: dict) -> bool:
        if not self.encoder_capsfilter:
            return False
        new_caps_str = self.get_sink_video_caps().to_string()
        for key in caps_dict:
            new_caps_str += f",{key}={str(caps_dict[key])}"
        self.encoder_caps = Gst.Caps.from_string(new_caps_str)
        self.encoder_capsfilter.set_property("caps-change-mode", "delayed")
        self.encoder_capsfilter.set_property("caps", self.encoder_caps)
        LOGGER.info(f"ACTION: set new caps for encoder {self.encoder_caps.to_string()}")
        return True

    ################# NOTIFIERS #####################
    ## gcc
    def on_estimated_bitrate_changed(self, bwe, pspec) -> None:
        if bwe and pspec.name == "estimated-bitrate":
            estimated_bitrate = self.gcc.get_property(pspec.name)
            self.gcc_estimated_bitrates.put_nowait(estimated_bitrate)
        else:
            raise GSTWEBRTCAPP_EXCEPTION("Can't get estimated bitrate by gcc")

    ################# CALLBACKS #####################
    ## get webrtcbin
    def _cb_webrtcbin_created(self, _, __, bin):
        if bin:
            LOGGER.info(f"OK: got webrtcbin, collecting its transceivers...")
            self.webrtcbin = bin
            # NOTE: it is possible to create data channels ONLY here because webrtcbin does not support
            # renegotiation for new data channels. Therefore pass their cfgs as a parameter to the constructor
            # and call here before webrtcbin goes into STABLE state
            self.set_data_channels()

            # add gcc estimator
            self.webrtcbin.connect("request-aux-sender", self._cb_add_gcc)
            self.webrtcbin.connect('deep-element-added', self._cb_deep_element_added)

            # get all transceivers
            index = 0
            while True:
                transceiver = self.webrtcbin.emit('get-transceiver', index)
                if transceiver:
                    self.transceivers.append(transceiver)
                    index += 1
                else:
                    break

    ## get webrtcsink pipeline an all its elements
    def _cb_webrtcsink_pipeline_created(self, _, __, ppl):
        if ppl:
            LOGGER.info(f"OK: got webrtcsink pipeline, collecting its elements...")
            self.webrtcsink_pipeline = ppl
            self.webrtcsink_pipeline.connect(
                'deep-element-added',
                self._cb_get_all_elements,
            )

    ## get all encoders to tweak their properties later
    def _cb_encoder_setup(self, _, __, ___, enc):
        if enc and self.webrtcsink_elements:
            name = str(enc.get_name())
            self.encoder = enc
            if name.startswith(self.encoder_gst_name):
                LOGGER.info(f"OK: the target encoder is found: {name}")
            else:
                LOGGER.info(f"OK: another than {self.encoder_gst_name} encoder is found: {name}")
        return False

    def _cb_payloader_setup(self, _, __, ___, payloader):
        if payloader:
            self.payloader = payloader
            if self.gcc_settings is not None and self.twcc_id is None:
                try:
                    # NOTE: this requires GStreamer 1.24+
                    extensions = self.payloader.get_property("extensions")
                    if extensions is not None:
                        size = Gst.ValueArray.get_size(extensions)
                        if size > 0:
                            ids = []
                            for i in range(Gst.ValueArray.get_size(extensions)):
                                e = Gst.ValueArray.get_value(extensions, i)
                                if e.get_uri() == TWCC_URI:
                                    # transport-cc already exists
                                    self.twcc_id = e.get_id()
                                    return False
                        self.twcc_id = next(i for i in range(len(ids) + 1) if i not in set(ids)) if ids else 1
                    else:
                        self.twcc_id = 1
                except Exception:
                    extensions = None
                    self.twcc_id = 1
                twcc_ext = GstRtp.RTPHeaderExtension.create_from_uri(TWCC_URI)
                twcc_ext.set_id(self.twcc_id)
                self.payloader.emit("add-extension", twcc_ext)
        return False

    ## get all elements from the webrtcsink pipeline
    def _cb_get_all_elements(self, _, __, element):
        if element:
            self.webrtcsink_elements[element.get_name()] = element
            if "scale" in element.get_name():
                self.scaling_elements.append(element)

    def _cb_deep_element_added(self, _, __, ___):
        pass

    ## set gcc algorithm in passive mode and save its estimated bitrate on each notification
    def _cb_add_gcc(self, _, __):
        LOGGER.info("OK: adding gcc estimator...")
        min_bitrate = (
            self.gcc_settings["min-bitrate"]
            if self.gcc_settings is not None and "min-bitrate" in self.gcc_settings
            else DEFAULT_GCC_SETTINGS["min-bitrate"]
        )
        max_bitrate = (
            self.gcc_settings["max-bitrate"]
            if self.gcc_settings is not None and "max-bitrate" in self.gcc_settings
            else DEFAULT_GCC_SETTINGS["max-bitrate"]
        )
        self.gcc.set_property("min-bitrate", min_bitrate)
        self.gcc.set_property("max-bitrate", max_bitrate)
        self.gcc.set_property("estimated-bitrate", self.bitrate * 1000)
        self.gcc.connect("notify::estimated-bitrate", self.on_estimated_bitrate_changed)
        return self.gcc
