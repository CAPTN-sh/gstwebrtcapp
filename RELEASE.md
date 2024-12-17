# Release Notes

## Version 1.6.2 (2024-12-16)
* Reworked the dockerfiles. They now support the latest GStreamer git tags, branches or stable versions, python 3.12 but do not support 3.13 yet, ubuntu 22 & 24 versions and the latest CUDA versions. Versions are managed through the build arguments. The CUDA version requires `CUDA_VER`, `CUDA_MINOR_VER` and `UBUNTU_VER` to be set, by default they are 12.4, 1 and 22.04, the CPU only `UBUNTU_VER` any by default it is 24.04. If you are using `CUDA_VER` <= 12.1 then you also need to set `CUDNN_VER`, for 12.1 it should be "cudnn8", for later versions NVIDIA got rid of it and it is just "cudnn" that is also the default. These arguments form the tag name for the base NVIDIA image, and in case the ensemble of versions is incompatible among each other, you will fail to pull the base image (e.g. cuda < 12.6 does not support ubuntu 24.04, and generally any cuda version does not support odd versions of ubuntu like 23.04). The Python and GStreamer versions are set via the `PYTHON_VER` and `GST_VER` build arguments, the defaults at the moment of release are 3.12.7 and "main".
* Added a new patch (`tools/webrtc-ui-patches/patch-webpack.sh`) for the webpack to turn it into a proxied version for the newer API versions (GStreamer > 1.24.5). Older do not require this patch.
* Fixed multiple issues with the latest GStreamer builds.

## Version 1.6.1 (2024-12-10)
* Added a new tool for `gst-shark` tracers to trace inner GStreamer performance.
* Added an option to have an external controller for the `FeedController` to run several feeds with one controller instance and to wrap them in subprocesses (`-ec` cmd arg). Look at the example in the `examples/external_feed_controller` folder. This feature is in the experimental mode and so far a bit uncomfortable to use.
* Multiple pipeline and application improvements and bug fixes.

## Version 1.6.0 (2024-10-22)
* Added a new `Monitor` control service. It generalizes the monitoring capabilities of `SafetyDetector` agents, introduces three possible states of monitored statistics and allows to add callbacks with immediate actions between switchers. See the updated example.
* Added the possibility to manually switch between allocated (all actions are shared based on weights) and independent (a separate agent) state of the media feeds.
* `SafetyDetector` can now also be manually turned on/off if the `-cat any` argument is set in the `GstWebRTCApp` entrypoint script. 
* Fixed unremovable letterboxes in the SinkApp pipelines. Now it is an optional feature that can be turned on/off using the `maybe_set_letterboxes` method in the `GstWebRTCApp' class.
* Improved the UI for the `SinkApp` to facilitate quick control.
* Added the possibility to set the certificate file for the MQTT broker in the `MqttConfig` and `BrokerConfig` objects.
* Multiple improvements and bug fixes.

## Version 1.5.0 (2024-09-11)
* Patched the UI for `SinkApp` to build under each feed a We0RTC stats table and an action trigger with dropdowns to select control mode, bitrate, framerate, resolution, fec and preset.
* Added a new feature to switch the type of the control agent: AI, GCC or fully manual. This could be set via the `-cat any` argument in the `GstWebRTCApp` entrypoint script or via adding a `SafetyDetector` agent with an empty switcher config (`SwitchingPair` should be created as usual).
* Added a possibility to add an extra data channel to enable a (bi)-directional communication between the UI used for the `SinkApp` and the backend. Added an option to relay the output of the `RecorderAgent` to the UI via the data channel. Added handling the actions from the UI at the backend over the data channel in the `SinkConnector`.
* Heavily improved `RecorderAgent`. Added `RecorderAgentMode` enum to specify the desired output options: relay over the MQTT or data channel, save to the CSV file or any combination of these.
* Added a websocket listener config to the `mosquitto.conf` file. Added an instruction to issue a self-signed TLS certificate for the MQTT broker.
* Updated MQTT classes to use the `paho-mqtt >=2.0`. Added new mqtt parameter to select the MQTT protocol version.
* Improved pipelines towards using more multi-threaded capabilities.
* Added a Makefile to simplify the installation process.

## Version 1.4.1 (2024-07-29)
* Added an auto-restart mechanism for the DRL agent. The agent will be restarted if observations are stuck (reached `max_inactivity_time`).
* Added a timeout mechanism for getting all the actions from the aggregation sub-coroutine in the `FeedController`. It could be set via the `max_aggregation_time` constructor parameter. If the timeout is reached, only the actions that were received will be used.

## Version 1.4.0 (2024-07-25)
* Added a cmd script and object builders. Now the application could be started from a command line with the given arguments. Run `python cmd/run.py -h` for the help info. Configurations for the MQTT broker and video streams could be provided via yaml files. Check the `examples/run_multiple_feeds` for the example of the yaml configurations.
* Added new examples: one for training/evaluating the DRL model and another for running multiple feeds with the GCC control via the new cmd script. The examples are located in the `examples` folder.
* Improved the performance for the execution wrappers. The connector(s) coroutines are recommended to be wrapped in the sync `threaded_wrapper` and the controller coroutines in the async `executor_wrapper`.
* Multiple improvements and bug fixes.

## Version 1.3.0 (2024-06-21)
* Added `FeedController` class to concurrently control multiple feeds (video streams). The feeds could be automatically controlled by `DrlAgent` or `GccAgent` or switched to the manual mode to control them directly. Added wrappers for restarting the coroutines and running them in a separate thread.
* Added action allocation for multiple feeds. The weight imprortance of the feed could be updated via the actions sent to the `FeedController`'s aggregation topic.
* Added weights for each feed that could be dynamically updated via the MQTT. The action values will be adjusted (if given) to the action limits (e.g., 0.4-10 Mbit/s for "bitrate" actions).
* Updated GStreamer version in the Dockerfile to built it from the source (latest commit in the main branch) with all needed plugins.
* Added docker compose file to run container as a service and to ease the deployment.
* Completed python installation and updated the code. Now the app could be installed via poetry (locally) or built as a wheel and installed via pip (globally, use `install.sh` script). Poetry is already installed in the docker environment.
* Added new tool to tweak the GstWebRTCAPI (webrtcsink js-based webrtc client).
* Added hardware acceleration for the AV1 codec (nvav1enc plugin).
* Improved connectors to allow waiting for the feed to be ready.

## Version 1.2.0 (2024-05-16)
* Added `SafetyDetector` agent to automatically switch between different control agents (e.g., DRL -> GCC) in case the agent's actions tend to show a negative trend in some statistics, e.g., growing RTT. A `GccAgent` is also introduced and works in active and passive modes.
* Added MQTT support for the communication between agents and different parts of the application as well as for publishing the statistics. Supports internal and external brokers.
* Added `NetworkController` class for bandwidth limitation. It allows to train/evaluate the DRL agent with different network conditions.
* Added new MDP and reward designs for the DRL agent.
* Improved GStreamer pipeline configuration and the control API. Added new setters for the pipeline elements. Added new pipelines for different encoder elements.
* Various bug fixes and improvements.

## Version 1.1.1 (2024-02-12)
* Added a bandwidth estimation element using the Google Congestion Control algorithm. The estimates are so far collected within a deque in the app class.
* `DrlAgent` and `CsvViewerRecorderAgent` now handle RTCP feedback for each SSRC (viewer) independently.
* Added many new pipelines for all supported encoders.

## Version 1.1.0 (2024-02-06)
* New sink application introduced in the `apps/sinkapp` submodule. It allows to stream via high-level webrtcsink rs plugin to the JS client.
* New recorder agent introduced in the `control/recorder` submodule. It saves webrtc stats to the CSV file.
* Refactoring and re-structuring of the codebase. Improving the docker environment. Extended examples for ahoy/sink apps, hardware accelerated encoders, control API, recorder and the full DRL agent.

## Version 1.0.1 (2024-01-15)
* New Control API introduced in the `control` submodule. It allows to define the AI-enablers / CC algorithms to control the video stream on the fly via the API and GStreamer app setters.
* First Deep Reinforcement Learning AI-enabler (`control/drl`) that uses the WebRTC stats from the viewer's browser to control the video stream. It is based on the stable-baselines3 library and uses the SAC algorithm. Currently the reward design and hyperparameters are not publicly available.
* Fully isolated Docker environment with CUDA, with a built-in VPN support via openconnect and with tcconfig to tweak the network. Check `docker` folder for the corresponding Dockerfiles.
* Support GStreamer NVENC encoders for CUDA containers (h264, h265, vp8, vp9, av1). Currently no support for VAAPI or Jetson Gstreamer plugins.

## Version 1.0.0 (2023-12-19)
* Stream video through the given GStreamer pipeline to AhoyMedia in a fast manner without any extra steps. One needs a pipeline in a string format, a video source (like rtsp://...) and Ahoy address/api key parameters to stream.
* Support stop/resume streaming with efficient resource re-allocation and self-restarting without any additional calls.
* Flexibly configure the GStreamer pipeline elements. By default, the pipeline is tuned towards the lowest latency.
* Control resolution, framerate and bitrate of the video on the fly via setters provided by the application.
* Control video encoder and RTP payloader parameters of the pipeline.
* Receive WebRTCBin statistics from the viewer's browser.