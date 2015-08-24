import json
import os


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
