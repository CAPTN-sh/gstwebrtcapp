#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <path-to-webpack.config.js>"
  exit 1
fi

FILE=$1
if [ ! -f "$FILE" ]; then
  echo "Error: File '$FILE' does not exist."
  exit 1
fi

sed -i \
'/devServer: {/ {N;:a;N;/}/!ba;s/devServer: {\([^}]*\)}/devServer: { \n     open: true, \n     static: false, \n     proxy: { \n       \"\/\webrtc\": { \n         target: \"ws:\/\/127.0.0.1:8443\", \n         ws: true \n       } \n     }, \n     server: \"https\", \n     port: 9090 \n   }/}' "$FILE"

echo "devServer configuration updated in webpack file '$FILE'."