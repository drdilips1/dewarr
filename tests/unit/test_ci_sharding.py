import argparse
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.pytest_shard import parse_shard, pytest_collection_modifyitems


@pytest.mark.parametrize("value", ["0/4", "5/4", "1/0", "1", "one/4", "1/2/3", "-1/4"])
def test_invalid_shards_are_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_shard(value)


def test_shards_cover_every_test_once_in_collection_order():
    original = [SimpleNamespace(nodeid=f"tests/test_jobs.py::test_job[{i}]") for i in range(1000)]
    partitions = []
    for index in range(1, 5):
        config = Mock()
        config.getoption.return_value = parse_shard(f"{index}/4")
        items = original.copy()
        pytest_collection_modifyitems(config, items)
        partitions.append({item.nodeid for item in items})
        assert items == [item for item in original if item.nodeid in partitions[-1]]
        rejected = config.hook.pytest_deselected.call_args.kwargs["items"]
        assert len(items) + len(rejected) == len(original)
    assert sum(map(len, partitions)) == len(original)
    assert set.union(*partitions) == {item.nodeid for item in original}
    assert all(partitions)


def test_no_shard_leaves_collection_unchanged():
    config = Mock()
    config.getoption.return_value = None
    items = [SimpleNamespace(nodeid="test_one")]
    original = items.copy()
    pytest_collection_modifyitems(config, items)
    assert items == original
    config.hook.pytest_deselected.assert_not_called()


def test_assignment_is_stable_across_workers_with_different_hash_seeds():
    code = (
        "from scripts.pytest_shard import shard_for; "
        "print([shard_for(f'test_jobs.py::test_job[{i}]', 4) for i in range(100)])"
    )
    results = [
        subprocess.check_output(
            [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}, timeout=10
        )
        for seed in ("1", "42")
    ]
    assert results[0] == results[1]
