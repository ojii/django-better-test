import time
import multiprocessing

from django.conf import settings

from better_test.compat import unittest
from better_test.compat import PY_26
from better_test.utils import null_stdout
from better_test.utils import serialize


class Pool(object):
    def __init__(self, real_result, max_processes=multiprocessing.cpu_count()):
        self.real_result = real_result
        self.max_processes = max_processes
        self.processes = []
        self.results = multiprocessing.Queue()
        self.failed_executors = []

    def run(self, chunks, runner_class, runner_options):
        chunk_num = 0
        while chunks:
            while len(self.processes) >= self.max_processes:
                self.handle_results()
            chunk = chunks.pop()
            process = multiprocessing.Process(
                target=executor,
                args=(
                    chunk,
                    runner_class,
                    runner_options,
                    chunk_num,
                    self.results
                )
            )
            process.start()
            self.processes.append((process, chunk))
            chunk_num += 1

        while len(self.processes):
            self.handle_results()

        return self.failed_executors

    def handle_results(self):
        while not self.results.empty():
            result = self.results.get_nowait()
            self.handle_result(result)
        done = []
        for process, chunk in self.processes:
            if not process.is_alive():
                done.append((process, chunk))
                if process.exitcode != 0:
                    self.failed_executors.append((
                        chunk, process.exitcode
                    ))
        for process in done:
            self.processes.remove(process)

    def handle_result(self, result):
        method_name, args = result
        arglist = list(args)
        test_info = arglist.pop(0)
        fake_test = FakeTest.deserialize(test_info)
        method = getattr(self.real_result, method_name)
        method(fake_test, *arglist)


def multi_processing_runner_factory(stream, results):
    """
    Creates a test runner with the MultiProcessinTestResult result class and
    overwriting the output stream.
    """
    test_result_class = type(
        'MultiProcessingTestResult',
        (MultiProcessingTestResult, ),
        {'_results_queue': results}
    )
    
    def inner(*args, **kwargs):
        args = list(args)
        if len(args) > 0:
            args[0] = stream
        else:
            kwargs['stream'] = stream
        if len(args) > 5:
            args[5] = test_result_class
        else:
            kwargs['resultclass'] = test_result_class
        return unittest.TextTestRunner(*args, **kwargs)
    return inner


def executor(labels, runner_class, runner_options, chunk_num, results):
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
                {'test_runner': multi_processing_runner_factory(
                    nullout, results
                )}
            )
            runner = real_runner_class(**runner_options)
            runner.run_tests(labels)
    except:
        import traceback
        traceback.print_exc()
        raise


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


class SilentMultiProcessingTextTestResult(MultiProcessingTextTestResult):
    def __init__(self, *args, **kwargs):
        super(SilentMultiProcessingTextTestResult, self).__init__(
            *args, **kwargs
        )
        self.dots = False
        self.showAll = False


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
        self._results_queue.put((
            'startTest', (
                serialize(test),
            )
        ))

    def _setupStdout(self):
        pass

    def startTestRun(self):
        pass

    def stopTest(self, test):
        self._results_queue.put((
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
        self._results_queue.put((
            'addError', (
                serialize(test),
                safe_err
            )
        ))

    def addFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        self._results_queue.put((
            'addFailure', (
                serialize(test),
                safe_err
            )
        ))

    def addSuccess(self, test):
        self._results_queue.put((
            'addSuccess', (
                serialize(test),
            )
        ))

    def addSkip(self, test, reason=None):
        self._results_queue.put((
            'addSkip', (
                serialize(test),
                reason
            )
        ))

    def addExpectedFailure(self, test, err):
        safe_err = self._exc_info_to_string(err, test)
        self._results_queue.put((
            'addExpectedFailure', (
                serialize(test),
                safe_err
            )
        ))

    def addUnexpectedSuccess(self, test):
        self._results_queue.put((
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
