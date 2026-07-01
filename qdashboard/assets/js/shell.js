/**
 * QDashboard shell: VS Code-style activity bar + side panel + tab strip.
 *
 * Singleton tabs (slurm, qpu_status, action_builder) stay in the DOM when
 * "closed" — only hidden — so state like a half-built action card survives.
 * Report tabs are the exception: a fresh <iframe> per open, removed on close.
 */
(function () {
    'use strict';

    var TAB_DEFS = {
        slurm:          { label: 'Slurm Monitor',     icon: 'fa-tasks' },
        qpu_status:     { label: 'QPU Status',        icon: 'fa-microchip' },
        action_builder: { label: 'Action Card Builder', icon: 'fa-flask' }
    };

    var TABS_KEY = 'qd_shell_tabs';
    var PANEL_KEY = 'qd_shell_panel';

    // Start/stop the Slurm SSE connection with its tab — leaving it always-on
    // is what made `qdashboard` take ~5-10s to exit on Ctrl+C.
    var TAB_LIFECYCLE = {
        slurm: {
            onOpen: function () { if (window.initializeDashboardCommon) window.initializeDashboardCommon(); },
            onClose: function () { if (window.stopAutoRefresh) window.stopAutoRefresh(); }
        }
    };

    // labels is persisted (it's part of tabState) so report tab titles survive
    // a reload — the DOM panes themselves don't, see ensureReportPane() below.
    var tabState = { open: ['slurm', 'action_builder'], active: 'action_builder', labels: {} };
    var panelState = { active: 'library', open: true };

    function loadState(key, fallback) {
        try {
            var raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (e) {
            return fallback;
        }
    }

    function saveState(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
    }

    // ---- Tabs ----

    function isReportTab(id) {
        return id.indexOf('report:') === 0;
    }

    function tabPaneId(id) {
        // Report tab ids contain a colon ("report:<experiment_id>"), which
        // breaks jQuery/CSS id selectors — sanitize for the DOM id only.
        return 'tab-pane-' + id.replace(/[^a-zA-Z0-9_-]/g, '-');
    }

    function renderTabsBar() {
        var $list = $('#qd-tabs-list').empty();
        tabState.open.forEach(function (id) {
            var def = TAB_DEFS[id] || { label: tabState.labels[id] || id, icon: 'fa-chart-bar' };
            var $tab = $('<div class="qd-tab" draggable="true"></div>')
                .attr('data-tab-id', id)
                .toggleClass('active', id === tabState.active)
                .html(
                    '<i class="fas ' + def.icon + ' mr-1"></i>' +
                    '<span class="qd-tab-label">' + def.label + '</span>' +
                    '<span class="qd-tab-close" title="Close"><i class="fas fa-times"></i></span>'
                );
            $list.append($tab);
        });
        renderAddMenu();
    }

    function renderAddMenu() {
        var $menu = $('#qd-tab-add-menu').empty();
        Object.keys(TAB_DEFS).forEach(function (id) {
            if (tabState.open.indexOf(id) !== -1) return;
            var def = TAB_DEFS[id];
            $menu.append(
                $('<a class="dropdown-item" href="#"></a>')
                    .attr('data-tab-id', id)
                    .html('<i class="fas ' + def.icon + ' mr-2"></i>' + def.label)
            );
        });
        if (!$menu.children().length) {
            $menu.append('<span class="dropdown-item disabled small text-muted">All views open</span>');
        }
    }

    function showPane(id) {
        $('.qd-tabpane').removeClass('active').css('display', 'none');
        var $pane = $('#' + tabPaneId(id));
        $pane.addClass('active').css('display', '');
    }

    function activateTab(id) {
        if (tabState.open.indexOf(id) === -1) return;
        tabState.active = id;
        renderTabsBar();
        showPane(id);
        saveState(TABS_KEY, tabState);
    }

    function openTab(id) {
        var wasOpen = tabState.open.indexOf(id) !== -1;
        if (!wasOpen) {
            tabState.open.push(id);
        }
        activateTab(id);
        if (!wasOpen && TAB_LIFECYCLE[id] && TAB_LIFECYCLE[id].onOpen) {
            TAB_LIFECYCLE[id].onOpen();
        }
    }

    // Recomputed each time rather than stored, so "Latest Report" always
    // re-fetches whatever the latest report currently is.
    function reportSrcForId(id) {
        if (id === 'report:latest') return '/latest_report_page?_=' + Date.now();
        return '/experiment_report_page/' + encodeURIComponent(id.slice('report:'.length));
    }

    // Creates the iframe pane for a report tab if it doesn't already exist —
    // used both when opening one fresh and when restoring tabs after a
    // reload, since only tabState (the list of ids) survives that, not the
    // DOM nodes openIframeTab() creates.
    function ensureReportPane(id) {
        if (document.getElementById(tabPaneId(id))) return;
        // data-tab-id carries the real (colon-bearing) id — tabPaneId()
        // sanitizes it for the DOM id, so that alone can't be reversed; this
        // is how the postMessage handler below maps an iframe back to its tab.
        $('#qd-tab-content').append(
            '<div id="' + tabPaneId(id) + '" class="qd-tabpane qd-tabpane-report" data-tab-id="' + id + '">' +
            '<iframe src="' + reportSrcForId(id) + '" title="Experiment Report"></iframe>' +
            '</div>'
        );
    }

    function openIframeTab(id, label) {
        tabState.labels[id] = label || id;
        var existing = document.getElementById(tabPaneId(id));
        if (existing) {
            // Re-point an already-open pinned tab (e.g. "Latest Report") at
            // a fresh src instead of stacking duplicate iframes.
            existing.querySelector('iframe').src = reportSrcForId(id);
        } else {
            ensureReportPane(id);
        }
        openTab(id);
    }

    function openReportTab(experimentId, label) {
        openIframeTab('report:' + experimentId, label || experimentId);
    }

    function openLatestReportTab() {
        openIframeTab('report:latest', 'Latest Report');
    }

    function closeTab(id) {
        var idx = tabState.open.indexOf(id);
        if (idx === -1) return;
        tabState.open.splice(idx, 1);

        if (isReportTab(id)) {
            $('#' + tabPaneId(id)).remove();
            delete tabState.labels[id];
        }

        if (tabState.active === id) {
            var next = tabState.open[idx] || tabState.open[idx - 1] || tabState.open[0];
            tabState.active = next || null;
        }

        renderTabsBar();
        if (tabState.active) {
            showPane(tabState.active);
        } else {
            $('.qd-tabpane').removeClass('active').css('display', 'none');
        }
        saveState(TABS_KEY, tabState);

        if (TAB_LIFECYCLE[id] && TAB_LIFECYCLE[id].onClose) {
            TAB_LIFECYCLE[id].onClose();
        }
    }

    function reorderTabs(draggedId, beforeId) {
        var from = tabState.open.indexOf(draggedId);
        if (from === -1) return;
        tabState.open.splice(from, 1);
        var to = beforeId ? tabState.open.indexOf(beforeId) : tabState.open.length;
        if (to === -1) to = tabState.open.length;
        tabState.open.splice(to, 0, draggedId);
        renderTabsBar();
        saveState(TABS_KEY, tabState);
    }

    $(document).on('click', '.qd-tab', function (e) {
        if ($(e.target).closest('.qd-tab-close').length) return;
        activateTab($(this).data('tab-id'));
    });

    $(document).on('click', '.qd-tab-close', function (e) {
        e.stopPropagation();
        closeTab($(this).closest('.qd-tab').data('tab-id'));
    });

    $(document).on('click', '#qd-tab-add-menu a[data-tab-id]', function (e) {
        e.preventDefault();
        openTab($(this).data('tab-id'));
    });

    $(document).on('dragstart', '.qd-tab', function (e) {
        e.originalEvent.dataTransfer.setData('text/plain', $(this).data('tab-id'));
    });
    $(document).on('dragover', '.qd-tab', function (e) {
        e.preventDefault();
    });
    $(document).on('drop', '.qd-tab', function (e) {
        e.preventDefault();
        var draggedId = e.originalEvent.dataTransfer.getData('text/plain');
        var beforeId = $(this).data('tab-id');
        if (draggedId && draggedId !== beforeId) reorderTabs(draggedId, beforeId);
    });

    // A report tab's iframe (e.g. error.html, rendered when a report fails to
    // load) can't navigate itself out of the iframe — "Back to Dashboard"
    // there posts a message asking the parent to close that tab instead.
    window.addEventListener('message', function (e) {
        if (!e.data || e.data.source !== 'qdashboard' || e.data.action !== 'close-report-tab') return;
        var pane = Array.prototype.find.call(
            document.querySelectorAll('.qd-tabpane-report'),
            function (p) { var f = p.querySelector('iframe'); return f && f.contentWindow === e.source; }
        );
        if (pane) closeTab(pane.dataset.tabId);
    });

    // ---- Side panel ----

    function showPanel(id) {
        $('.side-panel-pane').removeClass('active');
        $('#panel-' + id).addClass('active');
        $('#side-panel').show();
        $('#side-panel-resize-handle').show();
        $('#wrapper').addClass('panel-open');
        $('[data-panel]').removeClass('active');
        $('[data-panel="' + id + '"]').addClass('active');
        panelState.active = id;
        panelState.open = true;
        saveState(PANEL_KEY, panelState);
    }

    function hidePanel() {
        $('#side-panel').hide();
        $('#side-panel-resize-handle').hide();
        $('#wrapper').removeClass('panel-open');
        $('[data-panel]').removeClass('active');
        panelState.open = false;
        saveState(PANEL_KEY, panelState);
    }

    function togglePanel(id) {
        if (panelState.open && panelState.active === id) {
            hidePanel();
        } else {
            showPanel(id);
        }
    }

    $(document).on('click', '[data-panel]', function (e) {
        e.preventDefault();
        togglePanel($(this).data('panel'));
    });

    // Direct activity-bar shortcuts: open a tab without going through the
    // side panel or the tab strip's "+" menu.
    $(document).on('click', '[data-open-tab]', function (e) {
        e.preventDefault();
        openTab($(this).data('open-tab'));
    });
    $(document).on('click', '[data-open-latest-report]', function (e) {
        e.preventDefault();
        openLatestReportTab();
    });

    // ---- Resizable bars ----

    // Drags `handleId`, clamping to [min,max], writing the result (px) to
    // `cssVar` on :root, and persisting it under `storageKey`. `widthFromEvent`
    // computes the candidate width from a mousemove event — callers differ on
    // what reference point they measure from.
    function makeResizable(handleId, cssVar, storageKey, min, max, widthFromEvent, onResize) {
        function setWidth(px) {
            px = Math.max(min, Math.min(max, px));
            document.documentElement.style.setProperty(cssVar, px + 'px');
            if (onResize) onResize(px);
            return px;
        }

        var saved = parseInt(loadState(storageKey, null), 10);
        if (!isNaN(saved)) setWidth(saved);

        var handle = document.getElementById(handleId);
        if (!handle) return;
        var dragging = false;

        handle.addEventListener('mousedown', function (e) {
            dragging = true;
            handle.classList.add('resizing');
            document.body.style.userSelect = 'none';
            // Mouse events over an iframe go to its own document, not this
            // listener — dragging across a report tab would otherwise "lose"
            // the cursor. Suppress pointer events on iframes for the drag.
            document.body.classList.add('qd-resizing');
            e.preventDefault();
        });
        document.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            setWidth(widthFromEvent(e));
        });
        document.addEventListener('mouseup', function () {
            if (!dragging) return;
            dragging = false;
            handle.classList.remove('resizing');
            document.body.style.userSelect = '';
            document.body.classList.remove('qd-resizing');
            var current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(cssVar));
            saveState(storageKey, current || min);
        });
    }

    // Activity bar resize disabled — icon-only, doesn't need the width. Left
    // here in case a "wide" labeled mode is wanted later.
    // var ACTIVITY_BAR_MIN = 64;   // icon-only
    // var ACTIVITY_BAR_MAX = 240;  // wide enough for full labels
    // makeResizable('sidebar-resize-handle', '--activity-bar-width', 'qd_activity_bar_width',
    //     ACTIVITY_BAR_MIN, ACTIVITY_BAR_MAX,
    //     function (e) { return e.clientX; },
    //     function (px) { $('body').toggleClass('activity-bar-wide', px > ACTIVITY_BAR_MIN + 20); });

    makeResizable('side-panel-resize-handle', '--side-panel-width', 'qd_side_panel_width',
        180, 600,
        function (e) {
            var panel = document.getElementById('side-panel');
            return e.clientX - panel.getBoundingClientRect().left;
        });

    // Split between the builder and results columns; an in-flow flex sibling
    // (see experiments.css), so width is measured from its own row, not the viewport.
    makeResizable('panel-builder-handle', '--builder-panel-width', 'qd_builder_panel_width',
        320, 1100,
        function (e) {
            var workspace = document.querySelector('.action-builder-workspace');
            return e.clientX - workspace.getBoundingClientRect().left;
        });

    // ---- Bootstrap from URL query params, else localStorage ----

    function bootstrap() {
        var params = new URLSearchParams(window.location.search);
        var queryHandled = false;

        var savedTabs = loadState(TABS_KEY, null);
        if (savedTabs && savedTabs.open && savedTabs.open.length) {
            tabState = savedTabs;
            tabState.labels = tabState.labels || {};
        }
        var savedPanel = loadState(PANEL_KEY, null);
        if (savedPanel) {
            panelState = savedPanel;
        }

        // Only tabState (the ids) survives a reload — report tabs' actual
        // iframe panes were DOM nodes created on the fly, so recreate them
        // before trying to render/show anything.
        tabState.open.filter(isReportTab).forEach(ensureReportPane);

        renderTabsBar();
        if (tabState.active) showPane(tabState.active);

        // openTab() only fires onOpen for a closed->open transition, which
        // misses tabs already open at load (default or restored).
        tabState.open.forEach(function (id) {
            if (TAB_LIFECYCLE[id] && TAB_LIFECYCLE[id].onOpen) TAB_LIFECYCLE[id].onOpen();
        });

        if (panelState.open && panelState.active) {
            showPanel(panelState.active);
        }

        if (params.has('open')) {
            openTab(params.get('open'));
            queryHandled = true;
        }
        if (params.has('panel')) {
            showPanel(params.get('panel'));
            queryHandled = true;
        }
        if (params.has('path') && window.ExplorerPanel) {
            window.ExplorerPanel.init(params.get('path'));
        } else if (window.ExplorerPanel) {
            window.ExplorerPanel.init('');
        }

        if (queryHandled) {
            var url = new URL(window.location.href);
            url.search = '';
            window.history.replaceState({}, '', url.toString());
        }
    }

    $(document).ready(bootstrap);

    window.ShellTabs = {
        open: openTab,
        close: closeTab,
        activate: activateTab,
        openReportTab: openReportTab,
        openLatestReportTab: openLatestReportTab
    };
    window.ShellPanel = {
        show: showPanel,
        hide: hidePanel,
        toggle: togglePanel
    };
})();
