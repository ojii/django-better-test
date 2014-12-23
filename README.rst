##################
django-better-test
##################

A better test command for Django. Allows you to use ``--parallel`` to run tests
in parallel (distributed as evenly as possible across your CPU cores) and
``--isolate`` to run each test in a separate process to detect test that leak
state.

Simply add ``better_test`` to your ``INSTALLED_APPS`` and use
``manage.py test``.
