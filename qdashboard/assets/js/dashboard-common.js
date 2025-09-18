/**
 * QDashboard Common JavaScript Functions
 * Shared functionality for SLURM job management and monitoring across multiple pages
 * 
 * USAGE:
 * To use this module in a template, include it after the basic jQuery/Bootstrap scripts:
 * 
 * <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
 * <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.5.4/dist/umd/popper.min.js"></script>
 * <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
 * <script src="{{url_for('static', filename='js/dashboard-common.js')}}"></script>
 * 
 * FEATURES PROVIDED:
 * - cancelJob(jobId): Cancel SLURM jobs
 * - refreshSlurmData(): Refresh SLURM queue status
 * - refreshSlurmLog(): Refresh SLURM log content
 * - Auto-refresh functionality with start/stop controls
 * - Automatic DOM event binding on page load
 * 
 * REQUIRED HTML ELEMENTS (optional - functions gracefully handle missing elements):
 * - #refresh-slurm-btn: Button to manually refresh SLURM data
 * - #refresh-log-btn: Button to manually refresh SLURM log
 * - #toggle-auto-refresh: Button to toggle auto-refresh mode
 * - #slurm-content: Container for SLURM queue table
 * - #slurm-log-content: Container for SLURM log content
 * - #slurm-last-update: Element to show last update timestamp
 * - #slurm-log-last-update: Element to show log last update timestamp
 */

// Global variables for auto-refresh functionality
let slurmDataInterval;
let slurmLogInterval;
let isAutoRefreshActive = false;

/**
 * Job cancellation function
 * Used to cancel SLURM jobs that belong to the current user
 * @param {string} jobId - The SLURM job ID to cancel
 */
function cancelJob(jobId) {
    if (!confirm(`Are you sure you want to cancel job ${jobId}?`)) {
        return;
    }

    fetch('/cancel_job', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            job_id: jobId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert(data.message);
            // Refresh the page to update the job list
            location.reload();
        } else {
            alert(`Error: ${data.message}`);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while cancelling the job.');
    });
}

/**
 * SLURM data refresh functionality
 * Fetches updated SLURM queue status and updates the display
 */
function refreshSlurmData() {
    const refreshBtn = document.getElementById('refresh-slurm-btn'); // Refresh button (optional in the html)
    const slurmContent = document.getElementById('slurm-content'); 

    if (!slurmContent) return; // If element doesn't exist, skip update

    // Only show loading state in manual mode (when buttons exist and auto-refresh is not active)
    if (!isAutoRefreshActive && refreshBtn) {
        refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        refreshBtn.disabled = true;
    }
    
    fetch('/api/slurm_status')
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // Update SLURM queue table
            updateSlurmTable(data.queue_status);
            // Update SLURM log
            updateSlurmLog(data.last_log);
            
            // Update timestamp indicator
            const timestamp = document.getElementById('slurm-last-update');
            if (timestamp) {
                const now = new Date();
                timestamp.textContent = `Last updated: ${now.toLocaleTimeString()}`;
            }
        } else {
            if (!isAutoRefreshActive) {
                console.war('Failed to refresh SLURM data: ' + data.message);
            } else {
                // If in auto mode and API returns error, stop auto-refresh
                console.warn('Auto-refresh stopped due to SLURM  API error:', data.message);
                stopAutoRefresh();
            }
        }
    }) // Errors not managed in the API (or the SLURM API not working)
    .catch(error => {
        if (!isAutoRefreshActive) {
            console.error('An error occurred while refreshing SLURM data.');
        } else {
            // If in auto mode and error occurs, stop auto-refresh
            console.warn('Auto-refresh stopped due to SLURM data error:', error);
            stopAutoRefresh();
        }
    })
    .finally(() => {
        // Reset button state only in manual mode (when buttons exist and auto-refresh is not active)
        if (!isAutoRefreshActive && refreshBtn) {
            refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i>';
            refreshBtn.disabled = false;
        }
    });
}

/**
 * Update SLURM table with new job data
 * @param {Array} jobs - Array of job objects
 */
function updateSlurmTable(jobs) {
    const slurmContent = document.getElementById('slurm-content');
    
    if (!slurmContent) return; // If element doesn't exist, skip update
    
    if (jobs.length === 0) {
        slurmContent.innerHTML = `
            <div class="text-center text-muted">
                <i class="fas fa-inbox fa-2x mb-2"></i>
                <p>No jobs in queue</p>
            </div>
        `;
    } else {
        let tableHtml = `
            <div class="table-responsive">
                <table class="table table-dark table-striped table-hover">
                    <thead>
                        <tr>
                            <th>Job ID</th>
                            <th>Name</th>
                            <th>User</th>
                            <th>State</th>
                            <th>Time</th>
                            <th>Time Limit</th>
                            <th>Nodes</th>
                            <th>Node List</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        jobs.forEach(job => {
            let stateBadge = '';
            if (job.state === 'RUNNING') {
                stateBadge = `<span class="badge badge-success">${job.state}</span>`;
            } else if (job.state === 'PENDING') {
                stateBadge = `<span class="badge badge-warning">${job.state}</span>`;
            } else if (['COMPLETED', 'COMPLETING'].includes(job.state)) {
                stateBadge = `<span class="badge badge-info">${job.state}</span>`;
            } else if (['FAILED', 'CANCELLED', 'TIMEOUT'].includes(job.state)) {
                stateBadge = `<span class="badge badge-danger">${job.state}</span>`;
            } else {
                stateBadge = `<span class="badge badge-secondary">${job.state}</span>`;
            }
            
            let actionButton = '';
            if (job.is_current_user && ['RUNNING', 'PENDING'].includes(job.state)) {
                actionButton = `
                    <button class="btn btn-sm btn-danger" 
                            onclick="cancelJob('${job.job_id}')"
                            title="Cancel job">
                        <i class="fas fa-times"></i>
                    </button>
                `;
            } else {
                actionButton = '<span class="text-muted">—</span>';
            }
            
            tableHtml += `
                <tr>
                    <td>${job.job_id}</td>
                    <td>${job.name}</td>
                    <td>${job.user}</td>
                    <td>${stateBadge}</td>
                    <td>${job.time}</td>
                    <td>${job.time_limit}</td>
                    <td>${job.nodes}</td>
                    <td>${job.nodelist}</td>
                    <td>${actionButton}</td>
                </tr>
            `;
        });
        
        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;
        
        slurmContent.innerHTML = tableHtml;
    }
}

/**
 * Update SLURM log content
 * @param {string} logContent - The log content to display
 */
function updateSlurmLog(logContent) {
    const logElement = document.getElementById('slurm-log-content');
    if (logElement) {
        logElement.innerHTML = `<code>${logContent}</code>`;
    }
}

/**
 * Refresh only the SLURM log
 */
function refreshSlurmLog() {
    const refreshLogBtn = document.getElementById('refresh-log-btn');
    
    // Only show loading state in manual mode (when buttons exist and auto-refresh is not active)
    if (!isAutoRefreshActive && refreshLogBtn) {
        refreshLogBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        refreshLogBtn.disabled = true;
    }
    
    fetch('/api/slurm_status')
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            updateSlurmLog(data.last_log);
            
            // Update timestamp indicator for log
            const logTimestamp = document.getElementById('slurm-log-last-update');
            if (logTimestamp) {
                const now = new Date();
                logTimestamp.textContent = `Last updated: ${now.toLocaleTimeString()}`;
            }
        } else {
            console.error('Error refreshing SLURM log:', data.message);
            if (!isAutoRefreshActive) {
                alert('Failed to refresh SLURM log: ' + data.message);
            } else {
                // If in auto mode and API returns error, stop auto-refresh
                console.warn('Auto-refresh stopped due to SLURM log API error:', data.message);
                stopAutoRefresh();
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (!isAutoRefreshActive) {
            alert('An error occurred while refreshing SLURM log.');
        } else {
            // If in auto mode and error occurs, stop auto-refresh
            console.warn('Auto-refresh stopped due to SLURM log error:', error);
            stopAutoRefresh();
        }
    })
    .finally(() => {
        // Reset button state only in manual mode (when buttons exist and auto-refresh is not active)
        if (!isAutoRefreshActive && refreshLogBtn) {
            refreshLogBtn.innerHTML = '<i class="fas fa-sync-alt"></i>';
            refreshLogBtn.disabled = false;
        }
    });
}

/**
 * Start auto-refresh functionality
 */
function startAutoRefresh() {
    if (isAutoRefreshActive) return;
    
    isAutoRefreshActive = true;
    
    // Refresh SLURM queue every 2 seconds
    slurmDataInterval = setInterval(refreshSlurmData, 2000);
    // Refresh SLURM log every 2 seconds
    slurmLogInterval = setInterval(refreshSlurmLog, 2000);
    
    // Update toggle button
    const toggleBtn = document.getElementById('toggle-auto-refresh');
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i class="fas fa-pause"></i>';
        toggleBtn.title = 'Stop auto-refresh (2s interval)';
        toggleBtn.classList.remove('btn-outline-secondary');
        toggleBtn.classList.add('btn-outline-warning');
    }
    
    // Update refresh button text to indicate auto-refresh is active
    const refreshBtn = document.getElementById('refresh-slurm-btn');
    const refreshLogBtn = document.getElementById('refresh-log-btn');
    
    if (refreshBtn) {
        refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Auto (2s)';
        refreshBtn.title = 'Auto-refresh active (2s interval)';
    }
    
    if (refreshLogBtn) {
        refreshLogBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Auto (2s)';
        refreshLogBtn.title = 'Auto-refresh active (2s interval)';
    }
}

/**
 * Stop auto-refresh functionality
 */
function stopAutoRefresh() {
    if (!isAutoRefreshActive) return;
    
    isAutoRefreshActive = false;
    
    clearInterval(slurmDataInterval);
    clearInterval(slurmLogInterval);
    
    // Update toggle button
    const toggleBtn = document.getElementById('toggle-auto-refresh');
    
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i class="fas fa-play"></i>';
        toggleBtn.title = 'Start auto-refresh (2s interval)';
        toggleBtn.classList.remove('btn-outline-warning');
        toggleBtn.classList.add('btn-outline-secondary');
    }
    
    // Reset refresh button text to manual mode
    const refreshBtn = document.getElementById('refresh-slurm-btn');
    const refreshLogBtn = document.getElementById('refresh-log-btn');
    
    if (refreshBtn) {
        refreshBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh';
        refreshBtn.title = 'Click to refresh manually';
    }
    
    if (refreshLogBtn) {
        refreshLogBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh';
        refreshLogBtn.title = 'Click to refresh manually';
    }
}

/**
 * Toggle auto-refresh functionality
 */
function toggleAutoRefresh() {
    if (isAutoRefreshActive) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
    }
}

/**
 * Initialize dashboard common functionality
 * Call this function on page load to set up event listeners
 */
function initializeDashboardCommon() {
    // Add event listeners for refresh buttons and toggle
    const refreshBtn = document.getElementById('refresh-slurm-btn');
    const refreshLogBtn = document.getElementById('refresh-log-btn');
    const toggleBtn = document.getElementById('toggle-auto-refresh');
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshSlurmData);
    }
    
    if (refreshLogBtn) {
        refreshLogBtn.addEventListener('click', refreshSlurmLog);
    }
    
    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleAutoRefresh);
    }
    
    // Check if SLURM content elements exist to determine if auto-refresh should be enabled
    const slurmContent = document.getElementById('slurm-content');
    const slurmLogContent = document.getElementById('slurm-log-content');
    
    // Start auto-refresh immediately when page loads if SLURM elements are present
    if (slurmContent || slurmLogContent) {
        startAutoRefresh();
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initializeDashboardCommon);
