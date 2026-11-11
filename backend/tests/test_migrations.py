import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]


def alembic(*args, url=None):
    env = os.environ.copy()
    env.pop('DATABASE_URL', None)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    if url is not None:
        env['DATABASE_URL'] = url
    return subprocess.run(
        [sys.executable, '-m', 'alembic', *args], cwd=BACKEND,
        env=env, text=True, capture_output=True, check=False,
    )


@pytest.mark.parametrize('url', [None, '', 'sqlite:///test.db', 'postgresql://user:secret@/db',
                                  'postgresql://user:secret@localhost/',
                                  'postgresql://user:secret@localhost/db?host=evil',
                                  'postgresql://user:secret@/db?host=/tmp/sock&port=999999',
                                  'postgresql://user:secret@/db?host=/tmp/sock&port=123&port=124'])
def test_migration_refuses_missing_or_invalid_url_without_secrets(url):
    result = alembic('upgrade', 'head', '--sql', url=url)
    assert result.returncode != 0
    assert 'secret' not in result.stdout + result.stderr
    assert 'DATABASE_URL' in result.stderr


def test_invalid_url_never_echoes_unique_password():
    from uuid import uuid4

    sentinel = 'nonreal_pw_' + uuid4().hex
    url = f'postgresql://user:{sentinel}@localhost/'  # Missing database.
    assert sentinel in url
    result = alembic('upgrade', 'head', '--sql', url=url)
    assert result.returncode != 0
    assert 'DATABASE_URL' in result.stderr
    assert sentinel not in result.stdout + result.stderr


def test_offline_sql_contains_dataset_metadata_constraints():
    result = alembic('upgrade', 'head', '--sql',
                     url='postgresql+psycopg://user:secret@localhost/testdb')
    assert result.returncode == 0, result.stderr
    assert 'CREATE TABLE datasets' in result.stdout
    assert 'storage_key' in result.stdout
    assert 'display_name' in result.stdout
    assert 'created_at' in result.stdout
    assert 'lifecycle' in result.stdout
    assert 'CHECK' in result.stdout
    assert 'secret' not in result.stdout + result.stderr


@pytest.mark.parametrize('name', ['PGHOSTADDR', 'PGSERVICE', 'PGOPTIONS', 'PGSSLMODE', 'PGPASSWORD', 'PGUNKNOWN'])
@pytest.mark.parametrize('value', ['sensitive-sentinel', ''])
def test_migration_rejects_inherited_pg_environment_without_exposing_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    result = alembic('upgrade', 'head', url='postgresql://user:url-secret@localhost/testdb')
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert 'PG' in output
    assert 'sensitive-sentinel' not in output
    assert 'url-secret' not in output


def test_live_connection_rejects_inherited_pg_environment_without_exposing_values(monkeypatch):
    env = os.environ.copy()
    env.update(PGHOSTADDR='sensitive-sentinel', KATAAI_DISPOSABLE_DB='1',
               TEST_DATABASE_URL='postgresql://user:url-secret@localhost/testdb')
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-m', 'live_postgres',
                             '--run-live-postgres'], cwd=BACKEND, env=env,
                            text=True, capture_output=True, check=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert 'PG' in output
    assert 'sensitive-sentinel' not in output
    assert 'url-secret' not in output


def test_database_url_accepts_explicit_private_unix_socket():
    from app.database_config import database_url

    url = database_url('postgresql+psycopg://tester@/disposable?host=/tmp/private/socket&port=55432')
    assert url.database == 'disposable'
    assert url.query['host'] == '/tmp/private/socket'
    assert url.query['port'] == '55432'


def test_live_suite_requires_explicit_guard_and_url():
    env = os.environ.copy()
    for name in ('TEST_DATABASE_URL', 'DATABASE_URL', 'KATAAI_DISPOSABLE_DB', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-m', 'live_postgres',
                             '--run-live-postgres'], cwd=BACKEND, env=env,
                            text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert 'KATAAI_DISPOSABLE_DB=1' in result.stderr
