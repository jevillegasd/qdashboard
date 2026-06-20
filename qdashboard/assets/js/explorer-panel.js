// File Explorer side panel: AJAX directory navigation (no full-page reloads),
// mirroring the History panel's fetch+render pattern. Replaces the old
// file_browser.html full-page table with a flat, narrow-sidebar-friendly list.
(function () {
    'use strict';

    var currentPath = '';
    var hideDotfiles = (getCookie('hide-dotfile') || 'no') === 'yes';
    var allEntries = [];

    // The viewer/uploader modals are defined inside _panel_explorer.html, which
    // lives inside .side-panel (position:fixed) + .side-panel-pane (overflow:
    // hidden). A position:fixed Bootstrap modal nested in there can end up
    // clipped/mis-stacked — backdrop shows (dimmed) but the modal itself isn't
    // interactive. Move both to be direct children of <body> to escape that.
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

    // Fetching (network) and the modal's own fade-in (CSS transition) finish
    // in whichever order — if JSONEditor is created while the modal is still
    // mid-transition, its container measures 0 height and the tree never
    // recovers. pendingViewerData + the shown.bs.modal handler below make
    // rendering wait for whichever of the two finishes last.
    var pendingViewerData = null;

    // Created once and reused for every open — JSONEditor's mainMenuBar mode
    // (search box, dropdowns) attaches its own document-level listeners, and
    // destroy()/recreate on every cycle risks not all of them being cleaned
    // up, leaving a stray listener that swallows clicks elsewhere on the
    // page until a full reload. Reusing one instance avoids that entirely.
    var _viewerEditor = null;

    function renderViewerIfReady() {
        if (!pendingViewerData || !$('#viewer-modal').hasClass('show')) return;
        var pending = pendingViewerData;
        if (pending.error) {
            $('#viewer-error').text(pending.error).show();
            return;
        }
        ensureJsonEditor(function () {
            if (!_viewerEditor) {
                _viewerEditor = new JSONEditor(document.getElementById('viewer-json-container'),
                    { mode: 'view', mainMenuBar: true });
            }
            _viewerEditor.set(pending.data);
            _viewerEditor.expandAll();
        });
    }

    function openStructuredViewer(filePath, fileName, ext) {
        pendingViewerData = null;
        $('#file-name').text(fileName);
        $('.fullview').attr('href', '/files/' + filePath);
        $('#viewer-error').hide().text('');
        // Defensive: if a previous hide cycle left Bootstrap's modal plugin
        // data in a stuck _isShown/_isTransitioning state, .modal('show')
        // silently no-ops — looks exactly like "clicking a file does
        // nothing" rather than a visibly broken modal. Force a clean instance.
        $('#viewer-modal').data('bs.modal', null);
        $('.modal-backdrop').remove();
        $('body').removeClass('modal-open');
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
        // _viewerEditor is intentionally left alone here — see its
        // declaration above for why it's never destroyed/recreated.
        // Defensive: a stray .modal-backdrop (or a lingering .modal-open on
        // <body>) left behind by a botched hide cycle silently swallows every
        // click on the page underneath it — which looks like "clicking a
        // file does nothing" rather than an obviously broken modal.
        if (!$('.modal.show').length) {
            $('.modal-backdrop').remove();
            $('body').removeClass('modal-open');
        }
        $(this).data('bs.modal', null);
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
