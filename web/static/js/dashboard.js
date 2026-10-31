// ========================================
// Dashboard Functions
// ========================================

function enterpriseJson(id, fallback) {
    const value = document.getElementById(id)?.value?.trim();
    if (!value) return fallback;
    try { return JSON.parse(value); } catch (error) {
        throw new Error(`${id}: JSON non valido`);
    }
}

async function runEnterpriseResearch(tool, payload) {
    const output = document.getElementById('enterpriseResults');
    try {
        output.textContent = 'Loading...';
        const response = await fetch(`/api/seo/research/${encodeURIComponent(tool)}`, {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload || {})
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
        output.textContent = JSON.stringify(data, null, 2);
        return data;
    } catch (error) {
        output.textContent = `Errore: ${error.message}`;
        return null;
    }
}

async function runEnterpriseDashboard() {
    try {
        return runEnterpriseResearch('dashboard', {
            projects: enterpriseJson('enterpriseProjects', []),
            bot_logs: enterpriseJson('enterpriseBotLogs', []),
            data_rows: enterpriseJson('enterpriseProjects', [])
        });
    } catch (error) {
        document.getElementById('enterpriseResults').textContent = `Errore: ${error.message}`;
    }
}

async function runEnterpriseCapabilities() {
    return runEnterpriseResearch('capabilities', {});
}

async function runEnterpriseHistory() {
    try {
        return runEnterpriseResearch('page-history', {
            snapshots: enterpriseJson('enterpriseSnapshots', [])
        });
    } catch (error) {
        document.getElementById('enterpriseResults').textContent = `Errore: ${error.message}`;
    }
}

async function runEnterprisePatches() {
    try {
        return runEnterpriseResearch('patch-automation', {
            issues: enterpriseJson('enterpriseIssues', []), approved: false
        });
    } catch (error) {
        document.getElementById('enterpriseResults').textContent = `Errore: ${error.message}`;
    }
}

async function applyEnterprisePatchesLocally() {
    try {
        const issues = enterpriseJson('enterpriseIssues', []);
        const preview = await runEnterpriseResearch('patch-automation', {issues, approved: true});
        if (!preview) return;
        return runEnterpriseResearch('patch-apply', {rows: issues, plans: preview.plans || preview.data?.plans || [], approved: true});
    } catch (error) {
        document.getElementById('enterpriseResults').textContent = `Errore: ${error.message}`;
    }
}

async function runEnterpriseReportTask() {
    return runEnterpriseResearch('report-task', {
        async: true,
        data: {projects: enterpriseJson('enterpriseProjects', []), generated_at: new Date().toISOString()}
    });
}

async function runEnterpriseAiVisibility() {
    try {
        return runEnterpriseResearch('ai-visibility', {
            target_domain: document.getElementById('enterpriseAiDomain').value.trim(),
            prompts: enterpriseJson('enterpriseAiPrompts', [])
        });
    } catch (error) {
        document.getElementById('enterpriseResults').textContent = `Errore: ${error.message}`;
    }
}

async function runEnterpriseNextTool() {
    const output=document.getElementById('enterpriseNextResults');
    try {
        const raw=document.getElementById('enterpriseNextPayload').value.trim();
        const payload=raw ? JSON.parse(raw) : {};
        const tool=document.getElementById('enterpriseNextTool').value;
        const response=await fetch(`/api/enterprise-next/${encodeURIComponent(tool)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const data=await response.json();
        if(!response.ok||data.error) throw new Error(data.error||`HTTP ${response.status}`);
        output.textContent=JSON.stringify(data,null,2);
    } catch(error) { output.textContent=`Errore: ${error.message}`; }
}

async function openDashboard() {
    const modal = document.getElementById('dashboardModal');
    const content = document.getElementById('dashboardContent');

    // Show modal
    modal.style.display = 'flex';

    // Load crawls
    try {
        const response = await fetch('/api/crawls/list');
        const data = await response.json();

        if (!data.success) {
            content.innerHTML = `<p style="color: #ef4444;">Error loading crawls: ${data.error}</p>`;
            return;
        }

        const crawls = data.crawls || [];

        if (crawls.length === 0) {
            content.innerHTML = `<p style="text-align: center; color: #9ca3af;">No saved crawls found.</p>`;
            return;
        }

        // Build table
        let html = `
            <table class="data-table" style="width: 100%; table-layout: fixed;">
                <thead>
                    <tr>
                        <th style="width: 180px;">Date</th>
                        <th style="width: 200px;">Domain</th>
                        <th style="width: 80px;">URLs</th>
                        <th style="width: 100px;">Status</th>
                        <th style="width: 280px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
        `;

        crawls.forEach(crawl => {
            const date = new Date(crawl.started_at).toLocaleString();
            const domain = crawl.base_domain || crawl.base_url;
            const status = crawl.status || 'unknown';
            const statusColor = status === 'completed' ? '#10b981' : status === 'running' ? '#3b82f6' : status === 'paused' ? '#f59e0b' : '#6b7280';

            html += `
                <tr>
                    <td>${date}</td>
                    <td>${domain}</td>
                    <td>${crawl.urls_crawled || 0}</td>
                    <td><span style="color: ${statusColor};">${status}</span></td>
                    <td style="white-space: nowrap;">
                        <button class="btn btn-primary" style="margin-right: 5px; padding: 6px 12px; font-size: 13px;" onclick="loadCrawlFromDashboard(${crawl.id})">Load</button>
                        ${['paused', 'failed', 'running', 'stopped'].includes(status) ? `<button class="btn btn-secondary" style="margin-right: 5px; padding: 6px 12px; font-size: 13px;" onclick="resumeCrawlFromDashboard(${crawl.id})">Resume</button>` : ''}
                        <button class="btn btn-danger" style="padding: 6px 12px; font-size: 13px;" onclick="deleteCrawlFromDashboard(${crawl.id})">Delete</button>
                    </td>
                </tr>
            `;
        });

        html += `
                </tbody>
            </table>
        `;

        content.innerHTML = html;

    } catch (error) {
        console.error('Error loading dashboard:', error);
        content.innerHTML = `<p style="color: #ef4444;">Error loading crawls.</p>`;
    }
}

function closeDashboard() {
    document.getElementById('dashboardModal').style.display = 'none';
}

async function loadCrawlFromDashboard(crawlId) {
    if (!confirm('Load this crawl? Any unsaved current data will be lost.')) return;

    try {
        // Call backend to load data into current crawler
        const response = await fetch(`/api/crawls/${crawlId}/load`, {
            method: 'POST'
        });
        const data = await response.json();

        if (!data.success) {
            alert('Error: ' + (data.error || data.message));
            return;
        }

        // Close dashboard
        closeDashboard();

        // Fetch the loaded data
        const statusResponse = await fetch('/api/crawl_status');
        const statusData = await statusResponse.json();

        // Clear UI
        clearAllTables();
        resetStats();

        // Populate data
        crawlState.urls = [];
        crawlState.links = statusData.links || [];
        crawlState.issues = statusData.issues || [];
        crawlState.stats = statusData.stats || {};
        crawlState.baseUrl = statusData.stats?.baseUrl || '';

        // Set URL input
        if (crawlState.baseUrl) {
            document.getElementById('urlInput').value = crawlState.baseUrl;
        }

        // Add URLs to tables
        if (statusData.urls && statusData.urls.length > 0) {
            statusData.urls.forEach(url => addUrlToTable(url));
        }

        // Load links
        if (statusData.links && statusData.links.length > 0) {
            crawlState.pendingLinks = statusData.links;
        }

        // Load issues
        if (statusData.issues && statusData.issues.length > 0) {
            crawlState.pendingIssues = statusData.issues;
        }

        // Update displays
        updateStatsDisplay();
        updateFilterCounts();
        updateStatusCodesTable();
        updateCrawlButtons();
        updateStatus(`Loaded: ${statusData.urls?.length || 0} URLs`);

        showNotification('Crawl loaded successfully', 'success');

    } catch (error) {
        console.error('Error loading crawl:', error);
        alert('Error loading crawl');
    }
}

async function resumeCrawlFromDashboard(crawlId) {
    if (!confirm('Resume this crawl? Any unsaved current data will be lost.')) return;

    try {
        // Call backend to resume
        const response = await fetch(`/api/crawls/${crawlId}/resume`, {
            method: 'POST'
        });
        const data = await response.json();

        if (!data.success) {
            alert('Error: ' + (data.error || data.message));
            return;
        }

        // Close dashboard
        closeDashboard();

        // Fetch the loaded data
        const statusResponse = await fetch('/api/crawl_status');
        const statusData = await statusResponse.json();

        // Clear UI
        clearAllTables();
        resetStats();

        // Populate data
        crawlState.urls = [];
        crawlState.links = statusData.links || [];
        crawlState.issues = statusData.issues || [];
        crawlState.stats = statusData.stats || {};
        crawlState.baseUrl = statusData.stats?.baseUrl || '';

        // Set URL input
        if (crawlState.baseUrl) {
            document.getElementById('urlInput').value = crawlState.baseUrl;
        }

        // Add URLs to tables
        if (statusData.urls && statusData.urls.length > 0) {
            statusData.urls.forEach(url => addUrlToTable(url));
        }

        // Load links
        if (statusData.links && statusData.links.length > 0) {
            crawlState.pendingLinks = statusData.links;
        }

        // Load issues
        if (statusData.issues && statusData.issues.length > 0) {
            crawlState.pendingIssues = statusData.issues;
        }

        // Set crawl as running
        if (statusData.status === 'running') {
            crawlState.isRunning = true;
            crawlState.isPaused = false;
            crawlState.startTime = new Date();
            showProgress();
            updateCrawlButtons();
            pollCrawlProgress();
        }

        // Update displays
        updateStatsDisplay();
        updateFilterCounts();
        updateStatusCodesTable();
        updateStatus('Crawl resumed');

        showNotification('Crawl resumed successfully', 'success');

    } catch (error) {
        console.error('Error resuming crawl:', error);
        alert('Error resuming crawl');
    }
}

async function deleteCrawlFromDashboard(crawlId) {
    if (!confirm('Delete this crawl permanently? This cannot be undone.')) return;

    try {
        const response = await fetch(`/api/crawls/${crawlId}/delete`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (data.success) {
            showNotification('Crawl deleted', 'success');
            // Reload dashboard
            openDashboard();
        } else {
            alert('Error deleting crawl: ' + data.error);
        }
    } catch (error) {
        console.error('Error deleting crawl:', error);
        alert('Error deleting crawl');
    }
}
