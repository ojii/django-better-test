import time

from django.conf import settings

from better_test.compat import unittest
from better_test.compat import queue
from better_test.compat import PY_26
from better_test.utils import null_stdout
from better_test.utils import serialize


QUEUE = None  # See init_task


def init_task(result_queue):
    """
    Initialize task process. multiprocessing.Value and multiprocessing.Queue
    can't be sent via multiprocssing.Pool.apply_async, so have to be
    initialized by this (as globals unfortunately).
    """
    global QUEUE
    QUEUE = result_queue


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


def executor(labels, runner_class, runner_options, chunk_num):
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

    def run_suite(self, suite, **_):
        """
        Backport from Django 1.7
        """
        return self.test_runner(
            verbosity=self.verbosity,
            failfast=self.failfast,
        ).run(suite)
