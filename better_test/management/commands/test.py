from contextlib import contextmanager
from optparse import make_option
import multiprocessing
import os
import sys
import time
import itertools

try:
    import queue
except ImportError:
    import Queue as queue

from django.core.management.commands.test import Command as DjangoTest
from django.conf import settings

from better_test.database import read_database
from better_test.database import simple_weighted_partition
from better_test.database import write_database

PY_26 = sys.version_info[0] == 2 and sys.version_info[1] == 6

if PY_26:
    from django.utils import unittest
    from django.utils.unittest.suite import _ErrorHolder as ErrorHolder
else:
    import unittest
    from unittest.suite import _ErrorHolder as ErrorHolder
try:
    from unittest2.suite import _ErrorHolder as ErrorHolder2
except ImportError:
    ErrorHolder2 = False

if ErrorHolder2:
    ERROR_HOLDER_CLASSES = (ErrorHolder, ErrorHolder2)
else:
    ERROR_HOLDER_CLASSES = (ErrorHolder,)


QUEUE = None  # See init_task


def test_to_dotted(test):
    klass = test.__class__
    name = klass.__name__
    module = klass.__module__
    return '{module}.{name}.{method}'.format(
        module=module,
        name=name,
        method=test._testMethodName
    )


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


def run_tests(labels, runner_class, runner_options, chunk_num):
    """
    Test runner inside the task process.
    """
    # We need to patch the db name in case we're in --parallel or --isolate
    # mode (or any other mode with more than one chunk). But if there's only
    # a single chunk, don't change the db name. Therefore we don't modify the
    # name for the first chunk (chunk_num=0).
    if chunk_num:
        for config in settings.DATABASES.values():
            if config.get('NAME', None) != ':memory:':
                config['NAME'] += '_{num}'.format(num=chunk_num)
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
    """
    Serializes a test (which can either be a TestCase-like or an ErrorHolder)
    for safe transport via a Queue.
    ErrorHolder (if actual test setup failed, not anything during test run) is
    special cased because it's a dynamic class and isn't quite the same as
    normal tests.
    """
    if isinstance(test, ERROR_HOLDER_CLASSES):
        return (
            test.id(),
            str(test),
            test.shortDescription(),
        )
    return (
        test_to_dotted(test),
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
        make_option('--failed',
            action='store_true', dest='failed', default=False,
            help='Re-run tests that failed the last time.'),
        make_option('--list-slow',
            type=int, dest='list_slow', default=0,
            help='Amount of slow tests to print.'),
        make_option('--retest',
            action='store_true', dest='retest', default=False,
            help='Re-run the tests using the last configuration.'),
        make_option('--vanilla',
            action='store_true', dest='vanilla', default=False,
            help='Ignore better test.')
    )

    def handle(self, *test_labels, **options):
        if options['vanilla']:
            return DjangoTest().handle(*test_labels, **options)
        from django.conf import settings
        from django.test.utils import get_runner

        if 'south' in settings.INSTALLED_APPS:
            from south.management.commands import patch_for_test_db_setup
            patch_for_test_db_setup()

        # load test runner class
        TestRunner = get_runner(settings, options.get('testrunner'))

        options['verbosity'] = int(options.get('verbosity'))

        if options.get('liveserver') is not None:
            os.environ['DJANGO_LIVE_TEST_SERVER_ADDRESS'] = options['liveserver']
            del options['liveserver']

        database = read_database()

        # Re-run using last configuration
        if options['retest'] and database.get('last_run', None):
            last_run = database['last_run']
            options['parallel'] = last_run['parallel']
            options['isolate'] = last_run['isolate']
            options['list_slow'] = last_run['list_slow']
            test_labels = last_run['labels']

        # Get the test runner instance, this won't actually be used to run
        # anything, but rather builds the suite so we can get a list of test
        # labels to run
        # interactive is disabled since it doesn't work in multiprocessing
        options['interactive'] = False
        test_runner = TestRunner(**options)

        suite = test_runner.build_suite(test_labels)

        # Get an actual result class we can use
        pseudo_runner = unittest.TextTestRunner(
            resultclass=MultiProcessingTextTestResult
        )
        real_result = pseudo_runner._makeResult()

        all_test_labels = suite_to_labels(suite, real_result)

        # If there's nothing to run, let Django handle it.
        if not all_test_labels:
            return super(Command, self).handle(*test_labels, **options)

        if options['failed']:
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
        for chunk_num, chunk in enumerate(chunks):
            async_results.append(pool.apply_async(
                run_tests,
                (chunk, TestRunner, options, chunk_num)
            ))

        # Wait for results to come in
        wait_for_tests_to_finish(real_result, async_results, results_queue)

        failed_executors = sum(
            0 if result.successful() else 1 for result in async_results
        )

        # Stop all tasks
        pool.close()
        pool.join()

        end_time = time.time()

        # Report result, this is mostly taken from TextTestRunner.run
        time_taken = end_time - start_time

        real_result.printErrors()
        real_result.stream.writeln(real_result.separator2)
        real_result.stream.writeln(
            "Ran {number} test{plural} in {time:.3f}s".format(
                number=real_result.testsRun,
                plural=real_result.testsRun != 1 and "s" or "",
                time=time_taken
            )
        )
        real_result.stream.writeln()

        # Record timings to database
        data = {
            'timings': database.get('timings', {}),
        }
        for test, timing in real_result.timings.items():
            data['timings'][test] = timing

        # Record failed tests to database
        data['failed'] = [
            test.qualname for test, _ in itertools.chain(
                real_result.failures,
                real_result.errors,
                [(test, None) for test in real_result.unexpectedSuccesses]
            )
        ]

        # Record config to database
        data['last_run'] = {
            'isolate': options['isolate'],
            'parallel': options['parallel'],
            'list_slow': options['list_slow'],
            'labels': all_test_labels,
        }

        # Show slowest tests
        if options['list_slow']:
            real_result.stream.writeln("Slowest tests:")
            slowest = sorted(
                ((timing, test) for test, timing in data['timings'].items()),
                reverse=True
            )
            for timing, test in slowest[:options['list_slow']]:
                real_result.stream.writeln(" %.3fs: %s" % (timing, test))
            real_result.stream.writeln()

        # Display info about failures etc
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
        elif failed_executors:
            real_result.stream.write("%d executors failed" % failed_executors)
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

        # Save the database
        write_database(data)

        # For easy integration, returns the number of failed tests as the
        # return code. This means that if all tests passed, 0 is returned,
        # which happens to be the standard return code for "success"
        # Also the number of failed executors is added.
        return_code = sum(map(len, (
            real_result.failures,
            real_result.errors,
            real_result.unexpectedSuccesses,
            real_result.expectedFailures
        ))) + failed_executors
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
        self.successes = []

    @property
    def testsRun(self):
        """
        Usually incremented via startTest, but we don't call that function, so
        we simply introspect all results we have.
        """
        return sum(map(len, (
            self.errors,
            self.failures,
            self.unexpectedSuccesses,
            self.expectedFailures,
            self.successes,
            self.skipped
        )))

    @testsRun.setter
    def testsRun(self, value):
        """
        The super class sets/increments this value in some functions, so for
        simplicity we allow setting it and just discard the value.
        """
        pass

    def registerTiming(self, test, timing):
        self.timings[test.qualname] = timing

    def addSuccess(self, test):
        """
        The default result class doesn't store successes, so we do it ourselves
        """
        super(MultiProcessingTextTestResult, self).addSuccess(test)
        self.successes.append(test)

    def _exc_info_to_string(self, err, test):
        """
        Actual transformation from exception info to string happens in the
        executor, as exceptions can't be transferred through a Queue.
        """
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
    separator1 = '=' * 70
    separator2 = '-' * 70

    def __init__(self, *args, **kwargs):
        if PY_26:
            super(MultiProcessingTestResult, self).__init__()
        else:
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

    def addSkip(self, test, reason=None):
        QUEUE.put((
            'addSkip', (
                serialize(test),
                reason
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
