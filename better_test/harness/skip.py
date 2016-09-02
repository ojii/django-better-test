from __future__ import absolute_import

from ..compat import unittest


class SkipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise unittest.SkipTest("Skipping Class")

    def test_method(self):
        pass

