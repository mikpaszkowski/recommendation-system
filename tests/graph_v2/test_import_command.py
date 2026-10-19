"""
tests/graph_v2/test_import_command.py

Import, dump and restore-test commands and guards (FR-004, FR-004a, FR-019): AC-021.
All Docker calls go to a fake runner; nothing is executed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import List

import pytest

from src.knowledge_graph.graph_v2.import_command import (
    REL_FILES,
    NODE_FILES,
    build_dump_command,
    build_import_command,
    build_load_command,
    required_files,
)

from .conftest import FakeRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FLAGS = [
    "--overwrite-destination=true", "--bad-tolerance=0", "--skip-bad-relationships=false", "--skip-duplicate-nodes=false",
    "--multiline-fields=true", "--array-delimiter=U+001F", "--ignore-empty-strings=true", "--normalize-types=true",
    "--id-type=string", "--report-file=/reports/import.report",
]
GB = 1024 ** 3


def _cli():
    spec = importlib.util.spec_from_file_location("import_graph_v2_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "import_graph_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def import_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "import"
    directory.mkdir()
    for name in required_files():
        (directory / name).write_text("x\n", encoding="utf-8")
    return directory


def _args(import_dir: Path, tmp_path: Path, volume: str = "kg_neo4j_data_v2", extra: List[str] = ()) -> List[str]:
    return ["import", "--volume", volume, "--import-dir", str(import_dir), "--report-dir", str(tmp_path / "reports"),
            "--record", str(tmp_path / "import_run.json"), *extra]


def _docker_runs(runner: FakeRunner) -> List[List[str]]:
    return [call for call in runner.calls if call[:2] == ["docker", "run"]]


def test_import_command_flags_and_files(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: the import command contains every §4.1.6 flag and all 14 file arguments."""
    command = build_import_command("kg_neo4j_data_v2", import_dir, tmp_path / "reports")
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--volume=kg_neo4j_data_v2:/data" in command and "neo4j:5.14.0" in command
    assert f"--volume={import_dir.resolve()}:/import:ro" in command
    assert command[command.index("neo4j:5.14.0") + 1:command.index("neo4j:5.14.0") + 6] == ["neo4j-admin", "database", "import", "full", "neo4j"]
    assert all(flag in command for flag in SPEC_FLAGS)
    files = [arg for arg in command if arg.startswith(("--nodes=", "--relationships="))]
    assert len(files) == 14
    assert {f"--nodes={label}=/import/{name}" for label, name in NODE_FILES} <= set(files)
    assert {f"--relationships={rel}=/import/{name}" for rel, name in REL_FILES} <= set(files)
    assert "HEAP_SIZE=2G" in command


def test_without_execute_only_logs(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: without --execute the command is logged and the runner never sees docker run."""
    runner = FakeRunner()
    code = _cli().main(_args(import_dir, tmp_path), runner=runner, env={"NEO4J_DATA_VOLUME_V1": "kg_v1"}, disk_free=lambda p: 100 * GB)
    assert code == 0 and runner.calls == [] and not (tmp_path / "import_run.json").exists()


def test_refuses_v1_volume(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: a volume equal to NEO4J_DATA_VOLUME_V1 exits 2."""
    runner = FakeRunner()
    code = _cli().main(_args(import_dir, tmp_path, volume="kg_v1", extra=["--execute", "--confirm-volume", "kg_v1"]),
                       runner=runner, env={"NEO4J_DATA_VOLUME_V1": "kg_v1"}, disk_free=lambda p: 100 * GB)
    assert code == 2 and _docker_runs(runner) == []


def test_refuses_execute_without_v1_volume_name(import_dir: Path, tmp_path: Path) -> None:
    """NFR-004 (audit fix): --execute with NEO4J_DATA_VOLUME_V1 unset exits 2 (fail closed); log-only still logs."""
    runner = FakeRunner()
    code = _cli().main(_args(import_dir, tmp_path, volume="kg_any", extra=["--execute", "--confirm-volume", "kg_any"]),
                       runner=runner, env={}, disk_free=lambda p: 100 * GB)
    assert code == 2 and runner.calls == []
    assert _cli().main(_args(import_dir, tmp_path), runner=FakeRunner(), env={}, disk_free=lambda p: 100 * GB) == 0


def test_refuses_volume_in_use(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: a volume mounted by a running container exits 2 (fake runner)."""
    runner = FakeRunner({("docker", "ps"): (0, "3f2a1b\n")})
    code = _cli().main(_args(import_dir, tmp_path, extra=["--execute", "--confirm-volume", "kg_neo4j_data_v2"]),
                       runner=runner, env={"NEO4J_DATA_VOLUME_V1": "kg_v1"}, disk_free=lambda p: 100 * GB)
    assert code == 2 and _docker_runs(runner) == []


def test_refuses_mismatched_confirm_volume(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: --execute with a different --confirm-volume exits 2."""
    runner = FakeRunner()
    code = _cli().main(_args(import_dir, tmp_path, extra=["--execute", "--confirm-volume", "kg_other"]),
                       runner=runner, env={"NEO4J_DATA_VOLUME_V1": "kg_v1"}, disk_free=lambda p: 100 * GB)
    assert code == 2 and runner.calls == []


def test_refuses_low_disk(import_dir: Path, tmp_path: Path) -> None:
    """AC-021: free disk below 40 GB exits 2."""
    runner = FakeRunner()
    code = _cli().main(_args(import_dir, tmp_path, extra=["--execute", "--confirm-volume", "kg_neo4j_data_v2"]),
                       runner=runner, env={"NEO4J_DATA_VOLUME_V1": "kg_v1"}, disk_free=lambda p: 39 * GB)
    assert code == 2 and _docker_runs(runner) == []


def test_refuses_missing_csv_or_volume(import_dir: Path, tmp_path: Path) -> None:
    """FR-019: a missing required CSV or a non-existent volume exits 2; a guarded run records import_run.json."""
    env = {"NEO4J_DATA_VOLUME_V1": "kg_v1"}
    execute = ["--execute", "--confirm-volume", "kg_neo4j_data_v2"]
    missing_volume = FakeRunner({("docker", "volume", "inspect"): (1, "")})
    assert _cli().main(_args(import_dir, tmp_path, extra=execute), runner=missing_volume, env=env, disk_free=lambda p: 100 * GB) == 2
    assert _docker_runs(missing_volume) == []

    ok = FakeRunner({("docker", "run", "--rm", "--volume=kg_neo4j_data_v2:/data:ro"): (0, "123456\t/data\n")})
    assert _cli().main(_args(import_dir, tmp_path, extra=execute), runner=ok, env=env, disk_free=lambda p: 100 * GB) == 0
    record = json.loads((tmp_path / "import_run.json").read_text(encoding="utf-8"))
    assert record["exit_code"] == 0 and record["store_kb"] == 123456 and record["volume"] == "kg_neo4j_data_v2"
    assert "--bad-tolerance=0" in record["command"]

    (import_dir / "rels_wrote.csv").unlink()
    assert _cli().main(_args(import_dir, tmp_path), runner=FakeRunner(), env=env, disk_free=lambda p: 100 * GB) == 2


def test_dump_and_load_commands(tmp_path: Path) -> None:
    """FR-004 / FR-004a: dump and load commands mount the backup dir and use neo4j-admin database dump/load."""
    dump = build_dump_command("kg_v1", tmp_path)
    assert dump[:3] == ["docker", "run", "--rm"] and "--volume=kg_v1:/data" in dump
    assert f"--volume={tmp_path.resolve()}:/backups" in dump
    assert dump[-5:] == ["neo4j-admin", "database", "dump", "neo4j", "--to-path=/backups"]
    load = build_load_command("kg_v1_restore_test", tmp_path)
    assert load[-6:] == ["neo4j-admin", "database", "load", "neo4j", "--from-path=/backups", "--overwrite-destination=true"]
    runner = FakeRunner({("docker", "ps"): (0, "busy\n")})
    code = _cli().main(["dump", "--volume", "kg_v1", "--backup-dir", str(tmp_path), "--record", str(tmp_path / "DUMP.json"),
                        "--execute", "--confirm-volume", "kg_v1"], runner=runner, env={}, disk_free=lambda p: 100 * GB)
    assert code == 2 and _docker_runs(runner) == []
