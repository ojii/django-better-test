from __future__ import absolute_import

from ..compat import unittest


class Tests(unittest.TestCase):
    def test_segfault(self):
        from segfault import segfault
        segfault()
