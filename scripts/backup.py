"""Versioned PostgreSQL dumps and non-destructive restore drills through Docker."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{args[0]} command failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def backup():
    directory = ROOT / "backups"
    directory.mkdir(exist_ok=True)
    name = "job-pipeline-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".dump"
    remote = "/tmp/" + name
    output = directory / name
    try:
        run("docker", "compose", "exec", "-T", "db", "sh", "-c",
            'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', "backup", remote)
        run("docker", "compose", "cp", "db:" + remote, str(output))
        with output.open("rb") as stream:
            if output.stat().st_size < 100 or stream.read(5) != b"PGDMP":
                raise RuntimeError("Backup file is not a PostgreSQL custom archive")
    finally:
        try:
            run("docker", "compose", "exec", "-T", "db", "rm", "-f", remote)
        except RuntimeError:
            print("Temporary archive cleanup unavailable; check Docker is running.")
    print(output)


def verify(path):
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise ValueError("Use a PostgreSQL custom-format .dump backup")
    name = "job-pipeline-restore-" + uuid4().hex
    started = False
    try:
        # No network, published ports or persistent volume. Never connect to live DB.
        run("docker", "run", "--detach", "--name", name, "--network", "none",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-alpine")
        started = True
        for _ in range(30):
            try:
                run("docker", "exec", name, "pg_isready", "-U", "postgres")
                break
            except RuntimeError:
                time.sleep(1)
        else:
            raise RuntimeError("Temporary PostgreSQL did not become ready")
        run("docker", "cp", str(path), name + ":/tmp/restore.dump")
        run("docker", "exec", name, "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
            "-U", "postgres", "-d", "postgres", "/tmp/restore.dump")
        revision = run("docker", "exec", name, "psql", "-U", "postgres", "-d", "postgres", "-At", "-c",
                       "SELECT version_num FROM alembic_version")
        if revision != "0005":
            raise RuntimeError(f"Expected version 0005, found {revision}; use the matching application release")
        counts = run("docker", "exec", name, "psql", "-U", "postgres", "-d", "postgres", "-At", "-c",
                     "SELECT 'companies=' || count(*) FROM companies UNION ALL "
                     "SELECT 'jobs=' || count(*) FROM jobs UNION ALL "
                     "SELECT 'resumes=' || count(*) FROM resumes UNION ALL "
                     "SELECT 'applications=' || count(*) FROM application_preparations")
        print("Restore verified in an isolated temporary database. Revision=" + revision + "\n" + counts)
    finally:
        if started:
            # This exact generated container is the only resource we remove.
            run("docker", "rm", "--force", "--volumes", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "verify"])
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "verify" and not args.file:
        parser.error("verify requires a backup path")
    backup() if args.action == "create" else verify(args.file)
