import contextlib
import subprocess
import sys
import signal

from better_test.compat import unittest

from better_test import core
from better_test.parallel import SilentMultiProcessingTextTestResult
from better_test.utils import get_test_runner

if sys.platform == 'darwin':
    @contextlib.contextmanager
    def no_report_crash():
        subprocess.check_call([
            'launchctl',
            'unload',
            '-w',
            '/System/Library/LaunchAgents/com.apple.ReportCrash.plist'
        ])
        try:
            yield
        finally:
            subprocess.check_call([
                'launchctl',
                'load',
                '-w',
                '/System/Library/LaunchAgents/com.apple.ReportCrash.plist'
            ])
else:
    @contextlib.contextmanager
    def no_report_crash():
        yield


class TestCrashingExecutors(unittest.TestCase):
    def test_segfault(self):
        with no_report_crash():
            result = core.run(
                ['better_test.harness.crash.Tests.test_segfault'],
                {},
                core.Config(
                    test_runner_class=get_test_runner(),
                    mode=core.PARALLEL,
                    timings={},
                    processes=1,
                    debug=True
                ),
                real_result_class=SilentMultiProcessingTextTestResult
            )
        self.assertFalse(result.success)
        self.assertEqual(len(result.failed_executors), 1)
        _, exit_code = result.failed_executors[0]
        if sys.platform == 'linux':
            self.assertEqual(exit_code, -signal.SIGSEGV)
        elif sys.platform == 'darwin':
            self.assertEqual(exit_code, -signal.SIGILL)
        elif sys.platform == 'win32':
            self.assertEqual(exit_code, 3221225477)

