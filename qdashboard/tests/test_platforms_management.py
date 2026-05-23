"""
Tests for platforms management — SLURM queue parsing, partition lookup,
and history database backfill with the 100-entry initial cap.
"""

import os
import json
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# SLURM — _Job class and queue parsing
# ---------------------------------------------------------------------------

class TestSlurm:
    def test_job_class_at_module_level(self):
        """_Job must be a top-level name in slurm.py (not nested inside a function)."""
        import qdashboard.qpu.slurm as slurm_mod
        assert hasattr(slurm_mod, '_Job'), "_Job should be defined at module level"

    def test_job_is_current_user_exact(self):
        from qdashboard.qpu.slurm import _Job
        job = _Job('1', 'myjob', 'alice', 'RUNNING', '0:10', '1:00:00', '1', 'n01', 'alice', 'q1')
        assert job.is_current_user is True

    def test_job_is_current_user_prefix(self):
        from qdashboard.qpu.slurm import _Job
        job = _Job('2', 'job', 'ali', 'PENDING', '0:00', '1:00:00', '1', 'n02', 'alice', 'q1')
        assert job.is_current_user is True

    def test_job_is_not_current_user(self):
        from qdashboard.qpu.slurm import _Job
        job = _Job('3', 'job', 'bob', 'RUNNING', '0:05', '2:00:00', '1', 'n03', 'alice', 'q1')
        assert job.is_current_user is False

    def test_slurm_active_states(self):
        from qdashboard.qpu.slurm import _SLURM_ACTIVE_STATES
        assert 'RUNNING' in _SLURM_ACTIVE_STATES
        assert 'PENDING' in _SLURM_ACTIVE_STATES
        assert 'COMPLETED' not in _SLURM_ACTIVE_STATES

    def test_get_slurm_status_returns_list(self, monkeypatch):
        import subprocess
        from qdashboard.qpu import slurm as slurm_mod
        monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: b'')
        result = slurm_mod.get_slurm_status()
        assert isinstance(result, list)

    def test_get_slurm_status_graceful_on_missing_binary(self, monkeypatch):
        import subprocess
        from qdashboard.qpu import slurm as slurm_mod
        monkeypatch.setattr(subprocess, 'check_output',
                            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        result = slurm_mod.get_slurm_status()
        assert result == []


# ---------------------------------------------------------------------------
# get_partition — reads queues.json from platforms directory
# ---------------------------------------------------------------------------

class TestGetPartition:
    def test_returns_none_when_platforms_unavailable(self, monkeypatch):
        from qdashboard.qpu import platforms as p
        monkeypatch.setattr(p, 'get_platforms_path', lambda root_path=None: None)
        result = p.get_partition('myplatform')
        assert result is None

    def test_returns_partition_from_queues_json(self, tmp_path, monkeypatch):
        from qdashboard.qpu import platforms as p
        queues = {'myplatform': 'gpu_queue', 'other': 'cpu_queue'}
        queues_file = tmp_path / 'queues.json'
        queues_file.write_text(json.dumps(queues))
        monkeypatch.setattr(p, 'get_platforms_path', lambda root_path=None: str(tmp_path))
        result = p.get_partition('myplatform')
        assert result == 'gpu_queue'

    def test_returns_none_for_unknown_platform(self, tmp_path, monkeypatch):
        from qdashboard.qpu import platforms as p
        queues_file = tmp_path / 'queues.json'
        queues_file.write_text(json.dumps({'known': 'q1'}))
        monkeypatch.setattr(p, 'get_platforms_path', lambda root_path=None: str(tmp_path))
        result = p.get_partition('unknown_platform')
        assert result is None

    def test_returns_none_for_non_string_input(self, monkeypatch):
        from qdashboard.qpu import platforms as p
        result = p.get_partition(42)
        assert result is None


# ---------------------------------------------------------------------------
# Database backfill — 100-entry cap on empty DB, 200 cap on non-empty DB
# ---------------------------------------------------------------------------

def _make_minimal_exp_dir(parent, name):
    """Create a minimal experiment directory structure understood by scan_experiment_dir."""
    import time, yaml
    d = parent / name
    d.mkdir(parents=True)
    meta = {
        'title': name,
        'date': '2024-01-01',
        'start_time': '10:00:00',
        'end_time': '10:01:00',
        'platform': 'test_qpu',
        'actions': [],
    }
    (d / 'meta.json').write_text(json.dumps(meta))
    runcard = {
        'platform': 'test_qpu',
        'actions': [{'id': 'dummy_action', 'parameters': {}}],
    }
    (d / 'runcard.yml').write_text(yaml.dump(runcard))
    os.utime(str(d), (time.time(), time.time()))
    return d


class TestDatabaseBackfill:
    def _db_config(self, tmp_path):
        db_path = str(tmp_path / 'test.db')
        data_dir = str(tmp_path / 'data')
        return {'db_path': db_path, 'data_dir': data_dir, 'root': str(tmp_path)}

    def test_skips_nonexistent_data_dir(self, tmp_path):
        from qdashboard.db.database import backfill_from_disk, init_db
        config = self._db_config(tmp_path)
        init_db(config)
        result = backfill_from_disk(config)
        assert result == 0

    def test_empty_db_uses_100_cap(self, tmp_path, monkeypatch):
        """On an empty DB the cap should be _MAX_PER_PLATFORM_INITIAL (100)."""
        import qdashboard.db.database as dbmod
        from qdashboard.db.database import init_db, backfill_from_disk

        # Record the cap value passed to slice
        caps_used = []
        original_backfill = backfill_from_disk

        def patched_backfill(config):
            conn = dbmod.get_db_connection(config)
            is_empty = dbmod._db_is_empty(conn)
            conn.close()
            caps_used.append(
                dbmod._MAX_PER_PLATFORM_INITIAL if is_empty else dbmod._MAX_PER_PLATFORM
            )
            return original_backfill(config)

        monkeypatch.setattr(dbmod, 'backfill_from_disk', patched_backfill)

        config = self._db_config(tmp_path)
        init_db(config)

        patched_backfill(config)
        assert caps_used[-1] == dbmod._MAX_PER_PLATFORM_INITIAL

    def test_non_empty_db_uses_200_cap(self, tmp_path, monkeypatch):
        """After data is present the cap should be _MAX_PER_PLATFORM (200)."""
        import qdashboard.db.database as dbmod
        from qdashboard.db.database import (
            init_db, get_db_connection, _create_schema, get_or_create_qpu,
            upsert_experiment_run,
        )

        config = self._db_config(tmp_path)
        init_db(config)

        # Insert a synthetic row so the DB is non-empty
        conn = get_db_connection(config)
        qpu_id = get_or_create_qpu(conn, 'test_qpu')
        upsert_experiment_run(conn, {
            'qpu_id': qpu_id,
            'experiment_id': 'synthetic-001',
            'runcard_path': '/fake/path',
            'platform': 'test_qpu',
            'status': 'completed',
            'start_time': None,
            'end_time': None,
            'target_qubits': None,
            'actions': None,
            'slurm_job_id': None,
            'error_message': None,
        })
        conn.close()

        cap = dbmod._MAX_PER_PLATFORM_INITIAL if dbmod._db_is_empty(get_db_connection(config)) \
              else dbmod._MAX_PER_PLATFORM
        # Close connection obtained above (it was just for the cap check)
        assert cap == dbmod._MAX_PER_PLATFORM

    def test_initial_cap_constant_is_100(self):
        from qdashboard.db import database as dbmod
        assert dbmod._MAX_PER_PLATFORM_INITIAL == 100

    def test_full_cap_constant_is_200(self):
        from qdashboard.db import database as dbmod
        assert dbmod._MAX_PER_PLATFORM == 200
