/**
 * QDashboard shell: VS Code-style activity bar + side panel + tab strip.
 *
 * Singleton tabs (slurm, qpu_status, action_builder) are always rendered in
 * the DOM (see shell.html) — "closing" one only hides its tab/pane, it is
 * never destroyed, so in-progress state (e.g. a half-built action card) is
 * preserved across close/reopen. Report tabs are the one dynamic exception:
 * each is a fresh <iframe> created on open and removed from the DOM on close.
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

    var tabState = { open: ['slurm', 'action_builder'], active: 'action_builder' };
    var panelState = { active: 'library', open: true };
    var reportLabels = {}; // experimentId -> label, for report tabs re-render after reload (not persisted across reload by design)

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
        return 'tab-pane-' + id;
    }

    function renderTabsBar() {
        var $list = $('#qd-tabs-list').empty();
        tabState.open.forEach(function (id) {
            var def = TAB_DEFS[id] || { label: reportLabels[id] || id, icon: 'fa-chart-bar' };
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
        if (tabState.open.indexOf(id) === -1) {
            tabState.open.push(id);
        }
        activateTab(id);
    }

    function openReportTab(experimentId, label) {
        var id = 'report:' + experimentId;
        reportLabels[id] = label || experimentId;
        if (!document.getElementById(tabPaneId(id))) {
            $('#qd-tab-content').append(
                '<div id="' + tabPaneId(id) + '" class="qd-tabpane qd-tabpane-report">' +
                '<iframe src="/experiment_report_page/' + encodeURIComponent(experimentId) + '" ' +
                'style="width:100%;height:100%;border:none;" title="Experiment Report"></iframe>' +
                '</div>'
            );
        }
        openTab(id);
    }

    function closeTab(id) {
        var idx = tabState.open.indexOf(id);
        if (idx === -1) return;
        tabState.open.splice(idx, 1);

        if (isReportTab(id)) {
            $('#' + tabPaneId(id)).remove();
            delete reportLabels[id];
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

    // ---- Side panel ----

    function showPanel(id) {
        $('.side-panel-pane').hide();
        $('#panel-' + id).show();
        $('#side-panel').show();
        $('#wrapper').addClass('panel-open');
        $('[data-panel]').removeClass('active');
        $('[data-panel="' + id + '"]').addClass('active');
        panelState.active = id;
        panelState.open = true;
        saveState(PANEL_KEY, panelState);
    }

    function hidePanel() {
        $('#side-panel').hide();
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

    // ---- Bootstrap from URL query params, else localStorage ----

    function bootstrap() {
        var params = new URLSearchParams(window.location.search);
        var queryHandled = false;

        var savedTabs = loadState(TABS_KEY, null);
        if (savedTabs && savedTabs.open && savedTabs.open.length) {
            tabState = savedTabs;
        }
        var savedPanel = loadState(PANEL_KEY, null);
        if (savedPanel) {
            panelState = savedPanel;
        }

        renderTabsBar();
        if (tabState.active) showPane(tabState.active);

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
        openReportTab: openReportTab
    };
    window.ShellPanel = {
        show: showPanel,
        hide: hidePanel,
        toggle: togglePanel
    };
})();
