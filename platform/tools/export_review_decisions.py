"""Export collaboration-platform decisions into the complete review CSV.

The database stores task identity and human decisions, while the original review
CSV retains candidate geometry and matched-GT evidence required by safe apply.
This tool joins both sources by candidate_id without mutating either source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


DECISION_MAP = {
    "ACCEPT_ADD": "accept_add",
    "ACCEPT_REPLACE_GT": "accept_replace_gt",
    "ACCEPT_EVAL_LABEL": "accept_eval_label",
    "REJECT": "reject",
    "UNCERTAIN": "uncertain",
}


def read_env(path: Path) -> dict[str, str]:
    config: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Invalid config line in {path}: {raw!r}")
        config[key.strip()] = value.strip()
    return config


def require_config(config: dict[str, str], key: str) -> str:
    value = config.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing required setting: {key}")
    return value


def mysql_json_rows(
    mysql: Path,
    config: dict[str, str],
    database: str,
    sql: str,
) -> list[dict[str, Any]]:
    command = [
        str(mysql),
        "-h",
        require_config(config, "LABEL_REVIEW_DB_HOST"),
        "-P",
        config.get("LABEL_REVIEW_DB_PORT", "3306"),
        "-u",
        require_config(config, "LABEL_REVIEW_DB_USER"),
        "--default-character-set=utf8mb4",
        "--batch",
        "--raw",
        "--skip-column-names",
        database,
        "-e",
        sql,
    ]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = require_config(config, "LABEL_REVIEW_DB_PASSWORD")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"mysql export failed with exit code {completed.returncode}: {detail}")
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def database_snapshot(
    mysql: Path,
    config: dict[str, str],
    database: str,
    project_id: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    progress_sql = f"""
SELECT JSON_OBJECT(
  'project_id', p.id,
  'project_name', p.name,
  'project_status', p.status,
  'total_tasks', COUNT(t.id),
  'pending_tasks', SUM(t.state = 'PENDING'),
  'claimed_tasks', SUM(t.state = 'CLAIMED'),
  'completed_tasks', SUM(t.state = 'COMPLETED'),
  'escalated_tasks', SUM(t.state = 'ESCALATED')
)
FROM review_projects p
LEFT JOIN review_tasks t ON t.project_id = p.id
WHERE p.id = {project_id}
GROUP BY p.id, p.name, p.status;
"""
    progress_rows = mysql_json_rows(mysql, config, database, progress_sql)
    if len(progress_rows) != 1:
        raise ValueError(f"Project {project_id} was not found")

    decisions_sql = f"""
SELECT JSON_OBJECT(
  'candidate_id', t.candidate_id,
  'decision', d.decision,
  'comment', d.comment,
  'reviewer_username', u.username,
  'decided_at', DATE_FORMAT(d.decided_at, '%Y-%m-%dT%H:%i:%s.%fZ')
)
FROM review_decisions d
JOIN review_tasks t ON t.id = d.task_id
JOIN app_users u ON u.id = d.reviewer_id
WHERE t.project_id = {project_id}
ORDER BY t.id;
"""
    decisions: dict[str, dict[str, Any]] = {}
    for row in mysql_json_rows(mysql, config, database, decisions_sql):
        candidate_id = str(row["candidate_id"])
        if candidate_id in decisions:
            raise ValueError(f"Duplicate database decision for candidate {candidate_id}")
        decisions[candidate_id] = row
    return progress_rows[0], decisions


def load_template(path: Path) -> tuple[list[str], list[dict[str, str]], set[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or ())
        required = {"candidate_id", "reviewer_decision", "reviewer_comment"}
        missing_fields = required.difference(fields)
        if missing_fields:
            raise ValueError(f"Template is missing fields: {', '.join(sorted(missing_fields))}")
        rows = list(reader)
    ids = [row["candidate_id"].strip() for row in rows]
    duplicate_ids = {item for item, count in Counter(ids).items() if count > 1}
    if duplicate_ids:
        sample = ", ".join(sorted(duplicate_ids)[:10])
        raise ValueError(f"Template has duplicate candidate IDs ({len(duplicate_ids)}): {sample}")
    return fields, rows, set(ids)


def atomic_write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_decisions(args: argparse.Namespace) -> dict[str, Any]:
    template = args.template.expanduser().resolve()
    output = args.output.expanduser().resolve()
    env_file = args.env_file.expanduser().resolve()
    mysql = args.mysql.expanduser().resolve()
    for required in (template, env_file, mysql):
        if not required.is_file():
            raise FileNotFoundError(required)
    if output == template:
        raise ValueError("Output must not overwrite the source template")

    config = read_env(env_file)
    progress, decisions = database_snapshot(mysql, config, args.database, args.project_id)
    fields, rows, template_ids = load_template(template)
    unknown_database_ids = sorted(set(decisions).difference(template_ids))
    if unknown_database_ids:
        sample = ", ".join(unknown_database_ids[:10])
        raise ValueError(f"Database has {len(unknown_database_ids)} candidates absent from template: {sample}")
    if int(progress["total_tasks"]) != len(rows):
        raise ValueError(
            f"Task/template count mismatch: database={progress['total_tasks']} template={len(rows)}"
        )

    merged: list[dict[str, str]] = []
    missing: list[str] = []
    uncertain: list[str] = []
    decision_counts: Counter[str] = Counter()
    for source_row in rows:
        row = dict(source_row)
        candidate_id = row["candidate_id"].strip()
        decision = decisions.get(candidate_id)
        if decision is None:
            row["reviewer_decision"] = ""
            row["reviewer_comment"] = ""
            row["reviewer_username"] = ""
            row["decided_at"] = ""
            missing.append(candidate_id)
        else:
            exported = DECISION_MAP.get(str(decision["decision"]))
            if exported is None:
                raise ValueError(f"Unsupported database decision: {decision['decision']!r}")
            row["reviewer_decision"] = exported
            row["reviewer_comment"] = str(decision.get("comment") or "")
            row["reviewer_username"] = str(decision.get("reviewer_username") or "")
            row["decided_at"] = str(decision.get("decided_at") or "")
            decision_counts[exported] += 1
            if exported == "uncertain":
                uncertain.append(candidate_id)
        merged.append(row)

    if not args.allow_incomplete and (missing or uncertain):
        raise ValueError(
            f"Review is not final: missing={len(missing)} uncertain={len(uncertain)}. "
            "Use --allow-incomplete only for a non-final progress snapshot."
        )

    output_fields = list(fields)
    for field in ("reviewer_username", "decided_at"):
        if field not in output_fields:
            output_fields.append(field)
    atomic_write_csv(output, output_fields, merged)

    summary = {
        **progress,
        "template": str(template),
        "output": str(output),
        "template_rows": len(rows),
        "exported_decisions": len(decisions),
        "missing_decisions": len(missing),
        "uncertain_decisions": len(uncertain),
        "allow_incomplete": args.allow_incomplete,
        "decision_counts": dict(sorted(decision_counts.items())),
        "output_sha256": sha256(output),
    }
    summary_path = output.with_suffix(output.suffix + ".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--mysql", type=Path, default=Path("mysql.exe"))
    parser.add_argument("--database", default="label_review")
    parser.add_argument("--allow-incomplete", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        summary = export_decisions(parse_args(argv))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
