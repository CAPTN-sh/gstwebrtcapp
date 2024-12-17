#!/bin/bash

# REQUIREMENTS:
## apt-get install jq && pip install yq

# EXAMPLE USAGE:
## chmod +x publish.sh && ./publish.sh -b ../examples/run_multiple_feeds/broker.yaml -t internal/controller -m '{"video1":{"framerate":10}}'

usage() {
    echo "Usage: $0 -b <broker_yaml> -t <topic> -m <msg>"
    echo "  -b, --broker-config   Path to the MQTT broker configuration file in YAML format"
    echo "  -t, --topic           The MQTT topic to publish the message to"
    echo "  -m, --msg             The message to publish to the topic. IMPORTANT: properties must be enclosed in double quotes"
    exit 1
}

parse_mqtt_broker_config() {
    local yaml_file="$1"
    yq '.broker' "$yaml_file"
}

while [[ "$#" -gt 0 ]]; do
    case $1 in
        -b|--broker-config) broker_yaml="$2"; shift ;;
        -t|--topic) topic="$2"; shift ;;
        -m|--msg) msg="$2"; shift ;;
        *) usage ;;
    esac
    shift
done

if [ -z "$broker_yaml" ] || [ -z "$topic" ] || [ -z "$msg" ]; then
    usage
fi

broker_config=$(parse_mqtt_broker_config "$broker_yaml")
if ! echo "$broker_config" | jq empty; then
    echo "ERROR: Parsed broker configuration is not valid JSON"
    exit 1
fi

broker_host=$(echo "$broker_config" | jq -r '.broker_host')
broker_port=$(echo "$broker_config" | jq -r '.broker_port')
username=$(echo "$broker_config" | jq -r '.username')
password=$(echo "$broker_config" | jq -r '.password')
is_tls=$(echo "$broker_config" | jq -r '.is_tls')

timestamp=$(date +"%Y-%m-%d-%H_%M_%S_%3N")
id=$(openssl rand -hex 4)
mqtt_msg=$(jq -n --arg timestamp "$timestamp" --arg id "$id" --arg msg "$msg" --arg topic "$topic" \
    '{timestamp: $timestamp, id: $id, msg: $msg, source: "cmd-publish", topic: $topic}')

mqtt_cmd=("mosquitto_pub" "-h" "$broker_host" "-p" "$broker_port" "-t" "$topic" "-m" "$mqtt_msg")
[ -n "$username" ] && mqtt_cmd+=("-u" "$username")
[ -n "$password" ] && mqtt_cmd+=("-P" "$password")
[ "$is_tls" = "true" ] && mqtt_cmd+=("--tls")

"${mqtt_cmd[@]}"
