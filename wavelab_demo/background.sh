#!/bin/bash

set -m
trap 'kill -- -$$' SIGINT SIGTERM KILL EXIT

mosquitto -c /etc/mosquitto/mosquitto.conf & \
    gst-webrtc-signalling-server & \
    (cd /home/gstwebrtc-api && npm start) & \
    wait