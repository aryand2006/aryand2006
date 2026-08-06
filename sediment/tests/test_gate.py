"""End-to-end tests: build throwaway git repos and gate real commits."""

import subprocess
import textwrap

import pytest

from sediment import gitio
from sediment.analyze import snapshot_at_ref
from sediment.cli import main
from sediment.score import check_ratchet, compare, load_baseline, save_baseline

CLEAN = '''
def total(items):
    """Sum the price of every item."""
    return sum(item.price for item in items)
'''

ERODED = '''
def total(items, discount=None, tax=None, region=None, currency=None, mode=None):
    """Sum the price of every item."""
    result = 0
    for item in items:
        if item is not None:
            if item.price is not None:
                if item.price > 0:
                    if region is not None:
                        if region == "us":
                            result += item.price * 1.07
                        elif region == "eu":
                            result += item.price * 1.20
                        elif region == "uk":
                            result += item.price * 1.20
                        else:
                            result += item.price
                    else:
                        result += item.price
    try:
        return round(result, 2)
    except Exception:
        pass
'''


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "app.py").write_text(textwrap.dedent(CLEAN).lstrip())
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def gate_report(repo, base="HEAD~1", head="HEAD"):
    base_sha = gitio.resolve(str(repo), base)
    head_sha = gitio.resolve(str(repo), head)
    changes = gitio.changed_files(str(repo), base_sha, head_sha)
    head_paths = [c.path for c in changes if c.status != "D"]
    base_paths = [c.old_path or c.path for c in changes if c.status != "A"]
    before = snapshot_at_ref(str(repo), base_sha, paths=base_paths)
    after = snapshot_at_ref(str(repo), head_sha, paths=head_paths)
    return compare(
        before,
        after,
        touched_files=set(head_paths),
        added_loc=gitio.added_line_count(str(repo), base_sha, head_sha),
    )


def commit(repo, name, content, message="change"):
    (repo / name).write_text(textwrap.dedent(content).lstrip())
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def test_eroding_change_fails_the_gate(repo):
    commit(repo, "app.py", ERODED, "make it worse")
    report = gate_report(repo)

    assert report.net_erosion > 0
    assert report.verdict(max_rate=1.5) == "fail"
    # The nested rewrite is the same unit, so it shows up as worsened.
    assert any(d.key.endswith("::total") for d in report.worsened)
    assert "error_masking" in {f.kind for f in report.new_findings}


def test_reverting_the_change_reads_as_improvement(repo):
    commit(repo, "app.py", ERODED, "worse")
    commit(repo, "app.py", CLEAN, "revert")
    report = gate_report(repo)

    assert report.net_erosion < 0
    assert report.verdict(max_rate=1.5) == "pass"
    assert report.improved


def test_clean_addition_passes(repo):
    commit(
        repo,
        "helpers.py",
        '''
        def slugify(text):
            """Lowercase and hyphenate a title."""
            return "-".join(text.lower().split())
        ''',
        "add helper",
    )
    report = gate_report(repo)
    assert report.debt_added == 0.0
    assert report.verdict(max_rate=1.5) == "pass"


def test_unrelated_files_are_not_billed_to_the_change(repo):
    # Land debt in one file, then make a clean edit to a different file.
    commit(repo, "legacy.py", ERODED, "legacy debt")
    commit(
        repo,
        "clean.py",
        "def ok(a, b):\n    return a + b\n",
        "unrelated clean change",
    )
    report = gate_report(repo)
    assert report.debt_added == 0.0
    assert report.verdict(max_rate=1.5) == "pass"


def test_copy_pasted_function_is_reported_as_new_clone(repo):
    commit(
        repo,
        "app.py",
        """
        def process_orders(orders):
            results = []
            for order in orders:
                if order.total > 100:
                    results.append(order.id)
                elif order.total > 50:
                    results.append(order.ref)
                else:
                    continue
            return results

        def handle_invoices(invoices):
            collected = []
            for invoice in invoices:
                if invoice.amount > 100:
                    collected.append(invoice.key)
                elif invoice.amount > 50:
                    collected.append(invoice.tag)
                else:
                    continue
            return collected
        """,
        "duplicate logic",
    )
    report = gate_report(repo)
    assert report.new_clones
    assert report.new_clones[0].similarity >= 0.8


def test_ratchet_blocks_regrowth_in_a_baselined_file(repo):
    # Record the clean state as the floor.
    snapshot = snapshot_at_ref(str(repo), "HEAD")
    save_baseline(str(repo), snapshot, "HEAD")
    baseline = load_baseline(str(repo))
    assert "app.py" in baseline

    commit(repo, "app.py", ERODED, "regress")
    after = snapshot_at_ref(str(repo), "HEAD", paths=["app.py"])
    violations = check_ratchet(baseline, after, {"app.py"})

    assert "app.py" in violations
    recorded, now = violations["app.py"]
    assert now > recorded


def test_ratchet_ignores_files_absent_from_the_baseline(repo):
    snapshot = snapshot_at_ref(str(repo), "HEAD")
    save_baseline(str(repo), snapshot, "HEAD")
    baseline = load_baseline(str(repo))

    commit(repo, "new.py", ERODED, "new file with debt")
    after = snapshot_at_ref(str(repo), "HEAD", paths=["new.py"])
    assert check_ratchet(baseline, after, {"new.py"}) == {}


def test_erosion_rate_is_normalized_by_change_size(repo):
    commit(repo, "small.py", ERODED, "small eroding change")
    small = gate_report(repo)

    # The same debt inside a much larger clean change should score lower.
    filler = "\n\n".join(f"def clean_{i}(a, b):\n    return a + b" for i in range(200))
    commit(repo, "big.py", ERODED + "\n\n" + filler, "large mostly-clean change")
    big = gate_report(repo)

    assert big.debt_added >= small.debt_added
    assert big.erosion_rate < small.erosion_rate


def test_deleted_file_removing_debt_counts_as_improvement(repo):
    commit(repo, "junk.py", ERODED, "add debt")
    git(repo, "rm", "-q", "junk.py")
    git(repo, "commit", "-qm", "delete it")
    report = gate_report(repo)
    assert report.net_erosion < 0


def test_cli_gate_exit_codes(repo, capsys):
    commit(repo, "app.py", ERODED, "worse")
    assert main(["gate", "--repo", str(repo), "--base", "HEAD~1", "--no-ratchet"]) == 1
    assert "FAIL" in capsys.readouterr().out

    commit(repo, "app.py", CLEAN, "revert")
    assert main(["gate", "--repo", str(repo), "--base", "HEAD~1", "--no-ratchet"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_gate_json_is_machine_readable(repo, capsys):
    import json

    commit(repo, "app.py", ERODED, "worse")
    main(["gate", "--repo", str(repo), "--base", "HEAD~1", "--no-ratchet", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["verdict"] == "fail"
    assert payload["net_erosion"] > 0
    assert payload["new_findings"]


def test_cli_scan_and_ratchet_roundtrip(repo, capsys):
    assert main(["scan", "--repo", str(repo), "--ref", "HEAD"]) == 0
    assert "sediment" in capsys.readouterr().out

    assert main(["ratchet", "--repo", str(repo), "--accept"]) == 0
    assert "baseline written" in capsys.readouterr().out
    assert (repo / ".sediment" / "baseline.json").exists()


def test_cli_trajectory_runs_over_history(repo, capsys):
    commit(repo, "app.py", ERODED, "worse")
    commit(repo, "extra.py", ERODED, "worse again")
    assert main(["trajectory", "--repo", str(repo), "--since", "HEAD~2"]) == 0
    assert "debt density" in capsys.readouterr().out


def test_gate_with_no_python_changes_passes(repo, capsys):
    (repo / "README.md").write_text("# hello\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "docs")
    assert main(["gate", "--repo", str(repo), "--base", "HEAD~1"]) == 0
    assert "no Python files changed" in capsys.readouterr().out


def test_unparseable_file_does_not_crash_the_gate(repo):
    commit(repo, "broken.py", "def f(\n", "add broken file")
    report = gate_report(repo)
    assert report.verdict(max_rate=1.5) in ("pass", "warn", "fail")
