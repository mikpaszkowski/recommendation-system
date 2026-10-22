"""
Docker / neo4j-admin command builders and volume checks (FR-004, FR-004a, FR-019, §4.1.6).

Only builds argument lists and parses runner output. All Docker calls go through an injectable
`CommandRunner` (same pattern as `GitRunner` in `src/evaluation/provenance.py`) so tests use fakes.
Nothing here executes a command unless the caller passes a real runner.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

CommandRunner = Callable[[Sequence[str]], Tuple[int, str]]  # full argv -> (returncode, stdout)

NEO4J_IMAGE: str = "neo4j:5.14.0"
DEFAULT_IMPORT_HEAP: str = "2G"
DOCKER_COMMAND_TIMEOUT_S: float = 60.0
REPORT_FILE_NAME: str = "import.report"
DUMP_FILE_NAME: str = "neo4j.dump"            # neo4j-admin writes <database>.dump into --to-path
DATABASE_NAME: str = "neo4j"
MIN_FREE_DISK_BYTES: int = 40 * 1024 ** 3     # NFR-006

NODE_FILES: List[Tuple[str, str]] = [
    ("ParentProduct", "nodes_product.csv"), ("Review", "nodes_review.csv"),
    ("User", "nodes_user.csv"), ("Brand", "nodes_brand.csv"), ("Category", "nodes_category.csv"),
    ("Attribute", "nodes_attribute.csv"), ("Taxon", "nodes_taxon.csv"),
]
REL_FILES: List[Tuple[str, str]] = [
    ("HAS_BRAND", "rels_has_brand.csv"), ("BELONGS_TO_CATEGORY", "rels_belongs_to_category.csv"),
    ("HAS_ATTRIBUTE", "rels_has_attribute.csv"), ("IN_TAXON", "rels_in_taxon.csv"), ("BROADER", "rels_broader.csv"),
    ("ABOUT_PRODUCT", "rels_about_product.csv"), ("WROTE", "rels_wrote.csv"),
]
IMPORT_FLAGS: Tuple[str, ...] = (
    "--overwrite-destination=true", "--bad-tolerance=0", "--skip-bad-relationships=false",
    "--skip-duplicate-nodes=false", "--multiline-fields=true", "--array-delimiter=U+001F",
    "--ignore-empty-strings=true", "--normalize-types=true", "--id-type=string",
)


def default_command_runner(timeout_s: Optional[float] = DOCKER_COMMAND_TIMEOUT_S) -> CommandRunner:
    """Runner executing argv via subprocess (stdout captured, stderr logged); timeout None for long imports."""

    def _run(argv: Sequence[str]) -> Tuple[int, str]:
        try:
            proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout_s, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"[Docker] {' '.join(argv[:3])} … failed to run: {e}")
            return -1, ""
        if proc.returncode != 0 and proc.stderr:
            logger.error(f"[Docker] exit {proc.returncode}: {proc.stderr.strip()[-2000:]}")
        return proc.returncode, proc.stdout

    return _run


def required_files() -> List[str]:
    """The 14 CSV file names the import needs."""
    return [name for _, name in NODE_FILES] + [name for _, name in REL_FILES]


def missing_files(import_dir: Path) -> List[str]:
    """Required CSVs that do not exist in `import_dir`."""
    return [name for name in required_files() if not (Path(import_dir) / name).is_file()]


def build_import_command(volume: str, import_dir: Path, report_dir: Path, image: str = NEO4J_IMAGE, heap: str = DEFAULT_IMPORT_HEAP) -> List[str]:
    """`docker run --rm` neo4j-admin database import full with every flag of §4.1.6 and all 14 file arguments."""
    command = [
        "docker", "run", "--rm",
        f"--volume={volume}:/data",
        f"--volume={Path(import_dir).resolve()}:/import:ro",
        f"--volume={Path(report_dir).resolve()}:/reports",
        "--env", f"HEAP_SIZE={heap}",
        image,
        "neo4j-admin", "database", "import", "full", DATABASE_NAME,
        *IMPORT_FLAGS,
        f"--report-file=/reports/{REPORT_FILE_NAME}",
    ]
    command += [f"--nodes={label}=/import/{name}" for label, name in NODE_FILES]
    command += [f"--relationships={rel}=/import/{name}" for rel, name in REL_FILES]
    return command


def build_dump_command(volume: str, backup_dir: Path, image: str = NEO4J_IMAGE) -> List[str]:
    """`docker run --rm` neo4j-admin database dump neo4j --to-path=/backups on the (stopped) volume."""
    return [
        "docker", "run", "--rm", f"--volume={volume}:/data", f"--volume={Path(backup_dir).resolve()}:/backups",
        image, "neo4j-admin", "database", "dump", DATABASE_NAME, "--to-path=/backups",
    ]


def build_load_command(volume: str, backup_dir: Path, image: str = NEO4J_IMAGE) -> List[str]:
    """`docker run --rm` neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true."""
    return [
        "docker", "run", "--rm", f"--volume={volume}:/data", f"--volume={Path(backup_dir).resolve()}:/backups:ro",
        image, "neo4j-admin", "database", "load", DATABASE_NAME, "--from-path=/backups", "--overwrite-destination=true",
    ]


def build_du_command(volume: str, image: str = NEO4J_IMAGE) -> List[str]:
    """Throw-away container measuring the store: `du -sk /data` on the volume mounted read-only."""
    return ["docker", "run", "--rm", f"--volume={volume}:/data:ro", "--entrypoint", "du", image, "-sk", "/data"]


def build_volume_create_command(volume: str) -> List[str]:
    """`docker volume create <volume>` (restore-test scratch volume only; v2 volumes are created by the user at CP-5/CP-6)."""
    return ["docker", "volume", "create", volume]


def build_volume_rm_command(volume: str) -> List[str]:
    """`docker volume rm <volume>` (restore-test scratch volume only)."""
    return ["docker", "volume", "rm", volume]


def build_restore_start_command(volume: str, container_name: str, image: str = NEO4J_IMAGE) -> List[str]:
    """Detached Neo4j container on the scratch volume, auth disabled, no published ports (counts are read via docker exec)."""
    return [
        "docker", "run", "-d", "--name", container_name, f"--volume={volume}:/data",
        "--env", "NEO4J_AUTH=none", image,
    ]


def build_cypher_shell_command(container_name: str, cypher: str) -> List[str]:
    """`docker exec <container> cypher-shell --format plain <cypher>` for read-only counting."""
    return ["docker", "exec", container_name, "cypher-shell", "--format", "plain", cypher]


def build_container_rm_command(container_name: str) -> List[str]:
    """`docker rm -f <container>`."""
    return ["docker", "rm", "-f", container_name]


def volume_in_use(volume: str, runner: CommandRunner) -> bool:
    """`docker ps --filter volume=<v> -q` returns any container ID. A runner failure counts as in use (fail closed)."""
    code, out = runner(["docker", "ps", "--filter", f"volume={volume}", "-q"])
    if code != 0:
        logger.error(f"[Docker] cannot list containers using volume {volume}; treating it as in use")
        return True
    return bool(out.strip())


def volume_exists(volume: str, runner: CommandRunner) -> bool:
    """`docker volume inspect <v>` succeeds. Guards against `docker run --volume` silently creating a volume."""
    code, _ = runner(["docker", "volume", "inspect", volume])
    return code == 0


def free_disk_bytes(path: Path) -> int:
    """Free bytes on the filesystem holding `path` (shutil.disk_usage)."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free
