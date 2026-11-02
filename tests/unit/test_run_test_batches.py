"""The batch runner: splitting, telling network failures from real ones, and reading results."""

from scripts.run_test_batches import is_network_failure, plan, read_junit, render, split_batches


def test_batches_stay_near_the_limit_and_keep_every_file_once():
    weights = {f"t{i:02d}.py": 30 for i in range(10)}
    batches = split_batches(weights, limit=100)
    assert all(len(b) <= 3 for b in batches)
    assert sorted(f for b in batches for f in b) == sorted(weights)


def test_a_file_bigger_than_the_limit_keeps_a_batch_of_its_own():
    batches = split_batches({"a.py": 10, "big.py": 500, "c.py": 10}, limit=100)
    assert ["big.py"] in batches


def test_the_plan_covers_every_database_test_file_once():
    files = [f for name, group in plan().items() if name != "unit" for f in group]
    assert len(files) == len(set(files))
    assert "tests/integration/test_engine_db.py" in files
    assert plan()["unit"] == ["tests/unit"]


def test_network_failures_are_told_apart_from_real_ones():
    assert is_network_failure("OperationalError: failed to resolve host 'x'")
    assert is_network_failure("consuming input failed: server closed the connection")
    assert not is_network_failure("AssertionError: assert 'escalated' == 'resolved'")


def _junit(tmp_path, cases):
    path = tmp_path / "r.xml"
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", "utf-8")
    return path


def test_results_count_and_hide_connection_details(tmp_path):
    cases = (
        '<testcase classname="tests.unit.test_a" name="ok"/>'
        '<testcase classname="tests.unit.test_a" name="no"><skipped/></testcase>'
        '<testcase classname="tests.unit.test_b" name="bad">'
        '<failure message="failed to resolve host ep-x.c-2.neon.tech"/></testcase>'
    )
    result = read_junit(_junit(tmp_path, cases))
    assert (result["passed"], result["skipped"], result["failed"]) == (1, 1, 1)
    assert result["network_only"] is True
    assert result["failures"][0]["file"] == "tests/unit/test_b.py"
    assert "neon.tech" not in result["failures"][0]["reason"]


def test_one_real_failure_means_the_batch_is_not_network_only(tmp_path):
    cases = (
        '<testcase classname="t.a" name="x"><failure message="server closed the connection"/>'
        '</testcase><testcase classname="t.a" name="y"><failure message="assert 1 == 2"/>'
        "</testcase>"
    )
    assert read_junit(_junit(tmp_path, cases))["network_only"] is False


def test_a_missing_result_file_counts_as_nothing_ran(tmp_path):
    result = read_junit(tmp_path / "none.xml")
    assert result["passed"] + result["failed"] + result["skipped"] == 0


def test_the_status_page_lists_batches_and_failures():
    state = {
        "commit": "abc",
        "batches": {
            "unit": {"status": "passed", "passed": 5, "failed": 0, "skipped": 1, "seconds": 60},
            "chaos-01": {"status": "failed", "passed": 1, "failed": 1, "skipped": 0,
                         "failures": [{"file": "f.py", "test": "t", "reason": "boom"}]},
        },
    }  # fmt: skip
    text = render(state, {"unit": [], "chaos-01": [], "integration-01": []})
    assert "Batches finished: 2 of 3" in text
    assert "| integration-01 | waiting |" in text
    assert "boom" in text
