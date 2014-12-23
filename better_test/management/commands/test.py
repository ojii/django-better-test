from contextlib import contextmanager
from optparse import make_option
import multiprocessing
import os
import queue
import unittest
import sys
import time

from django.core.management.commands.test import Command as DjangoTest

COUNTER = None
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
        kwargs['resultclass'] = MultiProcessingTestResult
        kwargs['stream'] = stream
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
            runner = runner_class(**runner_options)
            runner.test_runner = multi_processing_runner_factory(nullout)
            runner.run_tests(labels)
    finally:
        COUNTER.value -= 1


def init_task(task_counter, result_queue):
    """
    Initialize task process. multiprocessing.Value and multiprocessing.Queue
    can't be sent via multiprocssing.Pool.apply_async, so have to be
    initialized by this (as globals unfortunately).
    """
    global COUNTER, QUEUE
    COUNTER = task_counter
    QUEUE = result_queue


def wait_for_tests_to_finish(real_result, task_counter, results_queue):
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
        fake_test = FakeTest(*test_info)
        method = getattr(real_result, method_name)
        method(fake_test, *arglist)
    while task_counter.value != 0:
        try:
            result = results_queue.get_nowait()
        except queue.Empty:
            continue
        handle(result)
    while not results_queue.empty():
        handle(results_queue.get_nowait())


class Command(DjangoTest):
    option_list = DjangoTest.option_list + (
        make_option('--parallel',
            action='store_true', dest='parallel', default=False,
            help='Run tests in parallel.'),
        make_option('--isolate',
            action='store_true', dest='isolate', default=False,
            help='Run each test isolated.'),
    )

    def handle(self, *test_labels, **options):
        # if we're not doing anything fancy, let Django handle this.
        if not any([options['parallel'], options['isolate']]):
            super(Command, self).handle(*test_labels, **options)

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

        if options['isolate']:
            # Isolate means one test (label) per task process.
            chunks = [[label] for label in all_test_labels]
        else:
            # Try to distribute the test labels equally across the available
            # CPU cores
            chunk_count = multiprocessing.cpu_count()
            chunk_size = int(float(len(all_test_labels)) / chunk_count)
            if chunk_size == 0:
                chunk_size = 1
            chunks = [
                all_test_labels[index: index + chunk_size]
                for index in
                range(0, (chunk_count - 1) * chunk_size, chunk_size)
            ]
            chunks.append(all_test_labels[(chunk_count - 1) * chunk_size:])
            if chunk_size == 1:
                chunks = list(filter(bool, chunks))

        # Initialize shared values
        task_count = len(chunks)
        task_counter = multiprocessing.Value('i', task_count)
        results_queue = multiprocessing.Queue()

        # Initialize pool
        pool = multiprocessing.Pool(
            initializer=init_task,
            initargs=(task_counter, results_queue)
        )

        start_time = time.time()

        # Send tasks to pool
        for chunk in chunks:
            pool.apply_async(
                run_tests,
                (chunk, TestRunner, options)
            )

        # Get an actual result class we can use
        pseudo_runner = unittest.TextTestRunner(
            resultclass=MultiProcessingTextTestResult
        )
        real_result = pseudo_runner._makeResult()

        # Wait for results to come in
        wait_for_tests_to_finish(real_result, task_counter, results_queue)

        # Stop all tasks
        pool.close()
        pool.join()

        end_time = time.time()

        # Report result, this is mostly taken from TextTestRunner.run
        test_count = len(all_test_labels)
        time_taken = end_time - start_time # "{:10.4f}".format(x)

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

        return_code = len(real_result.failures) + len(real_result.errors)
        sys.exit(return_code)


class MultiProcessingTextTestResult(unittest.TextTestResult):
    """
    Thin wrapper around TextTestResult. Python tracebacks are not pickleable,
    so _exc_info_to_string is handled in MultiProcessingTestResult and the
    result sent to this as `err`.
    """
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
    def printErrors(self):
        pass

    def startTest(self, test):
        pass

    def _setupStdout(self):
        pass

    def startTestRun(self):
        pass

    def stopTest(self, test):
        pass

    def _restoreStdout(self):
        pass

    def stopTestRun(self):
        pass

    def addError(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addError', (
                (str(test), test.shortDescription()),
                safe_err
            )
        ))

    def addFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addFailure', (
                (str(test), test.shortDescription()),
                safe_err
            )
        ))

    def addSuccess(self, test):
        QUEUE.put((
            'addSuccess', (
                (str(test), test.shortDescription()),
            )
        ))

    def addSkip(self, test, reason):
        QUEUE.put((
            'addSkip', (
                (str(test), test.shortDescription()),
            )
        ))

    def addExpectedFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        QUEUE.put((
            'addExpectedFailure', (
                (str(test), test.shortDescription()),
                safe_err
            )
        ))

    def addUnexpectedSuccess(self, test):
        QUEUE.put((
            'addUnexpectedSuccess', (
                (str(test), test.shortDescription()),
            )
        ))

    def wasSuccessful(self):
        pass


class FakeTest(object):
    """
    Object faking to be a test case. All the test runner/result need are
    __str__ and shortDescription, so that's all that is provided.
    """
    def __init__(self, name, description):
        self.name = name
        self.description = description

    def __str__(self):
        return self.name

    def shortDescription(self):
        return self.description