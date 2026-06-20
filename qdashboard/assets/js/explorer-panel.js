// File Explorer side panel: AJAX directory navigation (no full-page reloads),
// mirroring the History panel's fetch+render pattern. Replaces the old
// file_browser.html full-page table with a flat, narrow-sidebar-friendly list.
(function () {
    'use strict';

    var currentPath = '';
    var hideDotfiles = (getCookie('hide-dotfile') || 'no') === 'yes';
    var allEntries = [];

    function getCookie(name) {
        var m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
        return m ? m.pop() : '';
    }

    function setCookie(name, value, days) {
        var d = new Date();
        d.setTime(d.getTime() + days * 24 * 60 * 60 * 1000);
        document.cookie = name + '=' + value + ';expires=' + d.toUTCString() + ';path=/';
    }

    function renderBreadcrumb(path) {
        var parts = path ? path.split('/').filter(Boolean) : [];
        var html = '<li class="breadcrumb-item"><a href="#" data-path=""><i class="fa fa-fw fa-home"></i></a></li>';
        var acc = [];
        parts.forEach(function (part) {
            acc.push(part);
            html += '<li class="breadcrumb-item"><a href="#" data-path="' + acc.join('/') + '">' + part + '</a></li>';
        });
        $('#explorer-breadcrumb').html(html);
    }

    function renderList(entries) {
        var filter = ($('#explorer-search').val() || '').toLowerCase();
        var filtered = entries.filter(function (e) {
            return !filter || e.name.toLowerCase().indexOf(filter) !== -1;
        });
        if (!filtered.length) {
            $('#explorer-list').html('<div class="text-center text-muted py-4 small">Empty directory.</div>');
            return;
        }
        var html = '';
        filtered.forEach(function (e) {
            var icon = e.type === 'dir'
                ? (e.is_qibocal_report ? 'fa-chart-bar qibocal-report-icon' : 'fa-folder text-warning')
                : e.icon_class || 'fa-file';
            var rowAttrs = e.type === 'dir'
                ? 'data-dir="' + e.name + '"'
                : 'data-file="' + e.name + '"';
            // Qibocal report directories browse like any other folder; the
            // chart-bar button opens the report as a tab without navigating.
            var reportBtn = (e.type === 'dir' && e.is_qibocal_report)
                ? '<button class="btn-doc-info explorer-open-report" title="Open report" data-dir="' + e.name + '">'
                  + '<i class="fas fa-chart-bar"></i></button>'
                : '';
            html += '<div class="vsc-list-row explorer-row" ' + rowAttrs + '>'
                + '<div class="d-flex align-items-center text-truncate" style="gap:.4rem;">'
                + '<i class="fa fa-fw ' + icon + '"></i><span class="text-truncate">' + e.name + '</span>'
                + '</div>'
                + (e.type === 'file'
                    ? '<span class="text-muted" style="font-size:.68rem;">' + e.size_fmt + '</span>'
                    : reportBtn)
                + '</div>';
        });
        $('#explorer-list').html(html);
    }

    function loadDir(path) {
        currentPath = path || '';
        $('#explorer-list').html('<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin"></i> Loading…</div>');
        $.getJSON('/api/files_list', { path: currentPath, 'hide-dotfile': hideDotfiles ? 'yes' : 'no' })
            .done(function (data) {
                allEntries = data.contents || [];
                renderBreadcrumb(currentPath);
                renderList(allEntries);
            })
            .fail(function () {
                $('#explorer-list').html('<div class="text-center text-danger py-3">Failed to load directory.</div>');
            });
    }

    $(document).on('click', '#explorer-breadcrumb a', function (e) {
        e.preventDefault();
        loadDir($(this).data('path') || '');
    });

    $(document).on('click', '.explorer-open-report', function (e) {
        e.stopPropagation();
        var dir = $(this).data('dir');
        // The report dir (conventionally "output") sits inside the
        // experiment_id-named directory currently being listed.
        var experimentId = currentPath.split('/').filter(Boolean).pop() || dir;
        if (window.ShellTabs) window.ShellTabs.openReportTab(experimentId, experimentId);
    });

    $(document).on('click', '.explorer-row', function () {
        var dir = $(this).data('dir');
        var file = $(this).data('file');
        if (dir !== undefined) {
            loadDir((currentPath ? currentPath + '/' : '') + dir);
        } else if (file !== undefined) {
            var filePath = (currentPath ? currentPath + '/' : '') + file;
            window.open('/files/' + filePath, '_blank');
        }
    });

    $('#explorer-search').on('input', function () {
        renderList(allEntries);
    });

    $('#explorer-toggle-dotfiles').on('click', function () {
        hideDotfiles = !hideDotfiles;
        setCookie('hide-dotfile', hideDotfiles ? 'yes' : 'no', 186);
        $(this).find('i').toggleClass('fa-eye-slash fa-eye');
        loadDir(currentPath);
    });

    $('#uploader-modal').on('hidden.bs.modal', function () {
        loadDir(currentPath);
    });

    // Bootstrap's jQuery uploader plugin (jquery.filer) expects a real form
    // action; point it at the current directory's upload endpoint.
    $(document).on('show.bs.modal', '#uploader-modal', function () {
        $('#upload-files').attr('action', '/files/' + currentPath);
    });

    window.ExplorerPanel = {
        init: function (initialPath) {
            loadDir(initialPath || '');
        },
        currentPath: function () { return currentPath; }
    };
})();
