from better_test.compat import unittest

from better_test import core
from better_test.parallel import SilentMultiProcessingTextTestResult
from better_test.utils import get_test_runner


class IsolationTests(unittest.TestCase):
    def test_state_isolation(self):
        result = core.run(
            ['better_test.harness.isolate.IsolateTests'],
            {},
            core.Config(
                test_runner_class=get_test_runner(),
                mode=core.ISOLATED,
                timings={},
                processes=1,
                debug=True
            ),
            real_result_class=SilentMultiProcessingTextTestResult
        )
        self.assertTrue(result.success)
        self.assertEqual(len(result.successes), 2)

    def test_state_leak(self):
        result = core.run(
            ['better_test.harness.isolate.IsolateTests'],
            {},
            core.Config(
                test_runner_class=get_test_runner(),
                mode=core.STANDARD,
                timings={},
                processes=1,
                debug=True
            ),
            real_result_class=SilentMultiProcessingTextTestResult
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.successes), 1)
        self.assertEqual(len(result.failures), 1)
