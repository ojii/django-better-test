import sys
import multiprocessing

try:
    import queue
except ImportError:
    import Queue as queue


PY_26 = sys.version_info[0] == 2 and sys.version_info[1] == 6

if PY_26:
    from django.utils import unittest
else:
    import unittest


try:
    get_multiprocessing_context = multiprocessing.get_context
except AttributeError:
    get_multiprocessing_context = lambda method: multiprocessing
