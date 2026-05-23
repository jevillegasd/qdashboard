"""
Tests for report rendering — asset-path rewriting, fragment extraction,
full-report HTML, and qibocal availability checking.
"""

import os
import pytest


# ---------------------------------------------------------------------------
# _rewrite_asset_paths
# ---------------------------------------------------------------------------

class TestRewriteAssetPaths:
    def test_rewrites_css_href(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        html = '<link href="css/style.css" rel="stylesheet">'
        result = _rewrite_asset_paths(html, 'exp123')
        # path is prefixed with the base; original filename appears as suffix
        assert 'href="exp123/css/style.css"' in result

    def test_rewrites_js_src(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        html = '<script src="js/app.js"></script>'
        result = _rewrite_asset_paths(html, 'exp123')
        assert 'src="exp123/js/app.js"' in result

    def test_rewrites_img_src(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        html = '<img src="images/plot.png">'
        result = _rewrite_asset_paths(html, 'exp123')
        assert 'src="exp123/images/plot.png"' in result

    def test_preserves_absolute_urls(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        html = '<link href="https://cdn.example.com/style.css">'
        result = _rewrite_asset_paths(html, 'exp123')
        assert 'https://cdn.example.com/style.css' in result

    def test_no_modification_on_empty_html(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        result = _rewrite_asset_paths('', 'exp123')
        assert result == ''

    def test_rewrites_data_src(self):
        from qdashboard.web.reports import _rewrite_asset_paths
        # Use a plain .json attribute that isn't also caught by the .js rule
        html = '<div data-src="results.json"></div>'
        result = _rewrite_asset_paths(html, 'exp456')
        assert 'exp456' in result


# ---------------------------------------------------------------------------
# get_report_fragment
# ---------------------------------------------------------------------------

class TestGetReportFragment:
    def _make_report(self, tmp_path, html_content):
        report_dir = tmp_path / 'report'
        report_dir.mkdir()
        (report_dir / 'index.html').write_text(html_content)
        (report_dir / 'meta.json').write_text('{}')
        (report_dir / 'runcard.yml').write_text('platform: dummy')
        return str(report_dir)

    def test_returns_dict_with_expected_keys(self, tmp_path):
        from qdashboard.web.reports import get_report_fragment
        html = '<html><head><link href="style.css"></head><body><p>Hello</p></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_report_fragment('exp001', report_path)
        assert isinstance(result, dict)
        assert 'head_css' in result
        assert 'body_html' in result

    def test_body_html_contains_content(self, tmp_path):
        from qdashboard.web.reports import get_report_fragment
        html = '<html><head></head><body><h1 id="title">My Report</h1></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_report_fragment('exp002', report_path)
        assert 'My Report' in result['body_html']

    def test_head_css_contains_rewritten_link(self, tmp_path):
        from qdashboard.web.reports import get_report_fragment
        html = '<html><head><link href="style.css" rel="stylesheet"></head><body></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_report_fragment('exp003', report_path)
        # The path is rewritten: it should no longer start with just 'style.css'
        assert 'href="style.css"' not in result['head_css']
        assert 'exp003' in result['head_css'] or '/api/experiment_assets/exp003' in result['head_css']

    def test_missing_index_raises(self, tmp_path):
        from qdashboard.web.reports import get_report_fragment
        report_dir = tmp_path / 'empty_report'
        report_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            get_report_fragment('exp_bad', str(report_dir))

    def test_rewritten_path_uses_experiment_id(self, tmp_path):
        from qdashboard.web.reports import get_report_fragment
        html = '<html><head><link href="a.css"></head><body><img src="b.png"></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_report_fragment('myexp', report_path)
        combined = result.get('head_css', '') + result.get('body_html', '')
        assert 'myexp' in combined


# ---------------------------------------------------------------------------
# get_full_report_html
# ---------------------------------------------------------------------------

class TestGetFullReportHtml:
    def _make_report(self, tmp_path, html_content):
        report_dir = tmp_path / 'report'
        report_dir.mkdir()
        (report_dir / 'index.html').write_text(html_content)
        (report_dir / 'meta.json').write_text('{}')
        (report_dir / 'runcard.yml').write_text('platform: dummy')
        return str(report_dir)

    def test_returns_string(self, tmp_path):
        from qdashboard.web.reports import get_full_report_html
        html = '<html><head></head><body><p>Full report</p></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_full_report_html('exp001', report_path)
        assert isinstance(result, str)
        assert 'Full report' in result

    def test_assets_are_rewritten(self, tmp_path):
        from qdashboard.web.reports import get_full_report_html
        html = '<html><head><link href="x.css"></head><body></body></html>'
        report_path = self._make_report(tmp_path, html)
        result = get_full_report_html('rexp', report_path)
        # Original bare href is gone; rewritten path contains the experiment id
        assert 'href="x.css"' not in result
        assert 'rexp' in result


# ---------------------------------------------------------------------------
# check_qibocal_availability
# ---------------------------------------------------------------------------

class TestCheckQibocalAvailability:
    def test_returns_bool(self):
        from qdashboard.web.reports import check_qibocal_availability
        result = check_qibocal_availability()
        assert isinstance(result, bool)

    def test_returns_false_when_qq_missing(self, monkeypatch):
        import subprocess
        from qdashboard.web import reports as rmod
        monkeypatch.setattr(subprocess, 'run',
                            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        result = rmod.check_qibocal_availability()
        assert result is False
