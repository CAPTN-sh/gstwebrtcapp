from argparse import ArgumentParser
import asyncio
from typing import List

from gstwebrtcapp.apps.ahoyapp.connector import AhoyConnector
from gstwebrtcapp.apps.sinkapp.connector import SinkConnector
from gstwebrtcapp.run.builders import (
    make_allocation_coro,
    make_connector,
    make_connector_coro,
    make_controller_coro,
    make_feed_controller,
    parse_feed_configs,
    parse_mqtt_broker_config,
    parse_monitor_configs,
)
from gstwebrtcapp.run.feed_controller import FeedController
from gstwebrtcapp.run.wrappers import executor_wrapper, threaded_wrapper
from gstwebrtcapp.utils.base import LOGGER

try:
    import uvloop
except ImportError:
    uvloop = None


async def main(
    connectors: List[SinkConnector | AhoyConnector],
    controller: FeedController | None,
    is_alloc_coro: bool = True,
) -> None:
    for connector in connectors:
        threaded_wrapper(
            make_connector_coro,
            connector,
            is_daemon=True,
            is_raise_exception=False,
        )

    tasks = []

    if controller:
        tasks.append(
            asyncio.create_task(
                executor_wrapper(
                    make_controller_coro,
                    controller,
                    is_raise_exception=False,
                )
            )
        )
        if is_alloc_coro:
            tasks.append(
                asyncio.create_task(
                    executor_wrapper(
                        make_allocation_coro,
                        controller,
                        is_raise_exception=False,
                    )
                )
            )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    else:
        await asyncio.sleep(float("inf"))


if __name__ == "__main__":
    if uvloop is not None:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    parser = ArgumentParser()
    # fmt: off
    parser.add_argument('-t', '--connector-type', dest='connector_type', type=str, choices=["ahoy", "sink"], default="sink", help='connector type (ahoy or sink)')
    parser.add_argument('-b', '--broker-cfg', dest='broker_yaml', type=str, required=True, help='MQTT broker configuration')
    parser.add_argument('-f', '--feeds-cfg', dest='feeds_yaml', type=str, required=True, help='video feeds configuration')
    parser.add_argument('-s', '--server', dest='server', type=str, default="", help='connector server')
    parser.add_argument('-ak', '--api-key', dest='api_key', type=str, default=None, help='ahoy connector API key')
    parser.add_argument('-cat', '--control-agent-type', dest='control_agent_type', type=str, choices=["drl","gcc","sd","any","none"], default="drl", help='control agent type: drl - DRL, gcc - GCC, sd -- DRL/GCC switch via adaptive thresholding, any -- DRL/GCC/MANUAL via manual switch, none -- no control agent')
    parser.add_argument('-cap', '--control-agent-action-period', dest='control_agent_action_period', type=float, default=3.0, help='control agent action period in seconds')
    parser.add_argument('-cam', '--control-agent-model-file', dest='control_agent_model_file', type=str, default=None, help='drl control agent model file')
    parser.add_argument('-camc', '--control-agent-monitor-cfg', dest='control_agent_monitors_yaml', type=str, default=None, help='monitors configuration')
    parser.add_argument('-mp', '--mqtt-prefix', dest='mqtt_prefix', type=str, default="", help='MQTT prefix for all topics, e.g., main/gstreamer')
    parser.add_argument('-at', '--aggregation-topic', dest='aggregation_topic', type=str, default="internal/aggregation", help='aggregation topic. NOTE: if empty, there would be no allocation, individual agents actions are directly sent to connectors')
    parser.add_argument('-ct', '--controller-topic', dest='controller_topic', type=str, default="internal/controller", help='controller topic. NOTE: if empty, there would be no controller, i.e., one should send actions directly to each feed connector')
    parser.add_argument('-ec', '--external-controller', dest='external_controller', action='store_true', help='use external feed controller')
    parser.add_argument('-rm', '--recorder-modes', dest='recorder_modes', type=str, default="", help="c-s values, e.g.: 'mqtt':(prefix/feed_name/recorder), 'csv': (./logs/feed_name), 'dc' (feedname_recoder relay dc)')")
    parser.add_argument('-bdc', '--bidirectional-data-channel', dest='bidirectional_data_channel', action='store_true', help='use bidirectional data channel (consumer -> producer leg). NOTE: recorder_modes must contain "dc"')
    parser.add_argument('-w', '--warmup', dest='warmup', type=float, default=10.0, help='warmup time in seconds')
    # fmt: on
    args = parser.parse_args()
    connector_type = args.connector_type
    broker_yaml = args.broker_yaml
    feeds_yaml = args.feeds_yaml
    server = args.server
    api_key = args.api_key
    control_agent_type = args.control_agent_type
    control_agent_action_period = args.control_agent_action_period
    control_agent_model_file = args.control_agent_model_file
    control_agent_monitors_yaml = args.control_agent_monitors_yaml
    mqtt_prefix = args.mqtt_prefix
    aggregation_topic = args.aggregation_topic
    controller_topic = args.controller_topic
    external_controller = args.external_controller
    recorder_modes = args.recorder_modes
    bidirectional_data_channel = args.bidirectional_data_channel
    warmup = args.warmup

    # create broker config
    broker_cfg = parse_mqtt_broker_config(broker_yaml)

    # create feed configs
    feed_cfgs = parse_feed_configs(feeds_yaml, connector_type)

    # create monitor configs
    ca_monitor_cfgs = parse_monitor_configs(control_agent_monitors_yaml) if control_agent_monitors_yaml else None

    # create connectors
    connectors = [
        make_connector(
            connector_type=connector_type,
            feed_name=feed_name,
            feed_config=feed_cfg,
            broker_config=broker_cfg,
            server=server,
            api_key=api_key,
            control_agent_type=control_agent_type,
            control_agent_action_period=control_agent_action_period,
            control_agent_model_file=control_agent_model_file,
            control_agent_monitor_configs=ca_monitor_cfgs,
            mqtt_prefix=mqtt_prefix,
            aggregation_topic=aggregation_topic,
            controller_topic=controller_topic,
            recorder_modes=recorder_modes,
            is_bidirectional_data_channel=bidirectional_data_channel,
            warmup=warmup,
        )
        for feed_name, feed_cfg in feed_cfgs.items()
    ]

    # create feed controller
    controller = (
        make_feed_controller(
            feeds=feed_cfgs,
            broker_config=broker_cfg,
            mqtt_prefix=mqtt_prefix,
            controller_topic=controller_topic,
            aggregation_topic=aggregation_topic,
            max_aggregation_time=control_agent_action_period * 2,
            warmup=warmup,
        )
        if controller_topic and not external_controller
        else None
    )

    # main
    try:
        asyncio.run(
            main(
                connectors=connectors,
                controller=controller,
                is_alloc_coro=aggregation_topic,
            )
        )
    except KeyboardInterrupt:
        LOGGER.info("KeyboardInterrupt received, exiting...")
        exit(0)
