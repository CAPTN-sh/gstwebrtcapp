import asyncio

from gstwebrtcapp.apps.app import GstWebRTCAppConfig
from gstwebrtcapp.apps.pipelines import SINK_H264_CUDA_IN_H264_CUDA_OUT_PIPELINE
from gstwebrtcapp.apps.sinkapp.connector import SinkConnector
from gstwebrtcapp.control.drl.agent import DrlAgent
from gstwebrtcapp.control.drl.config import DrlConfig
from gstwebrtcapp.control.drl.mdp import ViewerSeqMDP
from gstwebrtcapp.message.client import MqttConfig
from gstwebrtcapp.network.controller import NetworkController
from gstwebrtcapp.utils.base import LOGGER

try:
    import uvloop
except ImportError:
    uvloop = None


async def test_feed():
    try:
        # FIXME: adapt params
        mode = "train"  # or "eval"
        model_name = "sac"  # check control/drl/mconfigurator.py for available models
        model_file = None  # model file (.zip file stored by sb3). Required for eval, could be add for further training
        episodes = 10
        episode_length = 256
        action_period_sec = 3.0
        hyperparams_cfg = "../gstwebrtcapp/control/drl/hparams/sac.json"  # check control/drl/hparams for available template hyperparams or provide your own in a dict
        callbacks = ['save_model', 'save_step', 'print_step']  # cbs for saving model and state + printing state

        mqtt_cfg = MqttConfig(id="test", broker_port=1883)

        feed_cfg = GstWebRTCAppConfig(
            pipeline_str=SINK_H264_CUDA_IN_H264_CUDA_OUT_PIPELINE,
            video_url=None,  # TODO: Add video URL here
            codec="h264",
            bitrate=2000,
            resolution={"width": 1920, "height": 1080},
            gcc_settings={"min-bitrate": 400000, "max-bitrate": 10000000},
        )

        # train cfg
        train_drl_cfg = DrlConfig(
            mode="train",
            model_name=model_name,
            model_file=model_file,
            episodes=episodes,
            episode_length=episode_length,
            state_update_interval=action_period_sec,
            state_max_inactivity_time=60.0,
            hyperparams_cfg=hyperparams_cfg,
            save_log_path="logs",
            save_model_path="models",
            callbacks=callbacks,
            verbose=2,
        )

        # eval_cfg
        eval_drl_config = DrlConfig(
            mode="eval",
            model_file=model_file,
            model_name="sac",
            episodes=-1,  # infinite, replace with a positive number to limit
            episode_length=episode_length,
            state_update_interval=action_period_sec,
            state_max_inactivity_time=60.0,
            deterministic=False,
            verbose=2,
        )

        mdp = ViewerSeqMDP(
            reward_function_name="qoe_ahoy_seq_sensible",
            episode_length=episode_length,
            num_observations_for_state=5,
            constants={
                "MAX_BITRATE_STREAM_MBPS": 10,
                "MAX_BANDWIDTH_MBPS": feed_cfg.gcc_settings["max-bitrate"] / 1000000,
                "MIN_BANDWIDTH_MBPS": feed_cfg.gcc_settings["min-bitrate"] / 1000000,
            },
        )

        drl_agent = DrlAgent(
            drl_config=train_drl_cfg if mode == "train" else eval_drl_config,
            mdp=mdp,
            mqtt_config=mqtt_cfg,
            warmup=20.0,
        )

        # uncomment to add network controller
        network_controller = None
        # network_controller = NetworkController(
        #     gt_bandwidth=12.0,
        #     interval=(3.0, 3.0),
        #     is_stop_after_no_rule=True,
        #     warmup=20.0,
        # )
        # # load from traces
        # network_controller.generate_rules_from_traces(trace_folder="/path/to/traces/")
        # # or
        # network_controller.generate_rules(20000, [0.6, 0.32, 0.08])

        conn = SinkConnector(
            app_config=feed_cfg,
            agents=[drl_agent],
            feed_name="test",
            mqtt_config=mqtt_cfg,
            network_controller=network_controller,
        )

        await conn.webrtc_coro()

    except KeyboardInterrupt:
        LOGGER.info("KeyboardInterrupt received, exiting...")
        exit(0)


if __name__ == "__main__":
    if uvloop is not None:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    asyncio.run(test_feed())
