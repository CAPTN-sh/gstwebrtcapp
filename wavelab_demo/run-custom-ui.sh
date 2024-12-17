#!/bin/bash

exec python ../cmd/run.py \
    -t 'sink' \
    -b 'local_broker.yaml' \
    -f 'feeds_custom_ui.yaml' \
    -cat 'any' \
    -cap 2.0 \
    -cam '/home/gstwebrtcapp/gstwebrtcapp/models/default/last.zip' \
    -camc 'monitors.yaml' \
    -ct 'internal/controller' \
    -at '' \
    -rm 'mqtt,dc' \
    -bdc \
    -w 10.0 
