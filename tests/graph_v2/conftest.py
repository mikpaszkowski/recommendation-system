"""
Shared fixtures and fakes for the graph v2 unit tests (NFR-005).

Fixture data lives in tests/fixtures/graph_v2/ (synthetic IDs T…, U…, X…):
    meta.jsonl      T001 full record (Material/Color, "color" ignored, list Size, nested details), later
                    conflicting duplicate; T002 store "ANKER" (case group with "Anker"), blank title, string
                    description, price "12.99"; T003 blank store -> details Brand, price "$12.99"; T004 no
                    brand, price null, empty categories; T005 price "from 9.99", inner-node taxon, blank
                    main_category; T006 price NaN, no content, second root "Home Audio"; T007 price true,
                    features-only content; T008 price 0 (sampled at mod 4); T009 int price, whitespace/blank
                    levels, identical duplicate; T010 (sampled); T012 special characters; X999 not in
                    catalogue; one malformed line. T011 is in the catalogue with no meta line.
    reviews.jsonl   T001: 25 reviews with designed ties, a blank review in the top 5, U301 beyond the cap,
                    U025 missing timestamp; T002: duplicate review_ids (better rank key / earlier offset),
                    blank review; T003: valid pair with a different child asin, train, no-split and test
                    pairs; T004: U300's only review is a valid pair; T008/T010: sampled products; T011:
                    product_missing; X999: not_in_catalogue; one malformed line; two missing user_id lines.
    Electronics.{train,valid,test}.csv, catalogue.txt (T001 … T012), SHA256SUMS (meta.jsonl, reviews.jsonl).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pytest

from src.knowledge_graph.graph_v2.transform import TransformConfig, run_transform

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "graph_v2"


class FakeRecord(dict):
    """dict-backed stand-in for neo4j.Record (supports record["key"] and .get)."""


class FakeResult:
    """Iterable result with .single(), .data() and .consume() like neo4j.Result."""

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Wraps a list of records."""
        self._records = [FakeRecord(r) for r in records]

    def __iter__(self) -> Iterator[FakeRecord]:
        """Iterates the records."""
        return iter(self._records)

    def single(self) -> Optional[FakeRecord]:
        """First record or None."""
        return self._records[0] if self._records else None

    def data(self) -> List[Dict[str, Any]]:
        """Records as plain dicts."""
        return [dict(r) for r in self._records]

    def consume(self) -> None:
        """No-op summary consumption."""
        return None


Responder = Callable[[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]]


class FakeSession:
    """Records every (cypher, params) call and answers through a scripted responder; usable as a context manager."""

    def __init__(self, responder: Responder) -> None:
        """`responder(cypher, params)` returns the records for one call (may raise to simulate failures)."""
        self.responder = responder
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def run(self, cypher: str, parameters: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> FakeResult:
        """Logs the call and returns the responder's records."""
        params = {**(parameters or {}), **kwargs}
        self.calls.append((cypher, params))
        return FakeResult(self.responder(cypher, params))

    def __enter__(self) -> "FakeSession":
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: Any) -> bool:
        """Context-manager exit (never suppresses)."""
        return False


class FakeEmbedder:
    """Deterministic embedder: fixed 384-d vector per text; records every batch; raises on None or empty text."""

    def __init__(self, fail_after_batches: Optional[int] = None) -> None:
        """`fail_after_batches` simulates an interruption for the resume test (AC-023)."""
        self.fail_after_batches = fail_after_batches
        self.batches: List[List[str]] = []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Returns one vector per text."""
        if self.fail_after_batches is not None and len(self.batches) >= self.fail_after_batches:
            raise RuntimeError("simulated interruption")
        for text in texts:
            if text is None or not str(text).strip():
                raise AssertionError(f"blank text sent to the embedder: {text!r}")
        self.batches.append(list(texts))
        return [[float(len(text) % 7)] + [0.0] * 383 for text in texts]


class FakeRunner:
    """CommandRunner fake: records argv lists and answers by the first matching argv prefix."""

    def __init__(self, responses: Optional[Dict[Tuple[str, ...], Tuple[int, str]]] = None) -> None:
        """`responses` maps an argv prefix to (returncode, stdout); unmatched commands return (0, "")."""
        self.responses = responses or {}
        self.calls: List[List[str]] = []

    def __call__(self, argv: Sequence[str]) -> Tuple[int, str]:
        """Records and answers one command."""
        self.calls.append(list(argv))
        for prefix, answer in self.responses.items():
            if tuple(argv[:len(prefix)]) == prefix:
                return answer
        return 0, ""


def make_clean_git_runner(commit: str = "abc123") -> Callable[[Sequence[str]], Tuple[int, str]]:
    """GitRunner fake: fixed commit, clean tree, empty diff."""
    def run(args: Sequence[str]) -> Tuple[int, str]:
        if args[0] == "rev-parse":
            return 0, commit + "\n"
        if args[0] == "describe":
            return 0, commit[:7] + "\n"
        if args[0] in ("status", "diff"):
            return 0, ""
        return 1, ""
    return run


def fixture_config(base: Path, fixtures: Path = FIXTURE_DIR, **overrides: Any) -> TransformConfig:
    """TransformConfig over a fixture directory with outputs under `base`."""
    values: Dict[str, Any] = dict(
        meta_path=fixtures / "meta.jsonl", reviews_path=fixtures / "reviews.jsonl",
        sha256sums_path=fixtures / "SHA256SUMS", splits_dir=fixtures, catalogue_path=fixtures / "catalogue.txt",
        out_dir=base / "import", lineage_path=base / "lineage.json", repo_root=Path(__file__).resolve().parents[2],
    )
    values.update(overrides)
    return TransformConfig(**values)


@pytest.fixture
def fixture_dir() -> Path:
    """tests/fixtures/graph_v2."""
    return FIXTURE_DIR


@pytest.fixture
def fixture_copy(tmp_path: Path) -> Path:
    """A writable copy of the fixture directory (for SHA256SUMS mismatch and missing-split cases)."""
    target = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_DIR, target)
    return target


@pytest.fixture
def transform_config(tmp_path: Path) -> Callable[..., Any]:
    """Factory: TransformConfig over the fixtures with out_dir and lineage under tmp_path; keyword overrides."""
    def factory(name: str = "run", **overrides: Any) -> TransformConfig:
        return fixture_config(tmp_path / name, **overrides)
    return factory


@pytest.fixture
def clean_git_runner() -> Callable[[Sequence[str]], Tuple[int, str]]:
    """GitRunner fake reporting commit "abc123" and a clean src/scripts tree."""
    return make_clean_git_runner()


@pytest.fixture(scope="session")
def fixture_build(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """One full transform over the fixtures (clean fake git), shared read-only by tests: (TransformResult, base dir)."""
    base = tmp_path_factory.mktemp("fixture_build")
    result = run_transform(fixture_config(base), git_runner=make_clean_git_runner())
    return result, base
