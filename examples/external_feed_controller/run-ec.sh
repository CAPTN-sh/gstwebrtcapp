#!/bin/bash

python ../../cmd/run.py \
    -t 'sink' \
    -b 'broker.yaml' \
    -f 'feed1.yaml' \
    -cat 'gcc' \
    -cap 2.0 \
    -ct 'internal/controller' \
    -at 'internal/aggregation' \
    -rm 'mqtt,dc' \
    -bdc \
    -w 10.0 &
python ../../cmd/run.py \
    -t 'sink' \
    -b 'broker.yaml' \
    -f 'feed2.yaml' \
    -cat 'gcc' \
    -cap 2.0 \
    -ct 'internal/controller' \
    -at '' \
    -ec \
    -rm 'mqtt,dc' \
    -bdc \
    -w 10.0
