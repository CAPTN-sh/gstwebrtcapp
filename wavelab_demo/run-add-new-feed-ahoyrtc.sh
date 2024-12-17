#!/bin/bash

exec python ../cmd/run.py \
    -t 'ahoy' \
    -b 'local_broker.yaml' \
    -f 'new_feed.yaml' \
    -s 'https://devdirex.wavelab.addix.net/api/v2/feed/attach/' \
    -ak 'ADD_AN_API_KEY' \
    -cat 'drl' \
    -cap 2.0 \
    -cam '/home/gstwebrtcapp/gstwebrtcapp/models/default/last.zip' \
    -ct 'internal/controller' \
    -at '' \
    -ec \
    -w 10.0 