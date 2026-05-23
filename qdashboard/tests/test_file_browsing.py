"""
Tests for file browsing — is_qibocal_report detection, path-safety,
partial content, and format/icon utilities.
"""

import os
import pytest
from starlette.requests import Request
from starlette.datastructures import Headers


# ---------------------------------------------------------------------------
# is_qibocal_report
# ---------------------------------------------------------------------------

class TestIsQibocalReport:
    def test_valid_report_directory(self, tmp_path):
        from qdashboard.web.file_browser import is_qibocal_report
        (tmp_path / 'meta.json').write_text('{}')
        (tmp_path / 'runcard.yml').write_text('platform: dummy')
        assert is_qibocal_report(str(tmp_path)) is True

    def test_missing_meta_json(self, tmp_path):
        from qdashboard.web.file_browser import is_qibocal_report
        (tmp_path / 'runcard.yml').write_text('platform: dummy')
        assert is_qibocal_report(str(tmp_path)) is False

    def test_missing_runcard_yml(self, tmp_path):
        from qdashboard.web.file_browser import is_qibocal_report
        (tmp_path / 'meta.json').write_text('{}')
        assert is_qibocal_report(str(tmp_path)) is False

    def test_non_existent_path(self, tmp_path):
        from qdashboard.web.file_browser import is_qibocal_report
        assert is_qibocal_report(str(tmp_path / 'nowhere')) is False

    def test_plain_file_not_directory(self, tmp_path):
        from qdashboard.web.file_browser import is_qibocal_report
        f = tmp_path / 'file.txt'
        f.write_text('hello')
        assert is_qibocal_report(str(f)) is False


# ---------------------------------------------------------------------------
# get_range — HTTP Range header parsing
# ---------------------------------------------------------------------------

class TestGetRange:
    def _make_request(self, range_header):
        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/',
            'query_string': b'',
            'headers': [(b'range', range_header.encode())] if range_header else [],
        }
        return Request(scope)

    def test_parses_full_range(self):
        from qdashboard.web.file_browser import get_range
        req = self._make_request('bytes=0-1023')
        start, end = get_range(req)
        assert start == 0
        assert end == 1023

    def test_parses_open_ended_range(self):
        from qdashboard.web.file_browser import get_range
        req = self._make_request('bytes=512-')
        start, end = get_range(req)
        assert start == 512
        assert end is None

    def test_no_range_header(self):
        from qdashboard.web.file_browser import get_range
        req = self._make_request(None)
        result = get_range(req)
        # function returns (0, None) when no Range header is present
        assert result == (0, None)


# ---------------------------------------------------------------------------
# partial_response — Content-Range / 206 status
# ---------------------------------------------------------------------------

class TestPartialResponse:
    def test_returns_206_status(self, tmp_path):
        from qdashboard.web.file_browser import partial_response
        f = tmp_path / 'data.bin'
        f.write_bytes(b'0123456789')
        resp = partial_response(str(f), 0, 4)
        assert resp.status_code == 206

    def test_returns_correct_bytes(self, tmp_path):
        from qdashboard.web.file_browser import partial_response
        f = tmp_path / 'data.bin'
        f.write_bytes(b'ABCDEFGHIJ')
        resp = partial_response(str(f), 2, 5)
        # body should contain bytes at offsets 2-5
        assert b'CD' in resp.body

    def test_content_range_header(self, tmp_path):
        from qdashboard.web.file_browser import partial_response
        f = tmp_path / 'data.bin'
        f.write_bytes(b'0123456789')
        resp = partial_response(str(f), 0, 4)
        assert 'content-range' in dict(resp.headers)


# ---------------------------------------------------------------------------
# Format/icon utilities (size_fmt, icon_fmt, time_fmt)
# ---------------------------------------------------------------------------

class TestFormatUtilities:
    def test_size_fmt_bytes(self):
        from qdashboard.utils.formatters import size_fmt
        assert 'bytes' in size_fmt(500)

    def test_size_fmt_kilobytes(self):
        from qdashboard.utils.formatters import size_fmt
        result = size_fmt(2048)
        assert 'KB' in result

    def test_size_fmt_megabytes(self):
        from qdashboard.utils.formatters import size_fmt
        result = size_fmt(2 * 1024 * 1024)
        assert 'M' in result

    def test_icon_fmt_default(self):
        from qdashboard.utils.formatters import icon_fmt
        # icon_fmt takes a filename string; unknown extensions return 'fa-file-o'
        result = icon_fmt('unknown_file')
        assert result == 'fa-file-o'

    def test_icon_fmt_yaml(self):
        from qdashboard.utils.formatters import icon_fmt
        # yml is in the 'fa-code' group
        result = icon_fmt('config.yml')
        assert result == 'fa-code'
