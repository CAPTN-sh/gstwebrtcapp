# WebRTC Wavelab Demo
This is a demo for the CAPTN Förde5G project, showing the capabilities of the GstWebRTCApp developed within the project. For more detailed information about all possible features, go back to the main repo's [README](../README.md).

Table of Contents:
- [WebRTC Wavelab Demo](#webrtc-wavelab-demo)
- [Environment](#environment)
  - [Installation from scratch](#installation-from-scratch)
- [How to run the scripts](#how-to-run-the-scripts)
- [Demo](#demo)
  - [AhoyApp](#ahoyapp)
  - [SinkApp](#sinkapp)
    - [Shared Viewing](#shared-viewing)
  - [Video streams configuration](#video-streams-configuration)
    - [Hardware acceleration for the video encoding](#hardware-acceleration-for-the-video-encoding)
      - [Max simultaneous hardware accelerated encoding sessions](#max-simultaneous-hardware-accelerated-encoding-sessions)
  - [Add a new video stream](#add-a-new-video-stream)
- [Acknowledgments](#acknowledgments)
- [Authors](#authors)

# Environment
At the time of writing **(16 December 2024)** there is a running Docker container on the CAU server at the Wavelab (`192.168.237.62`, behind the Wavelab VPN). The container is called `gstreamer-gstwebrtcapp-cuda-1` and provides all the necessary infrastructure to run the demo, including dependencies, working GPU integration including AV1 hardware acceleration and AI model inference, compiled binaries of the latest version corresponding to this repository, cooked configuration files, well-tuned browser client and running independent background services needed to run the demo. This folder is available in the `/home/gstwebrtcapp/wavelab_demo` directory inside the container.

To gain an access to the container, you can attach a shell to the running container from the CAU server using the following command:
```bash
docker exec -it gstreamer-gstwebrtcapp-cuda-1 bash
```
To detach from the container, press `Ctrl+P` and `Ctrl+Q` in the attached shell in sequence.

Or you can attach a VSCode instance to the running container from anywhere by first connecting to the CAU server via SSH and then using the DevContainer extension.

## Installation from scratch
If you want to replicate the environment on another host machine, you will need to build a Docker image (CUDA or CPU version) and perform all the installation steps described in the [README](../README#installation).

Then you need to run the `background.sh` script in the demo folder to start the background services. Do this as follows:
```bash
cd /home/gstwebrtcapp/wavelab_demo && chmod +x background.sh && nohup ./background.sh > tmp/background.out 2>&1 & 
```

> [!NOTE]
> The demo assumes that the GPU support is enabled. If you want to run the demo on a CPU, you need to modify the `cuda_in` and `cuda_out` fields in the video streams configuration to `false` and rerun the scripts. See [this section](#video-streams-configuration) for more details.

# How to run the scripts
To run the scripts in the attached console, you need to navigate to the demo folder. There are several scripts available to run the demo. They are described [below](#demo).

To run them in a blocking mode:
```bash
./script.sh
```

To run them in a non-blocking mode:
```bash
./script.sh & disown
```
The latter returns the PID of the running process. You can use it to kill the process later on as `kill -9 <PID>`.

By default, the stdout and stderr of the scripts are redirected to the attached shell in both blocking and non-blocking mode. If you want to redirect them to the file, you can do this as follows:
```bash
./script.sh > script.out 2>&1
```
Note, if you got an error like "[1]+ killed ..." try to execute `ulimit -n 65536` to increase the number of allowed open file descriptors.

To disable logs completely, you can redirect them to `/dev/null`:
```bash
./script.sh > /dev/null 2>&1
```

So for example, if you want to run a script in a non-blocking mode and disable logging:
```bash
./script.sh > /dev/null 2>&1 & disown
```
# Demo
The demo works with two WebRTC clients, the AhoyRTC Director from the ADDIX GmbH and the static html open-source client modified by us. They are called `AhoyApp` and `SinkApp`. They use different browser clients, background plugins and signalling protocols but share the same control interface. We mostly used our own client for the development, research and testing during the real Wavelab runs to have more control, so it is a default client in the demo.

## AhoyApp
In the scope of the CAPTN Förde5G project, there is a dev-instance of the AhoyRTC Director available [here](https://devdirex.wavelab.addix.net/director/#/gallery). 

> [!NOTE]
> You must request the API-key from ADDIX to use the AhoyRTC Director. It is assumed that this is already done when accessing the CAU server, as it requires the Wavelab VPN, but it is missing here. In the container it is already pasted into the scripts.

To use the AhoyApp:
1. Run the `run-ahoyrtc.sh` script. You should see 3 new feeds waiting for the negotiation. 
2. Click on their play button and the streams should start playing in the AhoyRTC Director. 
3. Activate the WebRTC statistics by clicking once the following [link](https://devdirex.wavelab.addix.net/test/stats.html). If you do not do the latter, the AI adaptation won't work. You can disable any adaptation by setting `-cat 'none'` in the `run-ahoyrtc.sh` script and rerun it.
4. To perform actions, you need to send the special MQTT messages to the GstWebRTCApp's feed controller topic (set by `-ct` cmd option, by default it is `internal/controller` on the local broker). You can do this via the exposed publishing script from any folder as so (in a separate terminal):
```bash
/home/gstwebrtcapp/cmd/publish.sh -b /home/gstwebrtcapp/wavelab_demo/local_broker.yaml -t internal/controller -m '{"mast-steuerbord":{"framerate":60}}'
```
You can also send multiple commands for multiple streams at once, such as
```bash
/home/gstwebrtcapp/cmd/publish.sh -b /home/gstwebrtcapp/wavelab_demo/local_broker.yaml -t internal/controller -m '{ "mast-steuerbord":{ "framerate":60, "resolution": { "width": 3840, "height": 2160 } }, "mast-bb:{ "switch":"gcc" } }'
```
The available commands are:
- `switch` - (string) a switch between the automatic adaptation modes. The available modes are: `drl` (AI-based automatic adaptation), `gcc` (non-AI-based conservative automatic adaptation), `sd`  (SafetyDetector, auto-switch between `drl` and `gcc` depending on the ascending trends in the latency measured at runtime) and `man` (disable automatic adaptation).
- `alloc` - (boolean) set the allocation mode of the stream, true for fair allocation and false for the independent acting.
- `bitrate` - (int) set the bitrate of the stream in Kbps from 400 to 10000. Note that if the any automatic control is enabled, the manually set bitrate will be swapped by the automatic control in the next few seconds. To control bitrate manually, set control to `man` as described above.
- `framerate` - (int) set the framerate of the stream from 1 to 60 fps.
- `resolution` - (dict) set the resolution of the stream in pixels in the format {"width": 3840, "height": 2160}
- `fec` - (int) set the Forward Error Correction rate of the stream from 0 to 100 (in %). 
5. To stop the stream, click the Stop button in the AhoyRTC Director. It will revert to the pending state.
6. To stop the streams completely, kill the `run-ahoyrtc.sh` script either with `Ctrl+C` if blocking or `kill -9 <PID>` if non-blocking.

## SinkApp
To use the SinkApp:
1. Navigate to the https://192.168.237.62:9090/ in the browser. Accept the self-signed localhost certificate by allowing the browser to navigate to the "unsafe" page. Then you should see the UI. 
2. Run `run-custom-ui.sh` script. You should see 3 new feeds waiting for the negotiation.
3. Click on each name to start the streams. Then they should start playing in the client.
4. Below each stream you will see a table with its current WebRTC statistics, settings like resolution or FPS, and a 'C' button with a drop-down menu that opens when you click it, representing the available commands listed above. Unlike the direct MQTT commands, the commands here are split into several sub-dropdowns for each option, but the functionality is simplified by the UI, so you can, for example, set a resolution and FPS in two quick clicks in UI. Of course, you can still use the direct MQTT commands in the same way as described above.
5. To stop the stream, click on its name in the client. It will revert to the pending state.
6. To stop the streams completely, kill the `run-custom-ui.sh` script either with `Ctrl+C` if blocking or `kill -9 <PID>` if non-blocking.

### Shared Viewing
Although the `SinkApp` client provides much easier UI control of the streams, it does not currently support full shared viewing. It supports multiple viewers, for each new viewer a new GStreamer pipeline with AI inference is created, but since the stream sources are the same, the AI adaptation and other commands will only work for the last viewer. This is considered acceptable since the main scenario in the CAPTN Förde 5G project so far assumes one main viewer, the control centre. The `AhoyApp` client supports full shared viewing, so the commands will work for all viewers in the same way.

## Video streams configuration
The video streams aka feeds are configured in the `feeds_ahoyrtc.yaml` and `feeds_custom_ui.yaml` files. The only difference between them is the field `transceiver_settings` field which controls the advanced RTP extensions to mitigate packet loss. They are currently disabled for the AhoyRTC Director instance, our custom UI always supports them.

The typical feed configuration is as follows:
```yaml
  mast-steuerbord:
    video_url: "rtsp://..." # the video source, currently only RTSP sources, others are not used in the project at the moment of writing, though the GstWebRTCApp could support them
    codec_in: "h265" # the codec of the input video (available: h264, h265, vp8, vp9, av1) 
    codec_out: "av1" # the codec of the output video (available: h264, h265, vp8, vp9, av1)
    cuda_in: true # enable GPU hardware acceleration for the decoding of the input flow (supports h264, h265, av1)
    cuda_out: true # enable GPU hardware acceleration for the encoding of the output flow (supports h264, h265, av1)
    bitrate: 4000 # the initial bitrate of the stream in Kbps
    resolution: # the initial resolution of the stream in pixels, NOTE: different codecs have different resolution limits
      width: 3840
      height: 2160
    framerate: 20 # the initial framerate of the stream in fps (1-60), NOTE: max fps is limited programmatically to 60 as a reasonable upper limit for the WebRTC
    fec_percentage: 0 # the initial FEC rate of the stream in % (0-100)
    is_preset_tuning: false # whether the resolution and framerate are discretly tuned according to the bitrate values
    gcc_settings: # the settings for the GCC algorithm (conservative non-AI adaptation), the 'max_bitrate' is the upper limit of the bitrate in Bps for both AI and GCC adaptation
      min_bitrate: 400000
      max_bitrate: 6000000
    transceiver_settings: # the settings for the advanced RTP extensions: NACK is the retransmission of the lost packets, FEC is the redundant packets for the lost packets recovery
      nack: true
      fec: true
    data_channels_cfgs: [] # the list of the configurations for the WebRTC data channels that will be created for and used by the stream
    priority: 4 # the DSCP priority of the stream (1-4), used to select the operator: 1 - Starlink, 2 - auto, 3 - Telekom, 4 - Vodafone
    is_debug: false # whether to enable the debug mode for the stream
    is_graph: false # whether to store the pipeline graph in the file for the stream
```

> [!NOTE]
> At the time of writing, standard browsers do not support h265 video. So do not set it as far as the `codec_out` value or patch the browser to support it.

### Hardware acceleration for the video encoding
The CAU server has two GPUs at the time of writing: NVIDIA GeForce RTX 4060 and NVIDIA GeForce RTX 3080. Hardware acceleration for video encoding is enabled for the following codecs:
- **h264**: supported by both GPUs
- **h265**: supported by both GPUs
- **av1**: supported **on NVIDIA GeForce RTX 4060 only**.

Hardware acceleration for video encoding using the VP family codecs is not supported by the NVIDIA drivers and GStreamer plugins at the time of writing.

#### Max simultaneous hardware accelerated encoding sessions
At the time of writing, hardware acceleration for video encoding on a single GPU is limited by the NVIDIA driver to **5 simultaneous sessions**. 

By default, all new streams will use the RTX 4060 and it will have device ID = 1. If you hit the limit on this GPU, you will need to force the new feeds to use the RTX 3080 with device ID = 0. You can do this by prepending `CUDA_VISIBLE_DEVICES=0` to the script. While it is possible to set the device ID in the feed configuration for the `AhoyApp`, it is not possible for the `SinkApp` due to the internal 3rd party implementation it uses under the hood. Therefore it should be controlled at the operating system level. 

There is an [unofficial patch] (https://github.com/keylase/nvidia-patch) that removes this limitation, but at the time of writing it is not installed on the CAU server.

## Add a new video stream
To add a new video stream, you need to create a new feed config and run the new script with it. The demo provides a `new_feed.yaml` config file and `run-add-new-feed-ahoyrtc.sh` and `run-add-new-feed-custom-ui.sh` scripts to run the new feed.

The only change in both scripts apart from the feed configuration file is the `-ec` option. This tells the script not to create a new `FeedController` instance, but to attach to the existing one. They assume that at least one controller instance has been created somewhere and is listening to the controller MQTT topic specified by the `-ct` option, so it remains the same as in the main scripts. This provides a speedup because all the processing is offloaded to a new OS process, so the new feed can be truly parallel. The pipeline for the initial feeds uses coroutines, which are offloaded to threads but still run in the same process due to the well-known Python Global-Interpreter-Lock (GIL).

So far the main scripts are responsible for the controller creation, so you can run add a new feed with an external controller only after the main script is running. It is easily possible to make a script that is solely responsible for controller creation, and then attach each new feed to that controller instance via custom scripts, the creation of which could also be automated, offloading the execution to the new OS processes for each feed, and terminating it by killing the corresponding process. This is not implemented in the demo for simplicity, but it is a possible improvement. The controller creation is done in the `cmd/run.py` script.

# Acknowledgments
The development of this software has been funded by the German Federal Ministry for Digital and Transport (Bundesministerium für Digitales und Verkehr) within the project "CAPTN Förde 5G", funding guideline: "5G Umsetzungsförderung im Rahmen des 5G-Innovationsprogramms", funding code: 45FGU139_H. The authors acknowledge the financial support of the BMDV.

# Authors
M.Sc. Nikita Smirnov, Prof. Dr.-Ing. Sven Tomforde, Intelligent Systems AG, Department of Computer Science, Kiel University, Germany.

Please contact me in case of any questions: [mailto Nikita Smirnov](mailto:nikita.smirnov@cs.uni-kiel.de)
