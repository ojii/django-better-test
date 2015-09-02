from contextlib import contextmanager
import os
import sys
import itertools


class DisableMigrations(object):
    def __contains__(self, _):
        return True

    def __getitem__(self, _):
        return "notmigrations"


def simple_weighted_partition(weighted_data, partitions):
    results = [list() for _ in range(partitions)]
    sorted_data = reversed(sorted(weighted_data))
    index_iter = itertools.cycle(
        itertools.chain(range(partitions), reversed(range(partitions)))
    )
    for weight, value in sorted_data:
        results[next(index_iter)].append(value)
    return results


def suite_to_labels(suite, result):
    """
    Transform a unittest.TestSuite to a list of test labels that can be used
    by django.test.DiscoveryRunner.run_tests.
    """
    labels = []
    for test in suite._tests:
        klass = test.__class__
        name = klass.__name__
        module = klass.__module__
        if name == 'ModuleImportFailure' and module == 'unittest.loader':
            test.qualname = module + '.' + name
            try:
                getattr(test, test._testMethodName)()
            except Exception as err:
                result.addError(test, err)
        else:
            labels.append(test_to_dotted(test))
    return labels


@contextmanager
def null_stdout():
    """
    Context manager setting sys.stdout to devnull and yielding that stdout
    """
    stdout = sys.stdout
    nullout = open(os.devnull, 'w')
    sys.stdout = nullout
    try:
        yield nullout
    finally:
        sys.stdout = stdout
        nullout.close()


def serialize(test):
    """
    Serializes a test (which can either be a TestCase-like or an ErrorHolder)
    for safe transport via a Queue.
    ErrorHolder (if actual test setup failed, not anything during test run) is
    special cased because it's a dynamic class and isn't quite the same as
    normal tests.
    """
    if hasattr(test, '_testMethodName'):
        return (
            test_to_dotted(test),
            str(test),
            test.shortDescription()
        )
    else:
        return (
            test.id(),
            str(test),
            test.shortDescription(),
        )


def test_to_dotted(test):
    klass = test.__class__
    name = klass.__name__
    module = klass.__module__
    return '{module}.{name}.{method}'.format(
        module=module,
        name=name,
        method=test._testMethodName
    )


def get_test_runner(name=None):
    from django.conf import settings
    from django.test.utils import get_runner

    return get_runner(settings, name)


def get_settings_dict():
    from django.conf import settings
    return dict(
        (key, getattr(settings, key)) for key in dir(settings)
        if key.upper() == key
    )
