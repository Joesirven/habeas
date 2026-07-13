from habeas_cli.sqlguard import UnsafeSqlError, assert_select_only


def test_assert_select_only_allows_select():
    assert assert_select_only("SELECT 1") == "SELECT 1"


def test_assert_select_only_rejects_insert():
    try:
        assert_select_only("INSERT INTO requests DEFAULT VALUES")
        raise AssertionError("expected UnsafeSqlError")
    except UnsafeSqlError:
        pass
