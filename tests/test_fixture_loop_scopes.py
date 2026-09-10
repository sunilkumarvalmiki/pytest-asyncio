from __future__ import annotations

from textwrap import dedent

import pytest
from pytest import Pytester


@pytest.mark.parametrize(
    "fixture_scope", ("session", "package", "module", "class", "function")
)
def test_loop_scope_session_is_independent_of_fixture_scope(
    pytester: Pytester,
    fixture_scope: str,
):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function")
    pytester.makepyfile(dedent(f"""\
            import asyncio
            import pytest
            import pytest_asyncio

            loop: asyncio.AbstractEventLoop = None

            @pytest_asyncio.fixture(scope="{fixture_scope}", loop_scope="session")
            async def fixture():
                global loop
                loop = asyncio.get_running_loop()

            @pytest.mark.asyncio(loop_scope="session")
            async def test_runs_in_same_loop_as_fixture(fixture):
                global loop
                assert loop == asyncio.get_running_loop()
            """))
    result = pytester.runpytest("--asyncio-mode=strict")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("default_loop_scope", ("function", "module", "session"))
def test_default_loop_scope_config_option_changes_fixture_loop_scope(
    pytester: Pytester,
    default_loop_scope: str,
):
    pytester.makeini(dedent(f"""\
            [pytest]
            asyncio_default_fixture_loop_scope = {default_loop_scope}
            """))
    pytester.makepyfile(dedent(f"""\
            import asyncio
            import pytest
            import pytest_asyncio

            @pytest_asyncio.fixture
            async def fixture_loop():
                return asyncio.get_running_loop()

            @pytest.mark.asyncio(loop_scope="{default_loop_scope}")
            async def test_runs_in_fixture_loop(fixture_loop):
                assert asyncio.get_running_loop() is fixture_loop
            """))
    result = pytester.runpytest("--asyncio-mode=strict")
    result.assert_outcomes(passed=1)


def test_default_class_loop_scope_config_option_changes_fixture_loop_scope(
    pytester: Pytester,
):
    pytester.makeini(dedent("""\
            [pytest]
            asyncio_default_fixture_loop_scope = class
            """))
    pytester.makepyfile(dedent("""\
            import asyncio
            import pytest
            import pytest_asyncio

            class TestClass:
                @pytest_asyncio.fixture
                async def fixture_loop(self):
                    return asyncio.get_running_loop()

                @pytest.mark.asyncio(loop_scope="class")
                async def test_runs_in_fixture_loop(self, fixture_loop):
                    assert asyncio.get_running_loop() is fixture_loop
            """))
    result = pytester.runpytest("--asyncio-mode=strict")
    result.assert_outcomes(passed=1)


def test_default_package_loop_scope_config_option_changes_fixture_loop_scope(
    pytester: Pytester,
):
    pytester.makeini(dedent("""\
            [pytest]
            asyncio_default_fixture_loop_scope = package
            """))
    pytester.makepyfile(
        __init__="",
        test_a=dedent("""\
            import asyncio
            import pytest
            import pytest_asyncio

            @pytest_asyncio.fixture
            async def fixture_loop():
                return asyncio.get_running_loop()

            @pytest.mark.asyncio(loop_scope="package")
            async def test_runs_in_fixture_loop(fixture_loop):
                assert asyncio.get_running_loop() is fixture_loop
            """),
    )
    result = pytester.runpytest("--asyncio-mode=strict")
    result.assert_outcomes(passed=1)


def test_warns_when_fixture_and_test_loop_scopes_differ(pytester: Pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function")
    pytester.makepyfile(dedent("""\
            import pytest
            import pytest_asyncio

            @pytest_asyncio.fixture(loop_scope="session")
            async def fixture():
                pass

            @pytest.mark.asyncio(loop_scope="function")
            async def test_mismatched_loop_scope(fixture):
                pass
            """))
    result = pytester.runpytest(
        "--asyncio-mode=strict", "-W", "default::pytest.PytestWarning"
    )
    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        "*Async fixture 'fixture' with loop_scope='session' is requested by test*"
    )


def test_warns_when_async_fixtures_request_different_loop_scopes(pytester: Pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function")
    pytester.makepyfile(dedent("""\
            import pytest
            import pytest_asyncio

            @pytest_asyncio.fixture(loop_scope="function")
            async def inner_fixture():
                pass

            @pytest_asyncio.fixture(loop_scope="session")
            async def outer_fixture(inner_fixture):
                pass

            @pytest.mark.asyncio(loop_scope="session")
            async def test_mismatched_fixture_scopes(outer_fixture):
                pass
            """))
    result = pytester.runpytest(
        "--asyncio-mode=strict", "-W", "default::pytest.PytestWarning"
    )
    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        "*Async fixture 'inner_fixture' with loop_scope='function' is requested "
        "by fixture 'outer_fixture'*"
    )


@pytest.mark.parametrize("asyncio_mode", ("auto", "strict"))
def test_warns_when_fixture_and_test_loop_scopes_differ_in_auto_mode(
    pytester: Pytester, asyncio_mode: str
):
    """The warning must fire in auto mode too, where the test has no explicit asyncio marker."""
    pytester.makeini(
        f"[pytest]\nasyncio_mode = {asyncio_mode}\nasyncio_default_fixture_loop_scope = function"
    )
    pytester.makepyfile(dedent("""\
            import pytest_asyncio

            @pytest_asyncio.fixture(loop_scope="session")
            async def fixture():
                pass

            async def test_mismatched_loop_scope(fixture):
                pass
            """))
    result = pytester.runpytest(
        "--asyncio-mode", asyncio_mode, "-W", "default::pytest.PytestWarning"
    )
    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        "*Async fixture 'fixture' with loop_scope='session' is requested by test*"
    )


def test_warns_regardless_of_fixture_request_order(pytester: Pytester):
    """The warning must not depend on test order: it fires for every request,
    not just the first one that happens to create the fixture."""
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function"
    )
    pytester.makepyfile(dedent("""\
            import pytest_asyncio

            @pytest_asyncio.fixture(loop_scope="function")
            async def fixture():
                pass

            @pytest.mark.asyncio(loop_scope="session")
            async def test_fixture_is_created_first(fixture):
                pass
            """))
    # First run: the mismatched test is the only request, so the fixture is
    # created (and warned) by it.
    result = pytester.runpytest(
        "--asyncio-mode=auto", "-W", "default::pytest.PytestWarning"
    )
    result.assert_outcomes(passed=1, warnings=1)
    result.stdout.fnmatch_lines(
        "*Async fixture 'fixture' with loop_scope='function' is requested by test*"
    )

    # Second run: a matching test creates the fixture first; the mismatched
    # test then reuses the cached value and must STILL warn.
    pytester.makepyfile(dedent("""\
            import pytest
            import pytest_asyncio

            @pytest_asyncio.fixture(loop_scope="function")
            async def fixture():
                pass

            @pytest.mark.asyncio(loop_scope="function")
            async def test_matching_loop_scope_first(fixture):
                pass

            @pytest.mark.asyncio(loop_scope="session")
            async def test_mismatched_loop_scope(fixture):
                pass
            """))
    result = pytester.runpytest(
        "--asyncio-mode=auto", "-W", "default::pytest.PytestWarning"
    )
    result.assert_outcomes(passed=2, warnings=1)
    result.stdout.fnmatch_lines(
        "*Async fixture 'fixture' with loop_scope='function' is requested by test*"
    )


def test_invalid_default_fixture_loop_scope_raises_error(pytester: Pytester):
    pytester.makeini("""\
        [pytest]
        asyncio_default_fixture_loop_scope = invalid_scope
        """)
    result = pytester.runpytest("--assert=plain")
    result.stderr.fnmatch_lines(
        [
            "ERROR: 'invalid_scope' is not a valid "
            "asyncio_default_fixture_loop_scope. Valid scopes are: "
            "function, class, module, package, session."
        ]
    )
