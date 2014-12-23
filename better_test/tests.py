from django.utils import unittest
import time


class Tests(unittest.TestCase):
    def test_success(self):
        time.sleep(1)
        self.assertTrue(True)

    def test_fail(self):
        time.sleep(1)
        self.assertTrue(False)

    def test_exception(self):
        time.sleep(1)
        raise Exception("Test")

    @unittest.expectedFailure
    def test_expected_failure(self):
        time.sleep(1)
        self.assertTrue(False)

    @unittest.expectedFailure
    def test_unexpected_success(self):
        time.sleep(1)
