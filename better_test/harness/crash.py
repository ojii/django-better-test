from better_test.compat import unittest


class Tests(unittest.TestCase):
    def test_segfault(self):
        from segfault import segfault
        segfault()