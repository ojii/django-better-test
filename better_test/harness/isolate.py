from __future__ import absolute_import

from ..compat import unittest


class IsolateTests(unittest.TestCase):
    state = 0

    def test_one(self):
        IsolateTests.state += 2
        self.assertEqual(IsolateTests.state, 2)

    def test_two(self):
        IsolateTests.state += 20
        self.assertEqual(IsolateTests.state, 20)
