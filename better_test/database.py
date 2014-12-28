import itertools
import json
import os


def simple_weighted_partition(weighted_data, partitions):
    results = [list() for _ in range(partitions)]
    sorted_data = reversed(sorted(weighted_data))
    index_iter = itertools.cycle(range(partitions))
    for weight, value in sorted_data:
        results[next(index_iter)].append(value)
    return results


def _get_default_path():
    return os.path.join(os.getcwd(), '.better_test.db')


def read_database(path=None):
    if path is None:
        path = _get_default_path()
    if os.path.exists(path):
        with open(path) as fobj:
            return json.load(fobj)
    else:
        return {}


def write_database(database, path=None):
    if path is None:
        path = _get_default_path()
    with open(path, 'w') as fobj:
        json.dump(database, fobj)
