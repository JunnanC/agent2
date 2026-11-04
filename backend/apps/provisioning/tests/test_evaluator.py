from apps.provisioning.evaluator import outputs_match, public_report


def test_numeric_comparison_supports_tolerance_and_zero():
    assert outputs_match("1.000001", "1", comparator="numeric")
    assert not outputs_match("1.000001", "1", comparator="numeric", absolute_tolerance=0, relative_tolerance=0)
    assert not outputs_match("NaN", "NaN", comparator="numeric")


def test_hidden_results_are_redacted():
    report = public_report({"status": "FAILED", "results": [
        {"status": "PASSED", "stdout": "ok", "stderr": "", "input": "a"},
        {"status": "FAILED", "stdout": "secret", "stderr": "trace", "expected": "secret"},
    ]}, public_count=1)
    assert report["results"][0]["stdout"] == "ok"
    assert report["results"][1] == {"status": "FAILED", "hidden": True}
