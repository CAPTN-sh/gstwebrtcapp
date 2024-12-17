import copy
from dataclasses import asdict
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Tuple
import yaml

from gstwebrtcapp.apps.ahoyapp.connector import AhoyConnector
from gstwebrtcapp.apps.app import GstWebRTCAppConfig
from gstwebrtcapp.apps.sinkapp.connector import SinkConnector
from gstwebrtcapp.apps.pipelines import get_pipeline_by_specs
from gstwebrtcapp.control.cc.gcc_agent import GccAgent
from gstwebrtcapp.control.drl.agent import DrlAgent
from gstwebrtcapp.control.drl.config import DrlConfig
from gstwebrtcapp.control.drl.mdp import MDP, ViewerSeqMDP
from gstwebrtcapp.control.recorder.agent import RecorderAgent, RecorderAgentMode
from gstwebrtcapp.control.safety.agent import SafetyDetectorAgent
from gstwebrtcapp.control.safety.monitor import MonitorConfig
from gstwebrtcapp.control.safety.switcher import SwitchingPair
from gstwebrtcapp.message.broker import MqttBrokerConfig
from gstwebrtcapp.message.client import MqttConfig, MqttExternalEstimationTopics, MqttGstWebrtcAppTopics
from gstwebrtcapp.run.feed_controller import FeedController
from gstwebrtcapp.utils.base import LOGGER


def parse_mqtt_broker_config(yaml_config: str) -> MqttBrokerConfig:
    try:
        with open(yaml_config, "r") as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"parse_mqtt_broker_config: config file not found: {yaml_config}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"parse_mqtt_broker_config: error parsing config file: {e}")

    broker_dict = config_dict.get("broker", {})
    if not broker_dict:
        raise Exception("parse_mqtt_broker_config: no mqtt broker config found")

    return MqttBrokerConfig.from_dict(broker_dict)


def parse_feed_configs(yaml_config: str, connector_type: str = "sink") -> Dict[str, GstWebRTCAppConfig]:
    try:
        with open(yaml_config, "r") as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"parse_feed_configs: config file not found: {yaml_config}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"parse_feed_configs: error parsing config file: {e}")

    feeds_dict = config_dict.get("feeds", {})
    if not feeds_dict:
        raise Exception("parse_feed_configs: no feeds found")

    final_feeds_dict = {}
    for feed_name, feed_params in feeds_dict.items():
        if "video_url" not in feed_params:
            raise ValueError(f"parse_feed_configs: video_url key is required for feed {feed_name}")
        final_feeds_dict[feed_name] = {}
        codec_in = feed_params.pop("codec_in", "h264")
        codec_out = feed_params.pop("codec_out", "h264")
        cuda_in = feed_params.pop("cuda_in", False)
        cuda_out = feed_params.pop("cuda_out", False)
        final_feeds_dict[feed_name]["pipeline_str"] = get_pipeline_by_specs(
            type=connector_type,
            codec_in=codec_in,
            codec_out=codec_out,
            cuda_in=cuda_in,
            cuda_out=cuda_out,
        )
        final_feeds_dict[feed_name]["codec"] = codec_out
        for feed_key, feed_value in feed_params.items():
            if feed_key == "resolution":
                if feed_value is None:
                    final_feeds_dict[feed_name]["resolution"] = None
                else:
                    w = feed_value.get("width", None)
                    h = feed_value.get("height", None)
                    if w is None or h is None:
                        final_feeds_dict[feed_name]["resolution"] = None
                    else:
                        final_feeds_dict[feed_name]["resolution"] = {"width": w, "height": h}
            elif feed_key == "gcc_settings":
                if feed_value is None:
                    final_feeds_dict[feed_name]["gcc_settings"] = None
                else:
                    min_bitrate = feed_value.get("min_bitrate", None)
                    max_bitrate = feed_value.get("max_bitrate", None)
                    if min_bitrate is None or max_bitrate is None:
                        final_feeds_dict[feed_name]["gcc_settings"] = None
                    else:
                        final_feeds_dict[feed_name]["gcc_settings"] = {
                            "min-bitrate": min_bitrate,
                            "max-bitrate": max_bitrate,
                        }
            else:
                final_feeds_dict[feed_name][feed_key] = feed_value
    d = {feed_name: GstWebRTCAppConfig.from_dict(feed_params) for feed_name, feed_params in final_feeds_dict.items()}
    return d


def parse_monitor_configs(yaml_config: str) -> Dict[str, MonitorConfig]:
    try:
        with open(yaml_config, "r") as f:
            config_dict = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"parse_monitor_configs: config file not found: {yaml_config}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"parse_monitor_configs: error parsing config file: {e}")

    cfgs = {}
    for monitor_name, monitor_cfgs in config_dict.items():
        monitor_cfg = MonitorConfig.from_dict(monitor_cfgs)
        if monitor_cfg:
            cfgs[monitor_name] = monitor_cfg
    return cfgs


def make_feed_mqtt_config(
    broker_config: MqttBrokerConfig,
    feed_name: str,
    mqtt_prefix: str = "",
    aggregation_topic: str | None = None,
    controller_topic: str | None = None,
    external_topics: MqttExternalEstimationTopics | None = None,
) -> MqttConfig:
    prefix = f"{mqtt_prefix}/{feed_name}" if mqtt_prefix else feed_name
    return MqttConfig(
        id=feed_name,
        broker_host=broker_config.broker_host,
        broker_port=broker_config.broker_port,
        keepalive=broker_config.keepalive,
        username=broker_config.username,
        password=broker_config.password,
        is_tls=broker_config.is_tls,
        protocol=broker_config.protocol,
        topics=MqttGstWebrtcAppTopics(
            gcc=f"{prefix}/gcc",
            stats=f"{prefix}/stats",
            state=f"{prefix}/state",
            actions=aggregation_topic or f"{prefix}/actions",
            controller=controller_topic or "",
        ),
        external_topics=external_topics,
    )


def make_inactive_mqtt_config(
    broker_config: MqttBrokerConfig,
    id: str,
    controller_topic: str | None = None,
) -> MqttConfig:
    return MqttConfig(
        id=id,
        broker_host=broker_config.broker_host,
        broker_port=broker_config.broker_port,
        keepalive=broker_config.keepalive,
        username=broker_config.username,
        password=broker_config.password,
        is_tls=broker_config.is_tls,
        protocol=broker_config.protocol,
        topics=MqttGstWebrtcAppTopics(
            gcc="",
            stats="",
            state="",
            actions="",
            controller=controller_topic or "",
        ),
        external_topics=None,
    )


def make_feed_config(
    video_url: str,
    codec_in: str = "h264",
    codec_out: str = "h264",
    cuda_in: bool = True,
    cuda_out: bool = True,
    bitrate: int = 2000,
    resolution: Dict[str, int] = {"width": 1920, "height": 1080},
    framerate: int = 20,
    fec_percentage: int = 0,
    is_preset_tuning: bool = False,
    gcc_settings: Dict[str, int] = {"min-bitrate": 400000, "max-bitrate": 10000000},
    transceiver_settings: Dict[str, bool] = {"nack": True, "fec": True},
    priority: int = 3,
    max_timeout: int = 30,
    is_debug: bool = False,
) -> GstWebRTCAppConfig:
    pipeline = get_pipeline_by_specs(codec_in=codec_in, codec_out=codec_out, cuda_in=cuda_in, cuda_out=cuda_out)
    return GstWebRTCAppConfig(
        pipeline_str=pipeline,
        video_url=video_url,
        codec=codec_out,
        bitrate=bitrate,
        resolution=resolution,
        framerate=framerate,
        fec_percentage=fec_percentage,
        is_preset_tuning=is_preset_tuning,
        gcc_settings=gcc_settings,
        transceiver_settings=transceiver_settings,
        data_channels_cfgs=[],
        priority=priority,
        max_timeout=max_timeout,
        is_debug=is_debug,
    )


def make_drl_agent(
    mqtt_config: MqttConfig,
    drl_config: DrlConfig | None = None,
    mdp: MDP | None = None,
    model_file: str | None = None,
    gcc_settings: Dict[str, int] | None = None,
    action_period: float = 3.0,
    warmup: float = 10.0,
) -> DrlAgent:
    if drl_config:
        drl_config_ = drl_config
        if model_file:
            drl_config_.model_file = model_file
    else:
        if not model_file:
            raise ValueError("make_drl_agent: model file is required")
        drl_config_ = DrlConfig(
            mode="eval",
            model_file=model_file,
            model_name="sac",
            episodes=-1,  # infinite eval
            episode_length=256,
            state_update_interval=action_period,
            state_max_inactivity_time=20.0,
            deterministic=False,
            verbose=1,
        )
    mdp_ = mdp or ViewerSeqMDP(
        reward_function_name="qoe_ahoy_seq_sensible",
        episode_length=256,
        num_observations_for_state=5,
        constants={
            "MAX_BITRATE_STREAM_MBPS": gcc_settings["max-bitrate"] / 1000000 if gcc_settings else 10.0,
            "MIN_BITRATE_STREAM_MBPS": gcc_settings["min-bitrate"] / 1000000 if gcc_settings else 0.4,
            "MAX_BANDWIDTH_MBPS": gcc_settings["max-bitrate"] / 1000000 if gcc_settings else 10.0,
            "MIN_BANDWIDTH_MBPS": gcc_settings["min-bitrate"] / 1000000 if gcc_settings else 0.4,
        },
    )
    return DrlAgent(
        drl_config=drl_config_,
        mdp=mdp_,
        mqtt_config=mqtt_config,
        warmup=warmup,
    )


def make_gcc_agent(
    mqtt_config: MqttConfig,
    action_period: float = 3.0,
    is_force_action: bool = True,
    is_enable_actions_on_start: bool = True,
    warmup: float = 10.0,
) -> GccAgent:
    return GccAgent(
        mqtt_config=mqtt_config,
        action_period=action_period,
        is_force_action=is_force_action,
        is_enable_actions_on_start=is_enable_actions_on_start,
        warmup=warmup,
    )


def make_recorder_agent_modes(recorder_modes: str) -> List[RecorderAgentMode]:
    recorder_modes = recorder_modes.split(",")
    modes = []
    for rm in recorder_modes:
        if rm.upper() in RecorderAgentMode.__members__:
            modes.append(RecorderAgentMode[rm.upper()])
        else:
            LOGGER.warning(f"make_recorder_agent_modes: invalid recorder mode: {rm}")
    return modes


def make_recorder_agent(
    mqtt_config: MqttConfig,
    id: str = "recorder",
    max_inactivity_time: float = 20.0,
    log_path: str | None = "./logs",
    stats_publish_topic: str | None = None,
    external_data_channel: str | None = None,
    warmup: float = 10.0,
    verbose: bool = False,
) -> RecorderAgent:
    return RecorderAgent(
        mqtt_config=mqtt_config,
        id=id,
        max_inactivity_time=max_inactivity_time,
        log_path=log_path,
        stats_publish_topic=stats_publish_topic,
        external_data_channel=external_data_channel,
        warmup=warmup,
        verbose=verbose,
    )


def make_connector(
    connector_type: str,
    feed_name: str,
    feed_config: GstWebRTCAppConfig,
    broker_config: MqttBrokerConfig,
    server: str = "",
    api_key: str | None = None,
    control_agent_type: str = "drl",
    control_agent_action_period: float = 3.0,
    control_agent_model_file: str | None = None,
    control_agent_monitor_configs: Dict[str, MonitorConfig] | None = None,
    mqtt_prefix: str = "",
    aggregation_topic: str | None = None,
    controller_topic: str | None = None,
    recorder_modes: str = "",
    is_bidirectional_data_channel: bool = False,
    warmup: float = 10.0,
) -> AhoyConnector | SinkConnector:
    # TODO: add support for network controller and share_ice_topic
    type = connector_type.lower()
    if type == "ahoy":
        if not server or not api_key:
            raise ValueError("make_connector: server and api_key are required for AhoyConnector")

    if controller_topic:
        controller_topic_ = f"{mqtt_prefix}/{controller_topic}" if mqtt_prefix else controller_topic
    else:
        controller_topic_ = None
    if aggregation_topic:
        aggregation_topic_ = f"{mqtt_prefix}/{aggregation_topic}" if mqtt_prefix else aggregation_topic
    else:
        aggregation_topic_ = None

    template_mqtt_cfg = make_feed_mqtt_config(
        broker_config=broker_config,
        feed_name=feed_name,
        mqtt_prefix=mqtt_prefix,
        aggregation_topic=aggregation_topic_,
        controller_topic=controller_topic_,
    )

    agents = []
    switching_pair = None
    external_data_channel = f"{feed_name}_ui_dc" if is_bidirectional_data_channel else None

    if control_agent_type == "drl":
        control_agent = make_drl_agent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            model_file=control_agent_model_file,
            gcc_settings=feed_config.gcc_settings,
            action_period=control_agent_action_period,
            warmup=warmup,
        )
        agents.append(control_agent)
    elif control_agent_type == "gcc":
        control_agent = make_gcc_agent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            action_period=control_agent_action_period,
            warmup=warmup,
        )
        agents.append(control_agent)
    elif control_agent_type == "sd" or control_agent_type == "any":
        if control_agent_type == "sd" and not control_agent_monitor_configs:
            raise ValueError("make_connector: control_agent_monitor_configs is required for sd control agent")

        drl_agent = make_drl_agent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            model_file=control_agent_model_file,
            gcc_settings=feed_config.gcc_settings,
            action_period=control_agent_action_period,
            warmup=warmup,
        )
        gcc_agent = make_gcc_agent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            action_period=control_agent_action_period,
            is_enable_actions_on_start=False,
            warmup=warmup,
        )
        sd_agent = SafetyDetectorAgent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            monitor_configs=control_agent_monitor_configs,
            is_start_inactive=control_agent_type == "any" and not control_agent_monitor_configs,
            update_interval=control_agent_action_period / 10,
            warmup=warmup,
        )
        switching_pair = SwitchingPair(gcc_agent.id, drl_agent.id, sd_agent.id)
        agents.extend([drl_agent, gcc_agent, sd_agent])
    elif control_agent_type == "none":
        pass
    else:
        raise ValueError(f"make_connector: invalid control agent type: {control_agent_type}")

    if recorder_modes:
        recorder_agent_modes = make_recorder_agent_modes(recorder_modes)
        state_publish_topic = f"{mqtt_prefix}/{feed_name}/recorder" if mqtt_prefix else f"{feed_name}/recorder"
        if RecorderAgentMode.DC in recorder_agent_modes:
            external_data_channel = f"{feed_name}_ui_dc"
        recorder_agent = make_recorder_agent(
            mqtt_config=copy.deepcopy(template_mqtt_cfg),
            id=f"recorder_{feed_name}",
            log_path=f"./logs/{feed_name}" if RecorderAgentMode.CSV in recorder_agent_modes else None,
            stats_publish_topic=state_publish_topic if RecorderAgentMode.MQTT in recorder_agent_modes else None,
            external_data_channel=external_data_channel if RecorderAgentMode.DC in recorder_agent_modes else None,
            warmup=warmup,
        )
        agents.append(recorder_agent)

    agents = None if not agents else agents

    if external_data_channel:
        # triggered by the recoder's 'dc' mode or by '-bdc' cmd flag or both, the name is fixed in SinkApp UI
        feed_config.data_channels_cfgs.append(
            {
                "name": external_data_channel,
                "options": None,
                "callbacks": None,
            }
        )

    connector_mqtt_cfg = copy.deepcopy(template_mqtt_cfg)
    connector_mqtt_cfg.id = f"connector_{feed_name}"
    connector_mqtt_cfg.topics.actions = f"{feed_name}/actions"

    if type == "sink":
        return SinkConnector(
            signalling_server=server,
            app_config=feed_config,
            agents=agents,
            feed_name=feed_name,
            mqtt_config=connector_mqtt_cfg,
            switching_pair=switching_pair,
            external_data_channel=external_data_channel,
        )
    else:
        return AhoyConnector(
            server=server,
            api_key=api_key,
            app_config=feed_config,
            agents=agents,
            feed_name=feed_name,
            mqtt_config=connector_mqtt_cfg,
            switching_pair=switching_pair,
        )


def make_feed_controller(
    feeds: Dict[str, GstWebRTCAppConfig],
    broker_config: MqttBrokerConfig,
    mqtt_prefix: str = "",
    controller_topic: str | None = None,
    aggregation_topic: str | None = None,
    action_limits: Dict[str, Tuple[float, float]] | None = {"bitrate": (400, 10000)},
    max_aggregation_time: float = 5.0,
    warmup: float = 10.0,
) -> FeedController:
    feed_topic_prefix = f"{mqtt_prefix}/" if mqtt_prefix else ""
    return FeedController(
        mqtt_config=make_inactive_mqtt_config(broker_config, "controller", controller_topic=controller_topic),
        feed_topics={feed: f"{feed_topic_prefix}{feed}/actions" for feed in feeds},
        controller_topic=controller_topic,
        aggregation_topic=aggregation_topic,
        allocation_weights={},
        action_limits=action_limits,
        max_aggregation_time=max_aggregation_time,
        warmup=warmup,
    )


def make_log_file(log_path: str, feed_name: str) -> str:
    os.makedirs(log_path, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d-%H_%M_%S_%f")[:-3]
    return os.path.join(os.path.abspath(log_path), f"conn_{feed_name}_{now}.log")


async def make_connector_coro(connector: AhoyConnector | SinkConnector) -> None:
    if isinstance(connector, AhoyConnector):
        await connector.connect_coro()
    await connector.webrtc_coro()


async def make_controller_coro(controller: FeedController) -> None:
    await controller.controller_coro()


async def make_allocation_coro(controller: FeedController) -> None:
    await controller.allocation_coro()


def serialize_connector_kwargs(args: Dict[str, Any]) -> str:
    for k, v in args.items():
        if isinstance(v, GstWebRTCAppConfig):
            args[k] = asdict(v)
        elif isinstance(v, MqttBrokerConfig):
            args[k] = asdict(v)
        elif isinstance(v, dict) and all(isinstance(v_, MonitorConfig) for v_ in v.values()):
            args[k] = {k_: asdict(v_) for k_, v_ in v.items()}
        else:
            pass
    return json.dumps(args)


def deserialize_connector_kwargs(serialized_args: str) -> Dict[str, Any]:
    args = json.loads(serialized_args)
    if not isinstance(args, dict):
        raise Exception("deserialize_make_connector_arguments: args should be a dict")
    for k, v in args.items():
        k = str(k)
        if isinstance(v, dict):
            if k.startswith("feed"):
                args[k] = GstWebRTCAppConfig.from_dict(v)
            elif k.startswith("broker"):
                args[k] = MqttBrokerConfig.from_dict(v)
            elif "monitor" in k:
                args[k] = {k_: MonitorConfig.from_dict(v_) for k_, v_ in v.items()}
        else:
            args[k] = v
    return args
