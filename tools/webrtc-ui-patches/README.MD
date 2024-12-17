This script patches the WebRTC UI to allow to modify its layout or behavior. 

You need to replace the original index.html (by default, /home/gstwebrtc-api/index.html) with modified version(s) from the following subfolders. Run as:
```bash
chmod +x patch.sh && ./patch.sh <path_to_original_index.html> <path_to_modified_index1.html> [<path_to_modified_index2.html> ...]"
```

Current patches:
- **flexbox-layout**: Groups the video feeds in a flexbox layout -- in a l->r line with a scrollbar if there are too many feeds.

- **add-stats-and-actions**: A big patch that adds a stats table and a button ("C") with a dropdown menu to set actions to each video feed. The stats table shows the current WebRTC metrics. The action button so far allows to set control algorithm, bitrate, resolution, framerate, fec percentage and preset for each feed.

NOTE: this patch requires that the GstWebRTCApp is run with two arguments set (see `$GSTWEBRTCAPP_FOLDER/cmd/run.py`):
- The `-rm` argument should contain the `'dc'` option to relay stats messages to the UI over the data channel.
- the `-bdc` flag should be enabled to handle action messages from the UI at the backend over the data channel.

# Patch webpack
This script reverts non-proxied webpack configuration to the one that uses a proxy to communicate with the signalling server. Run as:
```bash
chmod +x patch-webpack.sh && ./patch-webpack.sh <path_to_webpack.config.js>"
```
