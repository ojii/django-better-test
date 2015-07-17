from django.utils import unittest
import time


class Tests(unittest.TestCase):
    def test_success(self):
        time.sleep(1.1)
        self.assertTrue(True)

    def test_fail(self):
        time.sleep(1.2)
        self.assertTrue(False)

    def test_exception(self):
        time.sleep(1.3)
        raise Exception("Test")

    @unittest.expectedFailure
    def test_expected_failure(self):
        time.sleep(1.4)
        self.assertTrue(False)

    @unittest.expectedFailure
    def test_unexpected_success(self):
        time.sleep(1.5)

    def test_skip(self):
        raise unittest.SkipTest("Skipping")
