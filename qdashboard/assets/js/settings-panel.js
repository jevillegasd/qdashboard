/**
 * settings-panel.js — Remote execution settings UI
 *
 * Manages the Settings tab: load/save RemoteSettings, SSH config
 * viewer/editor, test connection, and manual sync triggers.
 */

(function () {
    'use strict';

    // ------------------------------------------------------------------ //
    // State                                                                //
    // ------------------------------------------------------------------ //
    let _currentSettings = null;
    let _sshConfigEntries = [];

    // ------------------------------------------------------------------ //
    // Initialisation                                                       //
    // ------------------------------------------------------------------ //

    /** Called when the Settings tab pane is first shown. */
    function initSettingsPanel() {
        loadSettings();
        loadSshConfig();
        pollConnectionStatus();

        $('#btn-save-settings').on('click', saveSettings);
        $('#btn-reload-settings').on('click', loadSettings);
        $('#btn-ssh-connect').on('click', connectSSH);
        $('#btn-ssh-disconnect').on('click', disconnectSSH);
        $('#btn-save-ssh-config').on('click', saveSshConfig);
        $('#btn-sync-all').on('click', syncAll);
        $('#btn-proxy-from-config').on('click', showProxyJumpPicker);

        // Show/hide remote-only cards when execution mode changes
        $('input[name="executionMode"]').on('change', updateRemoteCardVisibility);
    }

    // ------------------------------------------------------------------ //
    // Settings load / save                                                 //
    // ------------------------------------------------------------------ //

    function loadSettings() {
        $('#settings-save-result').text('').removeClass('text-success text-danger');
        fetch('/api/settings/remote')
            .then(r => r.json())
            .then(data => {
                _currentSettings = data;
                _applySettingsToForm(data);
                updateRemoteCardVisibility();
            })
            .catch(err => console.error('Failed to load settings:', err));
    }

    function _applySettingsToForm(s) {
        // Execution mode radio
        $(`input[name="executionMode"][value="${s.execution_mode || 'local_slurm'}"]`).prop('checked', true);

        // Remote server
        $('#remote-host').val(s.remote_host || '');
        $('#remote-port').val(s.remote_port || 22);
        $('#remote-user').val(s.remote_user || '');
        $('#remote-root').val(s.remote_root || '~/.qdashboard');
        $('#remote-environment').val(s.remote_environment || '');
        $('#remote-platforms-path').val(s.remote_platforms_path || '');

        // SSH auth
        $('#ssh-key-path').val(s.ssh_key_path || '');
        $('#use-ssh-agent').prop('checked', s.use_ssh_agent !== false);

        // Proxy
        $('#proxy-jump').val(s.proxy_jump || '');

        // Sync
        $('#auto-sync').prop('checked', s.auto_sync !== false);
        $('#sync-interval').val(s.sync_interval || 30);
    }

    function _readSettingsFromForm() {
        return {
            execution_mode: $('input[name="executionMode"]:checked').val() || 'local_slurm',
            remote_host: $('#remote-host').val().trim(),
            remote_port: parseInt($('#remote-port').val()) || 22,
            remote_user: $('#remote-user').val().trim(),
            remote_root: $('#remote-root').val().trim() || '~/.qdashboard',
            remote_environment: $('#remote-environment').val().trim(),
            remote_platforms_path: $('#remote-platforms-path').val().trim(),
            ssh_key_path: $('#ssh-key-path').val().trim(),
            use_ssh_agent: $('#use-ssh-agent').is(':checked'),
            proxy_jump: $('#proxy-jump').val().trim(),
            auto_sync: $('#auto-sync').is(':checked'),
            sync_interval: parseInt($('#sync-interval').val()) || 30,
        };
    }

    function saveSettings() {
        const payload = _readSettingsFromForm();
        const $result = $('#settings-save-result');
        $result.text('Saving…').removeClass('text-success text-danger');

        fetch('/api/settings/remote', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(r => r.json())
            .then(data => {
                _currentSettings = data;
                $result.text('Saved.').addClass('text-success');
                setTimeout(() => $result.text(''), 3000);
            })
            .catch(err => {
                $result.text('Save failed: ' + err).addClass('text-danger');
            });
    }

    // ------------------------------------------------------------------ //
    // Card visibility                                                      //
    // ------------------------------------------------------------------ //

    function updateRemoteCardVisibility() {
        const mode = $('input[name="executionMode"]:checked').val() || 'local_slurm';
        const isRemote = mode.startsWith('remote_');
        $('#settings-remote-server-card, #settings-ssh-auth-card').toggle(isRemote);
        $('#settings-sync-card').toggle(isRemote);
    }

    // ------------------------------------------------------------------ //
    // SSH connection                                                       //
    // ------------------------------------------------------------------ //

    function connectSSH() {
        const $badge = $('#settings-conn-badge');
        $badge.removeClass('badge-success badge-danger badge-warning')
              .addClass('badge-warning')
              .html('<i class="fas fa-spinner fa-spin mr-1"></i> Connecting…');

        fetch('/api/remote/connect', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.connected) {
                    $badge.removeClass('badge-secondary badge-warning badge-danger')
                          .addClass('badge-success')
                          .html(`<i class="fas fa-circle mr-1"></i> Connected to ${data.host}`);
                } else {
                    $badge.removeClass('badge-secondary badge-warning badge-success')
                          .addClass('badge-danger')
                          .html(`<i class="fas fa-exclamation-circle mr-1"></i> ${data.message || 'Connection failed'}`);
                }
            })
            .catch(err => {
                $badge.removeClass('badge-secondary badge-warning badge-success')
                      .addClass('badge-danger')
                      .html('<i class="fas fa-exclamation-circle mr-1"></i> Error');
            });
    }

    function disconnectSSH() {
        fetch('/api/remote/disconnect', { method: 'POST' })
            .then(() => {
                $('#settings-conn-badge')
                    .removeClass('badge-success badge-warning badge-danger')
                    .addClass('badge-secondary')
                    .html('<i class="fas fa-circle mr-1"></i> Disconnected');
            });
    }

    function pollConnectionStatus() {
        fetch('/api/remote/status')
            .then(r => r.json())
            .then(data => {
                const $badge = $('#settings-conn-badge');
                if (data.connected) {
                    $badge.removeClass('badge-secondary badge-warning badge-danger')
                          .addClass('badge-success')
                          .html(`<i class="fas fa-circle mr-1"></i> Connected to ${data.host}`);

                    const $syncBadge = $('#settings-sync-status-badge');
                    if (data.pending_experiments > 0) {
                        $syncBadge.html(
                            `<span class="badge badge-warning">${data.pending_experiments} pending sync</span>`
                        );
                    } else {
                        $syncBadge.html('');
                    }
                } else {
                    $badge.removeClass('badge-success badge-warning badge-danger')
                          .addClass('badge-secondary')
                          .html('<i class="fas fa-circle mr-1"></i> Disconnected');
                }
            })
            .catch(() => {});

        // Re-poll every 15 s while the tab is active
        setTimeout(pollConnectionStatus, 15000);
    }

    // ------------------------------------------------------------------ //
    // SSH config                                                           //
    // ------------------------------------------------------------------ //

    function loadSshConfig() {
        fetch('/api/settings/ssh_config')
            .then(r => r.json())
            .then(data => {
                _sshConfigEntries = data.entries || [];
                _renderKnownHostsTable(_sshConfigEntries);
                $('#ssh-config-raw').val(data.raw || '');
            })
            .catch(err => {
                $('#known-hosts-tbody').html(
                    '<tr><td colspan="6" class="text-danger small">Failed to load SSH config.</td></tr>'
                );
            });
    }

    function _renderKnownHostsTable(entries) {
        const $tbody = $('#known-hosts-tbody');
        if (!entries.length) {
            $tbody.html('<tr><td colspan="6" class="text-center text-muted small">No host entries found in ~/.ssh/config</td></tr>');
            return;
        }
        const rows = entries.map(e => `
            <tr>
                <td><code>${_esc(e.alias)}</code></td>
                <td>${_esc(e.hostname)}</td>
                <td>${_esc(e.user)}</td>
                <td>${e.port || 22}</td>
                <td>${_esc(e.proxy_jump)}</td>
                <td>
                    <button class="btn btn-xs btn-outline-primary btn-use-host"
                            data-alias="${_esc(e.alias)}"
                            data-hostname="${_esc(e.hostname)}"
                            data-user="${_esc(e.user)}"
                            data-port="${e.port || 22}"
                            data-proxy="${_esc(e.proxy_jump)}"
                            data-keyfile="${_esc(e.identity_file || '')}"
                            title="Populate remote server fields">Use</button>
                </td>
            </tr>
        `).join('');
        $tbody.html(rows);

        // Attach click handlers
        $tbody.find('.btn-use-host').on('click', function () {
            const $btn = $(this);
            $('#remote-host').val($btn.data('hostname') || $btn.data('alias'));
            $('#remote-port').val($btn.data('port') || 22);
            $('#remote-user').val($btn.data('user') || '');
            $('#proxy-jump').val($btn.data('proxy') || '');
            if ($btn.data('keyfile')) {
                $('#ssh-key-path').val($btn.data('keyfile'));
            }
            // Switch to remote mode if not already
            const current = $('input[name="executionMode"]:checked').val();
            if (!current || !current.startsWith('remote_')) {
                $('#mode-remote-slurm').prop('checked', true).trigger('change');
            }
            showNotification('success', `Populated fields from SSH config entry: ${$btn.data('alias')}`);
        });
    }

    function saveSshConfig() {
        const content = $('#ssh-config-raw').val();
        const $result = $('#ssh-config-save-result');
        $result.text('Saving…');

        fetch('/api/settings/ssh_config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    $result.text('Saved. Reloading…');
                    setTimeout(() => {
                        loadSshConfig();
                        $result.text('');
                    }, 1000);
                } else {
                    $result.text('Error: ' + (data.message || 'unknown'));
                }
            })
            .catch(err => $result.text('Save failed.'));
    }

    function showProxyJumpPicker() {
        if (!_sshConfigEntries.length) {
            showNotification('warning', 'No SSH config entries loaded yet.');
            return;
        }
        // Build a simple selection from existing entries that have ProxyJump or could serve as jumps
        const items = _sshConfigEntries.map(e =>
            `<button class="btn btn-sm btn-outline-secondary btn-block text-left mb-1 btn-pick-proxy"
                data-val="${_esc(e.alias)}">${_esc(e.alias)} — ${_esc(e.hostname) || '?'}</button>`
        ).join('');
        const html = `
            <div style="max-height:200px;overflow-y:auto;">
                ${items}
            </div>`;
        // Use a Bootstrap modal if available, otherwise a simple prompt
        if (typeof $().modal === 'function') {
            // Create ad-hoc modal
            const modalId = 'proxy-pick-modal';
            if (!$('#' + modalId).length) {
                $('body').append(`
                    <div class="modal fade" id="${modalId}" tabindex="-1">
                        <div class="modal-dialog modal-sm">
                            <div class="modal-content">
                                <div class="modal-header py-2">
                                    <h6 class="modal-title">Pick ProxyJump host</h6>
                                    <button type="button" class="close" data-dismiss="modal">&times;</button>
                                </div>
                                <div class="modal-body" id="${modalId}-body"></div>
                            </div>
                        </div>
                    </div>`);
            }
            $('#' + modalId + '-body').html(html);
            $('#' + modalId + '-body .btn-pick-proxy').on('click', function () {
                $('#proxy-jump').val($(this).data('val'));
                $('#' + modalId).modal('hide');
            });
            $('#' + modalId).modal('show');
        } else {
            const choice = prompt('Enter a ProxyJump alias or user@host:');
            if (choice) $('#proxy-jump').val(choice);
        }
    }

    // ------------------------------------------------------------------ //
    // Data sync                                                            //
    // ------------------------------------------------------------------ //

    function syncAll() {
        const $btn = $('#btn-sync-all');
        const $result = $('#sync-all-result');
        $btn.prop('disabled', true);
        $result.text('Syncing…');

        fetch('/api/remote/sync_all', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    $result.text(`Synced ${data.synced} experiment(s). Errors: ${data.errors}`);
                } else {
                    $result.text(data.message || 'Sync failed.');
                }
            })
            .catch(err => $result.text('Sync error.'))
            .finally(() => $btn.prop('disabled', false));
    }

    // ------------------------------------------------------------------ //
    // Helpers                                                              //
    // ------------------------------------------------------------------ //

    function _esc(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /** Show a Bootstrap notification card (reuses the global helper if present). */
    function showNotification(type, msg) {
        if (typeof window.showNotification === 'function') {
            window.showNotification(type, msg);
        } else {
            console.info('[Settings]', type, msg);
        }
    }

    // ------------------------------------------------------------------ //
    // Public API (attached to window so shell.js can call initSettingsPanel)
    // ------------------------------------------------------------------ //
    window.initSettingsPanel = initSettingsPanel;
    window.loadSettings = loadSettings;

})();
