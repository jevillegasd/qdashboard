// Experiment History side panel: compact list (not a wide table, this lives in
// a ~300px sidebar) with the same filter/pagination API calls as before.
// Extracted from the legacy history.html page.
(function () {
    'use strict';

    var currentPage = 1;
    var perPage = 20;
    var debounceTimer;

    function fmtDate(ts) {
        if (!ts) return '—';
        var d = new Date(ts * 1000);
        return d.toISOString().slice(0, 16).replace('T', ' ');
    }

    function fmtExec(secs) {
        if (secs == null) return '—';
        if (secs < 60) return secs.toFixed(1) + ' s';
        return (secs / 60).toFixed(1) + ' min';
    }

    function statusBadge(s) {
        var cls = { pending: 'badge-pending', running: 'badge-running',
                    completed: 'badge-completed', failed: 'badge-failed' }[s] || 'badge-secondary';
        return '<span class="badge ' + cls + '">' + (s || '—') + '</span>';
    }

    function fitBadge(overall) {
        if (overall === 1) return '<span class="badge badge-fit-pass"><i class="fas fa-check"></i></span>';
        if (overall === 0) return '<span class="badge badge-fit-fail"><i class="fas fa-times"></i></span>';
        return '<span class="badge badge-fit-unknown">—</span>';
    }

    function fmtQubits(qubits) {
        if (!qubits || !qubits.length) return '—';
        var joined = qubits.join(',');
        return joined.length > 18 ? joined.slice(0, 16) + '…' : joined;
    }

    function loadHistory(page) {
        currentPage = page || 1;
        var params = {
            platform:  $('#filter-platform').val(),
            protocol:  $('#filter-protocol').val(),
            status:    $('#filter-status').val(),
            fit:       $('#filter-fit').val(),
            date_from: $('#filter-date-from').val(),
            date_to:   $('#filter-date-to').val(),
            page:      currentPage,
            per_page:  perPage
        };
        $.getJSON('/api/history', params)
            .done(function (data) {
                renderRows(data.runs);
                renderPagination(data.total, data.pages);
                $('#history-count-label').text(data.total + ' experiment(s)');
            })
            .fail(function () {
                $('#history-list').html(
                    '<div class="text-center text-danger py-3">Failed to load history.</div>'
                );
            });
    }

    function renderRows(runs) {
        if (!runs || !runs.length) {
            $('#history-list').html(
                '<div class="text-center text-muted py-4 small">No experiments found.</div>'
            );
            return;
        }
        var html = '';
        runs.forEach(function (r) {
            var reportBtn = r.report_available
                ? '<button class="btn-doc-info" title="Open report" onclick="openHistoryReport(\'' + r.experiment_id + '\', \'' + (r.protocol_name || r.protocol_id || r.experiment_id) + '\')">'
                  + '<i class="fas fa-chart-bar"></i></button>'
                : '';
            var explorerBtn = r.explorer_path
                ? '<button class="btn-doc-info" title="Open experiment directory" onclick="openHistoryDirectory(\'' + r.explorer_path + '\')">'
                  + '<i class="fas fa-folder-open"></i></button>'
                : '';
            var refreshBtn = '<button class="btn-doc-info" title="Refresh" onclick="refreshRun(\'' + r.experiment_id + '\')">'
                + '<i class="fas fa-sync-alt"></i></button>';
            html += '<div class="vsc-list-row history-row">'
                + '<div class="flex-grow-1" style="overflow:hidden;">'
                + '<div class="d-flex align-items-center" style="gap:.3rem;">'
                + statusBadge(r.status) + fitBadge(r.overall_fit_success)
                + '<span class="text-truncate small">' + (r.protocol_name || r.protocol_id || '—') + '</span>'
                + '</div>'
                + '<div class="text-muted" style="font-size:.68rem;" title="Qubits: ' + (r.target_qubits || []).join(', ') + '">'
                + (r.qpu_name || '—') + ' · <i class="fas fa-microchip"></i> ' + fmtQubits(r.target_qubits) + ' · ' + fmtDate(r.submitted_at) + ' · ' + fmtExec(r.execution_time_seconds)
                + '</div>'
                + '</div>'
                + '<div class="text-nowrap">' + explorerBtn + reportBtn + refreshBtn + '</div>'
                + '</div>';
        });
        $('#history-list').html(html);
    }

    function renderPagination(total, pages) {
        var html = '';
        if (pages <= 1) { $('#history-pagination').html(''); return; }
        if (currentPage > 1) {
            html += '<li class="page-item"><a class="page-link" href="#" data-page="' + (currentPage - 1) + '">&laquo;</a></li>';
        }
        var start = Math.max(1, currentPage - 1);
        var end = Math.min(pages, currentPage + 1);
        for (var p = start; p <= end; p++) {
            html += '<li class="page-item' + (p === currentPage ? ' active' : '') + '">'
                + '<a class="page-link" href="#" data-page="' + p + '">' + p + '</a></li>';
        }
        if (currentPage < pages) {
            html += '<li class="page-item"><a class="page-link" href="#" data-page="' + (currentPage + 1) + '">&raquo;</a></li>';
        }
        $('#history-pagination').html(html);
    }

    // Opening a report now opens a shell tab (iframe) instead of a Bootstrap modal.
    window.openHistoryReport = function (experimentId, label) {
        if (window.ShellTabs && typeof window.ShellTabs.openReportTab === 'function') {
            window.ShellTabs.openReportTab(experimentId, label);
        }
    };

    window.openHistoryDirectory = function (explorerPath) {
        if (window.ShellPanel) window.ShellPanel.show('explorer');
        if (window.ExplorerPanel) window.ExplorerPanel.init(explorerPath);
    };

    window.refreshRun = function (experimentId) {
        $.post('/api/history/' + experimentId + '/refresh')
            .done(function () { loadHistory(currentPage); })
            .fail(function () { alert('Failed to refresh run ' + experimentId); });
    };

    function updateActiveFilterCount() {
        var active = $('#filter-platform, #filter-protocol, #filter-status, #filter-fit, #filter-date-from, #filter-date-to')
            .filter(function () { return $(this).val(); }).length;
        $('#history-active-filters-count').text(active || '');
    }

    function debounceLoad() {
        updateActiveFilterCount();
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () { loadHistory(1); }, 350);
    }

    $('#filter-platform, #filter-protocol, #filter-status, #filter-fit').on('change', debounceLoad);
    $('#filter-date-from, #filter-date-to').on('change', debounceLoad);

    $('#btn-reset-filters').on('click', function () {
        $('#filter-platform, #filter-protocol, #filter-status, #filter-fit').val('');
        $('#filter-date-from, #filter-date-to').val('');
        updateActiveFilterCount();
        loadHistory(1);
    });

    $(document).on('click', '#history-pagination .page-link', function (e) {
        e.preventDefault();
        var page = parseInt($(this).data('page'), 10);
        if (!isNaN(page)) loadHistory(page);
    });

    // Initial load
    loadHistory(1);
})();
