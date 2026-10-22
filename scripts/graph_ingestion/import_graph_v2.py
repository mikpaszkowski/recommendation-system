#!/usr/bin/env python3
"""
Offline import, v1 dump and dump restore-test wrapper (Technical Specification Graph Rebuild FR-004,
FR-004a, FR-019, NFR-004, NFR-006, §4.1.6).

Every sub-command only LOGS the Docker command unless both `--execute` and
`--confirm-volume <same volume>` are given; in log-only mode no Docker command at all is run (the
static guards still apply). Guards (exit 2), checked before anything runs:
    import       volume == NEO4J_DATA_VOLUME_V1, or NEO4J_DATA_VOLUME_V1 unset with --execute (fail closed;
                 the repository .env is loaded without overriding the shell); volume does not exist (no implicit creation);
                 a running container mounts it; a required CSV is missing; free disk < 40 GB.
    dump         volume does not exist; a running container mounts it; target dump file exists.
    restore-test scratch volume == NEO4J_DATA_VOLUME_V1 or the current NEO4J_DATA_VOLUME; already exists;
                 dump file missing or not named neo4j.dump.

Dumps are written to `<backup-dir>/kg_v1_<YYYYmmdd_HHMM>/neo4j.dump` (neo4j-admin names the file
after the database), outside git; `graph_versions/v1/DUMP.json` records path, SHA-256 and size.

Exit codes: 0 success (or command logged); 1 Docker failure; 2 guard refused.

Usage:
    import_graph_v2.py import --volume V --import-dir D --report-dir R [--heap 2G]
        [--record graph_versions/v2/import_run.json] [--execute --confirm-volume V]
    import_graph_v2.py dump --volume V1 --backup-dir B --record graph_versions/v1/DUMP.json [--execute --confirm-volume V1]
    import_graph_v2.py restore-test --dump F --volume kg_v1_restore_test --record graph_versions/v1/DUMP.json
        --snapshot graph_versions/v1/snapshot.json [--execute --confirm-volume kg_v1_restore_test]
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Union

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.knowledge_graph.graph_v2.import_command import (  # noqa: E402
    DUMP_FILE_NAME,
    MIN_FREE_DISK_BYTES,
    NEO4J_IMAGE,
    REPORT_FILE_NAME,
    CommandRunner,
    build_container_rm_command,
    build_cypher_shell_command,
    build_du_command,
    build_dump_command,
    build_import_command,
    build_load_command,
    build_restore_start_command,
    build_volume_create_command,
    build_volume_rm_command,
    default_command_runner,
    free_disk_bytes,
    missing_files,
    volume_exists,
    volume_in_use,
)
from src.knowledge_graph.graph_v2.lineage import InputVerificationError, sha256_file  # noqa: E402
from src.knowledge_graph.graph_v2.models import DumpRecord, ImportRun, RestoreTestResult  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_graph_v2")

EXIT_OK = 0
EXIT_DOCKER_FAILURE = 1
EXIT_GUARD = 2
ENV_V1_VOLUME = "NEO4J_DATA_VOLUME_V1"
ENV_CURRENT_VOLUME = "NEO4J_DATA_VOLUME"
ENV_BACKUP_DIR = "GRAPH_BACKUP_DIR"
DEFAULT_BACKUP_DIR = Path("~/neo4j-backups").expanduser()
DEFAULT_IMPORT_RECORD = REPO_ROOT / "graph_versions" / "v2" / "import_run.json"
DEFAULT_DUMP_RECORD = REPO_ROOT / "graph_versions" / "v1" / "DUMP.json"
DEFAULT_V1_SNAPSHOT = REPO_ROOT / "graph_versions" / "v1" / "snapshot.json"
RESTORE_CONTAINER_NAME = "kg_v1_restore_test_run"
RESTORE_START_TIMEOUT_S = 300.0
RESTORE_POLL_INTERVAL_S = 5.0
NODE_COUNT_CYPHER = "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n"
REL_COUNT_CYPHER = "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n"

DiskFree = Callable[[Path], int]


class GuardRefused(Exception):
    """A safety guard refused the sub-command (exit 2)."""


def build_parser() -> argparse.ArgumentParser:
    """Sub-command parser of §4.1.7."""
    parser = argparse.ArgumentParser(description="Graph v2 offline import, v1 dump and dump restore test.")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="neo4j-admin database import full into a NEW volume")
    imp.add_argument("--volume", required=True)
    imp.add_argument("--import-dir", required=True, type=Path)
    imp.add_argument("--report-dir", required=True, type=Path)
    imp.add_argument("--heap", default="2G")
    imp.add_argument("--image", default=NEO4J_IMAGE)
    imp.add_argument("--record", type=Path, default=DEFAULT_IMPORT_RECORD, help="import_run.json path")

    dump = sub.add_parser("dump", help="Offline neo4j-admin dump of the stopped v1 volume")
    dump.add_argument("--volume", required=True)
    dump.add_argument("--backup-dir", type=Path, default=Path(os.environ.get(ENV_BACKUP_DIR, str(DEFAULT_BACKUP_DIR))))
    dump.add_argument("--record", type=Path, default=DEFAULT_DUMP_RECORD)
    dump.add_argument("--image", default=NEO4J_IMAGE)

    rt = sub.add_parser("restore-test", help="Load the dump into a scratch volume, compare counts, remove the volume")
    rt.add_argument("--dump", required=True, type=Path, help="<backup-dir>/kg_v1_<ts>/neo4j.dump")
    rt.add_argument("--volume", default="kg_v1_restore_test")
    rt.add_argument("--record", type=Path, default=DEFAULT_DUMP_RECORD)
    rt.add_argument("--snapshot", type=Path, default=DEFAULT_V1_SNAPSHOT)
    rt.add_argument("--image", default=NEO4J_IMAGE)

    for p in (imp, dump, rt):
        p.add_argument("--execute", action="store_true", help="Actually run Docker (otherwise only log)")
        p.add_argument("--confirm-volume", default=None, help="Must repeat --volume exactly when --execute is set")
    return parser


def _now() -> str:
    """Current UTC time, ISO-8601 with Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_confirmation(volume: str, execute: bool, confirm_volume: Optional[str]) -> bool:
    """True if the command must run; False to only log. Raises GuardRefused when --execute lacks a matching --confirm-volume."""
    if not execute:
        return False
    if confirm_volume != volume:
        raise GuardRefused(f"--execute requires --confirm-volume {volume!r} (got {confirm_volume!r})")
    return True


def guard_import(volume: str, import_dir: Path, runner: CommandRunner, env: Dict[str, str], disk_free: DiskFree, execute: bool = True) -> None:
    """FR-019 / NFR-006 guards for `import`; raises GuardRefused with the reason. Docker-querying guards run only with --execute."""
    v1 = env.get(ENV_V1_VOLUME)
    if v1 and volume == v1:
        raise GuardRefused(f"volume {volume!r} is the v1 volume ({ENV_V1_VOLUME}); the import never writes to v1")
    if not v1:
        if execute:
            # Fail closed: without the v1 name the guard cannot prove the target is not v1 (NFR-004).
            raise GuardRefused(f"{ENV_V1_VOLUME} is not set; refusing to --execute an import without the v1-name guard")
        logger.warning(f"{ENV_V1_VOLUME} is not set; the v1-name guard cannot be checked (an --execute run will refuse)")
    missing = missing_files(import_dir)
    if missing:
        raise GuardRefused(f"required CSVs missing in {import_dir}: {missing}")
    free = disk_free(Path(import_dir))
    if free < MIN_FREE_DISK_BYTES:
        raise GuardRefused(f"only {free / 1024 ** 3:.1f} GB free; at least {MIN_FREE_DISK_BYTES / 1024 ** 3:.0f} GB required (NFR-006)")
    if not execute:
        return
    if not volume_exists(volume, runner):
        raise GuardRefused(f"volume {volume!r} does not exist; create it explicitly (CP-5 / CP-6) before importing")
    if volume_in_use(volume, runner):
        raise GuardRefused(f"volume {volume!r} is mounted by a running container")


def guard_dump(volume: str, dump_dir: Path, runner: CommandRunner, execute: bool = True) -> None:
    """FR-004 guards for `dump`; raises GuardRefused with the reason. Docker-querying guards run only with --execute."""
    if (Path(dump_dir) / DUMP_FILE_NAME).exists():
        raise GuardRefused(f"{Path(dump_dir) / DUMP_FILE_NAME} already exists")
    if not execute:
        return
    if not volume_exists(volume, runner):
        raise GuardRefused(f"volume {volume!r} does not exist")
    if volume_in_use(volume, runner):
        raise GuardRefused(f"volume {volume!r} is mounted by a running container; stop v1 first (CP-3)")


def guard_restore_test(volume: str, dump_file: Path, runner: CommandRunner, env: Dict[str, str], execute: bool = True) -> None:
    """FR-004a guards for `restore-test`; raises GuardRefused with the reason."""
    protected = {env.get(ENV_V1_VOLUME), env.get(ENV_CURRENT_VOLUME)} - {None, ""}
    if volume in protected:
        raise GuardRefused(f"scratch volume {volume!r} equals a protected graph volume ({ENV_V1_VOLUME} / {ENV_CURRENT_VOLUME})")
    if Path(dump_file).name != DUMP_FILE_NAME or not Path(dump_file).is_file():
        raise GuardRefused(f"dump file must exist and be named {DUMP_FILE_NAME}: {dump_file}")
    if execute and volume_exists(volume, runner):
        raise GuardRefused(f"scratch volume {volume!r} already exists; remove it or choose another name")


def write_record(path: Path, record: Union[ImportRun, DumpRecord]) -> None:
    """Writes a validated JSON artefact (indented, UTF-8, trailing newline)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _report_facts(report_file: Path) -> tuple:
    """(sha256, line count) of the import report, or (None, None) when it does not exist."""
    if not report_file.is_file():
        return None, None
    with open(report_file, "rb") as handle:
        lines = sum(1 for _ in handle)
    return sha256_file(report_file), lines


def _store_kb(volume: str, image: str, runner: CommandRunner) -> Optional[int]:
    """Store size in KB from `du -sk /data` in a throw-away container."""
    code, out = runner(build_du_command(volume, image))
    if code != 0 or not out.strip():
        logger.warning(f"Could not measure the store size of {volume}")
        return None
    try:
        return int(out.split()[0])
    except ValueError:
        logger.warning(f"Unexpected du output: {out!r}")
        return None


def run_import(args: argparse.Namespace, runner: CommandRunner, env: Dict[str, str], disk_free: DiskFree) -> int:
    """Builds and (optionally) runs the import, measures the store with du, writes import_run.json."""
    execute = check_confirmation(args.volume, args.execute, args.confirm_volume)
    guard_import(args.volume, args.import_dir, runner, env, disk_free, execute=execute)
    command = build_import_command(args.volume, args.import_dir, args.report_dir, image=args.image, heap=args.heap)
    if not execute:
        logger.info(f"[log only] {shlex.join(command)}")
        return EXIT_OK
    Path(args.report_dir).mkdir(parents=True, exist_ok=True)
    started_at = _now()
    logger.info(f"Running import into {args.volume}: {shlex.join(command)}")
    code, _ = runner(command)
    ended_at = _now()
    report_sha, report_lines = _report_facts(Path(args.report_dir) / REPORT_FILE_NAME)
    store_kb = _store_kb(args.volume, args.image, runner) if code == 0 else None
    write_record(args.record, ImportRun(
        volume=args.volume, image=args.image, command=command, started_at=started_at, ended_at=ended_at,
        exit_code=code, report_file_sha256=report_sha, report_file_lines=report_lines, store_kb=store_kb,
    ))
    if code != 0:
        logger.error(f"neo4j-admin import exited {code}; see {Path(args.report_dir) / REPORT_FILE_NAME}")
        return EXIT_DOCKER_FAILURE
    logger.info(f"Import finished; record {args.record}, store {store_kb} KB")
    return EXIT_OK


def run_dump(args: argparse.Namespace, runner: CommandRunner, now: Callable[[], str]) -> int:
    """Builds and (optionally) runs the dump, hashes the file, writes DUMP.json (restore_test null)."""
    execute = check_confirmation(args.volume, args.execute, args.confirm_volume)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M")
    dump_dir = Path(args.backup_dir).expanduser() / f"kg_v1_{stamp}"
    guard_dump(args.volume, dump_dir, runner, execute=execute)
    command = build_dump_command(args.volume, dump_dir, image=args.image)
    if not execute:
        logger.info(f"[log only] {shlex.join(command)}")
        return EXIT_OK
    dump_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Dumping {args.volume} to {dump_dir}: {shlex.join(command)}")
    code, _ = runner(command)
    dump_file = dump_dir / DUMP_FILE_NAME
    if code != 0 or not dump_file.is_file() or dump_file.stat().st_size == 0:
        logger.error(f"Dump failed (exit {code}) or produced no file at {dump_file}")
        return EXIT_DOCKER_FAILURE
    record = DumpRecord(
        volume=args.volume, dump_path=str(dump_file.resolve()), sha256=sha256_file(dump_file),
        bytes=dump_file.stat().st_size, created_at=now(), neo4j_version=args.image.split(":")[-1], restore_test=None,
    )
    write_record(args.record, record)
    logger.info(f"Dump written: {dump_file} ({record.bytes} bytes, sha256 {record.sha256})")
    return EXIT_OK


def _parse_plain_counts(output: str) -> Dict[str, int]:
    """Parses cypher-shell plain output `name, n` rows (header first) into name -> count."""
    counts: Dict[str, int] = {}
    for line in output.strip().splitlines()[1:]:
        if ", " not in line:
            continue
        name, value = line.rsplit(", ", 1)
        counts[name.strip().strip('"')] = int(value.strip())
    return counts


def read_restore_counts(container_name: str, runner: CommandRunner) -> Dict[str, Dict[str, int]]:
    """{"nodes": label -> count, "relationships": type -> count} via cypher-shell in the scratch container."""
    counts: Dict[str, Dict[str, int]] = {}
    for key, cypher in (("nodes", NODE_COUNT_CYPHER), ("relationships", REL_COUNT_CYPHER)):
        code, out = runner(build_cypher_shell_command(container_name, cypher))
        if code != 0:
            raise RuntimeError(f"cypher-shell count query failed in {container_name} (exit {code})")
        counts[key] = _parse_plain_counts(out)
    return counts


def _wait_for_neo4j(container_name: str, runner: CommandRunner, timeout_s: float) -> bool:
    """Polls `RETURN 1` through cypher-shell until it succeeds or the timeout passes."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        code, _ = runner(build_cypher_shell_command(container_name, "RETURN 1"))
        if code == 0:
            return True
        time.sleep(RESTORE_POLL_INTERVAL_S)
    return False


def run_restore_test(args: argparse.Namespace, runner: CommandRunner, env: Dict[str, str], now: Callable[[], str]) -> int:
    """Creates the scratch volume, loads, starts, counts, compares with snapshot.json, records restore_test, then removes container and volume."""
    execute = check_confirmation(args.volume, args.execute, args.confirm_volume)
    guard_restore_test(args.volume, args.dump, runner, env, execute=execute)
    if not Path(args.record).is_file() or not Path(args.snapshot).is_file():
        raise GuardRefused(f"{args.record} and {args.snapshot} must exist before a restore test")
    record = DumpRecord.model_validate_json(Path(args.record).read_text(encoding="utf-8"))
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    commands = [
        build_volume_create_command(args.volume),
        build_load_command(args.volume, Path(args.dump).parent, image=args.image),
        build_restore_start_command(args.volume, RESTORE_CONTAINER_NAME, image=args.image),
    ]
    if not execute:
        for command in commands:
            logger.info(f"[log only] {shlex.join(command)}")
        return EXIT_OK
    passed = False
    counts_match = False
    observed: Dict[str, Dict[str, int]] = {}
    try:
        for command in commands:
            code, _ = runner(command)
            if code != 0:
                logger.error(f"Restore-test step failed (exit {code}): {shlex.join(command)}")
                break
        else:
            if not _wait_for_neo4j(RESTORE_CONTAINER_NAME, runner, RESTORE_START_TIMEOUT_S):
                logger.error("Scratch Neo4j did not become ready in time")
            else:
                observed = read_restore_counts(RESTORE_CONTAINER_NAME, runner)
                counts_match = (observed.get("nodes") == snapshot.get("nodes")
                                and observed.get("relationships") == snapshot.get("relationships"))
                passed = counts_match
                if not counts_match:
                    logger.error(f"Restored counts differ from {args.snapshot}: {observed}")
    except RuntimeError as e:
        logger.error(f"Restore test failed: {e}")
    finally:
        runner(build_container_rm_command(RESTORE_CONTAINER_NAME))
        code, _ = runner(build_volume_rm_command(args.volume))
        if code != 0:
            logger.error(f"Could not remove scratch volume {args.volume}; remove it manually")
    record = record.model_copy(update={"restore_test": RestoreTestResult(
        passed=passed, counts_match=counts_match, at=now(), observed_counts=observed,
    )})
    write_record(args.record, record)
    logger.info(f"Restore test {'passed' if passed else 'FAILED'}; recorded in {args.record}")
    return EXIT_OK if passed else EXIT_DOCKER_FAILURE


def main(
    argv: Optional[Sequence[str]] = None,
    runner: Optional[CommandRunner] = None,
    env: Optional[Dict[str, str]] = None,
    disk_free: Optional[DiskFree] = None,
) -> int:
    """CLI entry point; runner, env and disk_free are injectable for tests (AC-021)."""
    args = build_parser().parse_args(argv)
    run = runner or default_command_runner(None)
    if env is None:
        # The volume names are documented in the repository .env (.env.example); load it without
        # overriding the shell so NEO4J_DATA_VOLUME_V1 / NEO4J_DATA_VOLUME guards see the same values as compose.
        load_dotenv(REPO_ROOT / ".env", override=False)
    environment = dict(os.environ) if env is None else env
    free = disk_free or free_disk_bytes
    try:
        if args.command == "import":
            return run_import(args, run, environment, free)
        if args.command == "dump":
            return run_dump(args, run, _now)
        return run_restore_test(args, run, environment, _now)
    except GuardRefused as e:
        logger.error(f"Refused: {e}")
        return EXIT_GUARD
    except (InputVerificationError, OSError, ValueError) as e:
        logger.error(f"{args.command} failed: {e}")
        return EXIT_GUARD


if __name__ == "__main__":
    raise SystemExit(main())
