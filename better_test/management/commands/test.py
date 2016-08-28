from optparse import make_option
import os
import multiprocessing
import itertools
import sys
import warnings

from django.core.management.commands.test import Command as DjangoTest
from django.conf import settings

from better_test.database import read_database
from better_test.utils import DisableMigrations
from better_test.utils import get_test_runner
from better_test.core import Config
from better_test.core import run
from better_test.core import ISOLATED
from better_test.core import PARALLEL
from better_test.core import STANDARD


SEPARATOR_1 = '=' * 70
SEPARATOR_2 = '-' * 70


def args_builder(factory, parallel=True):
    args = []
    if parallel:
        args.append(factory(
            '--parallel',
            action='store_true', dest='parallel', default=False,
            help='Run tests in parallel.'
        ))
    return args + [
        factory('--isolate',
                action='store_true', dest='isolate', default=False,
                help='Run each test isolated.'),
        factory('--failed',
                action='store_true', dest='failed', default=False,
                help='Re-run tests that failed the last time.'),
        factory('--list-slow',
                type=int, dest='list_slow', default=0,
                help='Amount of slow tests to print.'),
        factory('--retest',
                action='store_true', dest='retest', default=False,
                help='Re-run the tests using the last configuration.'),
        factory('--vanilla',
                action='store_true', dest='vanilla', default=False,
                help='Ignore better test.'),
        factory('--no-migrations',
                action='store_true', dest='no_migrate', default=False,
                help='Do not run migrations'),
        factory('--migrate',
                action='store_true', dest='migrate', default=False,
                help='Run migrations (slow)'),
    ]


class Command(DjangoTest):
    if hasattr(DjangoTest, 'option_list'):
        option_list = DjangoTest.option_list + tuple(args_builder(make_option))

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)
        args_builder(parser.add_argument, False)

    def handle(self, *test_labels, **options):
        from django.conf import settings

        if options['no_migrate']:
            warnings.warn(
                "The --no-migrations flag is deprecated. Migrations are "
                "skipped by default now, to use them, use --migrate.",
                DeprecationWarning
            )
            options['migrate'] = False

        if not options.pop('migrate'):
            settings.MIGRATION_MODULES = DisableMigrations()

        if options['vanilla']:
            return DjangoTest().handle(*test_labels, **options)
        else:
            database = read_database()
            test_runner_options = get_test_runner_options(options)
            test_labels, config = get_config(database, options, test_labels)
            patch_settings(options)
            result = run(test_labels, test_runner_options, config)
            display_result(self.stdout, result)
            if options['list_slow']:
                list_slow(self.stdout, result, options['list_slow'])
            save_result(result, database, options)
            sys.exit(result.total_failures)


def get_test_runner_options(options):
    """
    Build the options for the test runner class.
    """
    test_runner_options = dict(options.items())
    del test_runner_options['parallel']
    test_runner_options['verbosity'] = int(test_runner_options['verbosity'])
    test_runner_options['interactive'] = False
    return test_runner_options


def get_config(database, options, test_labels):
    """
    Turn the command options (and database info) into a Config object to be
    used by core.run.
    """
    test_runner = get_test_runner(options.get('testrunner'))

    if options['retest'] and database.get('last_run', None):
        last_run = database['last_run']
        if last_run['isolate']:
            mode = ISOLATED
        elif last_run['parallel']:
            mode = PARALLEL
        else:
            mode = STANDARD
        test_labels = last_run['labels']
    else:
        if options['isolate']:
            mode = ISOLATED
        elif options['parallel']:
            mode = PARALLEL
        else:
            mode = STANDARD

    return test_labels, Config(
        test_runner_class=test_runner,
        mode=mode,
        timings=database.get('timings', {}),
        processes=multiprocessing.cpu_count(),
        verbosity=int(options['verbosity']),
    )


def patch_settings(options):
    """
    Patch Django settings/environment.
    """
    if 'south' in settings.INSTALLED_APPS:
        from south.management.commands import patch_for_test_db_setup
        patch_for_test_db_setup()

    if options.get('liveserver') is not None:
        os.environ['DJANGO_LIVE_TEST_SERVER_ADDRESS'] = options['liveserver']


def _get_description(test):
    doc_first_line = test.shortDescription()
    if doc_first_line:
        return '\n'.join((str(test), doc_first_line))
    else:
        return str(test)


def _write_error_list(flavor, errors, writeln):
    for test, err in errors:
        writeln(SEPARATOR_1)
        writeln(
            '{flavor}: {description}'.format(
                flavor=flavor,
                description=_get_description(test)
            )
        )
        writeln(SEPARATOR_2)
        writeln(str(err))


def display_result(stream, result):
    """
    Write the result to the stream, mimicking unittest.
    """
    writeln = lambda s: stream.write('{0}\n'.format(s))
    writeln('')  # newline after the "dots"
    _write_error_list('ERROR', result.errors, writeln)
    _write_error_list('FAIL', result.failures, writeln)
    for chunk, exit_code in result.failed_executors:
        writeln(SEPARATOR_1)
        writeln('FAILED EXECUTOR: {exit_code}'.format(exit_code=exit_code))
        writeln(SEPARATOR_2)
        writeln(str(chunk))
    writeln(SEPARATOR_2)
    writeln(
        "Ran {number} test{plural} in {time:.3f}s".format(
            number=result.tests_run,
            plural=result.tests_run != 1 and "s" or "",
            time=result.time_taken
        )
    )
    writeln('')

    # Display info about failures etc
    infos = []
    skipped = len(result.skipped)
    expected_fails = len(result.expected_failures)
    unexpected_successes = len(result.unexpected_successes)
    failed_executors = len(result.failed_executors)
    if not result.success:
        stream.write("FAILED")
        failed = len(result.failures)
        errored = len(result.errors)
        if failed:
            infos.append("failures={failed}".format(failed=failed))
        if errored:
            infos.append("errors={errors}".format(errors=errored))
    elif result.failed_executors:
        stream.write("executors failed={failed_executors}".format(
            failed_executors=failed_executors
        ))
    else:
        stream.write("OK")
    if skipped:
        infos.append("skipped={skipped}".format(skipped=skipped))
    if expected_fails:
        infos.append("expected failures={expected_failures}".format(
            expected_failures=expected_fails
        ))
    if unexpected_successes:
        infos.append("unexpected successes={unexpected_successes}".format(
            unexpected_successes=unexpected_successes
        ))
    if infos:
        writeln(" ({info})".format(info=", ".join(infos)))
    else:
        writeln('')


def list_slow(stream, result, num):
    """
    List the `num` slowest tests.
    """
    writeln = lambda s: stream.write('{0}\n'.format(s))
    writeln("Slowest tests:")
    slowest = sorted(
        ((timing, test) for test, timing in result.timings.items()),
        reverse=True
    )
    for timing, test in slowest[:num]:
        writeln(" {timing:.3f}s: {test}".format(timing=timing, test=test))
    writeln('')


def save_result(result, database, options):
    """
    Persist the result and the options to the database.
    """
    # Record timings to database
    data = {
        'timings': database.get('timings', {}),
    }
    for test, timing in result.timings.items():
        data['timings'][test] = timing

    # Record failed tests to database
    data['failed'] = [
        test.qualname for test, _ in itertools.chain(
            result.failures,
            result.errors,
            [(test, None) for test in result.unexpected_successes]
        )
    ]

    # Record config to database
    data['last_run'] = {
        'isolate': options['isolate'],
        'parallel': options['parallel'],
        'list_slow': options['list_slow'],
        'labels': result.test_labels,
    }
