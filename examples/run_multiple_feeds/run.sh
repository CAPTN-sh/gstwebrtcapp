#!/bin/bash

python ../../cmd/run.py \
    -t 'sink' \
    -b 'broker.yaml' \
    -f 'feeds.yaml' \
    -cat 'gcc' \
    -cap 3.0 \
    -at 'internal/aggregation' \
    -ct 'internal/controller' \
    -w 10.0
