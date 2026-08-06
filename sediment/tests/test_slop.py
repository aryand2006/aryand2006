import textwrap

from sediment.slop import analyze_slop


def kinds(source: str) -> list[str]:
    return [f.kind for f in analyze_slop("t.py", textwrap.dedent(source))]


def test_bare_except_with_pass_is_error_masking():
    assert "error_masking" in kinds(
        """
        def f():
            try:
                g()
            except:
                pass
        """
    )


def test_broad_except_that_only_logs_is_error_masking():
    assert "error_masking" in kinds(
        """
        def f():
            try:
                g()
            except Exception as e:
                logger.error(e)
        """
    )


def test_handled_exception_is_not_flagged():
    assert "error_masking" not in kinds(
        """
        def f():
            try:
                return g()
            except ValueError:
                return fallback()
        """
    )


def test_raise_without_from_inside_except_is_flagged():
    assert "context_dropping_raise" in kinds(
        """
        def f():
            try:
                g()
            except ValueError:
                raise RuntimeError("boom")
        """
    )


def test_raise_from_is_not_flagged():
    assert "context_dropping_raise" not in kinds(
        """
        def f():
            try:
                g()
            except ValueError as exc:
                raise RuntimeError("boom") from exc
        """
    )


def test_stub_body_is_flagged():
    assert "stub_implementation" in kinds("def f():\n    pass\n")
    assert "stub_implementation" in kinds("def f():\n    ...\n")
    assert "stub_implementation" in kinds(
        "def f():\n    raise NotImplementedError\n"
    )


def test_abstract_and_protocol_stubs_are_not_flagged():
    assert "stub_implementation" not in kinds(
        """
        from abc import ABC, abstractmethod

        class C(ABC):
            @abstractmethod
            def m(self):
                ...
        """
    )
    assert "stub_implementation" not in kinds(
        """
        from typing import Protocol

        class P(Protocol):
            def m(self) -> int:
                ...
        """
    )


def test_mutable_defaults_are_flagged():
    assert kinds("def f(a=[]):\n    return a\n").count("mutable_default") == 1
    assert kinds("def f(a={}):\n    return a\n").count("mutable_default") == 1
    assert kinds("def f(a=list()):\n    return a\n").count("mutable_default") == 1
    assert "mutable_default" not in kinds("def f(a=None):\n    return a\n")


def test_unreachable_code_after_return():
    assert "unreachable_code" in kinds(
        """
        def f():
            return 1
            cleanup()
        """
    )


def test_narrating_comment_detected_and_useful_comment_spared():
    assert "narrating_comment" in kinds(
        """
        def f(counter):
            # increment the counter value
            counter = counter + 1
            return counter
        """
    )
    assert "narrating_comment" not in kinds(
        """
        def f(counter):
            # Off-by-one here would double-bill the customer.
            counter = counter + 1
            return counter
        """
    )


def test_repeated_literal_flagged_above_threshold():
    source = "def f():\n" + "".join(
        f"    x{i} = 'application/json'\n" for i in range(5)
    )
    assert "repeated_literal" in kinds(source)


def test_small_and_boring_literals_are_ignored():
    source = "def f():\n" + "".join(f"    x{i} = 1\n" for i in range(8))
    assert "repeated_literal" not in kinds(source)


def test_malformed_source_returns_no_findings():
    assert analyze_slop("bad.py", "def f(") == []
