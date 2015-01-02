from contextlib import contextmanager
from optparse import make_option
import multiprocessing
import os
import unittest
import sys
import time
import itertools

try:
    import queue
except ImportError:
    import Queue as queue

from django.core.management.commands.test import Command as DjangoTest

from better_test.database import read_database
from better_test.database import simple_weighted_partition
from better_test.database import write_database

QUEUE = None


def suite_to_labels(suite):
    """
    Transform a unittest.TestSuite to a list of test labels that can be used
    by django.test.DiscoveryRunner.run_tests.
    """
    return [
        '{}.{}.{}'.format(
            test.__class__.__module__,
            test.__class__.__name__,
            test._testMethodName
        ) for test in suite._tests
    ]


def multi_processing_runner_factory(stream):
    """
    Creates a test runner with the MultiProcessinTestResult result class and
    overwriting the output stream.
    """
    def inner(*args, **kwargs):
        args = list(args)
        if len(args) > 0:
            args[0] = stream
        else:
            kwargs['stream'] = stream
        if len(args) > 5:
            args[5] = MultiProcessingTestResult
        else:
            kwargs['resultclass'] = MultiProcessingTestResult
        return unittest.TextTestRunner(*args, **kwargs)
    return inner


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


def run_tests(labels, runner_class, runner_options):
    """
    Test runner inside the task process.
    """
    try:
        with null_stdout() as nullout:
            real_runner_class = type(
                runner_class.__name__,
                (MultiProcessingTestRunner, runner_class),
                {'test_runner': multi_processing_runner_factory(nullout)}
            )
            runner = real_runner_class(**runner_options)
            runner.run_tests(labels)
    except:
        import traceback
        traceback.print_exc()
        raise


def init_task(result_queue):
    """
    Initialize task process. multiprocessing.Value and multiprocessing.Queue
    can't be sent via multiprocssing.Pool.apply_async, so have to be
    initialized by this (as globals unfortunately).
    """
    global QUEUE
    QUEUE = result_queue


def wait_for_tests_to_finish(real_result, async_results, results_queue):
    """
    Waits for all tasks to finish by checking if task_counter is zero. Whenever
    a task (run_tests) finishes, it decrements the counter.

    While waiting, it pulls results out of the results queue and feeds them
    into the real result.
    """
    def handle(result):
        method_name, args = result
        arglist = list(args)
        test_info = arglist.pop(0)
        fake_test = FakeTest.deserialize(test_info)
        method = getattr(real_result, method_name)
        method(fake_test, *arglist)

    def get_remaining_results():
        return filter(
            lambda result: not result.ready(), async_results
        )

    remaining_results = get_remaining_results()
    while any(remaining_results):
        remaining_results = get_remaining_results()
        try:
            handle(results_queue.get_nowait())
        except queue.Empty:
            continue
    while not results_queue.empty():
        handle(results_queue.get_nowait())


def serialize(test):
    return (
        '{}.{}.{}'.format(
            test.__class__.__module__,
            test.__class__.__name__,
            test._testMethodName,
        ),
        str(test),
        test.shortDescription()
    )


class Command(DjangoTest):
    option_list = DjangoTest.option_list + (
        make_option('--parallel',
            action='store_true', dest='parallel', default=False,
            help='Run tests in parallel.'),
        make_option('--isolate',
            action='store_true', dest='isolate', default=False,
            help='Run each test isolated.'),
        make_option('--retest',
            action='store_true', dest='retest', default=False,
            help='Re-run tests that failed the last time.'),
        make_option('--list-slow',
            type=int, dest='list_slow', default=0,
            help='Amount of slow tests to print.'),
    )

    def handle(self, *test_labels, **options):
        from django.conf import settings
        from django.test.utils import get_runner

        # load test runner class
        TestRunner = get_runner(settings, options.get('testrunner'))

        options['verbosity'] = int(options.get('verbosity'))

        if options.get('liveserver') is not None:
            os.environ['DJANGO_LIVE_TEST_SERVER_ADDRESS'] = options['liveserver']
            del options['liveserver']

        # Get the test runner instance, this won't actually be used to run
        # anything, but rather builds the suite so we can get a list of test
        # labels to run
        test_runner = TestRunner(**options)

        suite = test_runner.build_suite(test_labels)

        all_test_labels = suite_to_labels(suite)

        # If there's nothing to run, let Django handle it.
        if not all_test_labels:
            return super(Command, self).handle(*test_labels, **options)

        database = read_database()

        if options['retest']:
            all_test_labels = [
                label for label in all_test_labels
                if label in database.get('failed', all_test_labels)
            ]

        if options['isolate']:
            # Isolate means one test (label) per task process.
            chunks = [
                [label] for label in all_test_labels
            ]
        elif options['parallel']:
            # Try to distribute the test labels equally across the available
            # CPU cores
            chunk_count = multiprocessing.cpu_count()
            weighted_chunks = [
                (database.get('timings', {}).get(label, 0), label)
                for label in all_test_labels
            ]
            # Try to split the tests into chunks of equal time, not equal size
            chunks = simple_weighted_partition(weighted_chunks, chunk_count)

            # filter empty chunks
            chunks = list(filter(bool, chunks))
        else:
            chunks = [all_test_labels]

        # Initialize shared values
        results_queue = multiprocessing.Queue()

        # Initialize pool
        pool = multiprocessing.Pool(
            initializer=init_task,
            initargs=(results_queue,)
        )

        start_time = time.time()

        # Send tasks to pool
        async_results = []
        for chunk in chunks:
            async_results.append(pool.apply_async(
                run_tests,
                (chunk, TestRunner, options)
            ))

        # Get an actual result class we can use
        pseudo_runner = unittest.TextTestRunner(
            resultclass=MultiProcessingTextTestResult
        )
        real_result = pseudo_runner._makeResult()

        # Wait for results to come in
        wait_for_tests_to_finish(real_result, async_results, results_queue)

        # Stop all tasks
        pool.close()
        pool.join()

        end_time = time.time()

        # Report result, this is mostly taken from TextTestRunner.run
        test_count = len(all_test_labels)
        time_taken = end_time - start_time

        real_result.printErrors()
        real_result.stream.writeln(real_result.separator2)
        real_result.stream.writeln("Ran {} test{} in {:.3f}s".format(
            test_count, test_count != 1 and "s" or "", time_taken
        ))
        real_result.stream.writeln()

        infos = []
        skipped = len(real_result.skipped)
        expected_fails = len(real_result.expectedFailures)
        unexpected_successes = len(real_result.unexpectedSuccesses)
        if not real_result.wasSuccessful():
            real_result.stream.write("FAILED")
            failed = len(real_result.failures)
            errored = len(real_result.errors)
            if failed:
                infos.append("failures=%d" % failed)
            if errored:
                infos.append("errors=%d" % errored)
        else:
            real_result.stream.write("OK")
        if skipped:
            infos.append("skipped=%d" % skipped)
        if expected_fails:
            infos.append("expected failures=%d" % expected_fails)
        if unexpected_successes:
            infos.append("unexpected successes=%d" % unexpected_successes)
        if infos:
            real_result.stream.writeln(" (%s)" % (", ".join(infos),))
        else:
            real_result.stream.write("\n")

        # record timings to database
        data = {
            'timings': database.get('timings', {}),
        }
        for test, timing in real_result.timings.items():
            data['timings'][test] = timing

        data['failed'] = [
            test.qualname for test, _ in itertools.chain(
                real_result.failures,
                real_result.errors,
                [(test, None) for test in real_result.unexpectedSuccesses]
            )
        ]

        write_database(data)

        if options['list_slow']:
            real_result.stream.writeln("Slowest tests:")
            slowest = sorted(
                ((timing, test) for test, timing in data['timings'].items()),
                reverse=True
            )
            for timing, test in slowest[:options['list_slow']]:
                real_result.stream.writeln(" %.3fs: %s" % (timing, test))

        return_code = len(real_result.failures) + len(real_result.errors)
        sys.exit(return_code)


class MultiProcessingTextTestResult(unittest.TextTestResult):
    """
    Thin wrapper around TextTestResult. Python tracebacks are not pickleable,
    so _exc_info_to_string is handled in MultiProcessingTestResult and the
    result sent to this as `err`.
    """
    def __init__(self, *args, **kwargs):
        super(MultiProcessingTextTestResult, self).__init__(*args, **kwargs)
        self.timings = {}

    def registerTiming(self, test, timing):
        self.timings[test.qualname] = timing

    def _exc_info_to_string(self, err, test):
        return err


class MultiProcessingTestResult(unittest.TestResult):
    """
    Result class for used by the task processes. Instead of printing/storing
    any information, feeds results into QUEUE.

    Important to note is that `test` is transformed into a tuple of
    `(str(test), test.shortDescription())` as test case instances are not
    pickleable. Also note that exceptions are transformed to strings in the
    task as they're not picklable.
    """
    def __init__(self, *args, **kwargs):
        super(MultiProcessingTestResult, self).__init__(*args, **kwargs)
        self._timings = {}

    def printErrors(self):
        pass

    def startTest(self, test):
        self._timings[test] = time.time()

    def _setupStdout(self):
        pass

    def startTestRun(self):
        pass

    def stopTest(self, test):
        QUEUE.put((
            'registerTiming', (
                serialize(test),
                time.time() - self._timings[test],
            )
        ))

    def _restoreStdout(self):
        pass

    def stopTestRun(self):
        pass

    def addError(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addError', (
                serialize(test),
                safe_err
            )
        ))

    def addFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addFailure', (
                serialize(test),
                safe_err
            )
        ))

    def addSuccess(self, test):
        QUEUE.put((
            'addSuccess', (
                serialize(test),
            )
        ))

    def addSkip(self, test, reason):
        QUEUE.put((
            'addSkip', (
                serialize(test),
            )
        ))

    def addExpectedFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addExpectedFailure', (
                serialize(test),
                safe_err
            )
        ))

    def addUnexpectedSuccess(self, test):
        QUEUE.put((
            'addUnexpectedSuccess', (
                serialize(test),
            )
        ))

    def wasSuccessful(self):
        pass


class FakeTest(object):
    """
    Object faking to be a test case. All the test runner/result need are
    __str__ and shortDescription, so that's all that is provided.
    """
    def __init__(self, qualname, name, description):
        self.qualname = qualname
        self.name = name
        self.description = description

    @classmethod
    def deserialize(cls, data):
        return cls(*data)

    def __str__(self):
        return self.name

    def shortDescription(self):
        return self.description


class MultiProcessingTestRunner(object):
    test_runner = unittest.TextTestRunner

    def run_suite(self, suite, **kwargs):
        """
        Backport from Django 1.7
        """
        return self.test_runner(
            verbosity=self.verbosity,
            failfast=self.failfast,
        ).run(suite)
