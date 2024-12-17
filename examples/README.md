All examples should be run with the SinkApp since AhoyApp requires a license. To do this, open four terminals in the vscode attached to the container and run the following commands in each terminal:
1. In the first terminal, run the local mosquitto broker:
```bash
mosquitto -c /etc/mosquitto/mosquitto.conf
```
2. In the second terminal, run the signalling server:
```bash
WEBRTCSINK_SIGNALLING_SERVER_LOG=debug gst-webrtc-signalling-server
```
3. In the third terminal, run the JS client:
```bash
cd /home/gstwebrtc-api/ && npm install && npm start
```
4. In the fourth terminal, run one of the example scripts, read below for more information.

# Prerequisites
- Valid RTSP stream URL(s). Can be artificially generated with OBS Studio + RTSP server plugin for it from the webcam or any other source.

# Examples
## 1. Train/eval Deep Reinforcement Learning model
Add valid RTSP URL in `train_eval_drl/drl.py` and, if needed, adapt hyperparameters in the main coroutine. Then run `python train_eval_drl/drl.py`.

It trains or evaluates an SB3 DRL model to control the RTSP stream.

## 2. Multiple streams with the GCC control
Add valid RTSP URLs to `run_multiple_feeds/feeds.yaml` and run `run_multiple_feeds/run.sh`.

It tests running 2 RTSP streams and controlling them with GCC. You should see the allocated actions printed in the console.

You can turn off action allocation by passing empty string to `-at` argument of the script. It switches to the independent control of the streams.

You can turn off conroller by passing empty string to `-ct` argument of the script. It disables the possibility for the manual control and frees the main asyncio loop.

To manually control the streams via MQTT, you can use `cmd/publish.sh` script. Look for the example usage in the script.

### 2.1 Multiple streams with the SafetyDetector control (switching between the GCC and DRL based on the trends of certain WebRTC metrics + callbacks for the instant actions)
Do steps from the previous example and then change the `run_multiple_feeds/run.sh` script to use the SafetyDetector control instead of the GCC. You can do it by
- changing the `-cat` argument to `sd`
- passing the path to the DRL model to the `-cam` argument
- passing the path to the yaml file with the monitor configuration to the `-camc` argument. Example configuration is provided in `run_multiple_feeds/monitors.yaml`. It adds one switcher and one callback to the agent.

## 3. External FeedController
Add valid RTSP URLs to `external_feed_controller/feed1.yaml` and `external_feed_controller/feed2.yaml` and run `external_feed_controller/run_ec.sh`.