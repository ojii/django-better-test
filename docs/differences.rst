#############################################
Differences to Django's built-in test command
#############################################

Differences
***********

* By default, migrations are not run, speeding up the tests. Use :ref:`migrate`
  to run migrations.
* In :ref:`parallel` or :ref:`isolate` mode, for non-sqlite3 in-memory
  databases, better-test appends ``_<number>`` to the database name, where
  ``<number>`` is a positive, non-zero integer.
* Tests are always run in a subprocess, which can cause problems with 3rd party
  tools such as `coverage.py`_, see :ref:`coverage`.
* Tests are not run in the same order as the normal test command runs them,
  especially in :ref:`parallel` mode.


Common Problems
***************


Tests fail with better-test but pass without it
===============================================

The number one reason for this is tests that depend on other tests leaking
state. While bugs in better-test cannot be ruled out, usually if tests fail
under better-test but pass without it, the issue is in the test suite being
run. Use :ref:`isolate` mode to find tests that depend on external state.


.. _coverage:

coverage.py reporting very low coverage
=======================================

Since tests are run in a subprocess, `coverage.py`_ will not report the correct
coverage by default. To get the correct coverage, run `coverage.py`_ with the
``--parallel-mode`` flag and use ``coverage combine`` after running the tests.


.. _coverage.py: http://nedbatchelder.com/code/coverage/
