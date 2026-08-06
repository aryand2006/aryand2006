"""Detectors for structural habits characteristic of machine-authored code.

These are not style opinions. Each one is a pattern that is individually
defensible as a defect or a comprehension cost, and that shows up markedly more
often in generated code than in human-maintained code: error handling that
swallows the error, exceptions that drop their cause, stubs that were never
filled in, comments that restate the line below them, and literals duplicated
instead of named.

Every detector is a pure AST or token-stream check. No model is consulted.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass

# Weight is the debt each finding contributes, on the same scale as the
# structural overage in metrics.py, so one severe finding is comparable to one
# badly over-complex function.
SIGNAL_WEIGHTS = {
    "error_masking": 1.2,
    "context_dropping_raise": 0.8,
    "stub_implementation": 1.0,
    "mutable_default": 1.0,
    "unreachable_code": 0.9,
    "narrating_comment": 0.15,
    "repeated_literal": 0.3,
}

SIGNAL_DESCRIPTIONS = {
    "error_masking": "exception caught and discarded without handling",
    "context_dropping_raise": "raise inside except without `from`, losing the cause",
    "stub_implementation": "function body is a placeholder",
    "mutable_default": "mutable default argument",
    "unreachable_code": "statements after an unconditional exit",
    "narrating_comment": "comment restates the code beneath it",
    "repeated_literal": "same literal repeated instead of being named",
}

# Statements that end control flow unconditionally.
_TERMINALS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    lineno: int
    detail: str

    @property
    def weight(self) -> float:
        return SIGNAL_WEIGHTS.get(self.kind, 0.5)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "lineno": self.lineno,
            "detail": self.detail,
            "weight": self.weight,
        }


def _is_no_op_body(body: list[ast.stmt]) -> bool:
    """True if a block does nothing an observer could detect."""
    meaningful = [s for s in body if not _is_docstring(s)]
    if not meaningful:
        return True
    return all(
        isinstance(s, ast.Pass)
        or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        for s in meaningful
    )


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_stub_body(body: list[ast.stmt]) -> bool:
    """Body is a placeholder: pass, ellipsis, or bare NotImplementedError."""
    meaningful = [s for s in body if not _is_docstring(s)]
    if not meaningful:
        return True
    if len(meaningful) > 1:
        return False
    stmt = meaningful[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        target = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        return isinstance(target, ast.Name) and target.id == "NotImplementedError"
    return False


def _has_decorator(node: ast.AST, names: set[str]) -> bool:
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        label = getattr(target, "attr", None) or getattr(target, "id", None)
        if label in names:
            return True
    return False


class _SlopVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.findings: list[Finding] = []
        self._in_protocol = False

    def _add(self, kind: str, lineno: int, detail: str) -> None:
        self.findings.append(Finding(kind, self.path, lineno, detail))

    # -- error handling ---------------------------------------------------

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        broad = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")
        )
        if _is_no_op_body(node.body):
            label = "bare except" if node.type is None else f"except {getattr(node.type, 'id', '...')}"
            self._add(
                "error_masking",
                node.lineno,
                f"{label} with a body that does nothing",
            )
        elif broad and self._body_only_logs(node.body):
            self._add(
                "error_masking",
                node.lineno,
                "broad except that only logs and continues",
            )

        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Raise) and stmt.exc is not None and stmt.cause is None:
                # `raise` bare re-raises and keeps context; `raise X()` does not.
                self._add(
                    "context_dropping_raise",
                    stmt.lineno,
                    "raise inside except without `from` discards the original traceback",
                )
                break

        self.generic_visit(node)

    @staticmethod
    def _body_only_logs(body: list[ast.stmt]) -> bool:
        for stmt in body:
            if _is_docstring(stmt) or isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                label = getattr(func, "attr", None) or getattr(func, "id", None) or ""
                if label.lower() in {"print", "debug", "info", "warning", "warn", "error", "exception"}:
                    continue
            return False
        return True

    # -- definitions ------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {
            getattr(b, "attr", None) or getattr(b, "id", None) for b in node.bases
        }
        # Stubs are the entire point of a Protocol or ABC; do not flag them.
        was_protocol = self._in_protocol
        self._in_protocol = was_protocol or bool(
            base_names & {"Protocol", "ABC", "ABCMeta"}
        )
        self.generic_visit(node)
        self._in_protocol = was_protocol

    def _visit_function(self, node: ast.AST) -> None:
        if (
            not self._in_protocol
            and _is_stub_body(node.body)
            and not _has_decorator(node, {"abstractmethod", "overload", "abstractproperty"})
        ):
            self._add(
                "stub_implementation",
                node.lineno,
                f"`{node.name}` has a placeholder body",
            )

        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
        for default in defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(
                    "mutable_default",
                    default.lineno,
                    f"`{node.name}` has a mutable default argument",
                )
            elif isinstance(default, ast.Call):
                target = getattr(default.func, "id", None)
                if target in ("list", "dict", "set"):
                    self._add(
                        "mutable_default",
                        default.lineno,
                        f"`{node.name}` has a mutable default argument",
                    )

        self._check_unreachable(node.body)
        self.generic_visit(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _check_unreachable(self, body: list[ast.stmt]) -> None:
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, _TERMINALS):
                nxt = body[i + 1]
                # A trailing function/class def after a return is a legitimate
                # conditional-definition idiom in some codebases; still dead here.
                self._add(
                    "unreachable_code",
                    nxt.lineno,
                    "statement follows an unconditional return/raise/break",
                )
                break


_WORD = re.compile(r"[a-z][a-z0-9]*")
# Splits identifiers into their parts: `user_id` and `userId` both -> user, id.
_IDENT_PART = re.compile(r"[a-z][a-z0-9]*")

_STOPWORDS = frozenset(
    """a an the this that these those to of for from in on at by with and or if
    is are was were be been it its as we you they then than so into over out up
    down here there when while each every any all not no do does done our their
    """.split()
)

# Verbs that describe what a line of code mechanically does. A comment built
# only from these plus words already in the code states nothing new.
_NARRATION_VERBS = frozenset(
    """set get create initialize init increment decrement define declare assign
    call return check loop iterate add append update remove delete calculate
    compute store build make convert parse load save read write print log
    handle process instantiate construct fetch send receive start stop close
    open reset clear copy sort filter map reduce find search insert push pop
    """.split()
)

# Nouns that carry no information beyond the identifier they refer to.
_FILLER_NOUNS = frozenset(
    """value values variable variables result results list lists dict dicts data
    object objects item items element elements function functions method methods
    string strings number numbers array arrays count counter index flag temp
    array field fields key keys entry entries record records instance param
    params parameter parameters argument arguments arg args output input
    """.split()
)


def _code_words(line: str) -> set[str]:
    """Identifier parts appearing in a line of code."""
    return set(_IDENT_PART.findall(line.lower()))


def _narrating_comments(source: str, path: str) -> list[Finding]:
    """Comments that restate the line beneath them.

    The test is informational, not lexical: strip stopwords, mechanical verbs
    ("increment", "return") and filler nouns ("value", "result") from the
    comment, and see whether what remains is already spelled out in the code.
    A comment reading `# increment the counter value` above `counter += 1`
    reduces to {counter}, which the code already says, so it carries nothing.

    A comment explaining *why* survives the reduction -- "off-by-one here would
    double-bill the customer" keeps {off, one, double, bill, customer}, none of
    which appear in the line -- and is left alone. Weighted very lightly, since
    on its own a narrating comment is a texture signal rather than a defect.
    """
    findings: list[Finding] = []
    lines = source.splitlines()

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return findings

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        # Only own-line comments; trailing comments are usually clarifying.
        if lines[tok.start[0] - 1].strip() != tok.string.strip():
            continue

        text = tok.string.lstrip("#").strip()
        lowered = text.lower()
        # Directives and tracked notes are not narration.
        if lowered.startswith(("type:", "noqa", "pragma", "todo", "fixme", "!")):
            continue

        words = _WORD.findall(lowered)
        if len(words) < 3:
            continue

        mentions_mechanics = any(w in _NARRATION_VERBS for w in words)
        substantive = [
            w
            for w in words
            if w not in _STOPWORDS
            and w not in _NARRATION_VERBS
            and w not in _FILLER_NOUNS
        ]
        if not substantive:
            # Pure mechanics with no subject at all, e.g. "# do the loop".
            if mentions_mechanics:
                findings.append(
                    Finding(
                        "narrating_comment",
                        path,
                        tok.start[0],
                        "comment describes mechanics the code already shows",
                    )
                )
            continue

        following = lines[tok.start[0] : tok.start[0] + 1]
        if not following or not following[0].strip():
            continue
        code_words = _code_words(following[0])
        if not code_words:
            continue

        covered = sum(1 for w in substantive if w in code_words)
        overlap = covered / len(substantive)

        # Everything the comment still says is spelled out in the line below it.
        if overlap >= 0.6 and (mentions_mechanics or overlap == 1.0):
            findings.append(
                Finding(
                    "narrating_comment",
                    path,
                    tok.start[0],
                    f"comment restates the following line ({overlap:.0%} of its"
                    " content words already appear there)",
                )
            )

    return findings


# Literals too common or too trivial to be worth naming.
_BORING_LITERALS = {0, 1, -1, 2, "", " ", "\n", "utf-8", True, False, None}
_REPEAT_THRESHOLD = 4


def _repeated_literals(tree: ast.Module, path: str) -> list[Finding]:
    counts: Counter = Counter()
    first_seen: dict[object, int] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        value = node.value
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            continue
        if value in _BORING_LITERALS:
            continue
        if isinstance(value, str) and len(value) < 4:
            continue
        key = (type(value).__name__, value)
        counts[key] += 1
        first_seen.setdefault(key, node.lineno)

    findings = []
    for (_, value), count in counts.items():
        if count >= _REPEAT_THRESHOLD:
            shown = repr(value)
            if len(shown) > 40:
                shown = shown[:37] + "...'"
            findings.append(
                Finding(
                    "repeated_literal",
                    path,
                    first_seen[(type(value).__name__, value)],
                    f"{shown} appears {count} times",
                )
            )
    return findings


def analyze_slop(path: str, source: str) -> list[Finding]:
    """All slop findings for one file. Never raises on malformed input."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = _SlopVisitor(path)
    visitor.visit(tree)

    findings = visitor.findings
    findings += _repeated_literals(tree, path)
    findings += _narrating_comments(source, path)
    findings.sort(key=lambda f: (f.lineno, f.kind))
    return findings
