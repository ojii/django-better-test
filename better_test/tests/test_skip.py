from django.utils import unittest


class SkipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest("Skipping Class")

    def test_method(self):
        pass

