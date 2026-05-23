"""
Tests for experiment submission — job creation, runcard preparation,
config management, and the SignalDisabler used during protocol discovery.
"""

import os
import signal
import pytest


# ---------------------------------------------------------------------------
# SignalDisabler (used by protocol discovery at experiment setup)
# ---------------------------------------------------------------------------

class TestSignalDisabler:
    def test_suppresses_signal_calls(self):
        from qdashboard.utils.signals import SignalDisabler

        calls = []
        original = signal.signal
        spy = lambda sig, h: calls.append((sig, h))
        signal.signal = spy
        try:
            with SignalDisabler():
                signal.signal(signal.SIGINT, signal.SIG_DFL)
            assert signal.signal is spy
        finally:
            signal.signal = original

        assert calls == [], "SignalDisabler should suppress signal.signal calls inside the block"

    def test_restores_on_exception(self):
        from qdashboard.utils.signals import SignalDisabler

        original = signal.signal
        try:
            with SignalDisabler():
                raise RuntimeError("test")
        except RuntimeError:
            pass
        assert signal.signal is original


# ---------------------------------------------------------------------------
# Config (required by all submission paths)
# ---------------------------------------------------------------------------

class TestConfig:
    def test_get_app_config_removed(self):
        import qdashboard.core.config as cfg
        assert not hasattr(cfg, 'get_app_config'), "get_app_config alias should have been removed"

    def test_set_and_get_config(self):
        from qdashboard.core.config import set_config, get_config
        set_config({'port': 9999, 'root': '/tmp'})
        assert get_config()['port'] == 9999

    def test_get_config_raises_before_set(self):
        from qdashboard.core.config import ConfigError
        import qdashboard.core.config as cfg
        old = cfg._config.copy()
        cfg._config.clear()
        try:
            with pytest.raises(ConfigError):
                cfg.get_config()
        finally:
            cfg._config.update(old)

    def test_ensure_directory_exists(self, tmp_path):
        from qdashboard.core.config import ensure_directory_exists
        result = ensure_directory_exists(str(tmp_path / 'a' / 'b' / 'c'))
        assert os.path.isdir(result)

    def test_validate_config_valid(self, tmp_path):
        from qdashboard.core.config import validate_config
        cfg = {'port': 5005, 'root': str(tmp_path), 'qd_root': str(tmp_path / 'qd')}
        validate_config(cfg)
        for sub in ('logs', 'data', 'temp'):
            assert os.path.isdir(str(tmp_path / 'qd' / sub))

    def test_validate_config_bad_port(self):
        from qdashboard.core.config import validate_config, ConfigError
        with pytest.raises(ConfigError):
            validate_config({'port': 99999})

    def test_validate_config_missing_root(self):
        from qdashboard.core.config import validate_config, ConfigError
        with pytest.raises(ConfigError):
            validate_config({'port': 5005, 'root': '/no/such/path/qdash_test'})


# ---------------------------------------------------------------------------
# Response helpers used by submission API routes
# ---------------------------------------------------------------------------

class TestResponseHelpers:
    def test_yaml_response(self):
        from qdashboard.utils.formatters import yaml_response
        resp = yaml_response({'key': 'value'})
        assert resp.status_code == 200
        assert b'key' in resp.body

    def test_json_response(self):
        from qdashboard.utils.formatters import json_response
        resp = json_response({'x': 1})
        assert resp.status_code == 200
        assert b'"x"' in resp.body

    def test_dead_file_io_functions_removed(self):
        import qdashboard.utils.formatters as fmt
        for name in ('read_yaml_file', 'write_yaml_file', 'read_json_file', 'write_json_file'):
            assert not hasattr(fmt, name), f"{name} should have been removed"


# ---------------------------------------------------------------------------
# Job submission — runcard preparation and experiment directory creation
# ---------------------------------------------------------------------------

class TestJobSubmission:
    def test_prepare_runcard_legacy_removed(self):
        import qdashboard.experiments.job_submission as js
        assert not hasattr(js, 'prepare_runcard'), \
            "Legacy prepare_runcard wrapper should have been removed"

    def test_prepare_runcard_from_path(self, tmp_path):
        from qdashboard.experiments.job_submission import prepare_runcard_from_path
        runcard = tmp_path / 'runcard.yml'
        runcard.write_text('platform: dummy\nactions: []\n')
        exp_dir = tmp_path / 'exp'
        exp_dir.mkdir()
        dest, data = prepare_runcard_from_path(str(runcard), str(exp_dir))
        assert os.path.exists(dest)
        assert data['platform'] == 'dummy'

    def test_prepare_runcard_from_path_missing_file(self, tmp_path):
        from qdashboard.experiments.job_submission import prepare_runcard_from_path
        with pytest.raises(FileNotFoundError):
            prepare_runcard_from_path(str(tmp_path / 'nope.yml'), str(tmp_path))

    def test_prepare_runcard_from_data(self, tmp_path):
        from qdashboard.experiments.job_submission import prepare_runcard_from_data
        exp_dir = tmp_path / 'exp'
        exp_dir.mkdir()
        dest, data = prepare_runcard_from_data({'platform': 'dummy'}, str(exp_dir))
        assert os.path.exists(dest)
        assert data['platform'] == 'dummy'

    def test_prepare_runcard_from_data_missing_platform(self, tmp_path):
        from qdashboard.experiments.job_submission import prepare_runcard_from_data
        with pytest.raises(ValueError, match="platform"):
            prepare_runcard_from_data({'actions': []}, str(tmp_path))

    def test_generate_experiment_id_format(self, tmp_path):
        from qdashboard.experiments.job_submission import generate_experiment_id
        exp_id = generate_experiment_id(str(tmp_path / 'rc.yml'), 'myplatform')
        parts = exp_id.split('-')
        assert len(parts) == 2
        assert len(parts[0]) == 8   # YYYYMMDD
        assert len(parts[1]) == 6   # hex hash

    def test_generate_experiment_id_unique(self, tmp_path):
        import time
        from qdashboard.experiments.job_submission import generate_experiment_id
        id1 = generate_experiment_id(str(tmp_path / 'r.yml'), 'p1')
        time.sleep(0.01)
        id2 = generate_experiment_id(str(tmp_path / 'r.yml'), 'p2')
        assert id1 != id2

    def test_create_experiment_directory(self, tmp_path):
        from qdashboard.experiments.job_submission import (
            generate_experiment_id, create_experiment_directory,
        )
        runcard = tmp_path / 'rc.yml'
        runcard.write_text('platform: dummy\n')
        exp_id = generate_experiment_id(str(runcard), 'dummy')
        config = {'qd_root': str(tmp_path), 'data_dir': str(tmp_path / 'data')}
        exp_dir = create_experiment_directory(exp_id, 'dummy', config)
        assert os.path.isdir(exp_dir)
        assert exp_id in exp_dir
