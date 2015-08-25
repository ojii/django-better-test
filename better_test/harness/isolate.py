from better_test.compat import unittest


class IsolateTests(unittest.TestCase):
    state = 1

    def test_one(self):
        IsolateTests.state += 1
        self.assertEqual(IsolateTests.state, 2)

    def test_two(self):
        IsolateTests.state += 1
        self.assertEqual(IsolateTests.state, 2)
