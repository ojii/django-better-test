##################
django-better-test
##################

A better test command for Django. Allows you to use ``--parallel`` to run tests
in parallel (distributed as evenly as possible across your CPU cores) and
``--isolate`` to run each test in a separate process to detect test that leak
state. You can also quickly re-run the tests failed in the last run using
``--failed``. To show which tests are slowing you down, use
``--list-slow=<number>`` to show the ``<number>`` slowest tests in your test
suite. To simply re-run the tests using the last configuration, use
``--retest``.

Simply add ``better_test`` to your ``INSTALLED_APPS`` and use
``manage.py test --help for all options``.
