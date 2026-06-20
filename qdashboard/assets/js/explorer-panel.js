// File Explorer side panel: AJAX directory navigation (no full-page reloads),
// mirroring the History panel's fetch+render pattern. Replaces the old
// file_browser.html full-page table with a flat, narrow-sidebar-friendly list.
(function () {
    'use strict';

    var currentPath = '';
    var hideDotfiles = (getCookie('hide-dotfile') || 'no') === 'yes';
    var allEntries = [];

    // These modals live inside .side-panel (position:fixed) + .side-panel-pane
    // (overflow:hidden), which clips/mis-stacks a nested fixed-position modal.
    // Move them to <body> to escape that.
    $('#viewer-modal, #uploader-modal').appendTo(document.body);

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
            // Report dirs browse like any folder; the button opens the report
            // as a tab instead.
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
        // The report dir ("output") sits inside the experiment_id-named dir.
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
            var ext = (file.split('.').pop() || '').toLowerCase();
            if (ext === 'json' || ext === 'yaml' || ext === 'yml') {
                openStructuredViewer(filePath, file, ext);
            } else {
                window.open('/files/' + filePath, '_blank');
            }
        }
    });

    // ---- Interactive viewer for .json/.yaml/.yml (collapsible tree, via JSONEditor) ----

    function loadScriptOnce(src, globalCheck, cb) {
        if (globalCheck()) return cb();
        var script = document.createElement('script');
        script.src = src;
        script.onload = cb;
        document.head.appendChild(script);
    }

    function ensureJsonEditor(cb) {
        if (window.JSONEditor) return cb();
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://cdn.jsdelivr.net/npm/jsoneditor@9.10.0/dist/jsoneditor.min.css';
        document.head.appendChild(link);
        loadScriptOnce('https://cdn.jsdelivr.net/npm/jsoneditor@9.10.0/dist/jsoneditor.min.js',
            function () { return !!window.JSONEditor; }, cb);
    }

    function ensureYamlParser(cb) {
        loadScriptOnce('https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js',
            function () { return !!window.jsyaml; }, cb);
    }

    // KNOWN ISSUE: the viewer still doesn't reliably show content on a second
    // open — not yet fixed. pendingViewerData/_viewerRetryTimer poll the
    // container's real rendered height instead of trusting Bootstrap's
    // shown.bs.modal timing, since fetch and the modal's fade-in can finish
    // in either order.
    var pendingViewerData = null;
    var _viewerRetryTimer = null;
    var _viewerEditor = null;

    // Destroy + empty the container before building a new instance — JSONEditor
    // appends directly into it, so stale markup from a previous instance can
    // make it render underneath or no-op.
    function destroyViewerEditor() {
        if (_viewerEditor) {
            try { _viewerEditor.destroy(); } catch (e) { /* ignore */ }
            _viewerEditor = null;
        }
        $('#viewer-json-container').empty();
    }

    function renderViewerIfReady() {
        clearTimeout(_viewerRetryTimer);
        if (!pendingViewerData) return;
        var pending = pendingViewerData;
        if (pending.error) {
            $('#viewer-error').text(pending.error).show();
            return;
        }
        var container = document.getElementById('viewer-json-container');
        if (!container || container.offsetHeight === 0) {
            _viewerRetryTimer = setTimeout(renderViewerIfReady, 50);
            return;
        }
        ensureJsonEditor(function () {
            destroyViewerEditor();
            container = document.getElementById('viewer-json-container');
            _viewerEditor = new JSONEditor(container, { mode: 'view', mainMenuBar: true });
            _viewerEditor.set(pending.data);
            _viewerEditor.expandAll();
        });
    }

    function openStructuredViewer(filePath, fileName, ext) {
        pendingViewerData = null;
        $('#file-name').text(fileName);
        $('.fullview').attr('href', '/files/' + filePath);
        $('#viewer-error').hide().text('');
        destroyViewerEditor(); // clear before showing/fetching, not after
        $('#viewer-modal').modal('show');

        fetch('/files/' + filePath)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (text) {
                var parse = function () {
                    try {
                        pendingViewerData = { data: (ext === 'json') ? JSON.parse(text) : window.jsyaml.load(text) };
                    } catch (e) {
                        pendingViewerData = { error: 'Could not parse ' + ext.toUpperCase() + ': ' + e.message };
                    }
                    renderViewerIfReady();
                };
                if (ext === 'json') parse();
                else ensureYamlParser(parse);
            })
            .catch(function (e) {
                pendingViewerData = { error: 'Could not load file: ' + e.message };
                renderViewerIfReady();
            });
    }

    $('#viewer-modal').on('shown.bs.modal', renderViewerIfReady);

    $('#viewer-modal').on('hidden.bs.modal', function () {
        pendingViewerData = null;
        clearTimeout(_viewerRetryTimer);
        destroyViewerEditor();
        // Defensive: a stray .modal-backdrop left behind by a bad hide cycle
        // silently blocks every click on the page underneath it.
        if (!$('.modal.show').length) {
            $('.modal-backdrop').remove();
            $('body').removeClass('modal-open');
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
