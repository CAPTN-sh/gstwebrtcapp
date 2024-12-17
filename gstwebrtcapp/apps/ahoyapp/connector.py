"""
connector.py

Description: A connector that connects to the ADDIX AhoyMedia WebRTC client and handles the WebRTC signalling.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import asyncio
import json
import requests
import threading
from typing import List

import gi


gi.require_version('Gst', '1.0')
gi.require_version('GstSdp', '1.0')
gi.require_version('GstWebRTC', '1.0')
from gi.repository import Gst
from gi.repository import GstSdp
from gi.repository import GstWebRTC

from gstwebrtcapp.apps.app import GstWebRTCAppConfig
from gstwebrtcapp.apps.ahoyapp.app import AhoyApp
from gstwebrtcapp.control.agent import Agent, AgentType
from gstwebrtcapp.control.safety.switcher import SwitchingPair
from gstwebrtcapp.media.preset import get_video_preset, get_video_preset_by_bitrate
from gstwebrtcapp.message.client import MqttConfig, MqttPair, MqttPublisher, MqttSubscriber
from gstwebrtcapp.network.controller import NetworkController
from gstwebrtcapp.utils.app import get_agent_type_by_switch_code, get_switch_code_by_agent_type
from gstwebrtcapp.utils.base import LOGGER, wait_for_condition, async_wait_for_condition
from gstwebrtcapp.utils.gst import GstWebRTCStatsType, find_stat, stats_to_dict


class AhoyConnector:
    """
    A connector that connects to the ADDIX AhoyMedia WebRTC client and handles the WebRTC signalling.

    :param str server: AhoyMedia server URL.
    :param str api_key: AhoyMedia API key.
    :param app_config: Configuration for the GStreamer WebRTC application.
    :param agents: List of agents that manipulate the pipeline. Nullable.
    :param feed_name: Feed name for the connection.
    :param signalling_channel_name: Name of the signalling channel.
    :param stats_channel_name: Name of the stats channel.
    :param mqtt_config: Configuration for the MQTT client.
    :param network_controller: Network controller that optionally controls the network rules. Nullable.
    :param switching_pair: Pair of agents for safety detector and switching. Nullable.
    :param share_ice_topic: Topic for sharing ICE candidates. Nullable.
    """

    def __init__(
        self,
        server: str,
        api_key: str,
        app_config: GstWebRTCAppConfig = GstWebRTCAppConfig(),
        agents: List[Agent] | None = None,
        feed_name: str = "gstreamerwebrtcapp",
        signalling_channel_name: str = "control",
        stats_channel_name: str = "telemetry",
        mqtt_config: MqttConfig = MqttConfig(),
        network_controller: NetworkController | None = None,
        switching_pair: SwitchingPair | None = None,
        share_ice_topic: str | None = None,
    ):
        self.server = server
        self.api_key = api_key
        self.feed_name = feed_name

        # pc_out is used to send SDP offer to Ahoy and receive SDP answer to set the signalling data channel
        self.pc_out = RTCPeerConnection(RTCConfiguration([RTCIceServer("stun:stun.l.google.com:19302")]))
        self.signalling_channel = self.pc_out.createDataChannel(signalling_channel_name, ordered=True)
        self.stats_channel = self.pc_out.createDataChannel(stats_channel_name, ordered=True)

        # internal webrtc
        self._app = None
        self.app_config = app_config
        self.payload_type = None
        self.webrtcbin_sdp = None
        self.webrtcbin_ice_connection_state = GstWebRTC.WebRTCICEConnectionState.NEW
        self.pc_out_ice_connection_state = "new"

        # agents
        self.agents = {}
        self.agent_threads = {}
        self.switching_pair = switching_pair
        self.is_switching = False
        self._prepare_agents(agents)

        # mqtt
        self.mqtt_config = mqtt_config
        self.mqtts = MqttPair(
            publisher=MqttPublisher(self.mqtt_config),
            subscriber=MqttSubscriber(self.mqtt_config),
        )
        self.network_controller = network_controller
        self.share_ice_topic = share_ice_topic
        self.is_share_ice = False

        self.is_running = False
        self.is_locked = True

        self.webrtc_coro_control_task = None

    async def connect_coro(self) -> None:
        LOGGER.info(f"OK: connecting to AhoyMedia...")

        # set handlers for pc_out
        self._set_pc_out_handlers()

        # create local offer
        local_offer = await self.pc_out.createOffer()
        await self.pc_out.setLocalDescription(local_offer)

        # send request to ahoy director
        headers = {
            "accept": "application/json",
            "x-api-key": self.api_key,
            "content-type": "application/json",
        }
        data = {
            "sdp": self.pc_out.localDescription.sdp,
            "candidates": "",
            "capabilities": {"video": {"codecs": [self.app_config.codec.upper()]}},
            "name": self.feed_name,
        }
        request = requests.post(
            self.server + requests.utils.quote(self.feed_name),
            headers=headers,
            data=json.dumps(data),
        )
        LOGGER.info(f"INFO: connect, request ... {request}")
        LOGGER.info(f"INFO: connect, request.status_code ... {request.status_code}")

        # retrieve response
        response = request.json()
        LOGGER.info(f"INFO: connect_pc_out, response ... {response}")

        # create sdp with candidates
        sdp_lines = response["sdp"].split("\r\n")[:-1]
        sdp_candidates = [f"a={candidate['candidate']}" for candidate in response["candidates"]]
        remote_sdp = "\r\n".join([*sdp_lines, *sdp_candidates, ""])
        LOGGER.info(f"INFO: connect_pc_out, remote_sdp ... {remote_sdp}")

        # create remote answer
        remote_answer = RTCSessionDescription(type="answer", sdp=remote_sdp)
        await self.pc_out.setRemoteDescription(remote_answer)
        LOGGER.info(f"OK: webrtc signalling is finished, waiting for messages on signalling channel...")

    def _set_pc_out_handlers(self) -> None:
        @self.pc_out.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            LOGGER.info(f"INFO: on_connectionstatechange, pc_out ... {self.pc_out.connectionState}")
            self.pc_out_ice_connection_state = self.pc_out.connectionState

        @self.signalling_channel.on("message")
        async def on_message(msg) -> None:
            msg = json.loads(msg)
            if "streamStartRequest" in msg:
                # streamStartRequest is received when the stream is played on the Ahoy side
                if msg["streamStartRequest"]["feedUuid"] == self.feed_name:
                    LOGGER.info(f"INFO: SIGNALLING CHANNEL received streamStartRequest {msg}")

                    self.is_running = True
                    self.is_locked = False

                    streamStartResponse = {
                        "streamStartResponse": {
                            "success": True,
                            "uuid": msg["streamStartRequest"]["uuid"],
                            "feedUuid": msg["streamStartRequest"]["feedUuid"],
                        }
                    }
                    data = {
                        "message": {
                            "to": f"director.api_{self.api_key}",
                            "payload": streamStartResponse,
                        }
                    }
                    self.signalling_channel.send(json.dumps(data))
            elif "sdpRequest" in msg:
                # sdpRequest is received next after streamStartRequest to set up the WebRTC connection
                if not self.is_locked:
                    self.is_locked = True
                    LOGGER.info(f"INFO: SIGNALLING CHANNEL received sdpRequest {msg}")

                    self._on_received_sdp_request(msg["sdpRequest"]["sdp"])

                    wait_for_condition(lambda: self.webrtcbin_sdp is not None, self._app.max_timeout)
                    LOGGER.info(
                        f"INFO: on_message, succesfully created local answer for webrtcbin on incoming SDP request..."
                    )

                    candidates = msg["sdpRequest"]["candidates"]
                    for candidate in candidates:
                        LOGGER.info(f"INFO: on_message, adding ice candidate ... {candidate['candidate']}")
                        self._app.webrtcbin.emit(
                            'add-ice-candidate', candidate['sdpMLineIndex'], candidate['candidate']
                        )

                    sdpResponse = {
                        "sdpResponse": {
                            "success": True,
                            "uuid": msg["sdpRequest"]["uuid"],
                            "sdp": self.webrtcbin_sdp.as_text(),
                        }
                    }
                    data = {"message": {"to": f"director.api_{self.api_key}", "payload": sdpResponse}}
                    self.signalling_channel.send(json.dumps(data))
            elif "streamStopRequest" in msg:
                # streamStopRequest is received when the stream is stopped on the Ahoy side
                if msg["streamStopRequest"]["feedUuid"] == self.feed_name:
                    if self.is_running:
                        LOGGER.info(f"INFO: SIGNALLING CHANNEL received streamStopRequest {msg}")
                        if self.mqtts.publisher.client.is_connected() and self.mqtt_config.topics.controller:
                            # if it is terminated by the UI, notify the controller
                            self.mqtts.publisher.publish(
                                self.mqtt_config.topics.controller,
                                json.dumps({self.feed_name: {"off": False}}),
                            )
                        self.terminate_webrtc_coro(is_restart_webrtc_coro=True)
            else:
                LOGGER.info(f"INFO: SIGNALLING CHANNEL received currently unhandled message {msg}")

        @self.stats_channel.on("message")
        async def on_message(msg) -> None:
            # TODO: currently nothing comes from Ahoy to trigger this handler
            LOGGER.info(f"INFO: STATS CHANNEL received stats message {msg}")

    def _on_received_sdp_request(self, sdp) -> None:
        LOGGER.info(f"INFO: _on_received_sdp_request callback, processing the incoming SDP request...")
        res, sdpmsg = GstSdp.SDPMessage.new_from_text(sdp)
        if res < 0:
            LOGGER.error(f"ERROR: _on_received_sdp_request callback, failed to parse remote offer SDP")
            self.terminate_webrtc_coro()

        # NOTE: the app (GstPipeline) starts first when the video content is requested. Before that this object is None
        try:
            self._app = AhoyApp(self.app_config)
            if self._app is None:
                LOGGER.error(f"ERROR: _on_received_sdp_request callback, failed to create AhoyApp object")
                self.terminate_webrtc_coro()
        except Exception as e:
            LOGGER.error(
                f"ERROR: _on_received_sdp_request callback, failed to create AhoyApp object due to an excepion:\n {str(e)}..."
            )
            self.terminate_webrtc_coro()
        wait_for_condition(lambda: self._app.is_webrtc_ready(), self._app.max_timeout)
        self._app.webrtcbin.connect('on-negotiation-needed', lambda _: None)
        self._app.webrtcbin.connect('notify::ice-connection-state', self._on_ice_connection_state_notify)

        # add new transceiver
        # self._add_transceiver(sdpmsg)

        # set remote offer and create answer
        remote_offer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, sdpmsg)
        promise = Gst.Promise.new_with_change_func(self._on_offer_set, None, None)
        self._app.webrtcbin.emit('set-remote-description', remote_offer, promise)

    def _add_transceiver(self, sdpmsg) -> None:
        # assign new media, we assumed that we are interested only in the first one
        media = sdpmsg.get_media(0)
        if media is None:
            LOGGER.error(f"ERROR: _add_transceiver callback, failed to get media at index 0 from remote offer's sdp")
            self.terminate_webrtc_coro()

        # get new caps
        trans_caps = Gst.Caps.from_string("application/x-rtp")
        res = media.attributes_to_caps(trans_caps)
        if res != GstSdp.SDPResult.OK or trans_caps.is_empty():
            LOGGER.error(f"ERROR: _add_transceiver callback, failed to convert media's attributes to the caps")
            self.terminate_webrtc_coro()

        # add new transceiver
        dir = GstWebRTC.WebRTCRTPTransceiverDirection.SENDRECV
        self._app.webrtcbin.emit('add-transceiver', dir, trans_caps)
        # app has at least 1 default transceiver, when we add first new here, we have len(app.tr..) + 1
        ahoy_transceiver = self._app.webrtcbin.emit('get-transceiver', len(self._app.transceivers))
        if ahoy_transceiver is None:
            LOGGER.error(f"ERROR: _add_transceiver callback, failed to retrieve a newly added transceiver")
            self.terminate_webrtc_coro()
        else:
            ahoy_transceiver.set_property('do-nack', True)
            ahoy_transceiver.set_property("fec-type", GstWebRTC.WebRTCFECType.ULP_RED)
        self._app.transceivers.append(ahoy_transceiver)

        LOGGER.info(
            "INFO: _add_transceiver, added new transceiver, now there are"
            f" {self._app.webrtcbin.emit('get-transceivers').len} transceivers in webrtcbin"
        )

    def _on_offer_set(self, promise, _, __) -> None:
        assert promise.wait() == Gst.PromiseResult.REPLIED, "FAIL: offer set promise was not replied"
        promise = Gst.Promise.new_with_change_func(self._on_answer_created, None, None)
        self._app.webrtcbin.emit('create-answer', None, promise)

    def _on_answer_created(self, promise, _, __) -> None:
        assert promise.wait() == Gst.PromiseResult.REPLIED, "FAIL: create answer promise was not replied"
        reply = promise.get_reply()
        answer = reply.get_value('answer')
        answer_sdp = answer.sdp
        for i in range(0, answer_sdp.medias_len()):
            media = answer_sdp.get_media(i)
            for j in range(0, media.attributes_len()):
                attr = media.get_attribute(j)
                if attr.key == 'recvonly':
                    LOGGER.info(f"INFO: _on_answer_created callback, found recvonly attribute")
                    media.remove_attribute(j)
                    attr = GstSdp.SDPAttribute()
                    attr.set('sendrecv', attr.value)
                    media.insert_attribute(j, attr)
                    LOGGER.info(f"INFO: _on_answer_created callback, changed recvonly to sendrecv")
                if attr.key == 'fmtp':
                    self.payload_type = int(attr.value.split(' ')[0])
                    LOGGER.info(f"INFO: _on_answer_created callback, found payload type {self.payload_type}")
        promise = Gst.Promise.new()
        self._app.webrtcbin.emit('set-local-description', answer, promise)
        promise.interrupt()
        self.webrtcbin_sdp = answer.sdp
        LOGGER.info(f"INFO: _on_answer_created callback, successfully created a local answer for webrtcbin")

    def _on_ice_connection_state_notify(self, pspec, _) -> None:
        self.webrtcbin_ice_connection_state = self._app.webrtcbin.get_property('ice-connection-state')
        LOGGER.info(f"INFO: webrtcbin's ICE connecting state has been changed to {self.webrtcbin_ice_connection_state}")
        if self.webrtcbin_ice_connection_state == GstWebRTC.WebRTCICEConnectionState.CONNECTED:
            LOGGER.info("OK: ICE connection is established")
            if self.share_ice_topic and not self.is_share_ice:
                self.is_share_ice = True

    def _on_get_webrtcbin_stats(self, promise, _, __) -> None:
        assert promise.wait() == Gst.PromiseResult.REPLIED, "FAIL: get webrtcbin stats promise was not replied"
        stats = {}
        stats_struct = promise.get_reply()
        if stats_struct.n_fields() > 0:
            session_struct_n_fields = stats_struct.n_fields()
            for i in range(session_struct_n_fields):
                stat_name = stats_struct.nth_field_name(i)
                stat_value = stats_struct.get_value(stat_name)
                if isinstance(stat_value, Gst.Structure):
                    stats[stat_name] = stats_to_dict(stat_value.to_string())
        else:
            LOGGER.error(f"ERROR: no stats to save...")

        if self.is_share_ice:
            self.is_share_ice = False
            icls = find_stat(stats, GstWebRTCStatsType.ICE_CANDIDATE_LOCAL)
            icrs = find_stat(stats, GstWebRTCStatsType.ICE_CANDIDATE_REMOTE)
            if icls and icrs:
                payload = {
                    "feed_name": self.feed_name,
                    "ice_candidate_local_stats": icls[0],
                    "ice_candidate_remote_stats": icrs[0],
                }
                self.mqtts.publisher.publish(self.share_ice_topic, json.dumps(payload))

        self.mqtts.publisher.publish(self.mqtt_config.topics.stats, json.dumps(stats))

    async def handle_ice_connection(self) -> None:
        LOGGER.info(f"OK: ICE CONNECTION HANDLER IS ON -- ready to check for ICE connection state")
        while (
            self.webrtcbin_ice_connection_state != GstWebRTC.WebRTCICEConnectionState.FAILED
            and self.webrtcbin_ice_connection_state != GstWebRTC.WebRTCICEConnectionState.DISCONNECTED
            and self.webrtcbin_ice_connection_state != GstWebRTC.WebRTCICEConnectionState.CLOSED
            and self.pc_out_ice_connection_state != "failed"
            and self.pc_out_ice_connection_state != "disconnected"
            and self.pc_out_ice_connection_state != "closed"
        ):
            await asyncio.sleep(0.1)
        LOGGER.info(f"OK: ICE CONNECTION HANDLER IS OFF!")
        if self.is_running:
            LOGGER.error(
                f"ERROR: ICE connection has failed! Webrtcbin state is {self.webrtcbin_ice_connection_state}, "
                f"pc_out state is {self.pc_out_ice_connection_state}"
            )
            self.terminate_webrtc_coro()

    async def handle_webrtcbin_stats(self) -> None:
        LOGGER.info(f"OK: WEBRTCBIN STATS HANDLER IS ON -- ready to check for stats")
        while self.is_running:
            await asyncio.sleep(0.1)
            promise = Gst.Promise.new_with_change_func(self._on_get_webrtcbin_stats, None, None)
            if self._app and self._app.webrtcbin:
                self._app.webrtcbin.emit('get-stats', None, promise)
        LOGGER.info(f"OK: WEBRTCBIN STATS HANDLER IS OFF!")

    async def handle_actions(self) -> None:
        LOGGER.info(f"OK: ACTIONS HANDLER IS ON -- ready to pick and apply actions")
        while self.is_running:
            action_msg = await self.mqtts.subscriber.message_queues[self.mqtt_config.topics.actions].get()
            msg = json.loads(action_msg.msg)
            if self._app is not None and len(msg) > 0:
                for action in msg:
                    if msg.get(action) is None:
                        LOGGER.error(f"ERROR: Action {action} has no value!")
                        continue
                    else:
                        match action:
                            case "bitrate":
                                # add 5% policy: if bitrate difference is less than 5% then don't change it
                                if abs(self._app.bitrate - msg[action]) / self._app.bitrate > 0.05:
                                    if self._app.set_bitrate(msg[action]):
                                        LOGGER.info(f"ACTION: feed {self.feed_name} set bitrate to {msg[action]}")
                                    if self._app.is_preset_tuning:
                                        p = get_video_preset_by_bitrate(msg[action])
                                        if self._app.set_preset(p, False):
                                            LOGGER.info(
                                                f"ACTION: feed {self.feed_name} changed preset to w: {p.width}, h: {p.height}, fps: {p.framerate}"
                                            )
                            case "resolution":
                                if isinstance(msg[action], dict) and "width" in msg[action] and "height" in msg[action]:
                                    if self._app.set_resolution(msg[action]['width'], msg[action]['height']):
                                        LOGGER.info(
                                            f"ACTION: feed {self.feed_name} set resolution to {msg[action]['width']}x{msg[action]['height']}"
                                        )
                                else:
                                    LOGGER.error(f"ERROR: Resolution action has invalid value: {msg[action]}")
                            case "framerate":
                                if self._app.set_framerate(msg[action]):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} set framerate to {msg[action]}")
                            case "fec":
                                if self._app.set_fec_percentage(msg[action]):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} set FEC % to {msg[action]}")
                            case "preset":
                                if self._app.set_preset(get_video_preset(msg[action])):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} set preset to {msg[action]}")
                            case "switch":
                                algo = msg[action]

                                if isinstance(algo, str):
                                    algo = get_switch_code_by_agent_type(algo)
                                    is_user_command = True
                                else:
                                    is_user_command = False

                                if self._switch_agents(algo, is_user_command):
                                    a_type = get_agent_type_by_switch_code(algo)
                                    s_str = "user" if is_user_command else "safety detector"
                                    LOGGER.info(
                                        f"ACTION: feed {self.feed_name} switched agent to {a_type} by the {s_str}"
                                    )
                            case "reload_agent":
                                if self._reload_agent(msg[action]):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} reloaded its {msg[action]} agent")
                            case "send_dc":
                                action = msg[action]
                                if isinstance(action, dict) and "name" in action and "msg" in action:
                                    if self._app.send_data_channel_message(
                                        action["name"],
                                        {"feed_name": self.feed_name, "msg": action["msg"]},
                                    ):
                                        LOGGER.debug(
                                            f"ACTION: feed {self.feed_name} sent message to {action['name']} dc"
                                        )
                                    else:
                                        LOGGER.error(
                                            f"ERROR: feed {self.feed_name} failed to send message to {action['name']} dc"
                                        )
                            case "off":
                                if msg[action]:
                                    self.terminate_webrtc_coro()
                            case _:
                                LOGGER.error(f"ERROR: Unknown action in the message: {msg}")
        LOGGER.info(f"OK: ACTION HANDLER IS OFF!")

    async def handle_bandwidth_estimations(self) -> None:
        LOGGER.info(f"OK: BANDWIDTH ESTIMATIONS HANDLER IS ON -- ready to publish bandwidth estimations")
        while self.is_running:
            gcc_bw = await self._app.gcc_estimated_bitrates.get()
            self.mqtts.publisher.publish(self.mqtt_config.topics.gcc, str(gcc_bw))
        LOGGER.info(f"OK: BANDWIDTH ESTIMATIONS HANDLER IS OFF!")

    async def webrtc_coro(self) -> None:
        while not (self._app and self._app.is_running):
            await asyncio.sleep(0.1)

        tasks = []
        try:
            LOGGER.info(f"OK: main webrtc coroutine has been started!")
            self.mqtts.publisher.start()
            self.mqtts.subscriber.start()
            self.mqtts.subscriber.subscribe([self.mqtt_config.topics.actions])
            ######################################## TASKS ########################################
            signalling_task = asyncio.create_task(self.handle_ice_connection())
            pipeline_task = asyncio.create_task(self._app.handle_pipeline())
            webrtcbin_stats_task = asyncio.create_task(self.handle_webrtcbin_stats())
            actions_task = asyncio.create_task(self.handle_actions())
            be_task = asyncio.create_task(self.handle_bandwidth_estimations())
            tasks = [signalling_task, pipeline_task, webrtcbin_stats_task, actions_task, be_task]
            #######################################################################################
            if self.agents:
                # start agent threads
                for agent in self.agents.values():
                    agent_thread = threading.Thread(target=agent.run, args=(True,))
                    agent_thread.start()
                    self.agent_threads[agent.id] = agent_thread
            if self.network_controller is not None:
                # start network controller's task
                network_controller_task = asyncio.create_task(self.network_controller.update_network_rule())
                tasks.append(network_controller_task)
            if self.mqtt_config.topics.controller:
                # notify controller that the feed is on
                LOGGER.info(f"OK: Feed {self.feed_name} is on, notifying the controller...")
                self.mqtts.publisher.publish(
                    self.mqtt_config.topics.controller,
                    json.dumps({self.feed_name: {"on": self.mqtt_config.topics.actions}}),
                )
            #######################################################################################
            self.webrtc_coro_control_task = asyncio.create_task(asyncio.sleep(float('inf')))
            tasks = [self.webrtc_coro_control_task, *tasks]
            await asyncio.gather(*tasks)
        except asyncio.exceptions.CancelledError:
            if not self.is_running:
                # this is on streamStopRequest where self.is_running was set to False.
                # In this case webrtc_coro will be recursively rescheduled.
                try:
                    await async_wait_for_condition(lambda: not self._app.is_running, 5)
                except Exception:
                    pass
                for task in tasks:
                    task.cancel()
                if self.agent_threads:
                    self._terminate_agents()
                self.mqtts.publisher.stop()
                self.mqtts.subscriber.stop()
                self._app = None
                LOGGER.info("OK: main webrtc coroutine is stopped on streamStopRequest, pending...")
                return await self.webrtc_coro()
            else:
                # this is on some internal exception where self.is_running is True and terminate_webrtc_coro was trigerred.
                # In this case webrtc_coro will be stopped.
                try:
                    await async_wait_for_condition(lambda: not self._app.is_running, 5)
                except Exception:
                    pass
                for task in tasks:
                    task.cancel()
                if self.agent_threads:
                    self._terminate_agents()
                self.mqtts.publisher.stop()
                self.mqtts.subscriber.stop()
                self._app = None
                LOGGER.error(
                    "ERROR: main webrtc coroutine has been interrupted due to an internal exception, stopping..."
                )
                return
        except Exception as e:
            # this is on some external exception where terminate_webrtc_coro was not trigerred e.g., pipeline error msg.
            # TODO: maybe also try to rerun it in case of pipeline error? since this may be related to the network link failure
            self.terminate_webrtc_coro()
            for task in tasks:
                task.cancel()
            if self.agent_threads:
                self._terminate_agents()
            self.mqtts.publisher.stop()
            self.mqtts.subscriber.stop()
            self._app = None
            LOGGER.error(
                "ERROR: main webrtc coroutine has been unexpectedly interrupted due to an exception:"
                f" '{str(e)}', stopping..."
            )
            return

    def terminate_webrtc_coro(self, is_restart_webrtc_coro: bool = False) -> None:
        self.is_running = not is_restart_webrtc_coro
        self.webrtcbin_sdp = None
        if self._app is not None:
            if self._app.is_running:
                self._app.send_termination_message_to_bus()
            else:
                self._app.terminate_pipeline()
        if self.webrtc_coro_control_task is not None:
            self.webrtc_coro_control_task.cancel()
            self.webrtc_coro_control_task = None

    def _prepare_agents(self, agents: List[Agent] | None) -> None:
        if agents is not None:
            self.agents = {agent.id: agent for agent in agents}

            if self.switching_pair is None:
                return
            if (
                AgentType.SAFETY_DETECTOR in [agent.type for agent in self.agents.values()]
                and self.switching_pair is None
            ):
                LOGGER.error("ERROR: SafetyDetectorAgent has no corresponding switching pair. Switching is off")
                return
            if not all(
                agent_id in self.agents.keys()
                for agent_id in [self.switching_pair.safe_id, self.switching_pair.unsafe_id]
            ):
                LOGGER.error("ERROR: Swithing pair contains invalid agent ids. Switching is off")
                return

            self.is_switching = True
            LOGGER.info("INFO: SafetyAgentDetector is on, switching is enabled!")

    def _switch_agents(self, algo: int, is_user_command: bool = False) -> bool:
        if self.agents and self.is_switching:
            is_first_switch = False  # if true then do not restart the agents as they are already running
            if not self.switching_pair.is_warmups_resetted:
                # reset warmups
                self.agents[self.switching_pair.safe_id].warmup = 0.0
                self.agents[self.switching_pair.unsafe_id].warmup = 0.0
                self.switching_pair.is_warmups_resetted = True
                is_first_switch = True

            if is_user_command:
                # if it is a user command, then disable the automatic safety detector on prefire
                if self.switching_pair.switcher_id and algo < 2:
                    self.agents[self.switching_pair.switcher_id].change_status(is_inactive=True)

            if algo >= 0:
                # include back to action aggregation
                if self.mqtts.publisher.topics.controller:
                    self.mqtts.publisher.publish(
                        self.mqtt_config.topics.controller,
                        json.dumps({self.feed_name: {"manual": False}}),
                    )

            if algo == 0:
                # enable gcc, disable drl if drl is running
                if not is_first_switch:
                    if not self.agents[self.switching_pair.safe_id].is_running:
                        self.agent_threads[self.switching_pair.safe_id] = threading.Thread(
                            target=self.agents[self.switching_pair.safe_id].run, args=(True,)
                        )
                        self.agent_threads[self.switching_pair.safe_id].start()
                self.agents[self.switching_pair.safe_id].enable_actions()

                if self.agents[self.switching_pair.unsafe_id].is_running:
                    self.agents[self.switching_pair.unsafe_id].stop()
                    self.agent_threads[self.switching_pair.unsafe_id].join()

            elif algo == 1:
                # enable drl, disable gcc if gcc is running
                if not is_first_switch:
                    if not self.agents[self.switching_pair.unsafe_id].is_running:
                        self.agent_threads[self.switching_pair.unsafe_id] = threading.Thread(
                            target=self.agents[self.switching_pair.unsafe_id].run, args=(True,)
                        )
                        self.agent_threads[self.switching_pair.unsafe_id].start()

                if self.agents[self.switching_pair.safe_id].is_running:
                    self.agents[self.switching_pair.safe_id].stop()
                    self.agent_threads[self.switching_pair.safe_id].join()

            elif algo == 2:
                # turn on safety detector, activate both agents
                if self.switching_pair.switcher_id:
                    self.agents[self.switching_pair.switcher_id].change_status(is_inactive=False)
                    if not is_first_switch:
                        if not self.agents[self.switching_pair.safe_id].is_running:
                            self.agent_threads[self.switching_pair.safe_id] = threading.Thread(
                                target=self.agents[self.switching_pair.safe_id].run, args=(True,)
                            )
                            self.agent_threads[self.switching_pair.safe_id].start()
                            self.agents[self.switching_pair.safe_id].enable_actions()
                        if not self.agents[self.switching_pair.unsafe_id].is_running:
                            self.agent_threads[self.switching_pair.unsafe_id] = threading.Thread(
                                target=self.agents[self.switching_pair.unsafe_id].run, args=(True,)
                            )
                            self.agent_threads[self.switching_pair.unsafe_id].start()

            elif algo == -1:
                # enable manual control, disable others
                if self.agents[self.switching_pair.safe_id].is_running:
                    self.agents[self.switching_pair.safe_id].stop()
                    self.agent_threads[self.switching_pair.safe_id].join()
                if self.agents[self.switching_pair.unsafe_id].is_running:
                    self.agents[self.switching_pair.unsafe_id].stop()
                    self.agent_threads[self.switching_pair.unsafe_id].join()

                # exclude from action aggregation
                if self.mqtts.publisher.topics.controller:
                    self.mqtts.publisher.publish(
                        self.mqtt_config.topics.controller,
                        json.dumps({self.feed_name: {"manual": True}}),
                    )
            else:
                LOGGER.error(f"ERROR: feed {self.feed_name} unknown switch algo code: {algo}")
                return False

            return True

        return False

    def _reload_agent(self, at: str) -> bool:
        if self.agents:
            agent_name = next((a for a in self.agents.keys() if a.startswith(at)), None)
            if agent_name is None:
                LOGGER.error(f"ERROR: feed {self.feed_name} no agent to reload with id starting with {at} is found!")
                return False
            else:
                self.agents[agent_name].stop()
                self.agents[agent_name].warmup = 0.0
                if agent_name in self.agent_threads:
                    self.agent_threads[agent_name].join()
                    self.agent_threads[agent_name] = threading.Thread(target=self.agents[agent_name].run, args=(True,))
                    self.agent_threads[agent_name].start()
                return True
        return False

    def _terminate_agents(self) -> None:
        if self.agent_threads:
            for agent in self.agents.values():
                agent.stop()
            for agent_thread in self.agent_threads.values():
                if agent_thread:
                    agent_thread.join()

    @property
    def app(self) -> AhoyApp | None:
        return self._app
