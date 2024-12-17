import asyncio
import copy
import enum
import json
import time
from typing import Any, Dict, Tuple

from gstwebrtcapp.message.client import MqttConfig, MqttMessage, MqttPair, MqttPublisher, MqttSubscriber
from gstwebrtcapp.utils.base import (
    LOGGER,
    async_sleep_until_condition_with_intervals,
    async_wait_for_condition,
    map_value,
    wait_for_condition,
)


class FeedState(enum.Enum):
    ALLOCATED = "allocated"
    INDEPENDENT = "independent"
    MANUAL = "manual"
    OFF = "off"


class FeedController:
    def __init__(
        self,
        mqtt_config: MqttConfig,
        feed_topics: Dict[str, str],
        controller_topic: str | None = None,
        aggregation_topic: str | None = None,
        allocation_weights: Dict[str, float] = {},
        action_limits: Dict[str, Tuple[float, float]] = {},
        max_aggregation_time: float = 5.0,
        warmup: float = 0.0,
    ) -> None:
        self.mqtt_config = mqtt_config
        self.mqtts = MqttPair(
            publisher=MqttPublisher(self.mqtt_config),
            subscriber=MqttSubscriber(self.mqtt_config),
        )
        self.mqtts.publisher.start()
        self.mqtts.subscriber.start()

        self.feeds = {feed_name: FeedState.ALLOCATED for feed_name in feed_topics}
        self.feed_topics = feed_topics
        self.allocated_feed_topics = copy.deepcopy(self.feed_topics)
        self.controller_topic = controller_topic or self.mqtt_config.topics.controller
        self.aggregation_topic = aggregation_topic or self.mqtt_config.topics.actions
        self.mqtts.subscriber.subscribe([self.controller_topic, self.aggregation_topic])

        self.allocation_weights = {}
        self._init_allocation_weights(allocation_weights)

        self.init_action_limits = copy.deepcopy(action_limits)
        self.action_limits = action_limits

        self.max_aggregation_time = max_aggregation_time
        self.warmup = warmup

        self.is_running = False

    async def controller_coro(self) -> None:
        if not self.controller_topic:
            LOGGER.error("ERROR: FeedController: controller topic is not set, STOPPING...")
            return
        self.is_running = True
        LOGGER.info(f"INFO: FeedController's controller coroutine is starting...")

        while self.is_running:
            try:
                mqtt_msg = await self.mqtts.subscriber.await_message(self.controller_topic)
                feed_action_dict = json.loads(mqtt_msg.msg)
                if not (
                    isinstance(feed_action_dict, dict) and all(isinstance(v, dict) for v in feed_action_dict.values())
                ):
                    LOGGER.error(
                        f"ERROR: FeedController: invalid action format: {type(feed_action_dict)} but should be a dict of a dict"
                    )
                    self.cleanup()
                else:
                    for feed_name, action_dict in feed_action_dict.items():
                        # NOTE: fix "all" feed name for actions for all feeds
                        if feed_name == "all":
                            for action_name, action_value in action_dict.items():
                                match action_name:
                                    case "weights":
                                        # pass it in a form of {"all": {"weights": {feed_name: weight, ...}}}
                                        self.update_allocation_weights(action_value)
                                        LOGGER.info(f"ACTION: updated weights for all feeds: {self.allocation_weights}")
                                    case "limits":
                                        # pass it in a form of {"all": {"limits": {action_name: (min, max), ...}}}
                                        self.update_action_limits(action_value)
                                        LOGGER.info(
                                            f"ACTION: updated action limits for all feeds: {self.action_limits}"
                                        )
                                    case _:
                                        LOGGER.error(
                                            f"ERROR: FeedController : Unknown general action with the name: {action_name}"
                                        )
                            continue
                        # INDIVIDUAL ACTIONS
                        for action_name, action_value in action_dict.items():
                            action_name = action_name.lower()
                            if feed_name not in self.feeds and action_name != "on":
                                LOGGER.error(
                                    f"ERROR: FeedController: unknown feed name in the actions: {feed_name} and the action is not 'on'"
                                )
                                break

                            match action_name:
                                case (
                                    "bitrate"
                                    | "resolution"
                                    | "framerate"
                                    | "fec"
                                    | "preset"
                                    | "switch"
                                    | "reload_agent"
                                    | "send_dc"
                                ):
                                    # pass key: val: Any and catch it in the connector
                                    self.mqtts.publisher.publish(
                                        self.feed_topics[feed_name],
                                        json.dumps({action_name: action_value}),
                                    )
                                case "max_bitrate":
                                    # pass "max_bitrate": bitrate: int -- comes from SafetyDetector's callbacks
                                    # FIXME: one stream callback sets the max_bitrate for all streams. Could be ok
                                    if "bitrate" in self.action_limits:
                                        self.update_action_limits(
                                            {"bitrate": (self.init_action_limits["bitrate"][0], action_value)}
                                        )
                                case "alloc":
                                    # pass "alloc": True/False
                                    if action_value:
                                        if self.feeds[feed_name] == FeedState.INDEPENDENT:
                                            self.change_alloc_status(feed_name, action_value)
                                            LOGGER.info(
                                                f"ACTION: feed {feed_name} has been turned into ALLOCATED state"
                                            )
                                    else:
                                        if self.feeds[feed_name] == FeedState.ALLOCATED:
                                            self.change_alloc_status(feed_name, action_value)
                                            LOGGER.info(
                                                f"ACTION: feed {feed_name} has been turned into INDEPENDENT state"
                                            )
                                case "manual":
                                    # pass "manual": True/False
                                    if action_value:
                                        self.remove_feed(feed_name, FeedState.MANUAL)
                                        LOGGER.info(
                                            f"ACTION: feed {feed_name} has been turned into MANUAL state, allocated feeds are: {self.allocated_feed_topics}"
                                        )
                                    else:
                                        self.add_feed(feed_name)
                                        LOGGER.info(
                                            f"ACTION: feed {feed_name} has been turned into ALLOCATED state, allocated feeds are: {self.allocated_feed_topics}"
                                        )
                                case "off":
                                    # pass "off": True/False
                                    if action_value:
                                        # notify the connector to stop the feed, else it is the other way around
                                        self.mqtts.publisher.publish(
                                            self.feed_topics[feed_name], json.dumps({action_name: action_value})
                                        )
                                    self.remove_feed(feed_name, FeedState.OFF)
                                    LOGGER.info(
                                        f"ACTION: feed {feed_name} has been turned off, ALLOCATED feeds are: {self.allocated_feed_topics}"
                                    )
                                case "on":
                                    # pass "on": action_topic: str | None
                                    self.add_feed(feed_name, action_value)
                                    LOGGER.info(
                                        f"ACTION: feed {feed_name} has been turned on, ALLOCATED feeds are: {self.allocated_feed_topics}"
                                    )
                                case _:
                                    LOGGER.error(f"ERROR: FeedController : Unknown action with the name: {action_name}")
            except Exception as e:
                raise Exception(f"ERROR: FeedController's controller coro has thrown an exception: reason {e}")

    async def allocation_coro(self) -> None:
        await asyncio.sleep(self.warmup)
        if not self.aggregation_topic:
            # if the aggregation topic is not set, the allocation coroutine normally won't start from the main loop
            LOGGER.error("ERROR: FeedController: aggregation topic is not set, STOPPING...")
            return
        self.mqtts.subscriber.clean_message_queue(self.aggregation_topic)
        self.is_running = True
        LOGGER.info(f"INFO: FeedController's allocation coroutine is starting...")

        while self.is_running:
            try:
                if not self.allocated_feed_topics:
                    await async_wait_for_condition(lambda: self.allocated_feed_topics, -1, 0.1)
                aggregated_actions = await self._aggregation_coro()
                if aggregated_actions:
                    self._allocate_actions(aggregated_actions)
            except Exception as e:
                raise Exception(f"ERROR: FeedController's allocation coro has thrown an exception: reason {e}")

    async def _aggregation_coro(self) -> Dict[str, Any]:
        # it should aggregate N actions where N is the number of feeds
        if self.mqtts.subscriber.message_queues.get(self.aggregation_topic, None) is None:
            # if first message has not appeared, wait for it for 10 seconds
            wait_for_condition(
                lambda: self.mqtts.subscriber.message_queues.get(self.aggregation_topic, None) is not None, 10.0
            )
        else:
            queue = self.mqtts.subscriber.message_queues[self.aggregation_topic]

        time_starts = time.time()
        time_wait = self.max_aggregation_time
        aggregated_msgs = {}
        while len(aggregated_msgs) < len(self.allocated_feed_topics):
            is_msg = await async_sleep_until_condition_with_intervals(
                int(time_wait / 0.1),
                time_wait,
                lambda: not queue.empty(),
            )
            if is_msg:
                mqtt_msg: MqttMessage = queue.get_nowait()
            else:
                mqtt_msg = None
                break
            time_wait = max(0.0, self.max_aggregation_time - (time.time() - time_starts))
            feed_name = next((k for k in self.allocated_feed_topics if mqtt_msg.id.startswith(k)), None)
            if feed_name is None:
                feed_name = next((k for k in self.feed_topics if mqtt_msg.id.startswith(k)), None)
                if feed_name is not None:
                    if self.feeds[feed_name] == FeedState.INDEPENDENT:
                        # if it is independent propagate the action to the feed mapping its value to the limits
                        actions = json.loads(mqtt_msg.msg)
                        if not isinstance(actions, dict):
                            continue
                        m_actions = {}
                        for key, value in actions.items():
                            if key in self.action_limits:
                                m_actions[key] = map_value(
                                    value,
                                    *self.init_action_limits[key],
                                    *self.action_limits[key],
                                )
                            else:
                                m_actions[key] = value
                        self.mqtts.publisher.publish(self.feed_topics[feed_name], json.dumps(m_actions))
                else:
                    # if not found -- an unknown feed
                    LOGGER.warning(f"WARNING: FeedController: unknown feed name in the MQTT message: {mqtt_msg.id}")
            else:
                aggregated_msgs[feed_name] = json.loads(mqtt_msg.msg)

        return aggregated_msgs

    def _allocate_actions(self, actions: Dict[str, Any] | Dict[str, Dict[str, Any]]) -> None:
        # sum all actions for each feed that are allocated (a mismatch could be due to a concurrency)
        actions_ = {feed_name: actions[feed_name] for feed_name in actions if feed_name in self.allocated_feed_topics}
        summed_actions = {
            action_key: sum([actions_[feed_name][action_key] for feed_name in actions_])
            for action_key in actions_[list(actions_.keys())[0]]
        }

        # initial allocation based on weights
        feeds_arrived = actions_.keys()
        allocated_actions = {
            feed_name: {
                action_key: summed_actions[action_key] * self.allocation_weights[feed_name]
                for action_key in summed_actions
            }
            for feed_name in feeds_arrived
        }

        # adjust allocations to respect min and max limits if provided
        for action_key in summed_actions:
            if action_key in self.action_limits:
                min_limit, max_limit = self.action_limits[action_key]
                while True:
                    adjustment_value = 0.0
                    max_feeds = []
                    min_feeds = []
                    for feed_name in feeds_arrived:
                        allocated = allocated_actions[feed_name][action_key]
                        if allocated > max_limit:
                            adjustment_value += allocated - max_limit
                            allocated_actions[feed_name][action_key] = max_limit
                            max_feeds.append(feed_name)
                        elif allocated < min_limit:
                            adjustment_value -= min_limit - allocated
                            allocated_actions[feed_name][action_key] = min_limit
                            min_feeds.append(feed_name)

                    if adjustment_value != 0.0:
                        no_more_feeds = min_feeds if adjustment_value < 0.0 else max_feeds
                        remaining_feeds = [feed for feed in feeds_arrived if feed not in no_more_feeds]
                        if remaining_feeds:
                            remaining_weight_denom = sum([self.allocation_weights[feed] for feed in remaining_feeds])
                            for feed_name in remaining_feeds:
                                weight = self.allocation_weights[feed_name] / remaining_weight_denom
                                allocated_actions[feed_name][action_key] += adjustment_value * weight
                        else:
                            # should not be reachable as the AI agent should also follow the same limits
                            break
                    else:
                        break

        # publish allocated actions to the feeds' connectors listening for them
        for feed_name, feed_topic in self.allocated_feed_topics.items():
            if feed_name in allocated_actions:
                self.mqtts.publisher.publish(feed_topic, json.dumps(allocated_actions[feed_name]))

    def add_feed(
        self,
        name: str,
        action_topic: str | None = None,
        new_weights: Dict[str, float] | None = None,
    ) -> None:
        if name not in self.feeds:
            if action_topic is not None:
                self.feeds[name] = FeedState.ALLOCATED
                self.feed_topics[name] = action_topic
                self.allocated_feed_topics[name] = action_topic
                self.mqtts.subscriber.subscribe([action_topic])
            else:
                raise Exception(f"ERROR: FeedController: no action topic is provided for a new feed {name}")
        else:
            if self.feeds[name] != FeedState.ALLOCATED:
                self.feeds[name] = FeedState.ALLOCATED
                self.allocated_feed_topics[name] = self.feed_topics[name]
                self.mqtts.subscriber.subscribe([self.feed_topics[name]])

        self.update_allocation_weights(new_weights or self.allocation_weights)

    def remove_feed(
        self,
        name: str,
        state: FeedState,
        is_forever: bool = False,
        new_weights: Dict[str, float] | None = None,
    ) -> None:
        if name in self.feeds:
            self.mqtts.subscriber.unsubscribe([self.feed_topics[name]])
            self.feeds[name] = state
            _ = self.allocated_feed_topics.pop(name, None)
            if is_forever:
                _ = self.feed_topics.pop(name, None)
                _ = self.feeds.pop(name, None)

            self.update_allocation_weights(new_weights or self.allocation_weights)
        else:
            raise Exception(f"ERROR: FeedController: unknown feed {name} to remove")

    def change_alloc_status(self, name: str, is_alloc: bool) -> None:
        if name not in self.feeds:
            return

        if is_alloc:
            self.feeds[name] = FeedState.ALLOCATED
            self.allocated_feed_topics[name] = self.feed_topics[name]
        else:
            self.feeds[name] = FeedState.INDEPENDENT
            if len(self.allocated_feed_topics) > 1:
                # HACK: do not remove the last feed from the allocated feeds
                _ = self.allocated_feed_topics.pop(name, None)

        self.update_allocation_weights(self.allocation_weights)

    def _init_allocation_weights(self, weights: Dict[str, float] | None = None) -> None:
        if weights:
            self.allocation_weights = weights
        else:
            self.allocation_weights = {
                feed_name: 1.0 / len(self.allocated_feed_topics) for feed_name in self.allocated_feed_topics
            }

    def update_allocation_weights(self, weights: Dict[str, float]) -> None:
        if not self.allocated_feed_topics:
            return
        if sum(weights.values()) > 1.0:
            LOGGER.error(f"ERROR: FeedController: sum of given weights is greater than 1, cannot update the weights")
            return

        # update the weights for the ALLOCATED feeds
        new_feed = ""
        for feed_name in self.feeds:
            if feed_name in self.allocated_feed_topics and feed_name not in weights:
                self.allocation_weights[feed_name] = 0.0
                new_feed = feed_name
            elif feed_name not in self.allocated_feed_topics and feed_name in weights:
                _ = weights.pop(feed_name, None)
                _ = self.allocation_weights.pop(feed_name, None)
            elif feed_name in self.allocated_feed_topics and feed_name in weights:
                self.allocation_weights[feed_name] = weights[feed_name]
            else:
                pass

        allocation_weights_sum = sum(self.allocation_weights.values())
        allocated_topics_len = len(self.allocated_feed_topics)

        if not new_feed and allocation_weights_sum != 1.0:
            # recalculate the weights to keep the sum equal to 1
            extra_averaged_weight = (1.0 - allocation_weights_sum) / allocated_topics_len
            for feed_name in self.allocation_weights:
                self.allocation_weights[feed_name] += extra_averaged_weight
        elif new_feed:
            # if a new feed is added distribute the weights equally
            new_equal_weight = 1.0 / allocated_topics_len
            self.allocation_weights[new_feed] = new_equal_weight
            minus_averaged_weight = new_equal_weight / (allocated_topics_len - 1)
            for feed_name in self.allocation_weights:
                if feed_name != new_feed:
                    self.allocation_weights[feed_name] -= minus_averaged_weight

        LOGGER.info(f"ACTION: updated weights for all feeds: {self.allocation_weights}")

    def update_action_limits(self, limits: Dict[str, Tuple[float, float]]) -> None:
        LOGGER.info(f"ACTION: updating action limits: {limits}")
        for action_name, limit in limits.items():
            match action_name:
                case "bitrate":
                    self.action_limits[action_name] = limit
                case _:
                    pass  # add other cases if needed

    def cleanup(self) -> None:
        self.is_running = False
        self.mqtts.publisher.stop()
        self.mqtts.subscriber.stop()
