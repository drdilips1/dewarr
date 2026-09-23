"""Deterministically partition collected tests across independent CI runners."""

import argparse
import hashlib


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index, count = map(int, value.split("/"))
        if 1 <= index <= count:
            return index, count
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use INDEX/COUNT with 1 <= INDEX <= COUNT")


def shard_for(nodeid: str, count: int) -> int:
    # Python's hash() is randomized per process; xdist workers must agree.
    return int.from_bytes(hashlib.sha256(nodeid.encode()).digest(), "big") % count + 1


def pytest_addoption(parser):
    parser.addoption("--ci-shard", type=parse_shard, help="Run shard INDEX/COUNT of collected tests")


def pytest_collection_modifyitems(config, items):
    shard = config.getoption("--ci-shard")
    if shard is None:
        return
    index, count = shard
    selected, deselected = [], []
    for item in items:
        (selected if shard_for(item.nodeid, count) == index else deselected).append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
