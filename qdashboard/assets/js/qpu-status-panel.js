// QPU Status tab: platform git management + QPU table + topology modal.
// Extracted from the legacy qpus.html page so it can run inside the shell's
// always-rendered, hidden/shown tab pane.
$(document).ready(function() {
    // Initialize topology click handlers
    attachTopologyHandlers();

    // Reset modal on close
    $('#topologyModal').on('hidden.bs.modal', function () {
        $('#topologyLoading').show();
        $('#topologyContent').hide();
        $('#topologyError').hide();
        $('#topologyImage').attr('src', '');
    });

    // Branch Management Functionality
    let availableBranches = null;
    let currentBranch = window.QD_CURRENT_BRANCH;

    // Load available branches
    function loadBranches() {
        fetch('/api/platforms/branches')
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error('Error loading branches:', data.error);
                    return;
                }

                availableBranches = data;
                populateBranchSelector();
            })
            .catch(error => {
                console.error('Error fetching branches:', error);
            });
    }

    // Populate the branch selector dropdown
    function populateBranchSelector() {
        const selector = $('#branchSelector');
        selector.empty();

        if (!availableBranches) return;

        // Add current branch first
        selector.append(`<option value="${currentBranch}" selected>${currentBranch} (current)</option>`);

        // Add separator
        selector.append('<option disabled>──── Local Branches ────</option>');

        // Add other local branches
        availableBranches.local.forEach(branch => {
            if (branch !== currentBranch) {
                selector.append(`<option value="${branch}">${branch}</option>`);
            }
        });

        // Add separator for remote branches
        selector.append('<option disabled>──── Remote Branches ────</option>');

        // Add remote branches (excluding those already in local)
        availableBranches.remote.forEach(remoteBranch => {
            const branchName = remoteBranch.replace('origin/', '');
            if (!availableBranches.local.includes(branchName)) {
                selector.append(`<option value="${branchName}">${branchName} (remote)</option>`);
            }
        });
    }

    // Handle branch selection change
    $('#branchSelector').on('change', function() {
        const selectedBranch = $(this).val();
        const switchButton = $('#switchBranch');

        if (selectedBranch && selectedBranch !== currentBranch) {
            switchButton.prop('disabled', false);
            switchButton.html('<i class="fas fa-exchange-alt"></i> Switch to ' + selectedBranch);
        } else {
            switchButton.prop('disabled', true);
            switchButton.html('<i class="fas fa-exchange-alt"></i> Switch');
        }
    });

    // Handle branch switching
    $('#switchBranch').on('click', function() {
        const selectedBranch = $('#branchSelector').val();
        if (!selectedBranch || selectedBranch === currentBranch) return;

        const button = $(this);
        const originalText = button.html();

        // Show loading state
        button.prop('disabled', true);
        button.html('<i class="fas fa-spinner fa-spin"></i> Switching...');

        // Hide previous alerts
        $('#switchAlert').hide();

        // First try to switch without handling changes (to detect if there are changes)
        performBranchSwitch(selectedBranch, 'fail', button, originalText);
    });

    function performBranchSwitch(branchName, handleChanges, button, originalText) {
        fetch('/api/platforms/switch', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                branch: branchName,
                handle_changes: handleChanges
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                // Check if the error is due to uncommitted changes
                if (data.has_changes && handleChanges === 'fail') {
                    // Show changes modal
                    showChangesModal(branchName, button, originalText);
                    return;
                }
                throw new Error(data.error);
            }

            // Success - update UI
            handleSuccessfulBranchSwitch(data, branchName, button, originalText);
        })
        .catch(error => {
            console.error('Error switching branch:', error);

            // Show error message
            $('#switchAlert')
                .removeClass('alert-success')
                .addClass('alert-danger')
                .html(`<i class="fas fa-exclamation-triangle"></i> Error switching branch: ${error.message}`)
                .show();

            // Reset button
            button.prop('disabled', true);
            button.html('<i class="fas fa-exchange-alt"></i> Switch');
        });
    }

    function showChangesModal(branchName, button, originalText) {
        // Reset button first
        button.prop('disabled', true);
        button.html('<i class="fas fa-exchange-alt"></i> Switch');

        // Create and show modal
        const modalHtml = `
            <div class="modal fade" id="changesModal" tabindex="-1" role="dialog" aria-labelledby="changesModalLabel" aria-hidden="true">
                <div class="modal-dialog" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="changesModalLabel">
                                <i class="fas fa-exclamation-triangle text-warning"></i>
                                Uncommitted Changes Detected
                            </h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <p>You have uncommitted changes in your working directory. Before switching to branch <strong>${branchName}</strong>, you need to handle these changes.</p>
                            <p>What would you like to do?</p>
                            <div class="alert alert-info">
                                <strong>Stash:</strong> Temporarily save your changes so you can restore them later.<br>
                                <strong>Cancel:</strong> Keep your changes and stay on the current branch.
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">
                                <i class="fas fa-times"></i> Cancel
                            </button>
                            <button type="button" class="btn btn-outline-warning" id="stashAndSwitch">
                                <i class="fas fa-archive"></i> Stash Changes & Switch
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Remove existing modal if any
        $('#changesModal').remove();

        // Add modal to body
        $('body').append(modalHtml);

        // Show modal
        $('#changesModal').modal('show');

        // Handle stash and switch
        $('#stashAndSwitch').on('click', function() {
            const stashButton = $(this);

            stashButton.html('<i class="fas fa-spinner fa-spin"></i> Stashing...');
            stashButton.prop('disabled', true);

            // Close modal
            $('#changesModal').modal('hide');

            // Perform switch with stash
            button.prop('disabled', true);
            button.html('<i class="fas fa-spinner fa-spin"></i> Switching...');
            performBranchSwitch(branchName, 'stash', button, originalText);
        });

        // Clean up modal on close
        $('#changesModal').on('hidden.bs.modal', function () {
            $(this).remove();
        });
    }

    function handleSuccessfulBranchSwitch(data, branchName, button, originalText) {
        // Update current branch
        currentBranch = branchName;

        // Build success message
        let successMessage = `<i class="fas fa-check-circle"></i> Successfully switched to branch: <strong>${branchName}</strong>`;

        // Add stash information
        if (data.changes_handled === 'stashed') {
            successMessage += `<br><small class="text-muted"><i class="fas fa-archive"></i> Changes were stashed as: ${data.stash_created}</small>`;
        }

        if (data.stash_restored) {
            successMessage += `<br><small class="text-success"><i class="fas fa-undo"></i> Automatically restored previous work from: ${data.stash_applied}</small>`;
        }

        $('#switchAlert')
            .removeClass('alert-danger')
            .addClass('alert-success')
            .html(successMessage)
            .show();

        // Update branch status information
        if (data.branch_info) {
            updateBranchStatus(data.branch_info);
            updateBranchBadge(data.branch_info);
        }

        // Update QPU table if QPUs changed
        if (data.qpus) {
            updateQPUTable(data.qpus);
        }

        // Refresh branch selector
        populateBranchSelector();

        // Auto-hide success message after 8 seconds (longer if stash info)
        const hideDelay = (data.changes_handled || data.stash_restored) ? 8000 : 5000;
        setTimeout(() => {
            $('#switchAlert').fadeOut();
        }, hideDelay);

        // Reset button
        button.prop('disabled', true);
        button.html('<i class="fas fa-exchange-alt"></i> Switch');
    }

    // Update branch status display (replace the hashed html block '#branchStatus')
    function updateBranchStatus(branchInfo) {
        let statusHtml = `
            <div class="row">
                <div class="col-4">
                    <p><strong>Commit:</strong></p>
                </div>
                <div class="col-8">
                    <p><code>${branchInfo.commit}</code></p>
                </div>
            </div>
            <div class="row">
                <div class="col-4">
                    <p><strong>Message:</strong></p>
                </div>
                <div class="col-8">
                    <small class="text-muted">${branchInfo.commit_message}</small></p>
                </div>
            </div>
        `;
        $('#branchStatus').html(statusHtml);
    }

    function updateBranchBadge(branchInfo) {
        let medalHtml = '';
        if (branchInfo.ahead > 0) {
            medalHtml += `<span class="badge badge-info">${branchInfo.ahead} commits ahead</span>`;
        }
        if (branchInfo.behind > 0) {
            medalHtml += `<span class="badge badge-info">${branchInfo.behind} commits behind</span>`;
        }
        if (!branchInfo.clean) {
            medalHtml += `<span class="badge badge-warning">Unstaged changes</span>`;
        }
        $('#branchBadge').html(medalHtml);
    }

    // Update QPU table with new data
    function updateQPUTable(qpus) {
        const tbody = $('#qpuTable tbody');
        tbody.empty();

        qpus.forEach(qpu => {
            // Determine status badge class
            let statusClass = 'badge-danger'; // default for offline
            if (qpu.status === 'online') {
                statusClass = 'badge-success';
            } else if (qpu.status === 'running') {
                statusClass = 'badge-success';
            }

            // Format topology column
            let topologyHtml;
            if (qpu.topology && qpu.topology !== 'N/A' && qpu.topology !== 'unknown') {
                topologyHtml = `<a href="#" class="topology-link" data-qpu="${qpu.name}" data-topology="${qpu.topology}">
                    <span class="badge badge-info">${qpu.topology}</span>
                </a>`;
            } else {
                topologyHtml = `<span class="text-muted">${qpu.topology || 'N/A'}</span>`;
            }

            const row = `
                <tr>
                    <td><strong>${qpu.name}</strong></td>
                    <td>${qpu.qubits || 'N/A'}</td>
                    <td>
                        <span class="badge ${statusClass}">${qpu.status}</span>
                    </td>
                    <td>${qpu.queue || 'N/A'}</td>
                    <td>${topologyHtml}</td>
                    <td>${qpu.calibration_time || 'N/A'}</td>
                </tr>
            `;
            tbody.append(row);
        });

        // Re-attach topology click handlers for the new elements
        attachTopologyHandlers();
    }

    // Refresh branches button
    $('#refreshBranches').on('click', function() {
        const button = $(this);
        const originalHtml = button.html();

        button.html('<i class="fas fa-spinner fa-spin"></i>');
        button.prop('disabled', true);

        loadBranches();

        setTimeout(() => {
            button.html(originalHtml);
            button.prop('disabled', false);
        }, 1000);
    });

    // Load branches on page load
    loadBranches();

    // Git Commit functionality
    $('#gitCommit').on('click', function() {
        const button = $(this);
        const originalHtml = button.html();

        button.html('<i class="fas fa-spinner fa-spin"></i>');
        button.prop('disabled', true);

        // Hide previous alerts
        $('#switchAlert').hide();

        fetch('/api/platforms/commit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: 'Update platform configurations (qibolab version detection)'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }

            // Show success message
            $('#switchAlert')
                .removeClass('alert-danger')
                .addClass('alert-success')
                .html(`<i class="fas fa-check-circle"></i> Successfully committed changes: <strong>${data.commit_hash}</strong>`)
                .show();

            // Update branch status if provided
            if (data.branch_info) {
                updateBranchStatus(data.branch_info);
                updateBranchBadge(data.branch_info);
            }

            // Auto-hide success message after 5 seconds
            setTimeout(() => {
                $('#switchAlert').fadeOut();
            }, 5000);
        })
        .catch(error => {
            console.error('Error committing changes:', error);

            // Show error message
            $('#switchAlert')
                .removeClass('alert-success')
                .addClass('alert-danger')
                .html(`<i class="fas fa-exclamation-triangle"></i> Error committing changes: ${error.message}`)
                .show();
        })
        .finally(() => {
            // Reset button
            button.html(originalHtml);
            button.prop('disabled', false);
        });
    });

    // Discard Changes functionality
    $('#discardChanges').on('click', function() {
        // Show confirmation modal
        const modalHtml = `
            <div class="modal fade" id="discardModal" tabindex="-1" role="dialog" aria-labelledby="discardModalLabel" aria-hidden="true">
                <div class="modal-dialog" role="document">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="discardModalLabel">
                                <i class="fas fa-exclamation-triangle text-danger"></i>
                                Confirm Discard Changes
                            </h5>
                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                <span aria-hidden="true">&times;</span>
                            </button>
                        </div>
                        <div class="modal-body">
                            <p><strong>Warning:</strong> This action will permanently delete all uncommitted changes in your working directory.</p>
                            <p>This includes:</p>
                            <ul>
                                <li>Modified files that haven't been committed</li>
                                <li>Staged changes that haven't been committed</li>
                                <li>New files that haven't been added to git</li>
                            </ul>
                            <div class="alert alert-danger">
                                <strong>This action cannot be undone!</strong> Make sure you don't need any of these changes.
                            </div>
                            <p>Are you sure you want to continue?</p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">
                                <i class="fas fa-times"></i> Cancel
                            </button>
                            <button type="button" class="btn btn-danger" id="confirmDiscard">
                                <i class="fas fa-trash"></i> Yes, Discard All Changes
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Remove existing modal if any
        $('#discardModal').remove();

        // Add modal to body
        $('body').append(modalHtml);

        // Show modal
        $('#discardModal').modal('show');

        // Handle confirmation
        $('#confirmDiscard').on('click', function() {
            const confirmButton = $(this);

            confirmButton.html('<i class="fas fa-spinner fa-spin"></i> Discarding...');
            confirmButton.prop('disabled', true);

            // Close modal
            $('#discardModal').modal('hide');

            // Perform discard
            performDiscardChanges();
        });

        // Clean up modal on close
        $('#discardModal').on('hidden.bs.modal', function () {
            $(this).remove();
        });
    });

    function performDiscardChanges() {
        // Hide previous alerts
        $('#switchAlert').hide();

        fetch('/api/platforms/discard', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }

            // Show success message
            const fileCount = data.discarded_files ? data.discarded_files.length : 0;
            const successMessage = `<i class="fas fa-check-circle"></i> Successfully discarded all uncommitted changes<br><small class="text-muted">Removed ${fileCount} modified file${fileCount !== 1 ? 's' : ''}</small>`;

            $('#switchAlert')
                .removeClass('alert-danger')
                .addClass('alert-success')
                .html(successMessage)
                .show();

            // Refresh current branch info to reflect clean state
            updateBranchInfoAfterDiscard();

            // Auto-hide success message after 5 seconds
            setTimeout(() => {
                $('#switchAlert').fadeOut();
            }, 5000);
        })
        .catch(error => {
            console.error('Error discarding changes:', error);

            // Show error message
            $('#switchAlert')
                .removeClass('alert-success')
                .addClass('alert-danger')
                .html(`<i class="fas fa-exclamation-triangle"></i> Error discarding changes: ${error.message}`)
                .show();
        });
    }

    function updateBranchInfoAfterDiscard() {
        // Fetch current branch info to update the display
        fetch('/api/platforms/current')
            .then(response => response.json())
            .then(data => {
                if (data && !data.error) {
                    updateBranchStatus(data);
                    updateBranchBadge(data);
                }
            })
            .catch(error => {
                console.log('Could not refresh branch info:', error);
            });
    }

    // Function to attach topology click handlers (used for dynamically added elements)
    function attachTopologyHandlers() {
        $('.topology-link').off('click').on('click', function(e) {
            e.preventDefault();

            const qpuName = $(this).data('qpu');
            const topologyType = $(this).data('topology');

            // Reset modal state
            $('#topologyLoading').show();
            $('#topologyContent').hide();
            $('#topologyError').hide();
            $('#topologyModalLabel').text(`${qpuName} - Topology Visualization`);

            // Show modal
            $('#topologyModal').modal('show');

            // Fetch topology visualization
            fetch(`/api/qpu_topology/${qpuName}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }
                    return response.json();
                })
                .then(data => {
                    // Hide loading indicator
                    $('#topologyLoading').hide();

                    // Populate topology info
                    $('#topologyInfo').html(`
                        <div class="row">
                            <div class="col-md-4">
                                <strong>Topology Type:</strong> ${data.topology_type.charAt(0).toUpperCase() + data.topology_type.slice(1)}
                            </div>
                            <div class="col-md-4">
                                <strong>Qubits:</strong> ${data.num_qubits}
                            </div>
                            <div class="col-md-4">
                                <strong>Connections:</strong> ${data.num_connections}
                            </div>
                        </div>
                    `);

                    // Set image source
                    $('#topologyImage').attr('src', `data:image/png;base64,${data.image}`);
                    $('#topologyImage').attr('alt', `${qpuName} ${data.topology_type} topology`);

                    // Show content
                    $('#topologyContent').show();
                })
                .catch(error => {
                    console.error('Error fetching topology:', error);

                    // Hide loading indicator
                    $('#topologyLoading').hide();

                    // Show error message
                    $('#errorMessage').text(error.message || 'Failed to load topology visualization.');
                    $('#topologyError').show();
                });
        });
    }

    // Git Push functionality
    $('#gitPush').on('click', function() {
        const button = $(this);
        const originalHtml = button.html();

        button.html('<i class="fas fa-spinner fa-spin"></i>');
        button.prop('disabled', true);

        // Hide previous alerts
        $('#switchAlert').hide();

        fetch('/api/platforms/push', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }

            // Show success message
            $('#switchAlert')
                .removeClass('alert-danger')
                .addClass('alert-success')
                .html(`<i class="fas fa-check-circle"></i> Successfully pushed to remote: <strong>${data.remote}</strong>`)
                .show();

            // Update branch status if provided
            if (data.branch_info) {
                updateBranchStatus(data.branch_info);
            }

            // Auto-hide success message after 5 seconds
            setTimeout(() => {
                $('#switchAlert').fadeOut();
            }, 5000);
        })
        .catch(error => {
            console.error('Error pushing changes:', error);

            // Show error message
            $('#switchAlert')
                .removeClass('alert-success')
                .addClass('alert-danger')
                .html(`<i class="fas fa-exclamation-triangle"></i> Error pushing changes: ${error.message}`)
                .show();
        })
        .finally(() => {
            // Reset button
            button.html(originalHtml);
            button.prop('disabled', false);
        });
    });
});
