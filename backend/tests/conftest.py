import os

import pytest


def pytest_addoption(parser):
    parser.addoption('--run-live-postgres', action='store_true', default=False,
                     help='Run PostgreSQL integration tests against an explicitly disposable DB')


def pytest_configure(config):
    if config.getoption('--run-live-postgres'):
        if os.environ.get('KATAAI_DISPOSABLE_DB') != '1' or not os.environ.get('TEST_DATABASE_URL'):
            raise pytest.UsageError('--run-live-postgres requires KATAAI_DISPOSABLE_DB=1 and TEST_DATABASE_URL')
    elif config.getoption('-m') == 'live_postgres':
        raise pytest.UsageError('Selecting live_postgres requires --run-live-postgres')


def pytest_collection_modifyitems(config, items):
    if not config.getoption('--run-live-postgres'):
        skip = pytest.mark.skip(reason='requires --run-live-postgres and a disposable PostgreSQL instance')
        for item in items:
            if 'live_postgres' in item.keywords:
                item.add_marker(skip)
