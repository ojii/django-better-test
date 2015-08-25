import unittest

from better_test import core
from better_test.parallel import SilentMultiProcessingTextTestResult
from better_test.utils import get_test_runner


class BasicTests(unittest.TestCase):
    def test_basic(self):
        result = core.run(
            ['better_test.harness.basic.Tests'],
            {},
            core.Config(
                test_runner_class=get_test_runner(),
                mode=core.PARALLEL,
                timings={},
                processes=2,
                debug=True
            ),
            real_result_class=SilentMultiProcessingTextTestResult
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.successes), 1)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.expected_failures), 1)
        self.assertEqual(len(result.unexpected_successes), 1)
        self.assertEqual(len(result.skipped), 2)
