"""
SQLite experiment history database — schema, queries, and disk-scan helpers.

Database is stored at <root>/experiments.db.
WAL mode is enabled for resilient concurrent reads during backfill.

Schema
------
qpu              : platform registry
qpu_qubits       : qubit labels per platform
experiment_runs  : one row per submitted experiment, kept in sync with disk
"""

import glob
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from qdashboard.utils.logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
# Connection management                                               #
# ------------------------------------------------------------------ #

def get_db_path(config: Dict[str, Any]) -> str:
    root = config.get("root") or os.path.expanduser("~/.qdashboard")
    return os.path.join(root, "experiments.db")


def get_db_connection(config: Dict[str, Any]) -> sqlite3.Connection:
    db_path = get_db_path(config)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ------------------------------------------------------------------ #
# Schema creation                                                     #
# ------------------------------------------------------------------ #

_CREATE_QPU = """
CREATE TABLE IF NOT EXISTS qpu (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_QPU_QUBITS = """
CREATE TABLE IF NOT EXISTS qpu_qubits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    qpu_id      INTEGER NOT NULL REFERENCES qpu(id) ON DELETE CASCADE,
    qubit_label TEXT    NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(qpu_id, qubit_label)
)
"""

_CREATE_EXPERIMENT_RUNS = """
CREATE TABLE IF NOT EXISTS experiment_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id         TEXT    UNIQUE NOT NULL,
    qpu_id                INTEGER REFERENCES qpu(id),
    protocol_id           TEXT    NOT NULL,
    protocol_name         TEXT,
    target_qubits         TEXT,          -- JSON array  ["q0","q1"]
    submitted_at          REAL,          -- Unix timestamp
    execution_time_seconds REAL,         -- sum of all stats acquisition+fit
    slurm_job_id          TEXT,
    status                TEXT    DEFAULT 'pending',
    fit_success           TEXT,          -- JSON dict  {"ssro-0": true, ...}
    overall_fit_success   INTEGER,       -- 1=all pass 0=any fail NULL=unknown
    runcard_path          TEXT,
    output_dir            TEXT,
    report_available      INTEGER DEFAULT 0,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_runs_qpu ON experiment_runs(qpu_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_protocol ON experiment_runs(protocol_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_submitted ON experiment_runs(submitted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON experiment_runs(status)",
]


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_QPU)
    conn.execute(_CREATE_QPU_QUBITS)
    conn.execute(_CREATE_EXPERIMENT_RUNS)
    for idx in _CREATE_INDEXES:
        conn.execute(idx)
    conn.commit()


# ------------------------------------------------------------------ #
# QPU helpers                                                        #
# ------------------------------------------------------------------ #

def get_or_create_qpu(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM qpu WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    conn.execute("INSERT INTO qpu(name) VALUES(?)", (name,))
    conn.commit()
    return conn.execute("SELECT id FROM qpu WHERE name=?", (name,)).fetchone()["id"]


def add_qpu_qubits(conn: sqlite3.Connection, qpu_id: int, qubit_labels: List[str]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO qpu_qubits(qpu_id, qubit_label) VALUES(?,?)",
        [(qpu_id, str(q)) for q in qubit_labels],
    )
    conn.commit()


# ------------------------------------------------------------------ #
# Experiment run upsert                                               #
# ------------------------------------------------------------------ #

def upsert_experiment_run(conn: sqlite3.Connection, data: Dict[str, Any]) -> None:
    """Insert or update an experiment_runs row from *data* dict."""
    conn.execute(
        """
        INSERT INTO experiment_runs (
            experiment_id, qpu_id, protocol_id, protocol_name,
            target_qubits, submitted_at, execution_time_seconds, slurm_job_id,
            status, fit_success, overall_fit_success,
            runcard_path, output_dir, report_available, updated_at
        ) VALUES (
            :experiment_id, :qpu_id, :protocol_id, :protocol_name,
            :target_qubits, :submitted_at, :execution_time_seconds, :slurm_job_id,
            :status, :fit_success, :overall_fit_success,
            :runcard_path, :output_dir, :report_available, :updated_at
        )
        ON CONFLICT(experiment_id) DO UPDATE SET
            qpu_id                = excluded.qpu_id,
            protocol_id           = excluded.protocol_id,
            protocol_name         = excluded.protocol_name,
            target_qubits         = excluded.target_qubits,
            submitted_at          = excluded.submitted_at,
            execution_time_seconds = excluded.execution_time_seconds,
            slurm_job_id          = excluded.slurm_job_id,
            status                = excluded.status,
            fit_success           = excluded.fit_success,
            overall_fit_success   = excluded.overall_fit_success,
            runcard_path          = excluded.runcard_path,
            output_dir            = excluded.output_dir,
            report_available      = excluded.report_available,
            updated_at            = excluded.updated_at
        """,
        {
            "experiment_id":          data.get("experiment_id", ""),
            "qpu_id":                 data.get("qpu_id"),
            "protocol_id":            data.get("protocol_id", "unknown"),
            "protocol_name":          data.get("protocol_name"),
            "target_qubits":          json.dumps(data.get("target_qubits") or []),
            "submitted_at":           data.get("submitted_at"),
            "execution_time_seconds": data.get("execution_time_seconds"),
            "slurm_job_id":           data.get("slurm_job_id"),
            "status":                 data.get("status", "pending"),
            "fit_success":            json.dumps(data.get("fit_success") or {}),
            "overall_fit_success":    data.get("overall_fit_success"),
            "runcard_path":           data.get("runcard_path"),
            "output_dir":             data.get("output_dir"),
            "report_available":       int(bool(data.get("report_available", False))),
            "updated_at":             data.get("updated_at", time.strftime("%Y-%m-%d %H:%M:%S")),
        },
    )
    conn.commit()


# ------------------------------------------------------------------ #
# Queries                                                             #
# ------------------------------------------------------------------ #

def _build_where(platform: str, protocol: str, status: str,
                 fit: str, date_from: str, date_to: str):
    clauses, params = [], []
    if platform:
        clauses.append("q.name = ?")
        params.append(platform)
    if protocol:
        clauses.append("r.protocol_id = ?")
        params.append(protocol)
    if status:
        clauses.append("r.status = ?")
        params.append(status)
    if fit == "pass":
        clauses.append("r.overall_fit_success = 1")
    elif fit == "fail":
        clauses.append("r.overall_fit_success = 0")
    elif fit == "partial":
        clauses.append("r.overall_fit_success IS NULL AND r.fit_success != '{}'")
    elif fit == "pending":
        clauses.append("r.overall_fit_success IS NULL")
    if date_from:
        try:
            ts = time.mktime(time.strptime(date_from, "%Y-%m-%d"))
            clauses.append("r.submitted_at >= ?")
            params.append(ts)
        except ValueError:
            pass
    if date_to:
        try:
            ts = time.mktime(time.strptime(date_to, "%Y-%m-%d")) + 86400
            clauses.append("r.submitted_at <= ?")
            params.append(ts)
        except ValueError:
            pass
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


_BASE_SELECT = """
    SELECT r.*, q.name as qpu_name
    FROM experiment_runs r
    LEFT JOIN qpu q ON q.id = r.qpu_id
"""


def query_runs(
    conn: sqlite3.Connection,
    platform: str = "",
    protocol: str = "",
    status: str = "",
    fit: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 25,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    where, params = _build_where(platform, protocol, status, fit, date_from, date_to)
    sql = f"{_BASE_SELECT} {where} ORDER BY r.submitted_at DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_runs(
    conn: sqlite3.Connection,
    platform: str = "",
    protocol: str = "",
    status: str = "",
    fit: str = "",
    date_from: str = "",
    date_to: str = "",
) -> int:
    where, params = _build_where(platform, protocol, status, fit, date_from, date_to)
    sql = f"SELECT COUNT(*) FROM experiment_runs r LEFT JOIN qpu q ON q.id=r.qpu_id {where}"
    return conn.execute(sql, params).fetchone()[0]


def get_run(conn: sqlite3.Connection, experiment_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"{_BASE_SELECT} WHERE r.experiment_id = ?", (experiment_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_distinct_protocols(conn: sqlite3.Connection) -> List[Dict[str, str]]:
    rows = conn.execute(
        "SELECT DISTINCT protocol_id, protocol_name FROM experiment_runs ORDER BY protocol_id"
    ).fetchall()
    return [{"id": r["protocol_id"], "name": r["protocol_name"] or r["protocol_id"]} for r in rows]


def get_distinct_qpus(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT name FROM qpu ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for json_field in ("target_qubits", "fit_success"):
        try:
            d[json_field] = json.loads(d[json_field]) if d.get(json_field) else []
        except (json.JSONDecodeError, TypeError):
            pass
    return d


# ------------------------------------------------------------------ #
# Disk-scan helpers                                                   #
# ------------------------------------------------------------------ #

def _read_json_safe(path: str) -> Optional[Dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _iter_actions(actions):
    """Yield individual action dicts regardless of whether *actions* is a
    list (qibocal standard) or a dict (keyed by action name)."""
    if isinstance(actions, list):
        yield from actions
    elif isinstance(actions, dict):
        yield from actions.values()


def _extract_protocol_info(runcard_data: Dict) -> tuple:
    """Return (protocol_id, protocol_name, target_qubits) from runcard.

    Works with both qibocal list-style actions and legacy dict-style actions.
    When multiple actions are present, *protocol_id* is the comma-joined list
    of all distinct action ids and *target_qubits* is the union of all targets.
    """
    actions = runcard_data.get("actions") or []
    if not actions:
        return "unknown", "Unknown", []

    # Runcard-level targets apply to any action that doesn't override them
    global_targets = runcard_data.get("targets") or []
    if not isinstance(global_targets, (list, tuple)):
        global_targets = [global_targets]

    seen_ids: list = []
    all_qubits: set = set()
    for action in _iter_actions(actions):
        aid = action.get("id", "unknown")
        if aid not in seen_ids:
            seen_ids.append(aid)
        targets = action.get("targets") or action.get("qubits") or global_targets
        if isinstance(targets, (list, tuple)):
            all_qubits.update(str(q) for q in targets)
        elif targets:
            all_qubits.add(str(targets))

    protocol_id = ",".join(seen_ids) if seen_ids else "unknown"
    protocol_name = " + ".join(pid.replace("_", " ").title() for pid in seen_ids)
    return protocol_id, protocol_name, sorted(all_qubits)


def _compute_execution_time(meta: Dict) -> Optional[float]:
    """Sum acquisition+fit across all routines in meta.json stats."""
    stats = meta.get("stats") or {}
    if not stats:
        return None
    total = 0.0
    for v in stats.values():
        total += (v.get("acquisition") or 0) + (v.get("fit") or 0)
    return total if total > 0 else None


def _compute_fit_success(output_dir: str, meta: Dict) -> tuple:
    """
    Returns (fit_success_dict, overall_fit_success).
    fit_success_dict: {routine_id: bool} based on presence of results.json
    overall_fit_success: 1 if all routines have results.json, 0 if any missing,
                         None if no stats info.
    """
    stats = (meta or {}).get("stats") or {}
    if not stats:
        return {}, None

    data_dir = os.path.join(output_dir, "data")
    fit_success = {}
    for routine_id in stats:
        results_path = os.path.join(data_dir, routine_id, "results.json")
        fit_success[routine_id] = os.path.exists(results_path)

    all_pass = all(fit_success.values())
    any_pass = any(fit_success.values())
    if all_pass:
        overall = 1
    elif not any_pass:
        overall = 0
    else:
        overall = None  # partial — represented as NULL in DB
    return fit_success, overall


def scan_experiment_dir(experiment_dir: str) -> Optional[Dict[str, Any]]:
    """
    Read all available info from one experiment directory.
    Returns a dict suitable for upsert_experiment_run, or None if the
    directory is not a valid experiment.
    """
    metadata_path = os.path.join(experiment_dir, "experiment_metadata.json")
    if not os.path.exists(metadata_path):
        return None

    metadata = _read_json_safe(metadata_path)
    if not metadata:
        return None

    experiment_id = metadata.get("experiment_id")
    if not experiment_id:
        return None

    platform = metadata.get("platform", "unknown")
    output_dir = metadata.get("output_dir") or os.path.join(experiment_dir, "output")

    # Read runcard for protocol + qubit info
    runcard_path = metadata.get("runcard_path") or os.path.join(experiment_dir, "runcard.yml")
    protocol_id, protocol_name, target_qubits = "unknown", "Unknown", []
    try:
        import yaml
        with open(runcard_path) as f:
            rc = yaml.safe_load(f)
        if rc:
            protocol_id, protocol_name, target_qubits = _extract_protocol_info(rc)
    except Exception:
        pass

    # Read output/meta.json for timing and fit info
    meta = _read_json_safe(os.path.join(output_dir, "meta.json"))
    exec_time = _compute_execution_time(meta) if meta else None
    fit_success, overall_fit = ({}, None) if not meta else _compute_fit_success(output_dir, meta)

    # Determine status
    report_available = os.path.exists(os.path.join(output_dir, "index.html"))
    if meta:
        status = "completed"
    elif os.path.exists(output_dir):
        status = "running"
    else:
        status = "pending"

    return {
        "experiment_id":          experiment_id,
        "platform":               platform,
        "protocol_id":            protocol_id,
        "protocol_name":          protocol_name,
        "target_qubits":          target_qubits,
        "submitted_at":           metadata.get("submitted_at"),
        "execution_time_seconds": exec_time,
        "slurm_job_id":           metadata.get("job_id"),
        "status":                 status,
        "fit_success":            fit_success,
        "overall_fit_success":    overall_fit,
        "runcard_path":           runcard_path,
        "output_dir":             output_dir,
        "report_available":       report_available,
    }


def refresh_run_status(
    conn: sqlite3.Connection, experiment_id: str, experiment_dir: str
) -> Optional[Dict[str, Any]]:
    """Re-scan one experiment dir, update DB, and return the updated row."""
    scanned = scan_experiment_dir(experiment_dir)
    if not scanned:
        return None
    row = get_run(conn, experiment_id)
    qpu_id = row["qpu_id"] if row else get_or_create_qpu(conn, scanned["platform"])
    scanned["qpu_id"] = qpu_id
    upsert_experiment_run(conn, scanned)
    return get_run(conn, experiment_id)


# ------------------------------------------------------------------ #
# Backfill                                                            #
# ------------------------------------------------------------------ #

_MAX_PER_PLATFORM = 200


def backfill_from_disk(config: Dict[str, Any]) -> int:
    """
    Walk data_dir and upsert experiment records not yet in the DB.
    Returns the count of records inserted/updated.
    """
    data_dir = config.get("data_dir") or os.path.join(
        config.get("root", os.path.expanduser("~/.qdashboard")), "data"
    )
    if not os.path.exists(data_dir):
        logger.info("backfill: data_dir does not exist, skipping")
        return 0

    conn = get_db_connection(config)
    try:
        count = 0
        # Walk platform directories
        for platform_name in os.listdir(data_dir):
            platform_dir = os.path.join(data_dir, platform_name)
            if not os.path.isdir(platform_dir) or platform_name.startswith("."):
                continue

            # Collect all experiment dirs (platform/date/experiment_id)
            exp_dirs = glob.glob(os.path.join(platform_dir, "*", "*"))
            exp_dirs = [d for d in exp_dirs if os.path.isdir(d)]

            # Sort newest-first by directory mtime, cap at MAX_PER_PLATFORM
            exp_dirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)
            exp_dirs = exp_dirs[:_MAX_PER_PLATFORM]

            qpu_id = get_or_create_qpu(conn, platform_name)

            for exp_dir in exp_dirs:
                try:
                    scanned = scan_experiment_dir(exp_dir)
                    if not scanned:
                        continue
                    scanned["qpu_id"] = qpu_id
                    # Register qubits
                    if scanned.get("target_qubits"):
                        add_qpu_qubits(conn, qpu_id, scanned["target_qubits"])
                    upsert_experiment_run(conn, scanned)
                    count += 1
                except Exception as exc:
                    logger.debug(f"backfill: skipping {exp_dir}: {exc}")

        logger.info(f"backfill: upserted {count} experiment records")
        return count
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Initialisation                                                      #
# ------------------------------------------------------------------ #

def init_db(config: Dict[str, Any]) -> None:
    """Create schema and backfill from disk. Called at app startup."""
    try:
        conn = get_db_connection(config)
        _create_schema(conn)
        conn.close()
        backfill_from_disk(config)
        logger.info("Experiment history database initialised")
    except Exception as exc:
        logger.error(f"Failed to initialise experiment DB: {exc}")
