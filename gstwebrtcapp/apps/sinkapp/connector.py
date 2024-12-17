"""
connector.py

Description: A connector that connects SinkApp to the browser JS client. It holds the main coroutine for the SinkApp.

Author:
    - Nikita Smirnov <nsm@informatik.uni-kiel.de>

License:
    GPLv3 License

"""

import asyncio
import json
import re
import threading
from typing import List
import gi


gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
from gi.repository import Gst
from gi.repository import GstWebRTC

from gstwebrtcapp.apps.app import GstWebRTCAppConfig
from gstwebrtcapp.apps.sinkapp.app import SinkApp
from gstwebrtcapp.control.agent import Agent, AgentType
from gstwebrtcapp.control.safety.switcher import SwitchingPair
from gstwebrtcapp.media.preset import get_video_preset, get_video_preset_by_bitrate
from gstwebrtcapp.message.client import MqttConfig, MqttPair, MqttPublisher, MqttSubscriber
from gstwebrtcapp.network.controller import NetworkController
from gstwebrtcapp.utils.app import get_agent_type_by_switch_code, get_switch_code_by_agent_type
from gstwebrtcapp.utils.base import LOGGER, async_wait_for_condition
from gstwebrtcapp.utils.gst import GstWebRTCStatsType, find_stat, stats_to_dict


class SinkConnector:
    """
    A connector that connects SinkApp to the browser JS client. It holds the main coroutine for the SinkApp.

    :param signalling_server: The URI of the signalling server (gst-webrtc-signalling-server ws URI)
    :param app_config: The configuration for the GStreamer WebRTC application.
    :param agents: List of agents that manipulate the pipeline. Nullable.
    :param feed_name: The name of the feed.
    :param mqtt_config: The configuration for the MQTT client.
    :param network_controller: The network controller object. Nullable.
    :param switching_pair: The switching pair object. Nullable.
    :param share_ice_topic: The topic to share ICE candidates. Nullable.
    :param external_data_channel: The name of the external data channel. Nullable.
    """

    def __init__(
        self,
        signalling_server: str = "",
        app_config: GstWebRTCAppConfig = GstWebRTCAppConfig(),
        agents: List[Agent] | None = None,
        feed_name: str = "gst-stream",
        mqtt_config: MqttConfig = MqttConfig(),
        network_controller: NetworkController | None = None,
        switching_pair: SwitchingPair | None = None,
        share_ice_topic: str | None = None,
        external_data_channel: str | None = None,
    ):
        self.app_config = app_config
        if signalling_server:
            if 'signaller::uri' in self.app_config.pipeline_str:
                self.app_config.pipeline_str, _ = re.subn(
                    r'(signaller::uri=)[^ ]*', f'\\1{signalling_server}', self.app_config.pipeline_str
                )
            else:
                self.app_config.pipeline_str, _ = re.subn(
                    r'(webrtcsink[^\n]*)', fr'\1 signaller::uri={signalling_server}', self.app_config.pipeline_str
                )

        self.agents = {}
        self.agent_threads = {}
        self.switching_pair = switching_pair
        self.is_switching = False
        self._prepare_agents(agents)

        self.mqtt_config = mqtt_config
        self.mqtts = MqttPair(
            publisher=MqttPublisher(self.mqtt_config),
            subscriber=MqttSubscriber(self.mqtt_config),
        )
        self.feed_name = feed_name
        self.network_controller = network_controller
        self.share_ice_topic = share_ice_topic
        self.is_share_ice = False
        self.external_data_channel = external_data_channel

        self._app = None
        self.is_running = False

        self.webrtc_coro_control_task = None

    async def webrtc_coro(self) -> None:
        try:
            self._app = SinkApp(self.app_config)
            if self._app is None:
                raise Exception("SinkApp object is None!")
            self._app.webrtcsink.set_property("meta", Gst.Structure.new_from_string(f"meta,name={self.feed_name}"))
            await self._app.async_connect_signal(
                attribute_name="signaller",
                signal="consumer-removed",
                callback=self._cb_removing_peer,
                condition=lambda: self._app.signaller is not None,
                timeout=-1,
            )
            await self._app.async_connect_signal(
                attribute_name="webrtcbin",
                signal="notify::ice-connection-state",
                callback=self._cb_ice_connection_state_notify,
                condition=lambda: self._app.webrtcbin is not None,
                timeout=-1,
            )
            self.is_running = True
        except Exception as e:
            LOGGER.error(f"ERROR: Failed to create SinkApp object, reason:\n {str(e)}")
            self.terminate_webrtc_coro()
            return

        tasks = []
        try:
            LOGGER.info(f"OK: main webrtc coroutine has been started!")
            self.mqtts.publisher.start()
            self.mqtts.subscriber.start()
            self.mqtts.subscriber.subscribe([self.mqtt_config.topics.actions])
            ######################################## TASKS ########################################
            tasks.append(asyncio.create_task(self._app.handle_pipeline()))
            tasks.append(asyncio.create_task(self.handle_post_init_pipeline()))
            tasks.append(asyncio.create_task(self.handle_webrtcsink_stats()))
            tasks.append(asyncio.create_task(self.handle_actions()))
            tasks.append(asyncio.create_task(self.handle_bandwidth_estimations()))
            if self.external_data_channel:
                tasks.append(asyncio.create_task(self.handle_external_data_channel()))
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
            await asyncio.gather(*tasks, self.webrtc_coro_control_task)
        except asyncio.exceptions.CancelledError as e:
            if not self.is_running:
                try:
                    await async_wait_for_condition(lambda: not self._app.is_running, 5)
                except Exception:
                    LOGGER.error("ERROR: Failed to stop the pipeline gracefully, force stopping...")
                for task in tasks:
                    task.cancel()
                if self.agent_threads:
                    self._terminate_agents()
                self.mqtts.publisher.stop()
                self.mqtts.subscriber.stop()
                self._app = None
                # NOTE: it is restarted via the external wrapper
                return
            else:
                raise Exception(str(e))
        except Exception as e:
            try:
                await async_wait_for_condition(lambda: not self._app.is_running, 5)
            except Exception:
                LOGGER.error("ERROR: Failed to stop the pipeline gracefully, force stopping...")
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

    async def handle_post_init_pipeline(self) -> None:
        await async_wait_for_condition(lambda: self._app.bus is not None, timeout_sec=5.0)
        await async_wait_for_condition(lambda: self._app.webrtcsink_elements, timeout_sec=self._app.max_timeout)
        self._app.send_post_init_message_to_bus()

    def terminate_webrtc_coro(self, is_restart_webrtc_coro: bool = False) -> None:
        self.is_running = not is_restart_webrtc_coro
        if self._app is not None:
            if self._app.is_running:
                self._app.send_termination_message_to_bus()
            else:
                self._app.terminate_pipeline()
        if self.webrtc_coro_control_task is not None:
            self.webrtc_coro_control_task.cancel()
            self.webrtc_coro_control_task = None

    async def handle_webrtcsink_stats(self) -> None:
        LOGGER.info(f"OK: WEBRTCSINK STATS HANDLER IS ON -- ready to check for stats")
        while self.is_running:
            await asyncio.sleep(0.1)
            stats = {}
            stats_struct = self.app.webrtcsink.get_property("stats")
            if stats_struct.n_fields() > 0:
                session_name = stats_struct.nth_field_name(0)
                if session_name is not None:
                    session_struct = stats_struct.get_value(session_name)
                    session_struct_n_fields = session_struct.n_fields()
                    for i in range(session_struct_n_fields):
                        stat_name = session_struct.nth_field_name(i)
                        stat_value = session_struct.get_value(stat_name)
                        if isinstance(stat_value, Gst.Structure):
                            stats[stat_name] = stats_to_dict(stat_value.to_string())
            # push the stats to the agent's controller queue or save it to an own one
            if stats:
                self.mqtts.publisher.publish(self.mqtt_config.topics.stats, json.dumps(stats))

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

        LOGGER.info(f"OK: WEBRTCSINK STATS HANDLER IS OFF!")

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
                                        if self.external_data_channel:
                                            self._app.send_data_channel_message(
                                                self.external_data_channel,
                                                {"feed_name": self.feed_name, "msg": {"resolution": msg[action]}},
                                            )
                                else:
                                    LOGGER.error(f"ERROR: Resolution action has invalid value: {msg[action]}")
                            case "framerate":
                                if self._app.set_framerate(msg[action]):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} set framerate to {msg[action]}")
                                    if self.external_data_channel:
                                        self._app.send_data_channel_message(
                                            self.external_data_channel,
                                            {"feed_name": self.feed_name, "msg": {"framerate": msg[action]}},
                                        )
                            case "fec":
                                if self._app.set_fec_percentage(msg[action]):
                                    LOGGER.info(f"ACTION: feed {self.feed_name} set FEC % to {msg[action]}")
                                    if self.external_data_channel:
                                        self._app.send_data_channel_message(
                                            self.external_data_channel,
                                            {"feed_name": self.feed_name, "msg": {"fec": msg[action]}},
                                        )
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
                                    if self.external_data_channel:
                                        self._app.send_data_channel_message(
                                            self.external_data_channel,
                                            {"feed_name": self.feed_name, "msg": {"switch": a_type}},
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

    async def handle_bandwidth_estimations(self) -> None:
        LOGGER.info(f"OK: BANDWIDTH ESTIMATIONS HANDLER IS ON -- ready to publish bandwidth estimations")
        while self.is_running:
            gcc_bw = await self._app.gcc_estimated_bitrates.get()
            self.mqtts.publisher.publish(self.mqtt_config.topics.gcc, str(gcc_bw))
        LOGGER.info(f"OK: BANDWIDTH ESTIMATIONS HANDLER IS OFF!")

    async def handle_external_data_channel(self) -> None:
        LOGGER.info(f"OK: EXT DATA CHANNEL HANDLER IS ON -- ready to receive cmds from the external data channel")
        while self.is_running:
            if self.external_data_channel in self._app.data_channels_data:
                msg = await self._app.data_channels_data[self.external_data_channel].get()
                topic = (
                    self.mqtt_config.topics.controller
                    if self.mqtt_config.topics.controller
                    else self.mqtt_config.topics.actions
                )
                await asyncio.get_event_loop().run_in_executor(
                    None, self.mqtts.publisher.publish, topic, msg, "ui_commands"
                )
        LOGGER.info(f"OK: EXT DATA CHANNEL HANDLER IS OFF!")

    def _cb_removing_peer(self, _, __, webrtcbin) -> None:
        LOGGER.info("OK: end session is received, pending the connector's coroutine...")
        # if connector receives a direct message in a handler, it will trigger termination before this callback occurs
        if self.is_running:
            if self.mqtt_config.topics.controller:
                # if it is terminated by the UI, notify the controller.
                # set the value to False, otherwise the controller will send an "off" message here again
                self.mqtts.publisher.publish(
                    self.mqtt_config.topics.controller,
                    json.dumps({self.feed_name: {"off": False}}),
                )
            self.terminate_webrtc_coro(is_restart_webrtc_coro=True)

    def _cb_ice_connection_state_notify(self, pspec, _) -> None:
        self.webrtcbin_ice_connection_state = self._app.webrtcbin.get_property('ice-connection-state')
        if self.webrtcbin_ice_connection_state == GstWebRTC.WebRTCICEConnectionState.CONNECTED:
            if self.share_ice_topic and not self.is_share_ice:
                self.is_share_ice = True

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
    def app(self) -> SinkApp | None:
        return self._app
