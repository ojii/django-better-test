from __future__ import absolute_import
import time

from .parallel import Pool
from .parallel import MultiProcessingTextTestResult
from .utils import suite_to_labels
from .utils import simple_weighted_partition
from .compat import unittest

ISOLATED = 1
PARALLEL = 2
STANDARD = 0


class Result(object):
    def __init__(self, tests_run, time_taken, timings, failures, errors,
                 skipped, expected_failures, unexpected_successes,
                 failed_executors, successes, test_labels):
        self.tests_run = tests_run
        self.time_taken = time_taken
        self.timings = timings
        self.failures = failures
        self.errors = errors
        self.skipped = skipped
        self.expected_failures = expected_failures
        self.unexpected_successes = unexpected_successes
        self.failed_executors = failed_executors
        self.successes = successes
        self.test_labels = test_labels

    @property
    def total_results(self):
        return sum(map(len, (
            self.failures,
            self.errors,
            self.skipped,
            self.expected_failures,
            self.unexpected_successes,
            self.failed_executors,
            self.successes,
        )))

    @property
    def success(self):
        return not any((
            self.unexpected_successes,
            self.failures,
            self.errors,
            self.failed_executors
        ))

    @property
    def total_failures(self):
        return sum(map(len, (
            self.failures,
            self.errors,
            self.unexpected_successes,
            self.expected_failures,
            self.failed_executors
        )))


class Config(object):
    def __init__(self, test_runner_class, mode, timings, processes,
                 verbosity=1, debug=False, start_method='spawn'):
        self.test_runner_class = test_runner_class
        self.mode = mode
        self.timings = timings
        self.processes = processes
        self.verbosity = verbosity
        self.debug = debug
        self.start_method = start_method


def run(test_labels, test_runner_options, config,
        real_result_class=MultiProcessingTextTestResult):
    test_runner = config.test_runner_class(**test_runner_options)

    suite = test_runner.build_suite(test_labels)

    # Get an actual result class we can use
    pseudo_runner = unittest.TextTestRunner(
        resultclass=real_result_class,
        verbosity=config.verbosity,
    )
    real_result = pseudo_runner._makeResult()

    all_test_labels = suite_to_labels(suite, real_result)

    if config.mode == ISOLATED:
        # Isolate means one test (label) per task process.
        chunks = [
            [label] for label in all_test_labels
        ]
    elif config.mode == PARALLEL:
        # Try to distribute the test labels equally across the available
        # CPU cores
        chunk_count = config.processes
        weighted_chunks = [
            (config.timings.get(label, 0), label)
            for label in all_test_labels
        ]
        # Try to split the tests into chunks of equal time, not equal size
        chunks = simple_weighted_partition(weighted_chunks, chunk_count)

        # filter empty chunks
        chunks = list(filter(bool, chunks))
    elif config.mode == STANDARD:
        chunks = [all_test_labels]
    else:
        raise ValueError("Unknown mode: {0}".format(config.mode))

    start_time = time.time()
    pool = Pool(real_result, config.processes, config.start_method)
    failed_executors = pool.run(
        chunks,
        config.test_runner_class,
        test_runner_options
    )
    end_time = time.time()

    # Report result, this is mostly taken from TextTestRunner.run
    time_taken = end_time - start_time

    timings = dict(real_result.timings.items())

    return Result(
        tests_run=real_result.testsRun,
        time_taken=time_taken,
        timings=timings,
        failures=real_result.failures,
        errors=real_result.errors,
        skipped=real_result.skipped,
        expected_failures=real_result.expectedFailures,
        unexpected_successes=real_result.unexpectedSuccesses,
        failed_executors=failed_executors,
        successes=real_result.successes,
        test_labels=all_test_labels,
    )
