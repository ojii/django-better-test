from better_test.compat import unittest


class Tests(unittest.TestCase):
    def test_success(self):
        self.assertTrue(True)

    def test_fail(self):
        self.assertTrue(False)

    def test_exception(self):
        raise Exception("Test")

    @unittest.expectedFailure
    def test_expected_failure(self):
        self.assertTrue(False)

    @unittest.expectedFailure
    def test_unexpected_success(self):
        self.assertTrue(True)

    def test_skip(self):
        raise unittest.SkipTest("Skipping (exc)")

    @unittest.skip("Skipping (deco)")
    def test_skip_deco(self):
        self.assertTrue(False)
