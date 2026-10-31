// Application State
let crawlState = {
    isRunning: false,
    isPaused: false,
    startTime: null,
    baseUrl: null,
    urls: [],
    links: [],
    issues: [],
    stats: {
        discovered: 0,
        crawled: 0,
        depth: 0,
        speed: 0
    },
    filters: {
        active: null,
        issueFilter: 'all',
        linksFilter: {
            internalStatusCode: 'all',
            externalStatusCode: 'all',
            internalSearch: '',
            externalSearch: ''
        }
    }
};

// Incremental polling instance
let incrementalPoller = null;
const LARGE_CRAWL_THRESHOLD = 5000;
const LARGE_CRAWL_CLIENT_LIMIT = 2500;
let largeCrawlMode = false;

// Virtual Scrollers
let virtualScrollers = {
    overview: null,
    internal: null,
    external: null,
    internalLinks: null,
    externalLinks: null,
    issues: null
};

// Initialize application
document.addEventListener('DOMContentLoaded', async function() {
    await initializeApp();
});

async function initializeApp() {
    // Load plugins first (before tabs are initialized)
    if (window.LibreCrawlPlugin && window.LibreCrawlPlugin.loader) {
        await window.LibreCrawlPlugin.loader.loadAllPlugins();
        window.LibreCrawlPlugin.loader.initializePlugins();
    }

    // Setup event listeners
    setupEventListeners();

    // Initialize tables
    initializeTables();

    // Load user info
    loadUserInfo();

    // DEBUG: Check sessionStorage
    console.log('DEBUG: Checking sessionStorage force_ui_refresh:', sessionStorage.getItem('force_ui_refresh'));

    // Check if we just loaded a crawl from dashboard
    if (sessionStorage.getItem('force_ui_refresh') === 'true') {
        console.log('DEBUG: Found force_ui_refresh flag, loading crawl data...');
        sessionStorage.removeItem('force_ui_refresh');

        try {
            // Fetch the loaded data immediately with FULL refresh (no incremental)
            const response = await fetch('/api/crawl_status');
            const data = await response.json();

            // DEBUG: Log the full response
            console.log('DEBUG: Full /api/crawl_status response:', JSON.stringify(data, null, 2));

            // Clear existing data first
            clearAllTables();
            resetStats();

            // Force populate all data
            crawlState.urls = [];
            crawlState.links = data.links || [];
            crawlState.issues = data.issues || [];
            crawlState.stats = data.stats || {};
            crawlState.baseUrl = data.stats?.baseUrl || '';

            // Set URL input
            if (crawlState.baseUrl) {
                document.getElementById('urlInput').value = crawlState.baseUrl;
            }

            // Add each URL to tables
            if (data.urls && data.urls.length > 0) {
                data.urls.forEach(url => addUrlToTable(url));
            }

            // Load links if present
            if (data.links && data.links.length > 0) {
                crawlState.pendingLinks = data.links;
                // If links tab is active, load them immediately
                if (isLinksTabActive()) {
                    updateLinksTable(data.links);
                }
            }

            // Load issues if present
            if (data.issues && data.issues.length > 0) {
                crawlState.pendingIssues = data.issues;
                // If issues tab is active, load them immediately
                if (isIssuesTabActive()) {
                    updateIssuesTable(data.issues);
                } else {
                    // Update badge count even if tab not active
                    const issuesTabButton = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.textContent.includes('Issues'));
                    if (issuesTabButton && data.issues.length > 0) {
                        const errorCount = data.issues.filter(i => i.type === 'error').length;
                        const warningCount = data.issues.filter(i => i.type === 'warning').length;
                        let badgeColor = '#3b82f6';
                        if (errorCount > 0) badgeColor = '#ef4444';
                        else if (warningCount > 0) badgeColor = '#f59e0b';
                        issuesTabButton.innerHTML = `Issues <span style="background: ${badgeColor}; color: white; padding: 2px 6px; border-radius: 12px; font-size: 12px;">${data.issues.length}</span>`;
                    }
                }
            }

            // Update all displays
            updateStatsDisplay();
            updateFilterCounts();
            updateStatusCodesTable();
            updateCrawlButtons();

            // Check if the crawl is currently running (resumed from dashboard)
            if (data.status === 'running') {
                // Set crawl state to running
                crawlState.isRunning = true;
                crawlState.isPaused = false;
                crawlState.startTime = new Date(); // Set start time to now for timer

                // Show progress UI
                showProgress();

                // Update buttons for running state
                updateCrawlButtons();

                // Start polling for updates
                updateStatus('Crawl resumed - updating...');
                pollCrawlProgress();
            } else {
                // Crawl is not running, just loaded data
                updateStatus(`Loaded crawl: ${data.stats.crawled} URLs, ${data.links?.length || 0} links, ${data.issues?.length || 0} issues`);
            }

            console.log('Loaded crawl from database:', {
                urls: data.urls?.length || 0,
                links: data.links?.length || 0,
                issues: data.issues?.length || 0,
                stats: data.stats,
                status: data.status,
                isRunning: crawlState.isRunning
            });
        } catch (error) {
            console.error('Error loading crawl data:', error);
            updateStatus('Error loading crawl data');
        }
    }

    // Set initial focus
    document.getElementById('urlInput').focus();

    console.log('LibreCrawl initialized');
}

function setupEventListeners() {
    // URL input enter key
    document.getElementById('urlInput').addEventListener('keypress', handleUrlKeypress);

    // Update timer every second when crawling
    setInterval(updateTimer, 1000);
}

function handleUrlKeypress(event) {
    if (event.key === 'Enter' && !crawlState.isRunning) {
        toggleCrawl();
    }
}

function toggleCrawl() {
    if (!crawlState.isRunning) {
        startCrawl();
    } else if (crawlState.isPaused) {
        resumeCrawl();
    } else {
        pauseCrawl();
    }
}

function startCrawl() {
    const urlInput = document.getElementById('urlInput');
    let url = urlInput.value.trim();
    const crawlMode = document.getElementById('crawlMode')?.value || 'spider';
    const seedText = document.getElementById('seedUrls')?.value.trim() || '';

    if (!url) {
        alert('Please enter a URL to crawl');
        urlInput.focus();
        return;
    }

    // Normalize the URL - add protocol if missing
    url = normalizeUrl(url);

    if (!isValidUrl(url)) {
        alert('Please enter a valid URL or domain');
        urlInput.focus();
        return;
    }

    // Update the input field with the normalized URL
    urlInput.value = url;

    crawlState.isRunning = true;
    crawlState.isPaused = false;
    crawlState.startTime = new Date();
    crawlState.baseUrl = url;

    // Initialize incremental poller for new crawl
    if (!incrementalPoller) {
        incrementalPoller = new IncrementalPoller();
    }
    incrementalPoller.reset();

    // Update UI
    updateCrawlButtons();
    showProgress();
    updateStatus('Starting crawl...');

    // Clear previous data
    clearAllTables();
    resetStats();

    // Start the actual crawling via Python backend
    const seedUrls = crawlMode === 'spider'
        ? undefined
        : seedText.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    if (crawlMode !== 'spider' && !seedUrls.length) {
        alert('Enter at least one seed URL');
        crawlState.isRunning = false;
        updateCrawlButtons();
        return;
    }
    startPythonCrawl(url, crawlMode, seedUrls);
}

function updateCrawlModeHelp() {
    const mode = document.getElementById('crawlMode')?.value || 'spider';
    const group = document.getElementById('seedUrlsGroup');
    const seed = document.getElementById('seedUrls');
    if (!group || !seed) return;
    group.style.display = mode === 'spider' ? 'none' : 'block';
    seed.placeholder = mode === 'sitemap' ? 'https://example.com/sitemap.xml' : 'One URL per line';
}

function pauseCrawl() {
    crawlState.isPaused = true;
    updateCrawlButtons();
    updateStatus('Crawl paused');

    // Pause Python crawler
    fetch('/api/pause_crawl', {
        method: 'POST'
    }).catch(error => {
        console.error('Error pausing crawl:', error);
    });
}

function resumeCrawl() {
    crawlState.isPaused = false;
    updateCrawlButtons();
    updateStatus('Resuming crawl...');

    // Resume Python crawler
    fetch('/api/resume_crawl', {
        method: 'POST'
    }).catch(error => {
        console.error('Error resuming crawl:', error);
    });
}

function stopCrawl() {
    crawlState.isRunning = false;
    crawlState.isPaused = false;

    // Update UI
    updateCrawlButtons();
    hideProgress();
    updateStatus('Crawl stopped');

    // Stop Python crawler
    stopPythonCrawl();
}

function finishCrawlUi(message = 'Crawl completed') {
    crawlState.isRunning = false;
    crawlState.isPaused = false;
    updateCrawlButtons();
    hideProgress();
    updateStatus(message);
}

function clearCrawlData() {
    if (crawlState.isRunning) {
        if (!confirm('A crawl is currently running. Stop the crawl and clear all data?')) {
            return;
        }
        stopCrawl();
    }

    // Clear all data
    clearAllTables();
    resetStats();
    crawlState.urls = [];
    crawlState.links = [];
    crawlState.issues = [];
    crawlState.baseUrl = null;
    crawlState.filters.active = null;
    crawlState.pendingLinks = null;
    crawlState.pendingIssues = null;
    updateStatusCodesTable();

    // Clear issues and reset badge
    window.currentIssues = [];
    updateIssuesTable([]);  // This will also clear the badge

    // Reset issue filter counts
    document.getElementById('issues-all-count').textContent = '(0)';
    document.getElementById('issues-error-count').textContent = '(0)';
    document.getElementById('issues-warning-count').textContent = '(0)';
    document.getElementById('issues-info-count').textContent = '(0)';

    // Clear visualization
    if (typeof window.clearVisualization === 'function') {
        window.clearVisualization();
    }

    // Notify plugins of data clear (send empty data)
    if (window.LibreCrawlPlugin && window.LibreCrawlPlugin.loader) {
        window.LibreCrawlPlugin.loader.notifyDataUpdate({
            urls: [],
            links: [],
            issues: [],
            stats: { discovered: 0, crawled: 0, depth: 0, speed: 0 }
        });
    }

    // Clear filter states
    document.querySelectorAll('.filter-item').forEach(item => {
        item.classList.remove('active');
    });

    // Reset the "All Issues" filter to active
    document.querySelector('[data-filter="all"]')?.classList.add('active');

    // Update UI
    updateStatus('Data cleared');
    hideProgress();
    updateCrawlButtons(); // Update save/load button states

    // Reset URL input
    document.getElementById('urlInput').value = '';
    document.getElementById('urlInput').focus();
}

function startPythonCrawl(url, crawlMode = 'spider', seedUrls) {
    // Call Python backend to start crawling
    fetch('/api/start_crawl', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url: url, crawl_mode: crawlMode, seed_urls: seedUrls })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateStatus('Crawling in progress...');
            // Refresh user info to update crawl count
            loadUserInfo();
            // Start polling for updates
            pollCrawlProgress();
        } else {
            updateStatus('Error: ' + data.error);
            stopCrawl();
        }
    })
    .catch(error => {
        console.error('Error starting crawl:', error);
        updateStatus('Error starting crawl');
        stopCrawl();
    });
}

function stopPythonCrawl() {
    fetch('/api/stop_crawl', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        console.log('Crawl stopped:', data);
    })
    .catch(error => {
        console.error('Error stopping crawl:', error);
    });
}

function pollCrawlProgress() {
    if (!crawlState.isRunning) return;

    // Use incremental poller if available, otherwise fall back to regular fetch
    const fetchPromise = incrementalPoller
        ? incrementalPoller.fetchUpdate()
        : fetch('/api/crawl_status').then(response => response.json());

    fetchPromise
        .then(data => {
            updateCrawlData(data);

            // Update bottom status bar based on current state
            if (data.is_running_pagespeed) {
                updateStatus('Running PageSpeed analysis...');
            } else if (data.status === 'running') {
                updateStatus('Crawling in progress...');
            }

            // Update visualization if visualization tab is active
            const vizTab = document.getElementById('visualization-tab');
            if (vizTab && vizTab.classList.contains('active') && typeof loadVisualizationData === 'function') {
                loadVisualizationData();
            }

            if (data.status === 'demo_stopped' || data.demo_stopped) {
                finishCrawlUi('Demo limit reached — crawl data saved');
                updateStatus('Demo limit reached — crawl data saved');
                showDemoLimitNotification();
                if (typeof loadVisualizationData === 'function') {
                    loadVisualizationData();
                }
            } else if (crawlState.isRunning && data.status !== 'completed') {
                setTimeout(pollCrawlProgress, largeCrawlMode ? 2500 : 1000);
            } else if (data.status === 'completed') {
                // A completed crawl must not call /api/stop_crawl: doing so
                // changes the persisted result from completed to stopped.
                finishCrawlUi('Crawl completed');
                // Update visualization one final time when crawl completes
                if (typeof loadVisualizationData === 'function') {
                    loadVisualizationData();
                }
                // Notify plugins that crawl is complete
                if (window.LibreCrawlPlugin && window.LibreCrawlPlugin.loader) {
                    window.LibreCrawlPlugin.loader.notifyCrawlComplete({
                        urls: crawlState.urls,
                        links: crawlState.links,
                        issues: crawlState.issues,
                        stats: crawlState.stats
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error polling crawl status:', error);
            // Continue polling even if there's an error (common on large crawls)
            if (crawlState.isRunning) {
            setTimeout(pollCrawlProgress, largeCrawlMode ? 2500 : 1000);
            }
        });
}

function updateCrawlData(data) {
    // Update statistics
    crawlState.stats = data.stats || crawlState.stats;
    largeCrawlMode = Number(crawlState.stats.discovered || data.urls?.length || 0) >= LARGE_CRAWL_THRESHOLD;
    document.body.classList.toggle('large-crawl-mode', largeCrawlMode);
    updateStatsDisplay();

    // Update memory statistics
    if (data.memory && data.memory_data) {
        updateMemoryDisplay(data.memory, data.memory_data);
    }

    // Update tables with new URLs
    if (data.urls) {
        if (largeCrawlMode) {
            // Keep only a bounded viewport cache in the browser. The complete
            // dataset remains available through the server/database exports.
            const visibleUrls = data.urls.slice(-LARGE_CRAWL_CLIENT_LIMIT);
            crawlState.urls = visibleUrls;
            if (virtualScrollers.overview) virtualScrollers.overview.setData(visibleUrls);
            if (virtualScrollers.internal) virtualScrollers.internal.setData(visibleUrls.filter(url => url.is_internal));
            if (virtualScrollers.external) virtualScrollers.external.setData(visibleUrls.filter(url => !url.is_internal));
        } else {
            data.urls.forEach(url => addUrlToTable(url));
        }
    }

    // Update links tables only if Links tab is active to improve performance
    if (data.links) {
        // Always store links data in crawlState
        crawlState.links = largeCrawlMode ? data.links.slice(-LARGE_CRAWL_CLIENT_LIMIT) : data.links;
        if (isLinksTabActive()) {
            updateLinksTable(data.links);
        } else {
            // Store in pendingLinks for lazy loading when switching to tab
            crawlState.pendingLinks = data.links;
        }
    }

    // Update issues table only if Issues tab is active
    if (data.issues) {
        // Always store issues data in crawlState
        crawlState.issues = largeCrawlMode ? data.issues.slice(-LARGE_CRAWL_CLIENT_LIMIT) : data.issues;
        if (isIssuesTabActive()) {
            updateIssuesTable(data.issues);
        } else {
            // Store in pendingIssues for lazy loading when switching to tab
            crawlState.pendingIssues = data.issues;
        }
    }

    // Update filter counts
    updateFilterCounts();

    // Update status codes table (respecting active filter)
    updateStatusCodesTable(crawlState.filters.active);

    // Update progress and status text
    updateProgress(data.progress || 0);
    updateProgressText(data);

    // Update PageSpeed results if available
    if (data.stats && data.stats.pagespeed_results) {
        displayPageSpeedResults(data.stats.pagespeed_results);
    }

    // Notify plugins of data update
    if (window.LibreCrawlPlugin && window.LibreCrawlPlugin.loader) {
        window.LibreCrawlPlugin.loader.notifyDataUpdate({
            urls: crawlState.urls,
            links: crawlState.links,
            issues: crawlState.issues,
            stats: crawlState.stats
        });
    }
}

function updateProgressText(data) {
    const progressText = document.getElementById('progressText');
    if (!progressText) return;

    if (data.is_running_pagespeed) {
        progressText.textContent = 'Running PageSpeed analysis...';
    } else if (data.status === 'completed') {
        progressText.textContent = 'Crawl completed';
    } else if (data.status === 'running') {
        const stats = data.stats || crawlState.stats;
        if (stats.crawled === 0) {
            progressText.textContent = 'Starting crawl...';
        } else if (stats.discovered > stats.crawled) {
            progressText.textContent = `Crawling... (${stats.crawled}/${stats.discovered} URLs)`;
        } else {
            progressText.textContent = `Finishing up... (${stats.crawled} URLs crawled)`;
        }
    } else {
        progressText.textContent = 'Initializing...';
    }
}

function updateStatsDisplay() {
    document.getElementById('discoveredCount').textContent = crawlState.stats.discovered;
    const overview = {
        overviewDiscovered: crawlState.stats.discovered,
        overviewCrawled: crawlState.stats.crawled,
        overviewIssues: crawlState.issues.length,
        overviewSpeed: Number(crawlState.stats.speed || 0).toFixed(1)
    };
    Object.entries(overview).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    });
    document.getElementById('crawledCount').textContent = crawlState.stats.crawled;
    document.getElementById('crawlDepth').textContent = crawlState.stats.depth;
    document.getElementById('crawlSpeed').textContent = crawlState.stats.speed + ' URLs/sec';
}

function updateMemoryDisplay(memoryData, memoryDataSizes) {
    if (!memoryData || !memoryDataSizes) return;

    // Actual data size (deep measurement)
    const dataMB = memoryDataSizes.total_deep_mb || 0;
    document.getElementById('memCurrent').textContent = dataMB.toFixed(1) + ' MB';

    // KB per URL (actual data)
    const kbPerUrl = memoryDataSizes.avg_per_url_kb || 0;
    document.getElementById('memPeak').textContent = kbPerUrl.toFixed(1) + ' KB/URL';

    // Estimate for 1M URLs (data only)
    const estimate1M = (kbPerUrl * 1000000) / 1024; // Convert to MB
    const estimate1MDisplay = estimate1M > 1024
        ? (estimate1M / 1024).toFixed(1) + ' GB'
        : estimate1M.toFixed(0) + ' MB';
    document.getElementById('memEstimate1M').textContent = estimate1MDisplay;

    // System available
    const availableMB = memoryData.system?.available_mb || 0;
    document.getElementById('memAvailable').textContent = availableMB.toFixed(0) + ' MB';
}

function updateCrawlButtons() {
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const clearBtn = document.getElementById('clearBtn');
    const saveCrawlBtn = document.getElementById('saveCrawlBtn');
    const loadCrawlBtn = document.getElementById('loadCrawlBtn');

    if (crawlState.isRunning) {
        if (crawlState.isPaused) {
            startBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M8 5v14l11-7z"/>
                </svg>
                Resume
            `;
        } else {
            startBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16"/>
                    <rect x="14" y="4" width="4" height="16"/>
                </svg>
                Pause
            `;
        }
        startBtn.disabled = false;
        stopBtn.disabled = false;
        clearBtn.disabled = false;
        saveCrawlBtn.disabled = true; // Disable during crawl
        loadCrawlBtn.disabled = true; // Disable during crawl
    } else {
        startBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z"/>
            </svg>
            Start
        `;
        startBtn.disabled = false;
        stopBtn.disabled = true;
        clearBtn.disabled = false;

        // Save button: only enabled if crawl is completed and has data
        const hasData = crawlState.stats.crawled > 0;
        saveCrawlBtn.disabled = !hasData;

        // Load button: only enabled if no current crawl data
        loadCrawlBtn.disabled = hasData;
    }
}

function showProgress() {
    document.getElementById('progressContainer').style.display = 'flex';
}

function hideProgress() {
    document.getElementById('progressContainer').style.display = 'none';
}

function updateProgress(percentage) {
    document.getElementById('progressFill').style.width = percentage + '%';
}

function updateStatus(message) {
    document.getElementById('statusText').textContent = message;
}

function showDemoLimitNotification() {
    // Remove existing demo notification if any
    const existing = document.getElementById('demoLimitNotification');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'demoLimitNotification';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.6); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
    `;

    const box = document.createElement('div');
    box.style.cssText = `
        background: #1a1a2e; border: 1px solid #f59e0b; border-radius: 12px;
        padding: 32px 40px; max-width: 480px; text-align: center;
        color: #e0e0e0; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    `;
    box.innerHTML = `
        <div style="font-size: 28px; margin-bottom: 12px;">&#9888;</div>
        <h2 style="color: #f59e0b; margin: 0 0 12px; font-size: 18px;">Demo Memory Limit Reached</h2>
        <p style="margin: 0 0 16px; line-height: 1.5; font-size: 14px;">
            This user has reached the 1.5 GB per-user memory limit.<br>
            Your crawl data has been saved automatically.<br><br>
            <strong>This is a free demo and is not intended for production use.</strong>
        </p>
        <button id="demoLimitDismiss" style="
            background: #f59e0b; color: #000; border: none; padding: 10px 28px;
            border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 14px;
        ">OK</button>
    `;

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    document.getElementById('demoLimitDismiss').addEventListener('click', function() {
        overlay.remove();
    });
}

function updateTimer() {
    if (crawlState.isRunning && crawlState.startTime) {
        const elapsed = new Date() - crawlState.startTime;
        const minutes = Math.floor(elapsed / 60000);
        const seconds = Math.floor((elapsed % 60000) / 1000);
        document.getElementById('crawlTime').textContent =
            `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
}

// Table Management
function initializeTables() {
    // Clear any existing data first
    clearAllTables();
    // Initialize virtual scrollers for all tables
    initializeVirtualScrollers();
    // Initialize column resizers after virtual scrollers
    setTimeout(() => {
        if (window.initializeColumnResizers) {
            initializeColumnResizers();
        }
    }, 100);
}

function initializeVirtualScrollers() {
    try {
        // Overview table
        const overviewContainer = document.querySelector('#overview-tab .table-container');
        if (overviewContainer && overviewContainer.querySelector('tbody')) {
            virtualScrollers.overview = new VirtualScroller(overviewContainer, {
                rowHeight: 100,
                buffer: 25,
                renderRow: renderOverviewRow
            });
            console.log('Overview virtual scroller initialized');
        }

        // Internal URLs table
        const internalContainer = document.querySelector('#internal-tab .table-container');
        if (internalContainer && internalContainer.querySelector('tbody')) {
            virtualScrollers.internal = new VirtualScroller(internalContainer, {
                rowHeight: 80,
                buffer: 25,
                renderRow: renderInternalRow
            });
            console.log('Internal virtual scroller initialized');
        }

        // External URLs table
        const externalContainer = document.querySelector('#external-tab .table-container');
        if (externalContainer && externalContainer.querySelector('tbody')) {
            virtualScrollers.external = new VirtualScroller(externalContainer, {
                rowHeight: 80,
                buffer: 25,
                renderRow: renderExternalRow
            });
            console.log('External virtual scroller initialized');
        }

        // Internal Links table
        const internalLinksContainer = document.querySelector('#links-tab .internal-links-container');
        if (internalLinksContainer && internalLinksContainer.querySelector('tbody')) {
            virtualScrollers.internalLinks = new VirtualScroller(internalLinksContainer, {
                rowHeight: 80,
                buffer: 25,
                renderRow: renderInternalLinkRow
            });
            console.log('Internal links virtual scroller initialized');
        }

        // External Links table
        const externalLinksContainer = document.querySelector('#links-tab .external-links-container');
        if (externalLinksContainer && externalLinksContainer.querySelector('tbody')) {
            virtualScrollers.externalLinks = new VirtualScroller(externalLinksContainer, {
                rowHeight: 80,
                buffer: 25,
                renderRow: renderExternalLinkRow
            });
            console.log('External links virtual scroller initialized');
        }

        // Issues table
        const issuesContainer = document.querySelector('#issues-tab .table-container');
        if (issuesContainer && issuesContainer.querySelector('tbody')) {
            virtualScrollers.issues = new VirtualScroller(issuesContainer, {
                rowHeight: 80,
                buffer: 25,
                renderRow: renderIssueRow
            });
            console.log('Issues virtual scroller initialized');
        }
    } catch (error) {
        console.error('Error initializing virtual scrollers:', error);
    }
}

function isLinksTabActive() {
    const linksTab = document.getElementById('links-tab');
    return linksTab && linksTab.classList.contains('active');
}

function isIssuesTabActive() {
    const issuesTab = document.getElementById('issues-tab');
    return issuesTab && issuesTab.classList.contains('active');
}

function updateLinksTable(links) {
    // Create a lookup map of URL statuses from crawled URLs
    const urlStatusMap = new Map();
    if (crawlState.urls && crawlState.urls.length > 0) {
        crawlState.urls.forEach(url => {
            urlStatusMap.set(url.url, url.status_code);
        });
    }

    // Remove duplicates from links array (extra safety check)
    const uniqueLinks = [];
    const seenLinks = new Set();
    links.forEach(link => {
        const key = `${link.source_url}|${link.target_url}`;
        if (!seenLinks.has(key)) {
            seenLinks.add(key);

            // Update target status with actual crawled status if available
            const crawledStatus = urlStatusMap.get(link.target_url);
            if (crawledStatus) {
                link.target_status = crawledStatus;
            }

            uniqueLinks.push(link);
        }
    });

    // Store unfiltered links in crawlState
    crawlState.links = uniqueLinks;

    // Apply filters and update virtual scrollers
    applyLinksFilter();

    console.log(`Links loaded: ${crawlState.links.filter(l => l.is_internal).length} internal, ${crawlState.links.filter(l => !l.is_internal).length} external`);
}

function applyLinksFilter() {
    if (!crawlState.links || crawlState.links.length === 0) return;

    // Separate internal and external links
    let internalLinks = crawlState.links.filter(link => link.is_internal);
    let externalLinks = crawlState.links.filter(link => !link.is_internal);

    // Apply status code filter for internal links
    const internalStatusFilter = crawlState.filters.linksFilter.internalStatusCode;
    if (internalStatusFilter && internalStatusFilter !== 'all') {
        internalLinks = internalLinks.filter(link => {
            if (!link.target_status) return false;
            const status = parseInt(link.target_status);
            switch (internalStatusFilter) {
                case '2xx': return status >= 200 && status < 300;
                case '3xx': return status >= 300 && status < 400;
                case '4xx': return status >= 400 && status < 500;
                case '5xx': return status >= 500;
                default: return true;
            }
        });
    }

    // Apply search filter for internal links
    const internalSearch = crawlState.filters.linksFilter.internalSearch.toLowerCase();
    if (internalSearch) {
        internalLinks = internalLinks.filter(link =>
            link.source_url.toLowerCase().includes(internalSearch) ||
            link.target_url.toLowerCase().includes(internalSearch) ||
            (link.anchor_text && link.anchor_text.toLowerCase().includes(internalSearch))
        );
    }

    // Apply status code filter for external links
    const externalStatusFilter = crawlState.filters.linksFilter.externalStatusCode;
    if (externalStatusFilter && externalStatusFilter !== 'all') {
        externalLinks = externalLinks.filter(link => {
            if (!link.target_status) return false;
            const status = parseInt(link.target_status);
            switch (externalStatusFilter) {
                case '2xx': return status >= 200 && status < 300;
                case '3xx': return status >= 300 && status < 400;
                case '4xx': return status >= 400 && status < 500;
                case '5xx': return status >= 500;
                default: return true;
            }
        });
    }

    // Apply search filter for external links
    const externalSearch = crawlState.filters.linksFilter.externalSearch.toLowerCase();
    if (externalSearch) {
        externalLinks = externalLinks.filter(link =>
            link.source_url.toLowerCase().includes(externalSearch) ||
            link.target_url.toLowerCase().includes(externalSearch) ||
            (link.target_domain && link.target_domain.toLowerCase().includes(externalSearch))
        );
    }

    // Update virtual scrollers with filtered data
    if (virtualScrollers.internalLinks) {
        virtualScrollers.internalLinks.setData(internalLinks);
    }

    if (virtualScrollers.externalLinks) {
        virtualScrollers.externalLinks.setData(externalLinks);
    }
}

function filterInternalLinks(filterType) {
    crawlState.filters.linksFilter.internalStatusCode = filterType;
    applyLinksFilter();
}

function filterExternalLinks(filterType) {
    crawlState.filters.linksFilter.externalStatusCode = filterType;
    applyLinksFilter();
}

function searchInternalLinks(searchText) {
    crawlState.filters.linksFilter.internalSearch = searchText;
    applyLinksFilter();
}

function searchExternalLinks(searchText) {
    crawlState.filters.linksFilter.externalSearch = searchText;
    applyLinksFilter();
}

function updateIssuesTable(issues) {
    if (!issues || !Array.isArray(issues)) {
        issues = [];
    }

    // Store issues globally for filtering
    window.currentIssues = issues;

    const emptyState = document.getElementById('issuesEmptyState');
    const issuesTable = document.getElementById('issuesTable');

    // Count by type
    let errorCount = 0;
    let warningCount = 0;
    let infoCount = 0;

    issues.forEach(issue => {
        if (issue.type === 'error') errorCount++;
        else if (issue.type === 'warning') warningCount++;
        else if (issue.type === 'info') infoCount++;
    });

    // Update filter counts
    document.getElementById('issues-all-count').textContent = `(${issues.length})`;
    document.getElementById('issues-error-count').textContent = `(${errorCount})`;
    document.getElementById('issues-warning-count').textContent = `(${warningCount})`;
    document.getElementById('issues-info-count').textContent = `(${infoCount})`;

    // Show/hide empty state
    if (issues.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (issuesTable) issuesTable.style.display = 'none';
    } else {
        if (emptyState) emptyState.style.display = 'none';
        if (issuesTable) issuesTable.style.display = 'table';

        // Use virtual scroller for issues
        if (virtualScrollers.issues) {
            virtualScrollers.issues.setData(issues);
        }
    }

    // Update issue count in tab button (find the button, not the tab content)
    const issuesTabButton = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.textContent.includes('Issues'));
    if (issuesTabButton) {
        const totalIssues = issues.length;
        if (totalIssues > 0) {
            let badgeColor = '#3b82f6';
            if (errorCount > 0) badgeColor = '#ef4444';
            else if (warningCount > 0) badgeColor = '#f59e0b';

            issuesTabButton.innerHTML = `Issues <span style="background: ${badgeColor}; color: white; padding: 2px 6px; border-radius: 12px; font-size: 12px;">${totalIssues}</span>`;
        } else {
            issuesTabButton.innerHTML = 'Issues';
        }
    }
}

function clearAllTables() {
    // Clear virtual scrollers if they exist
    if (virtualScrollers.overview) {
        virtualScrollers.overview.clear();
    }
    if (virtualScrollers.internal) {
        virtualScrollers.internal.clear();
    }
    if (virtualScrollers.external) {
        virtualScrollers.external.clear();
    }
    if (virtualScrollers.internalLinks) {
        virtualScrollers.internalLinks.clear();
    }
    if (virtualScrollers.externalLinks) {
        virtualScrollers.externalLinks.clear();
    }
    if (virtualScrollers.issues) {
        virtualScrollers.issues.clear();
    }

    // Clear status codes table (not virtualized)
    const statusCodesBody = document.getElementById('statusCodesTableBody');
    if (statusCodesBody) statusCodesBody.innerHTML = '';

    crawlState.urls = [];

    console.log('All tables cleared');
}

function formatAnalyticsInfo(analytics) {
    const detected = [];
    if (analytics.gtag || analytics.ga4_id) detected.push('GA4');
    if (analytics.google_analytics) detected.push('GA');
    if (analytics.gtm_id) detected.push('GTM');
    if (analytics.facebook_pixel) detected.push('FB');
    if (analytics.hotjar) detected.push('HJ');
    if (analytics.mixpanel) detected.push('MP');

    return detected.length > 0 ? detected.join(', ') : '';
}

function addUrlToTable(urlData) {
    // Check if URL already exists to prevent duplicates
    const existingUrl = crawlState.urls.find(u => u.url === urlData.url);
    if (existingUrl) {
        return; // Skip duplicate
    }

    crawlState.urls.push(urlData);

    // Update virtual scrollers with new data
    if (virtualScrollers.overview) {
        virtualScrollers.overview.appendData([urlData]);
    }

    if (urlData.is_internal && virtualScrollers.internal) {
        virtualScrollers.internal.appendData([urlData]);
    } else if (!urlData.is_internal && virtualScrollers.external) {
        virtualScrollers.external.appendData([urlData]);
    }

    // Reapply current filter if one is active
    if (crawlState.filters.active) {
        applyFilter(crawlState.filters.active);
    }
}

function addRowToTable(tableBodyId, rowData) {
    const tbody = document.getElementById(tableBodyId);
    const row = tbody.insertRow();

    rowData.forEach(cellData => {
        const cell = row.insertCell();
        // Check if cellData contains HTML (specifically our button)
        if (typeof cellData === 'string' && cellData.includes('<button')) {
            cell.innerHTML = cellData;
        } else {
            cell.textContent = cellData;
        }
    });
}

function spiderDatasetRows() {
    return window._spiderDatasetRows || [];
}

async function loadSpiderDataset() {
    const crawlId = Number(document.getElementById('spiderDatasetCrawlId')?.value);
    const tab = document.getElementById('spiderDatasetName')?.value;
    const output = document.getElementById('spiderDatasetTable');
    if (!crawlId || !tab) { showNotification('Inserisci un crawl ID e un tab', 'warning'); return; }
    const response = await fetch(`/api/crawls/${crawlId}/tabs/${encodeURIComponent(tab)}`);
    const data = await response.json();
    if (!data.success) { showNotification(data.error || 'Dataset non disponibile', 'error'); return; }
    window._spiderDatasetRows = data.rows || [];
    const keys = Array.from(new Set(window._spiderDatasetRows.flatMap(row => Object.keys(row)))).slice(0, 18);
    output.querySelector('thead').innerHTML = `<tr>${keys.map(key => `<th>${escapeHtml(key)}</th>`).join('')}</tr>`;
    output.querySelector('tbody').innerHTML = window._spiderDatasetRows.map(row => `<tr>${keys.map(key => {
        const value = row[key];
        const text = typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '');
        return `<td title="${escapeHtml(text)}">${escapeHtml(text.slice(0, 500))}</td>`;
    }).join('')}</tr>`).join('');
    document.getElementById('spiderDatasetCount').textContent = `${data.count} rows · ${data.tab}`;
}

function openSpiderDatasetTab(tab) {
    const select = document.getElementById('spiderDatasetName');
    if (select) select.value = tab;
    const overview = document.querySelector('[onclick="switchTab(\'overview\')"]');
    if (overview) overview.click();
    loadSpiderDataset();
}

function exportSpiderDataset() {
    const rows = spiderDatasetRows();
    if (!rows.length) { showNotification('Carica prima un dataset', 'warning'); return; }
    const blob = new Blob([JSON.stringify(rows, null, 2)], {type: 'application/json'});
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob);
    link.download = `librecrawl-${document.getElementById('spiderDatasetName').value}.json`;
    link.click(); URL.revokeObjectURL(link.href);
}

async function loadCrawlReport() {
    const crawlId = Number(document.getElementById('reportAnalysisCrawlId')?.value);
    if (!crawlId) { showNotification('Inserisci un crawl ID', 'warning'); return; }
    const response = await fetch(`/api/crawls/${crawlId}/report`);
    const data = await response.json();
    document.getElementById('analysisDetails').textContent = JSON.stringify(data, null, 2);
}

function downloadCrawlReport() {
    const crawlId = Number(document.getElementById('reportAnalysisCrawlId')?.value);
    if (!crawlId) { showNotification('Inserisci un crawl ID', 'warning'); return; }
    window.open(`/api/crawls/${crawlId}/report?format=csv`, '_blank');
}

// Tab Management
function switchTab(tabName) {
    // Remove active class from all tabs and panes
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));

    // Add active class to selected tab and pane
    event.target.classList.add('active');
    document.getElementById(tabName + '-tab').classList.add('active');

    // Load pending links data if switching to Links tab
    if (tabName === 'links' && crawlState.pendingLinks) {
        updateLinksTable(crawlState.pendingLinks);
        crawlState.pendingLinks = null; // Clear pending data
    }

    // Load pending issues data if switching to Issues tab
    if (tabName === 'issues' && crawlState.pendingIssues) {
        updateIssuesTable(crawlState.pendingIssues);
        crawlState.pendingIssues = null; // Clear pending data
    }

    // Initialize visualization if switching to Visualization tab
    if (tabName === 'visualization' && typeof initVisualization === 'function') {
        // Small delay to ensure the tab is visible before initializing
        setTimeout(() => {
            initVisualization();
        }, 100);
    }

    // Handle plugin tabs
    const pluginTab = document.getElementById(`${tabName}-tab`);
    if (pluginTab && pluginTab.classList.contains('plugin-tab')) {
        handlePluginTabSwitch(tabName);
    }
}

// Handle plugin tab activation
function handlePluginTabSwitch(tabName) {
    if (!window.LibreCrawlPlugin || !window.LibreCrawlPlugin.loader) {
        return;
    }

    const loader = window.LibreCrawlPlugin.loader;

    // Deactivate previously active plugin
    if (loader.activePluginId && loader.activePluginId !== tabName) {
        loader.deactivatePlugin(loader.activePluginId);
    }

    // Activate the new plugin
    loader.activatePlugin(tabName, {
        urls: crawlState.urls,
        links: crawlState.links,
        issues: crawlState.issues,
        stats: crawlState.stats
    });
}

// Issue Filtering
function filterIssues(filterType) {
    // Store the active filter
    crawlState.filters.issueFilter = filterType;

    // Update active button state and colors
    document.querySelectorAll('#issues-tab .filter-item').forEach(btn => {
        btn.classList.remove('active');
        const filter = btn.getAttribute('data-filter');

        if (filter === filterType) {
            btn.classList.add('active');
            // Set active state colors
            if (filter === 'all') {
                btn.style.background = '#374151';
                btn.style.borderColor = '#4b5563';
                btn.style.color = 'white';
            } else if (filter === 'error') {
                btn.style.background = 'rgba(239, 68, 68, 0.2)';
                btn.style.borderColor = 'rgba(239, 68, 68, 0.5)';
            } else if (filter === 'warning') {
                btn.style.background = 'rgba(245, 158, 11, 0.2)';
                btn.style.borderColor = 'rgba(245, 158, 11, 0.5)';
            } else if (filter === 'info') {
                btn.style.background = 'rgba(59, 130, 246, 0.2)';
                btn.style.borderColor = 'rgba(59, 130, 246, 0.5)';
            }
        } else {
            // Reset inactive state colors
            if (filter === 'all') {
                btn.style.background = 'transparent';
                btn.style.borderColor = '#4b5563';
                btn.style.color = '#9ca3af';
            } else if (filter === 'error') {
                btn.style.background = 'rgba(239, 68, 68, 0.1)';
                btn.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            } else if (filter === 'warning') {
                btn.style.background = 'rgba(245, 158, 11, 0.1)';
                btn.style.borderColor = 'rgba(245, 158, 11, 0.3)';
            } else if (filter === 'info') {
                btn.style.background = 'rgba(59, 130, 246, 0.1)';
                btn.style.borderColor = 'rgba(59, 130, 246, 0.3)';
            }
        }
    });

    // Filter issues data and update virtual scroller
    if (window.currentIssues && virtualScrollers.issues) {
        let filteredIssues = window.currentIssues;

        if (filterType !== 'all') {
            filteredIssues = window.currentIssues.filter(issue => issue.type === filterType);
        }

        virtualScrollers.issues.setData(filteredIssues);
    }
}

// Filter Management
function toggleFilter(filterType) {
    const filterItems = document.querySelectorAll('.filter-item');
    filterItems.forEach(item => item.classList.remove('active'));

    event.currentTarget.classList.add('active');
    crawlState.filters.active = filterType;

    // Apply filter to tables
    applyFilter(filterType);
}

function applyFilter(filterType) {
    // Set current filter as active
    crawlState.filters.active = filterType;

    // Filter the data arrays and update virtual scrollers
    filterVirtualScrollerData('overview', filterType);
    filterVirtualScrollerData('internal', filterType);
    filterVirtualScrollerData('external', filterType);

    // Update Status Codes table with filtered data
    updateStatusCodesTable(filterType);

    console.log('Applied filter:', filterType);
}

function clearActiveFilters() {
    crawlState.filters.active = null;

    // Reset all virtual scrollers to show full data
    if (virtualScrollers.overview) {
        virtualScrollers.overview.setData(crawlState.urls);
    }
    if (virtualScrollers.internal) {
        const internalUrls = crawlState.urls.filter(url => url.is_internal);
        virtualScrollers.internal.setData(internalUrls);
    }
    if (virtualScrollers.external) {
        const externalUrls = crawlState.urls.filter(url => !url.is_internal);
        virtualScrollers.external.setData(externalUrls);
    }

    // Reset Status Codes table to show all data
    updateStatusCodesTable();
}

function filterVirtualScrollerData(scrollerName, filterType) {
    const scroller = virtualScrollers[scrollerName];
    if (!scroller) return;

    let filteredData = crawlState.urls;

    // Apply base filter for internal/external tables
    if (scrollerName === 'internal') {
        filteredData = filteredData.filter(url => url.is_internal);
    } else if (scrollerName === 'external') {
        filteredData = filteredData.filter(url => !url.is_internal);
    }

    // Apply user-selected filter
    if (filterType) {
        filteredData = filteredData.filter(url => {
            switch (filterType) {
                case 'internal':
                    return isInternalURL(url.url);
                case 'external':
                    return !isInternalURL(url.url);
                case '2xx':
                    return url.status_code >= 200 && url.status_code < 300;
                case '3xx':
                    return url.status_code >= 300 && url.status_code < 400;
                case '4xx':
                    return url.status_code >= 400 && url.status_code < 500;
                case '5xx':
                    return url.status_code >= 500;
                case 'no_response':
                    return (url.status_code === 0 || url.status_code === null || url.status_code === undefined)
                        && url.error_type !== 'file_too_large';
                case 'html':
                    return (url.content_type || '').toLowerCase().includes('html');
                case 'css':
                    return (url.content_type || '').toLowerCase().includes('css');
                case 'js':
                    return (url.content_type || '').toLowerCase().includes('javascript');
                case 'images':
                    return (url.content_type || '').toLowerCase().includes('image');
                default:
                    return true;
            }
        });
    }

    scroller.setData(filteredData);
}

// Legacy function - kept for compatibility but no longer used
function filterTable(tableBodyId, filterType) {
    // This function is deprecated in favor of filterVirtualScrollerData
    // Kept for backwards compatibility only
}

function isInternalURL(url) {
    if (!url || !crawlState.baseUrl) return false;
    try {
        const urlObj = new URL(url);
        const baseObj = new URL(crawlState.baseUrl);

        // Normalize domains by removing www prefix for comparison
        const urlDomain = urlObj.hostname.replace('www.', '');
        const baseDomain = baseObj.hostname.replace('www.', '');

        return urlDomain === baseDomain;
    } catch (e) {
        return false;
    }
}

function isStatusCodeRange(statusText, min, max) {
    const status = parseInt(statusText);
    return status >= min && status <= max;
}

function isContentType(contentType, type) {
    if (!contentType) return false;
    return contentType.toLowerCase().includes(type.toLowerCase());
}

function updateFilterCounts() {
    // Count URLs by type and update filter counts
    const counts = {
        internal: 0,
        external: 0,
        '2xx': 0,
        '3xx': 0,
        '4xx': 0,
        '5xx': 0,
        no_response: 0,
        html: 0,
        css: 0,
        js: 0,
        images: 0
    };

    crawlState.urls.forEach(url => {
        // Count by internal/external using corrected logic
        if (isInternalURL(url.url)) counts.internal++;
        else counts.external++;

        // Count by status code
        const statusCode = parseInt(url.status_code);
        if (statusCode >= 200 && statusCode < 300) counts['2xx']++;
        else if (statusCode >= 300 && statusCode < 400) counts['3xx']++;
        else if (statusCode >= 400 && statusCode < 500) counts['4xx']++;
        else if (statusCode >= 500) counts['5xx']++;
        else if ((url.status_code === 0 || isNaN(statusCode)) && url.error_type !== 'file_too_large') counts.no_response++;

        // Count by content type
        const contentType = url.content_type || '';
        if (contentType.includes('html')) counts.html++;
        else if (contentType.includes('css')) counts.css++;
        else if (contentType.includes('javascript')) counts.js++;
        else if (contentType.includes('image')) counts.images++;
    });

    // Update DOM
    Object.keys(counts).forEach(key => {
        const element = document.getElementById(key + '-count');
        if (element) {
            element.textContent = counts[key];
        }
    });
}

function updateStatusCodesTable(filterType = null) {
    const tbody = document.getElementById('statusCodesTableBody');
    if (!tbody) return;

    // Count status codes, respecting current filter
    const statusCounts = {};
    let filteredUrls = crawlState.urls;

    // Apply filter if specified
    if (filterType === 'internal') {
        filteredUrls = crawlState.urls.filter(url => isInternalURL(url.url));
    } else if (filterType === 'external') {
        filteredUrls = crawlState.urls.filter(url => !isInternalURL(url.url));
    } else if (filterType === '2xx') {
        filteredUrls = crawlState.urls.filter(url => {
            const status = parseInt(url.status_code);
            return status >= 200 && status < 300;
        });
    } else if (filterType === '3xx') {
        filteredUrls = crawlState.urls.filter(url => {
            const status = parseInt(url.status_code);
            return status >= 300 && status < 400;
        });
    } else if (filterType === '4xx') {
        filteredUrls = crawlState.urls.filter(url => {
            const status = parseInt(url.status_code);
            return status >= 400 && status < 500;
        });
    } else if (filterType === '5xx') {
        filteredUrls = crawlState.urls.filter(url => {
            const status = parseInt(url.status_code);
            return status >= 500;
        });
    } else if (filterType === 'no_response') {
        filteredUrls = crawlState.urls.filter(url =>
            (url.status_code === 0 || url.status_code === null || url.status_code === undefined)
            && url.error_type !== 'file_too_large'
        );
    } else if (filterType === 'html') {
        filteredUrls = crawlState.urls.filter(url => (url.content_type || '').includes('html'));
    } else if (filterType === 'css') {
        filteredUrls = crawlState.urls.filter(url => (url.content_type || '').includes('css'));
    } else if (filterType === 'js') {
        filteredUrls = crawlState.urls.filter(url => (url.content_type || '').includes('javascript'));
    } else if (filterType === 'images') {
        filteredUrls = crawlState.urls.filter(url => (url.content_type || '').includes('image'));
    }

    let totalUrls = filteredUrls.length;

    filteredUrls.forEach(url => {
        // Group status_code=0 rows by error_type so DNS / timeout / refused
        // show as distinct rows instead of collapsing into a single "0".
        const isZero = url.status_code === 0 || url.status_code === null || url.status_code === undefined;
        const key = isZero ? `0|${url.error_type || 'unknown'}` : String(url.status_code);
        statusCounts[key] = (statusCounts[key] || 0) + 1;
    });

    // Clear existing rows
    tbody.innerHTML = '';

    // Sort: real HTTP codes first (numeric), then no-response variants
    const keys = Object.keys(statusCounts).sort((a, b) => {
        const aIsZero = a.startsWith('0|');
        const bIsZero = b.startsWith('0|');
        if (aIsZero && !bIsZero) return 1;
        if (!aIsZero && bIsZero) return -1;
        if (aIsZero && bIsZero) return a.localeCompare(b);
        return parseInt(a) - parseInt(b);
    });

    keys.forEach(key => {
        const count = statusCounts[key];
        const percentage = totalUrls > 0 ? ((count / totalUrls) * 100).toFixed(1) : 0;
        let displayCode, statusText;
        if (key.startsWith('0|')) {
            const errorType = key.slice(2);
            displayCode = '0';
            statusText = getStatusCodeText(0, errorType);
        } else {
            displayCode = key;
            statusText = getStatusCodeText(parseInt(key));
        }

        addRowToTable('statusCodesTableBody', [
            displayCode,
            statusText,
            count,
            percentage + '%'
        ]);
    });
}

function getStatusCodeText(statusCode, errorType) {
    if (statusCode >= 200 && statusCode < 300) {
        return 'Success';
    } else if (statusCode >= 300 && statusCode < 400) {
        return 'Redirect';
    } else if (statusCode >= 400 && statusCode < 500) {
        return 'Client Error';
    } else if (statusCode >= 500) {
        return 'Server Error';
    } else if (statusCode === 0) {
        switch (errorType) {
            case 'dns_not_found':       return 'DNS Not Found';
            case 'connection_refused':  return 'Connection Refused';
            case 'timeout':             return 'Timeout';
            case 'ssl_error':           return 'SSL/TLS Error';
            case 'connection_error':    return 'Connection Error';
            case 'file_too_large':      return 'Skipped (file too large)';
            default:                    return 'No Response';
        }
    } else {
        return 'Unknown';
    }
}

function resetStats() {
    crawlState.stats = {
        discovered: 0,
        crawled: 0,
        depth: 0,
        speed: 0
    };
    updateStatsDisplay();
}

// Utility Functions
function normalizeUrl(input) {
    // Remove any whitespace
    input = input.trim();

    // If it already has a protocol, return as-is
    if (input.match(/^https?:\/\//i)) {
        return input;
    }

    // If it looks like a domain or IP, add https://
    if (input.match(/^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*\.([a-zA-Z]{2,}|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/) ||
        input.match(/^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/) ||
        input.match(/^localhost(:[0-9]+)?$/i) ||
        input.match(/^[a-zA-Z0-9-]+\.(com|org|net|edu|gov|mil|int|co|io|dev|app|tech|info|biz|name|pro|museum|aero|coop|travel|jobs|mobi|tel|asia|cat|post|xxx|local|test)$/i)) {
        return 'https://' + input;
    }

    // If it doesn't match common patterns, try adding https:// anyway
    return 'https://' + input;
}

function isValidUrl(string) {
    try {
        const url = new URL(string);
        // Check if it has a valid protocol and hostname
        return (url.protocol === 'http:' || url.protocol === 'https:') && url.hostname.length > 0;
    } catch (_) {
        return false;
    }
}

// This is defined in settings.js - no need to redefine here

async function logout() {
    try {
        const response = await fetch('/api/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            // Redirect to login page
            window.location.href = '/login';
        } else {
            console.error('Logout failed:', data.message);
            // Still redirect even if logout fails
            window.location.href = '/login';
        }
    } catch (error) {
        console.error('Logout error:', error);
        // Redirect anyway
        window.location.href = '/login';
    }
}

async function loadUserInfo() {
    try {
        const response = await fetch('/api/user/info');
        const data = await response.json();

        if (data.success && data.user) {
            const user = data.user;
            const userInfoElement = document.getElementById('userInfo');

            if (user.tier === 'guest') {
                // Show crawls remaining for guests
                const remaining = user.crawls_remaining;
                userInfoElement.textContent = `Guest (${remaining}/3 crawls remaining)`;
                userInfoElement.style.color = remaining === 0 ? '#dc2626' : '#6b7280';
            } else {
                // Show username and tier for registered users
                userInfoElement.textContent = `${user.username} (${user.tier})`;
                userInfoElement.style.color = '#6b7280';
            }
        }
    } catch (error) {
        console.error('Error loading user info:', error);
    }
}

async function exportData() {
    try {
        // Get current settings to determine export format and fields
        const settingsResponse = await fetch('/api/get_settings');
        const settingsData = await settingsResponse.json();

        if (!settingsData.success) {
            showNotification('Failed to get export settings', 'error');
            return;
        }

        const settings = settingsData.settings;
        const exportFormat = settings.exportFormat || 'csv';
        const exportFields = settings.exportFields || ['url', 'status_code', 'title', 'meta_description', 'h1'];

        // Check if there's data to export - always fetch fresh data from backend
        let hasData = false;
        let exportUrls = [];
        let exportLinks = [];
        let exportIssues = [];

        // Always fetch from backend to ensure we have the latest data including links
        const status = await fetch('/api/crawl_status');
        const statusData = await status.json();

        if (statusData.urls && statusData.urls.length > 0) {
            hasData = true;
            exportUrls = statusData.urls;
            exportLinks = statusData.links || [];
            exportIssues = statusData.issues || [];
        } else if (crawlState.urls && crawlState.urls.length > 0) {
            // Fallback to local state if backend has no data (e.g., loaded crawl)
            hasData = true;
            exportUrls = crawlState.urls;
            // Get links and issues from stored state
            exportLinks = crawlState.links || [];
            exportIssues = crawlState.issues || window.currentIssues || [];
        }

        if (!hasData) {
            showNotification('No crawl data to export', 'error');
            return;
        }

        showNotification('Preparing export...', 'info');

        // Request export from backend, including local data if available
        const exportResponse = await fetch('/api/export_data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                format: exportFormat,
                fields: exportFields,
                // Send local data if we have it (for loaded crawls)
                localData: {
                    urls: exportUrls,
                    links: exportLinks,
                    issues: exportIssues
                }
            })
        });

        const exportData = await exportResponse.json();

        if (!exportData.success) {
            showNotification(exportData.error || 'Export failed', 'error');
            return;
        }

        // Check if we have multiple files to download
        if (exportData.multiple_files && exportData.files) {
            // Download each file separately
            exportData.files.forEach((file, index) => {
                setTimeout(() => {
                    const blob = new Blob([file.content], { type: file.mimetype });
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.style.display = 'none';
                    a.href = url;
                    a.download = file.filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                }, index * 500); // Delay between downloads to avoid browser blocking
            });

            showNotification(`Exporting ${exportData.files.length} files...`, 'success');
        } else {
            // Single file download (original logic)
            const blob = new Blob([exportData.content], { type: exportData.mimetype });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = exportData.filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showNotification(`Export complete: ${exportData.filename}`, 'success');
        }

    } catch (error) {
        console.error('Export error:', error);
        showNotification('Export failed', 'error');
    }
}

// Helper function to escape HTML for safe display
function escapeHtml(text) {
    if (!text) return text;
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showUrlDetails(url) {
    // Find the URL data
    const urlData = crawlState.urls.find(u => u.url === url);
    if (!urlData) {
        showNotification('URL data not found', 'error');
        return;
    }

    // Escape all user-controlled text fields to prevent HTML injection
    const safeUrl = escapeHtml(url);
    const safeTitle = escapeHtml(urlData.title) || 'N/A';
    const safeH1 = escapeHtml(urlData.h1) || 'N/A';
    const safeMetaDesc = escapeHtml(urlData.meta_description) || 'N/A';
    const safeLang = escapeHtml(urlData.lang) || 'N/A';
    const safeCharset = escapeHtml(urlData.charset) || 'N/A';
    const safeCanonical = escapeHtml(urlData.canonical_url) || 'N/A';
    const safeRobots = escapeHtml(urlData.robots) || 'N/A';
    const safeContentType = escapeHtml(urlData.content_type) || 'N/A';
    const safeGa4Id = escapeHtml(urlData.analytics?.ga4_id) || 'N/A';
    const safeGtmId = escapeHtml(urlData.analytics?.gtm_id) || 'N/A';

    // Create modal content
    const modalContent = `
        <div class="details-modal-overlay" onclick="closeUrlDetails()">
            <div class="details-modal" onclick="event.stopPropagation()">
                <div class="details-header">
                    <h3>Comprehensive URL Analysis</h3>
                    <button class="close-btn" onclick="closeUrlDetails()">×</button>
                </div>
                <div class="details-content">
                    <div class="details-url">${safeUrl}</div>
                    <div class="detail-panel-tabs" role="tablist">
                        <button class="btn btn-secondary" onclick="renderDetailPanel('summary')">Summary</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('inlinks')">Inlinks</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('outlinks')">Outlinks</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('resources')">Resources</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('headers')">HTTP Headers</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('cookies')">Cookies</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('structured_data')">Structured Data</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('rendering')">Rendering</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('accessibility')">Accessibility</button>
                        <button class="btn btn-secondary" onclick="renderDetailPanel('content')">N-grams</button>
                    </div>
                    <div id="detailPanelOutput" class="details-subsection" role="tabpanel"></div>

                    <div class="details-sections">
                        <div class="details-section">
                            <h4>🔍 Basic SEO</h4>
                            <div class="details-grid">
                                <div><strong>Title:</strong> ${safeTitle}</div>
                                <div><strong>H1:</strong> ${safeH1}</div>
                                <div><strong>Meta Description:</strong> ${safeMetaDesc}</div>
                                <div><strong>Word Count:</strong> ${urlData.word_count || 0}</div>
                                <div><strong>Language:</strong> ${safeLang}</div>
                                <div><strong>Charset:</strong> ${safeCharset}</div>
                                <div><strong>Canonical URL:</strong> ${safeCanonical}</div>
                                <div><strong>Robots Meta:</strong> ${safeRobots}</div>
                            </div>
                        </div>

                        <div class="details-section">
                            <h4>📊 Analytics & Tracking</h4>
                            <div class="details-grid">
                                <div><strong>Google Analytics:</strong> ${urlData.analytics?.google_analytics ? '✅ Yes' : '❌ No'}</div>
                                <div><strong>GA4/Gtag:</strong> ${urlData.analytics?.gtag ? '✅ Yes' : '❌ No'}</div>
                                <div><strong>GA4 ID:</strong> ${safeGa4Id}</div>
                                <div><strong>GTM ID:</strong> ${safeGtmId}</div>
                                <div><strong>Facebook Pixel:</strong> ${urlData.analytics?.facebook_pixel ? '✅ Yes' : '❌ No'}</div>
                                <div><strong>Hotjar:</strong> ${urlData.analytics?.hotjar ? '✅ Yes' : '❌ No'}</div>
                                <div><strong>Mixpanel:</strong> ${urlData.analytics?.mixpanel ? '✅ Yes' : '❌ No'}</div>
                            </div>
                        </div>

                        <div class="details-section">
                            <h4>📱 Social Media</h4>
                            <div class="details-grid">
                                <div><strong>OpenGraph Tags:</strong> ${Object.keys(urlData.og_tags || {}).length} found</div>
                                <div><strong>Twitter Cards:</strong> ${Object.keys(urlData.twitter_tags || {}).length} found</div>
                            </div>
                            ${Object.keys(urlData.og_tags || {}).length > 0 ? `
                                <div class="details-subsection">
                                    <h5>OpenGraph Tags:</h5>
                                    ${Object.entries(urlData.og_tags || {}).map(([key, value]) =>
                                        `<div><strong>og:${escapeHtml(key)}:</strong> ${escapeHtml(value)}</div>`
                                    ).join('')}
                                </div>
                            ` : ''}
                            ${Object.keys(urlData.twitter_tags || {}).length > 0 ? `
                                <div class="details-subsection">
                                    <h5>Twitter Cards:</h5>
                                    ${Object.entries(urlData.twitter_tags || {}).map(([key, value]) =>
                                        `<div><strong>twitter:${escapeHtml(key)}:</strong> ${escapeHtml(value)}</div>`
                                    ).join('')}
                                </div>
                            ` : ''}
                        </div>

                        <div class="details-section">
                            <h4>🔗 Links & Structure</h4>
                            <div class="details-grid">
                                <div><strong>Internal Links:</strong> ${urlData.internal_links || 0}</div>
                                <div><strong>External Links:</strong> ${urlData.external_links || 0}</div>
                                <div><strong>Images:</strong> ${(urlData.images || []).length}</div>
                                <div><strong>H2 Tags:</strong> ${(urlData.h2 || []).length}</div>
                                <div><strong>H3 Tags:</strong> ${(urlData.h3 || []).length}</div>
                            </div>
                        </div>

                        <div class="details-section">
                            <h4>⚡ Performance</h4>
                            <div class="details-grid">
                                <div><strong>Status Code:</strong> ${urlData.status_code}${urlData.error_type ? ' (' + escapeHtml(getStatusCodeText(parseInt(urlData.status_code) || 0, urlData.error_type)) + ')' : ''}</div>
                                <div><strong>Response Time:</strong> ${urlData.response_time || 0}ms</div>
                                <div><strong>Content Type:</strong> ${safeContentType}</div>
                                <div><strong>Size:</strong> ${urlData.size || 0} bytes</div>
                                ${urlData.error ? `<div><strong>Error:</strong> ${escapeHtml(urlData.error)}</div>` : ''}
                            </div>
                        </div>

                        <div class="details-section">
                            <h4>🗂️ Lower Window Panels</h4>
                            <div class="details-grid">
                                <div><strong>Inlinks:</strong> ${(urlData.inlinks || urlData.linked_from || []).length || urlData.internal_links || 0}</div>
                                <div><strong>Outlinks:</strong> ${(urlData.outlinks || []).length || (urlData.internal_links || 0) + (urlData.external_links || 0)}</div>
                                <div><strong>Resources:</strong> ${(urlData.resources || []).length}</div>
                                <div><strong>SERP Title:</strong> ${safeTitle}</div>
                                <div><strong>SERP Description:</strong> ${safeMetaDesc}</div>
                                <div><strong>N-grams:</strong> ${((urlData.content_analysis || {}).n_grams?.bigrams || []).length + ((urlData.content_analysis || {}).n_grams?.trigrams || []).length}</div>
                            </div>
                            ${urlData.outlinks?.length ? `<div class="details-subsection"><h5>Outlinks</h5><pre class="json-preview">${escapeHtml(JSON.stringify(urlData.outlinks.slice(0, 100), null, 2))}</pre></div>` : ''}
                            ${urlData.inlinks?.length ? `<div class="details-subsection"><h5>Inlinks</h5><pre class="json-preview">${escapeHtml(JSON.stringify(urlData.inlinks.slice(0, 100), null, 2))}</pre></div>` : ''}
                        </div>

                        <div class="details-section">
                            <h4>🧪 Advanced Crawl Audit</h4>
                            <div class="details-grid">
                                <div><strong>PDF:</strong> ${urlData.pdf_pages != null ? `${urlData.pdf_pages} pages` : 'N/A'}</div>
                                <div><strong>AMP:</strong> ${urlData.amp_url ? escapeHtml(urlData.amp_url) : 'N/A'}</div>
                                <div><strong>Mobile Alternate:</strong> ${urlData.mobile_alternate ? escapeHtml(urlData.mobile_alternate) : 'N/A'}</div>
                                <div><strong>Pagination:</strong> ${urlData.pagination?.next || urlData.pagination?.prev ? 'Detected' : 'N/A'}</div>
                                <div><strong>Meta Refresh:</strong> ${urlData.meta_refresh ? escapeHtml(JSON.stringify(urlData.meta_refresh)) : 'N/A'}</div>
                                <div><strong>Headers:</strong> ${Object.keys(urlData.http_headers || {}).length}</div>
                                <div><strong>Cookies:</strong> ${(urlData.cookies || []).length}</div>
                                <div><strong>HSTS:</strong> ${urlData.security?.hsts ? '✅ Present' : '⚠️ Missing/N/A'}</div>
                                <div><strong>HTML Validation:</strong> ${urlData.html_validation?.valid === false ? '❌ Issues' : (urlData.html_validation ? '✅ Valid' : 'N/A')}</div>
                                <div><strong>JS Errors:</strong> ${(urlData.javascript_errors || []).length}</div>
                                <div><strong>Resources:</strong> ${(urlData.resources || []).length}</div>
                                <div><strong>Rendered Screenshot:</strong> ${urlData.screenshot_path ? `<a href="/api/rendered-file?path=${encodeURIComponent(urlData.screenshot_path)}" target="_blank">Open</a>` : 'N/A'}</div>
                                <div><strong>Rendered Archive:</strong> ${urlData.rendered_archive_path ? `<a href="/api/rendered-file?path=${encodeURIComponent(urlData.rendered_archive_path)}" target="_blank">Open</a>` : 'N/A'}</div>
                                <div><strong>Network Requests:</strong> ${urlData.render_diagnostics?.network?.length ?? 0}</div>
                                <div><strong>Blocked Requests:</strong> ${urlData.render_diagnostics?.blocked_requests?.length ?? 0}</div>
                                <div><strong>Hydration:</strong> ${urlData.render_diagnostics?.hydration_mismatch ? 'Mismatch detected' : 'No mismatch detected'}</div>
                                <div><strong>Media:</strong> ${urlData.media_type ? escapeHtml(urlData.media_type) : 'N/A'}</div>
                                <div><strong>SWF:</strong> ${urlData.swf_detected ? '✅ Detected' : 'N/A'}</div>
                            </div>
                            ${Object.keys(urlData.http_headers || {}).length ? `<div class="details-subsection"><h5>Response Headers</h5><pre class="json-preview">${escapeHtml(JSON.stringify(urlData.http_headers, null, 2))}</pre></div>` : ''}
                            ${(urlData.cookies || []).length ? `<div class="details-subsection"><h5>Cookies (names only)</h5><p>${(urlData.cookies || []).map(cookie => escapeHtml(cookie.name || '')).join(', ')}</p></div>` : ''}
                            ${(urlData.pdf_text || urlData.html_validation?.errors?.length || urlData.javascript_errors?.length) ? `
                                <pre class="json-preview">${escapeHtml(JSON.stringify({pdf_text: urlData.pdf_text ? String(urlData.pdf_text).slice(0, 2000) : undefined, html_validation: urlData.html_validation, javascript_errors: urlData.javascript_errors}, null, 2))}</pre>
                            ` : ''}
                        </div>

                        <div class="details-section">
                            <h4>✍️ Content Quality</h4>
                            <div class="details-grid">
                                <div><strong>Content Area:</strong> ${escapeHtml(urlData.content_analysis?.content_area || 'N/A')}</div>
                                <div><strong>Readability:</strong> ${urlData.content_analysis?.readability?.flesch_score ?? 'N/A'}</div>
                                <div><strong>Grammar Findings:</strong> ${(urlData.content_analysis?.grammar || []).length}</div>
                                <div><strong>Spelling Findings:</strong> ${(urlData.content_analysis?.spelling || []).length}</div>
                                <div><strong>Repeated Phrases:</strong> ${(urlData.content_analysis?.repeated_phrases || []).length}</div>
                                <div><strong>Bigrams:</strong> ${(urlData.content_analysis?.n_grams?.bigrams || []).length}</div>
                                <div><strong>Trigrams:</strong> ${(urlData.content_analysis?.n_grams?.trigrams || []).length}</div>
                            </div>
                            ${(urlData.content_analysis?.grammar?.length || urlData.content_analysis?.spelling?.length) ? `<pre class="json-preview">${escapeHtml(JSON.stringify({grammar: urlData.content_analysis.grammar, spelling: urlData.content_analysis.spelling}, null, 2))}</pre>` : ''}
                        </div>

                        <div class="details-section">
                            <h4>♿ Accessibility & Validation</h4>
                            <div class="details-grid">
                                <div><strong>Accessibility Findings:</strong> ${(urlData.accessibility?.findings || []).length}</div>
                                <div><strong>Accessibility Score:</strong> ${urlData.accessibility?.score ?? 'N/A'}</div>
                                <div><strong>HTML Valid:</strong> ${urlData.html_validation ? (urlData.html_validation.valid ? '✅ Yes' : '❌ No') : 'N/A'}</div>
                                <div><strong>HTML Errors:</strong> ${(urlData.html_validation?.errors || []).length}</div>
                            </div>
                            ${(urlData.accessibility?.findings?.length || urlData.html_validation?.errors?.length) ? `<pre class="json-preview">${escapeHtml(JSON.stringify({accessibility: urlData.accessibility, html_validation: urlData.html_validation}, null, 2))}</pre>` : ''}
                        </div>

                        ${(urlData.linked_from && urlData.linked_from.length > 0) ? `
                        <div class="details-section">
                            <h4>🔗 Linked From</h4>
                            <div class="details-grid">
                                <div><strong>Found on ${urlData.linked_from.length} page${urlData.linked_from.length !== 1 ? 's' : ''}:</strong></div>
                            </div>
                            <div class="details-subsection">
                                <ul style="list-style: none; padding: 0; margin: 10px 0;">
                                    ${urlData.linked_from.slice(0, 20).map(sourceUrl => {
                                        const escapedUrl = escapeHtml(sourceUrl);
                                        return `<li style="padding: 5px 0; word-break: break-all;"><a href="${escapedUrl}" target="_blank" style="color: #8b5cf6; text-decoration: none;">${escapedUrl}</a></li>`;
                                    }).join('')}
                                    ${urlData.linked_from.length > 20 ? `<li style="padding: 5px 0; font-style: italic; color: #9ca3af;">... and ${urlData.linked_from.length - 20} more</li>` : ''}
                                </ul>
                            </div>
                        </div>
                        ` : ''}

                        <div class="details-section">
                            <h4>🏗️ Structured Data</h4>
                            <div class="details-grid">
                                <div><strong>JSON-LD Scripts:</strong> ${(urlData.json_ld || []).length}</div>
                                <div><strong>Schema.org Items:</strong> ${(urlData.schema_org || []).length}</div>
                            </div>
                            ${(urlData.json_ld || []).length > 0 ? `
                                <div class="details-subsection">
                                    <h5>JSON-LD Data:</h5>
                                    <pre class="json-preview">${escapeHtml(JSON.stringify(urlData.json_ld, null, 2))}</pre>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalContent);
    window._activeDetailData = urlData;
    renderDetailPanel('summary');
}

async function openUserManagement() {
    let response;
    try { response = await fetch('/api/admin/users'); } catch (_) { showNotification('User management unavailable', 'error'); return; }
    const data = await response.json();
    if (!response.ok || !data.success) { showNotification(data.error || 'Administrator access required', 'error'); return; }
    const rows = (data.users || []).map(user => `<tr><td>${escapeHtml(user.username)}</td><td>${escapeHtml(user.email)}</td><td>${escapeHtml(user.tier || 'guest')}</td><td>${user.verified ? 'Verified' : 'Pending'}</td></tr>`).join('');
    const modal = document.createElement('div');
    modal.className = 'modal'; modal.id = 'userManagementModal'; modal.style.display = 'flex';
    modal.innerHTML = `<div class="modal-content" style="max-width:900px"><div class="modal-header"><h2>User Management</h2><button class="modal-close" onclick="document.getElementById('userManagementModal').remove()">&times;</button></div><div class="modal-body"><h3>Create user</h3><form id="adminCreateUserForm" class="settings-form"><div class="input-group"><label>Username</label><input name="username" class="url-input" required minlength="3"></div><div class="input-group"><label>Email</label><input name="email" type="email" class="url-input" required></div><div class="input-group"><label>Password</label><input name="password" type="password" class="url-input" required minlength="8"></div><div class="input-group"><label>Role</label><select name="tier" class="url-input"><option value="user">User</option><option value="extra">Extra</option><option value="admin">Administrator</option></select></div><button class="btn btn-primary" type="submit">Create verified user</button></form><h3>Existing users</h3><div class="table-container"><table class="data-table"><thead><tr><th>Username</th><th>Email</th><th>Role</th><th>Status</th></tr></thead><tbody>${rows || '<tr><td colspan="4">No users</td></tr>'}</tbody></table></div></div></div>`;
    document.body.appendChild(modal);
    document.getElementById('adminCreateUserForm').addEventListener('submit', async event => {
        event.preventDefault();
        const payload = Object.fromEntries(new FormData(event.target).entries());
        const result = await fetch('/api/admin/users', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
        const body = await result.json();
        if (!result.ok || !body.success) { showNotification(body.error || 'User creation failed', 'error'); return; }
        showNotification('User created and verified', 'success');
        modal.remove();
        openUserManagement();
    });
}

function markdownCell(value) {
    return String(value ?? 'N/D').replace(/\|/g, '\\|').replace(/\r?\n/g, ' ').trim() || 'N/D';
}

function markdownDetails(value) {
    return String(value ?? 'Nessun dettaglio disponibile').replace(/```/g, '``\\`').trim();
}

async function exportAiRemediationReport() {
    try {
        const response = await fetch('/api/crawl_status');
        const data = await response.json();
        const urls = data.urls?.length ? data.urls : (crawlState.urls || []);
        const issues = data.issues?.length ? data.issues : (crawlState.issues || window.currentIssues || []);
        if (!urls.length && !issues.length) {
            showNotification('No crawl data to export', 'error');
            return;
        }

        const priority = { error: 'P0 - Critical', warning: 'P1 - High', info: 'P2 - Review' };
        const counts = issues.reduce((acc, issue) => {
            const key = issue.type || 'info';
            acc[key] = (acc[key] || 0) + 1;
            return acc;
        }, {});
        const site = urls[0]?.url ? (() => { try { return new URL(urls[0].url).origin; } catch (_) { return 'Sito analizzato'; } })() : 'Sito analizzato';
        const grouped = {};
        issues.forEach(issue => {
            const key = `${issue.type || 'info'}|${issue.category || 'General'}|${issue.issue || 'Issue'}`;
            if (!grouped[key]) grouped[key] = { ...issue, urls: [], total: 0 };
            grouped[key].total += 1;
            if (issue.url && grouped[key].urls.length < 100) grouped[key].urls.push(issue.url);
        });
        const groups = Object.values(grouped).sort((a, b) => {
            const rank = { error: 0, warning: 1, info: 2 };
            return (rank[a.type] ?? 2) - (rank[b.type] ?? 2) || b.total - a.total;
        });
        const generated = new Date().toISOString();
        let md = `# SEO Remediation Task\n\n`;
        md += `> Generated by Deep Crawling on ${generated}\n\n`;
        md += `## Obiettivo\n\nAnalizza e risolvi le problematiche SEO riportate per **${site}**. Mantieni invariati contenuti e funzionalità valide. Prima di applicare modifiche distruttive, chiedi conferma.\n\n`;
        md += `## Contesto del crawl\n\n- URL scoperte: ${data.stats?.discovered ?? urls.length}\n- URL analizzate: ${data.stats?.crawled ?? urls.length}\n- Issue totali: ${issues.length}\n- Critiche: ${counts.error || 0}\n- Alte: ${counts.warning || 0}\n- Da verificare: ${counts.info || 0}\n\n`;
        md += `## Istruzioni per l'assistente AI\n\n1. Raggruppa le modifiche per template e non correggere ripetutamente lo stesso problema.\n2. Verifica il codice sorgente e il contesto di ogni URL prima di modificare il sito.\n3. Proponi prima un piano con file, query o endpoint coinvolti.\n4. Applica le correzioni solo dopo approvazione del proprietario.\n5. Esegui un controllo post-intervento e restituisci URL modificati, esito e problemi residui.\n\n`;
        md += `## Issue rilevate\n\n`;
        if (!groups.length) md += `Nessuna issue rilevata nel crawl.\n`;
        groups.forEach((issue, index) => {
            md += `### ${index + 1}. [${priority[issue.type] || 'P2 - Review'}] ${markdownCell(issue.issue || 'Issue SEO')}\n\n`;
            md += `- Categoria: ${markdownCell(issue.category)}\n- Occorrenze: ${issue.total}\n`;
            md += `- Dettagli: ${markdownCell(issue.details)}\n- Azione richiesta: identifica la causa, applica una correzione coerente e verifica il risultato.\n- Criterio di accettazione: il problema non deve più comparire in un nuovo crawl.\n\n`;
            if (issue.urls.length) {
                md += `URL coinvolte (massimo 100):\n\n`;
                issue.urls.forEach(url => { md += `- ${markdownCell(url)}\n`; });
                md += `\n`;
            }
        });
        md += `## Verifica finale richiesta\n\n- [ ] Nuovo crawl completato\n- [ ] Issue critiche risolte\n- [ ] Redirect, canonical, robots e sitemap verificati\n- [ ] Nessuna regressione di status code o contenuto\n- [ ] Report delle modifiche restituito al proprietario\n`;

        const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = `deep-crawling-ai-remediation-${new Date().toISOString().slice(0, 10)}.md`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
        showNotification(`Report AI esportato: ${groups.length} categorie`, 'success');
    } catch (error) {
        console.error('AI remediation export error:', error);
        showNotification('Export AI report failed', 'error');
    }
}

function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    const collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('librecrawl_sidebar_collapsed', collapsed ? '1' : '0');
    const button = sidebar.querySelector('.sidebar-toggle');
    if (button) button.textContent = collapsed ? '›' : '‹';
}

function openProjectsWorkspace() {
    const integrationsButton = Array.from(document.querySelectorAll('.tab-btn')).find(button => button.textContent.trim() === 'Integrations');
    if (integrationsButton) integrationsButton.click();
    const anchor = document.getElementById('projectCrawlId');
    if (anchor) anchor.scrollIntoView({behavior: 'smooth', block: 'start'});
}

document.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('librecrawl_sidebar_collapsed') === '1') {
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) sidebar.classList.add('collapsed');
        const button = document.querySelector('.sidebar-toggle');
        if (button) button.textContent = '›';
    }
});

function renderDetailPanel(panel) {
    const data = window._activeDetailData || {};
    const output = document.getElementById('detailPanelOutput');
    if (!output) return;
    const values = {
        summary: {url: data.url, status_code: data.status_code, title: data.title, meta_description: data.meta_description, content_type: data.content_type},
        inlinks: data.inlinks || data.linked_from || [], outlinks: data.outlinks || [], resources: data.resources || [],
        headers: data.http_headers || {}, cookies: data.cookies || [], structured_data: {json_ld: data.json_ld || [], schema_org: data.schema_org || []},
        rendering: {screenshot_path: data.screenshot_path, rendered_archive_path: data.rendered_archive_path, diagnostics: data.render_diagnostics || {}, javascript_errors: data.javascript_errors || []},
        accessibility: data.accessibility || {}, content: data.content_analysis?.n_grams || {}
    };
    output.innerHTML = `<h5>${escapeHtml(panel.replace('_', ' '))}</h5><pre class="json-preview">${escapeHtml(JSON.stringify(values[panel] ?? {}, null, 2))}</pre>`;
}

function closeUrlDetails() {
    const modal = document.querySelector('.details-modal-overlay');
    if (modal) {
        modal.remove();
    }
}

function displayPageSpeedResults(results) {
    const container = document.getElementById('pagespeedResults');
    if (!container || !results || results.length === 0) {
        return;
    }

    container.innerHTML = '';

    results.forEach(pageResult => {
        const pageCard = document.createElement('div');
        pageCard.className = 'pagespeed-page-card';

        const mobile = pageResult.mobile || {};
        const desktop = pageResult.desktop || {};

        pageCard.innerHTML = `
            <div class="pagespeed-page-header">
                <h4 class="pagespeed-page-url">${pageResult.url}</h4>
                <span class="pagespeed-analysis-date">Analyzed: ${pageResult.analysis_date}</span>
            </div>

            <div class="pagespeed-results-grid">
                <div class="pagespeed-device-result">
                    <h5>📱 Mobile</h5>
                    ${mobile.success ? `
                        <div class="pagespeed-score ${getScoreClass(mobile.performance_score)}">
                            ${mobile.performance_score || 'N/A'}
                        </div>
                        <div class="pagespeed-metrics">
                            <div class="metric">
                                <span class="metric-label">FCP:</span>
                                <span class="metric-value">${mobile.metrics?.first_contentful_paint || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">LCP:</span>
                                <span class="metric-value">${mobile.metrics?.largest_contentful_paint || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">CLS:</span>
                                <span class="metric-value">${mobile.metrics?.cumulative_layout_shift || 'N/A'}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">SI:</span>
                                <span class="metric-value">${mobile.metrics?.speed_index || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">TTI:</span>
                                <span class="metric-value">${mobile.metrics?.time_to_interactive || 'N/A'}s</span>
                            </div>
                        </div>
                    ` : `
                        <div class="pagespeed-error">
                            Error: ${mobile.error || 'Analysis failed'}
                        </div>
                    `}
                </div>

                <div class="pagespeed-device-result">
                    <h5>🖥️ Desktop</h5>
                    ${desktop.success ? `
                        <div class="pagespeed-score ${getScoreClass(desktop.performance_score)}">
                            ${desktop.performance_score || 'N/A'}
                        </div>
                        <div class="pagespeed-metrics">
                            <div class="metric">
                                <span class="metric-label">FCP:</span>
                                <span class="metric-value">${desktop.metrics?.first_contentful_paint || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">LCP:</span>
                                <span class="metric-value">${desktop.metrics?.largest_contentful_paint || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">CLS:</span>
                                <span class="metric-value">${desktop.metrics?.cumulative_layout_shift || 'N/A'}</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">SI:</span>
                                <span class="metric-value">${desktop.metrics?.speed_index || 'N/A'}s</span>
                            </div>
                            <div class="metric">
                                <span class="metric-label">TTI:</span>
                                <span class="metric-value">${desktop.metrics?.time_to_interactive || 'N/A'}s</span>
                            </div>
                        </div>
                    ` : `
                        <div class="pagespeed-error">
                            Error: ${desktop.error || 'Analysis failed'}
                        </div>
                    `}
                </div>
            </div>
        `;

        container.appendChild(pageCard);
    });
}

function getScoreClass(score) {
    if (!score) return 'score-unknown';
    if (score >= 90) return 'score-good';
    if (score >= 50) return 'score-needs-improvement';
    return 'score-poor';
}

// Save/Load Crawl Functions
async function saveCrawl() {
    try {
        if (crawlState.stats.crawled === 0) {
            showNotification('No crawl data to save', 'error');
            return;
        }

        // Get current crawl data from backend or use local state
        let urls = crawlState.urls;
        let links = crawlState.links;
        let issues = crawlState.issues;
        let stats = crawlState.stats;

        // Try to get fresh data from backend if available
        try {
            const status = await fetch('/api/crawl_status');
            const crawlData = await status.json();
            if (crawlData.urls && crawlData.urls.length > 0) {
                urls = crawlData.urls;
                links = crawlData.links || links;
                issues = crawlData.issues || issues;
                // Update stats to include latest PageSpeed results if available
                if (crawlData.stats) {
                    stats = crawlData.stats;
                }
            }
        } catch (e) {
            console.log('Using local state for save:', e);
        }

        // Add metadata
        const saveData = {
            timestamp: new Date().toISOString(),
            baseUrl: crawlState.baseUrl,
            stats: stats,
            urls: urls,
            links: links,
            issues: issues,
            version: '1.1'
        };

        // Create and download the file
        const blob = new Blob([JSON.stringify(saveData, null, 2)], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        // Generate filename with domain and timestamp
        const domain = crawlState.baseUrl ? new URL(crawlState.baseUrl).hostname : 'crawl';
        const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
        a.download = `librecrawl_${domain}_${timestamp}.json`;

        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showNotification('Crawl saved successfully', 'success');

    } catch (error) {
        console.error('Save error:', error);
        showNotification('Failed to save crawl', 'error');
    }
}

function loadCrawl() {
    // Create file input
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.json';
    fileInput.style.display = 'none';

    fileInput.addEventListener('change', async function(event) {
        const file = event.target.files[0];
        if (!file) return;

        try {
            const text = await file.text();
            const saveData = JSON.parse(text);

            // Validate save data
            if (!saveData.version || !saveData.urls || !saveData.stats) {
                showNotification('Invalid crawl file format', 'error');
                return;
            }

            // Clear current data
            clearAllTables();
            resetStats();

            // Load the data
            crawlState.baseUrl = saveData.baseUrl;
            crawlState.stats = saveData.stats;
            crawlState.urls = [];
            crawlState.links = saveData.links || [];
            crawlState.issues = saveData.issues || [];

            // Update UI
            document.getElementById('urlInput').value = saveData.baseUrl || '';
            updateStatsDisplay();

            // Populate tables with loaded data
            if (saveData.urls && saveData.urls.length > 0) {
                console.log(`Loading ${saveData.urls.length} URLs...`);

                // Clear crawlState.urls first to avoid duplicate check issues
                crawlState.urls = [];

                // Add URLs to tables (addUrlToTable will handle adding to crawlState.urls)
                saveData.urls.forEach(url => {
                    // Debug: check if url has is_internal flag
                    if (url.is_internal === undefined) {
                        console.warn('URL missing is_internal flag:', url.url);
                        // Try to determine is_internal based on domain
                        if (crawlState.baseUrl) {
                            try {
                                const urlDomain = new URL(url.url).hostname.replace('www.', '');
                                const baseDomain = new URL(crawlState.baseUrl).hostname.replace('www.', '');
                                url.is_internal = urlDomain === baseDomain;
                            } catch (e) {
                                url.is_internal = false;
                            }
                        }
                    }
                    addUrlToTable(url);
                });

                console.log(`Added ${crawlState.urls.length} URLs to state`);
                console.log('Sample URL data:', crawlState.urls[0]);
            }

            // Load links data
            if (saveData.links && saveData.links.length > 0) {
                console.log(`Loading ${saveData.links.length} links...`);
                crawlState.pendingLinks = saveData.links;
                // If Links tab is currently active, load them immediately
                if (isLinksTabActive()) {
                    updateLinksTable(saveData.links);
                }
            }

            // Load issues data if present - filter them based on current exclusion settings
            if (saveData.issues && saveData.issues.length > 0) {
                console.log(`Loading ${saveData.issues.length} issues...`);

                // Filter issues using current exclusion patterns
                try {
                    const filterResponse = await fetch('/api/filter_issues', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ issues: saveData.issues })
                    });
                    const filterData = await filterResponse.json();

                    const filteredIssues = filterData.success ? filterData.issues : saveData.issues;
                    console.log(`Filtered to ${filteredIssues.length} issues after exclusions`);

                    crawlState.issues = filteredIssues;
                    crawlState.pendingIssues = filteredIssues;

                    // If Issues tab is currently active, load them immediately
                    if (isIssuesTabActive()) {
                        updateIssuesTable(filteredIssues);
                    } else {
                        // Update the badge count even if tab is not active
                        const issuesTabButton = Array.from(document.querySelectorAll('.tab-btn')).find(btn => btn.textContent.includes('Issues'));
                        if (issuesTabButton) {
                            const errorCount = filteredIssues.filter(i => i.type === 'error').length;
                            const warningCount = filteredIssues.filter(i => i.type === 'warning').length;
                            let badgeColor = '#3b82f6';
                            if (errorCount > 0) badgeColor = '#ef4444';
                            else if (warningCount > 0) badgeColor = '#f59e0b';
                            issuesTabButton.innerHTML = `Issues <span style="background: ${badgeColor}; color: white; padding: 2px 6px; border-radius: 12px; font-size: 12px;">${filteredIssues.length}</span>`;
                        }
                    }
                } catch (error) {
                    console.error('Failed to filter issues:', error);
                    // Fall back to unfiltered issues if filtering fails
                    crawlState.issues = saveData.issues;
                    crawlState.pendingIssues = saveData.issues;
                    if (isIssuesTabActive()) {
                        updateIssuesTable(saveData.issues);
                    }
                }
            }

            // Update all secondary data
            updateFilterCounts();
            updateStatusCodesTable();
            updateCrawlButtons();

            // Display PageSpeed results if available
            if (saveData.stats && saveData.stats.pagespeed_results) {
                console.log(`Loading ${saveData.stats.pagespeed_results.length} PageSpeed results...`);
                displayPageSpeedResults(saveData.stats.pagespeed_results);
            }

            // Force refresh of all tables
            setTimeout(() => {
                console.log('Force refreshing tables...');
                const overviewCount = document.getElementById('overviewTableBody').children.length;
                const internalCount = document.getElementById('internalTableBody').children.length;
                const externalCount = document.getElementById('externalTableBody').children.length;
                console.log(`Table counts - Overview: ${overviewCount}, Internal: ${internalCount}, External: ${externalCount}`);
            }, 100);

            // Update visualization if it exists and has been initialized
            if (typeof window.updateVisualizationFromLoadedData === 'function') {
                window.updateVisualizationFromLoadedData(saveData.urls, saveData.links);
            }

            // Notify plugins of loaded data
            if (window.LibreCrawlPlugin && window.LibreCrawlPlugin.loader) {
                window.LibreCrawlPlugin.loader.notifyDataUpdate({
                    urls: crawlState.urls,
                    links: crawlState.links,
                    issues: crawlState.issues,
                    stats: crawlState.stats
                });
            }

            showNotification(`Crawl loaded: ${saveData.stats.crawled} URLs from ${new Date(saveData.timestamp).toLocaleDateString()}`, 'success');

        } catch (error) {
            console.error('Load error:', error);
            showNotification('Failed to load crawl file', 'error');
        }
    });

    // Trigger file selection
    document.body.appendChild(fileInput);
    fileInput.click();
    document.body.removeChild(fileInput);
}

// ========================================
// Virtual Scroller Render Functions
// ========================================

function renderOverviewRow(row, urlData, index) {
    const analyticsInfo = formatAnalyticsInfo(urlData.analytics || {});
    const ogTagsCount = Object.keys(urlData.og_tags || {}).length;
    const jsonLdCount = (urlData.json_ld || []).length;
    const linksInfo = `${urlData.internal_links || 0}/${urlData.external_links || 0}`;
    const imagesCount = (urlData.images || []).length;
    const jsRendered = urlData.javascript_rendered ? '✅ JS' : '';

    const cells = [
        urlData.url,
        urlData.status_code,
        urlData.title || '',
        (urlData.meta_description || '').substring(0, 50) + (urlData.meta_description && urlData.meta_description.length > 50 ? '...' : ''),
        urlData.h1 || '',
        urlData.word_count || 0,
        urlData.response_time || 0,
        analyticsInfo,
        ogTagsCount > 0 ? `${ogTagsCount} tags` : '',
        jsonLdCount > 0 ? `${jsonLdCount} scripts` : '',
        linksInfo,
        imagesCount > 0 ? `${imagesCount} images` : '',
        jsRendered,
        `<button class="details-btn" onclick="showUrlDetails('${urlData.url.replace(/'/g, "\\'")}')">📊 Details</button>`
    ];

    cells.forEach(cellData => {
        const cell = document.createElement('td');
        if (typeof cellData === 'string' && cellData.includes('<button')) {
            cell.innerHTML = cellData;
        } else {
            cell.textContent = cellData;
        }
        row.appendChild(cell);
    });
}

function renderInternalRow(row, urlData, index) {
    const cells = [
        urlData.url,
        urlData.status_code,
        urlData.content_type || '',
        urlData.size || 0,
        urlData.title || ''
    ];

    cells.forEach(cellData => {
        const cell = document.createElement('td');
        cell.textContent = cellData;
        row.appendChild(cell);
    });
}

function renderExternalRow(row, urlData, index) {
    const cells = [
        urlData.url,
        urlData.status_code,
        urlData.content_type || '',
        urlData.size || 0,
        urlData.title || ''
    ];

    cells.forEach(cellData => {
        const cell = document.createElement('td');
        cell.textContent = cellData;
        row.appendChild(cell);
    });
}

function renderInternalLinkRow(row, link, index) {
    const statusBadge = link.target_status ? `<span class="status-badge status-${Math.floor(link.target_status / 100)}xx">${link.target_status}</span>` : '';
    const placement = link.placement ? link.placement.charAt(0).toUpperCase() + link.placement.slice(1) : 'Unknown';

    row.innerHTML = `
        <td style="word-break: break-all;">${link.source_url}</td>
        <td style="word-break: break-all;">${link.target_url}</td>
        <td>${statusBadge}</td>
        <td>${link.anchor_text || ''}</td>
        <td>${placement}</td>
    `;
}

function renderExternalLinkRow(row, link, index) {
    const statusBadge = link.target_status ? `<span class="status-badge status-${Math.floor(link.target_status / 100)}xx">${link.target_status}</span>` : '';
    const placement = link.placement ? link.placement.charAt(0).toUpperCase() + link.placement.slice(1) : 'Unknown';

    row.innerHTML = `
        <td style="word-break: break-all;">${link.source_url}</td>
        <td style="word-break: break-all;">${link.target_url}</td>
        <td>${statusBadge}</td>
        <td>${link.target_domain || ''}</td>
        <td>${placement}</td>
    `;
}

function renderIssueRow(row, issue, index) {
    row.setAttribute('data-issue-type', issue.type);

    // Set row style based on issue type
    if (issue.type === 'error') {
        row.style.backgroundColor = 'rgba(239, 68, 68, 0.1)';
    } else if (issue.type === 'warning') {
        row.style.backgroundColor = 'rgba(245, 158, 11, 0.1)';
    } else {
        row.style.backgroundColor = 'rgba(59, 130, 246, 0.1)';
    }

    // Create type indicator
    let typeIcon = '';
    let typeColor = '';
    if (issue.type === 'error') {
        typeIcon = '❌';
        typeColor = '#ef4444';
    } else if (issue.type === 'warning') {
        typeIcon = '⚠️';
        typeColor = '#f59e0b';
    } else {
        typeIcon = 'ℹ️';
        typeColor = '#3b82f6';
    }

    row.innerHTML = `
        <td style="word-break: break-all;" title="${issue.url}">${issue.url}</td>
        <td><span style="color: ${typeColor};">${typeIcon}</span> ${issue.type}</td>
        <td>${issue.category}</td>
        <td>${issue.issue}</td>
        <td style="word-break: break-word;" title="${issue.details}">${issue.details}</td>
    `;
}

function switchSpiderView(view) {
    const table = document.getElementById('overviewTable');
    if (!table) return;
    const columns = {
        all: [], internal: ['analytics', 'links'], external: ['links'], security: ['status', 'javascript'], response: ['status', 'response'],
        url: ['address'], titles: ['title'], meta: ['meta'], headings: ['h1', 'h2'], content: ['words'], images: ['images'], canonicals: ['canonical'],
        pagination: ['pagination'], directives: ['robots', 'canonical'], hreflang: ['hreflang'], javascript: ['js'], amp: ['amp'], structured: ['json-ld'],
        sitemaps: ['sitemap'], mobile: ['mobile'], accessibility: ['accessibility'], validation: ['validation'], analytics: ['analytics'], 'search-console': ['search'], links: ['links'], ai: ['ai'], changes: ['change']
    };
    const wanted = columns[view] || [];
    Array.from(table.rows).forEach(row => Array.from(row.cells).forEach((cell, index) => {
        if (index === 0 || !wanted.length) { cell.style.display = ''; return; }
        const header = table.rows[0]?.cells[index]?.textContent.toLowerCase() || '';
        cell.style.display = wanted.some(token => header.includes(token)) ? '' : 'none';
    }));
}

async function checkApplicationUpdate() {
    const output = document.getElementById('applicationUpdateResult');
    try {
        const manifestUrl = document.getElementById('updateManifestUrl')?.value.trim();
        const response = manifestUrl ? await fetch('/api/app/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'check', manifest_url: manifestUrl})}) : await fetch('/api/app/update');
        output.textContent = JSON.stringify(await response.json(), null, 2);
    } catch (error) { output.textContent = error.message; }
}

async function downloadApplicationUpdate() {
    const output = document.getElementById('applicationUpdateResult');
    const manifestUrl = document.getElementById('updateManifestUrl')?.value.trim();
    if (!manifestUrl) { output.textContent = 'Manifest URL required'; return; }
    const checked = await fetch('/api/app/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'check', manifest_url: manifestUrl})}).then(response => response.json());
    if (!checked.success || !checked.update?.update_available) { output.textContent = JSON.stringify(checked, null, 2); return; }
    const response = await fetch('/api/app/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'download', manifest: checked.update.manifest})});
    const data = await response.json();
    if (data.success) window._downloadedUpdate = data.update;
    output.textContent = JSON.stringify(data, null, 2);
}

async function applyApplicationUpdate() {
    const output = document.getElementById('applicationUpdateResult');
    const update = window._downloadedUpdate;
    if (!update?.path || !window.confirm('Apply the checksum-verified update?')) return;
    const response = await fetch('/api/app/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'apply', archive_path: update.path, confirm: true})});
    output.textContent = JSON.stringify(await response.json(), null, 2);
}

async function rollbackApplicationUpdate() {
    const output = document.getElementById('applicationUpdateResult');
    if (!window.confirm('Restore the backup created by the last update?')) return;
    const response = await fetch('/api/app/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'rollback'})});
    output.textContent = JSON.stringify(await response.json(), null, 2);
}

async function runSemanticSearch() {
    const query = document.getElementById('semanticQuery')?.value.trim();
    if (!query) return;
    const response = await fetch('/api/analysis/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query})});
    const data = await response.json();
    const container = document.getElementById('semanticResults');
    if (!data.success) { container.textContent = data.error || 'Search failed'; return; }
    container.innerHTML = data.results.map(item => `<p><strong>${escapeHtml(item.title || item.url)}</strong> — ${escapeHtml(item.url)} (${item.score})</p>`).join('') || '<p>No matching pages.</p>';
}

async function runEmbeddingSearch() {
    const query = document.getElementById('semanticQuery')?.value.trim();
    if (!query) return;
    const response = await fetch('/api/analysis/embeddings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query, api_key: document.getElementById('embeddingApiKey').value, model: document.getElementById('embeddingModel').value})});
    const data = await response.json();
    document.getElementById('semanticResults').innerHTML = data.success ? data.results.map(item => `<p><strong>${escapeHtml(item.title || item.url)}</strong> — ${escapeHtml(item.url)} (${item.score})</p>`).join('') : `<p>${escapeHtml(data.error || 'Embedding search failed')}</p>`;
}

async function runGoogleIntegration(kind) {
    const token = document.getElementById('googleToken')?.value.trim();
    const start = document.getElementById('googleStart')?.value;
    const end = document.getElementById('googleEnd')?.value;
    const payload = {access_token: token, start_date: start, end_date: end};
    let endpoint;
    if (kind === 'gsc') {
        endpoint = '/api/integrations/search-console'; payload.site_url = document.getElementById('gscSite').value.trim();
        payload.dimensions = document.getElementById('gscDimensions').value.split(',').map(value => value.trim()).filter(Boolean);
        payload.search_type = document.getElementById('gscSearchType').value;
        const rawGroups = document.getElementById('gscFilterGroups')?.value?.trim();
        if (rawGroups) { try { payload.dimension_filter_groups = JSON.parse(rawGroups); } catch (error) { document.getElementById('googleResults').textContent = 'Errore: filtri GSC non validi'; return; } }
    }
    else { endpoint = '/api/integrations/analytics'; payload.property_id = document.getElementById('gaProperty').value.trim(); }
    const output = document.getElementById('googleResults');
    const response = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    output.textContent = JSON.stringify(data, null, 2);
}

function integrationJsonValue(id, fallback = {}) {
    const raw = document.getElementById(id)?.value?.trim();
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (error) { throw new Error(`${id}: JSON non valido`); }
}

async function runIntegrationRequest(path, payload) {
    const output = document.getElementById('googleResults');
    try {
        output.textContent = 'Loading...';
        const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
        output.textContent = JSON.stringify(data, null, 2);
    } catch (error) { output.textContent = `Errore: ${error.message}`; }
}

async function runGscInspection() {
    return runIntegrationRequest('/api/integrations/search-console/inspection', {
        site_url: document.getElementById('gscSite').value.trim(),
        inspection_url: document.getElementById('gscInspectionUrl').value.trim(),
        access_token: document.getElementById('googleToken').value.trim()
    });
}

async function runGscResources(resource) {
    return runIntegrationRequest('/api/integrations/search-console/resources', {
        resource, site_url: document.getElementById('gscSite').value.trim(),
        access_token: document.getElementById('googleToken').value.trim(),
        sitemap_url: document.getElementById('gscSitemapUrl')?.value?.trim() || undefined
    });
}

async function runGa4Report() {
    let dimensionFilter;
    const rawFilter = document.getElementById('gaDimensionFilter')?.value?.trim();
    if (rawFilter) { try { dimensionFilter = JSON.parse(rawFilter); } catch (error) { document.getElementById('googleResults').textContent = 'Errore: filtro GA4 non è JSON valido'; return; } }
    return runIntegrationRequest('/api/integrations/ga4/report', {
        property_id: document.getElementById('gaProperty').value.trim(),
        access_token: document.getElementById('googleToken').value.trim(),
        start_date: document.getElementById('googleStart').value || '30daysAgo',
        end_date: document.getElementById('googleEnd').value || 'yesterday',
        dimensions: [document.getElementById('gaDimensions').value],
        metrics: document.getElementById('gaMetrics').value.split(',').map(value => value.trim()).filter(Boolean),
        dimension_filter: dimensionFilter,
        keep_empty_rows: document.getElementById('gaKeepEmpty')?.checked || false,
        return_property_quota: document.getElementById('gaQuota')?.checked || false
    });
}

async function runPageSpeedIntegration() {
    return runIntegrationRequest('/api/integrations/pagespeed', {
        url: document.getElementById('pagespeedUrl').value.trim(),
        strategy: document.getElementById('pagespeedStrategy').value,
        api_key: document.getElementById('pagespeedKey').value.trim() || undefined,
        categories: ['performance', 'accessibility', 'seo']
    });
}

function projectScheduleOutput(value) {
    const output = document.getElementById('projectScheduleResults');
    if (output) output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

async function exportProjectArchive() {
    const id = document.getElementById('projectCrawlId')?.value;
    if (!id) return projectScheduleOutput('Inserisci un crawl ID.');
    const response = await fetch(`/api/projects/${encodeURIComponent(id)}/export`, {method: 'POST'});
    if (!response.ok) return projectScheduleOutput(`Export fallito: HTTP ${response.status}`);
    const blob = await response.blob();
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `crawl-${id}.librecrawl`; link.click(); URL.revokeObjectURL(link.href);
    projectScheduleOutput('Progetto esportato.');
}

async function exportHistoricalDataset() {
    const id = document.getElementById('projectCrawlId')?.value;
    if (!id) return projectScheduleOutput('Inserisci un crawl ID.');
    const dataset = document.getElementById('historicalExportDataset').value;
    const format = document.getElementById('historicalExportFormat').value;
    const response = await fetch(`/api/crawls/${encodeURIComponent(id)}/export?dataset=${encodeURIComponent(dataset)}&format=${encodeURIComponent(format)}`);
    if (!response.ok) return projectScheduleOutput(`Export fallito: HTTP ${response.status}`);
    const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `librecrawl-${id}-${dataset}.${format}`; link.click(); URL.revokeObjectURL(link.href);
    projectScheduleOutput(`Dataset ${dataset} esportato.`);
}

async function importProjectArchive() {
    const file = document.getElementById('projectImportFile')?.files?.[0];
    if (!file) return projectScheduleOutput('Seleziona un file .librecrawl.');
    const form = new FormData(); form.append('project', file);
    const response = await fetch('/api/projects/import', {method: 'POST', body: form});
    const data = await response.json(); projectScheduleOutput(data); if (data.success && typeof openDashboard === 'function') await openDashboard();
}

async function createCrawlSchedule() {
    const recipients = (document.getElementById('scheduleRecipients')?.value || '').split(',').map(x => x.trim()).filter(Boolean);
    const payload = {name: document.getElementById('scheduleName').value.trim(), url: document.getElementById('scheduleUrl').value.trim(), interval_seconds: Number(document.getElementById('scheduleInterval').value || 86400), timezone: document.getElementById('scheduleTimezone').value.trim() || 'UTC', recipients};
    const response = await fetch('/api/schedules', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    projectScheduleOutput(await response.json());
}

async function startScheduleWorker() {
    const response = await fetch('/api/schedules/worker', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'start'})});
    projectScheduleOutput(await response.json());
}

async function stopScheduleWorker() {
    const response = await fetch('/api/schedules/worker', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'stop'})});
    projectScheduleOutput(await response.json());
}

async function runBingOperation() {
    return runIntegrationRequest('/api/integrations/bing-webmaster/operation', {
        operation: document.getElementById('bingOperation').value,
        site_url: document.getElementById('bingSite').value.trim(),
        api_key: document.getElementById('bingToken').value.trim(),
        endpoint: document.getElementById('bingEndpoint').value.trim(),
        payload: integrationJsonValue('bingPayload', {})
    });
}

async function runBacklinkMetrics() {
    const provider = document.getElementById('backlinkProvider').value.trim().toLowerCase();
    const token = document.getElementById('backlinkToken').value;
    const endpoint = document.getElementById('backlinkEndpoint').value.trim();
    const target = document.getElementById('backlinkTarget').value.trim();
    if (!target) { document.getElementById('backlinkResults').textContent = 'Inserisci una URL target.'; return; }
    if (['ahrefs', 'majestic', 'moz'].includes(provider) && !token) { document.getElementById('backlinkResults').textContent = 'Inserisci la chiave API del provider.'; return; }
    const response = await fetch('/api/integrations/backlinks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        endpoint, target_url: target, provider, api_key: token, access_token: token
    })});
    document.getElementById('backlinkResults').textContent = JSON.stringify(await response.json(), null, 2);
}

async function runAiAnalysis() {
    const output = document.getElementById('aiResults');
    const response = await fetch('/api/ai/analyze', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        prompt: document.getElementById('aiPrompt').value.trim(), api_key: document.getElementById('aiApiKey').value,
        endpoint: document.getElementById('aiEndpoint').value.trim()
    })});
    output.textContent = JSON.stringify(await response.json(), null, 2);
}

async function sendReportEmail() {
    const output = document.getElementById('emailResult');
    const response = await fetch('/api/reports/email', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        to: document.getElementById('reportEmail').value.trim(), crawl_id: Number(document.getElementById('reportCrawlId').value), format: document.getElementById('reportFormat').value
    })});
    output.textContent = JSON.stringify(await response.json(), null, 2);
}

async function syncCloudCrawl() {
    const response = await fetch('/api/team/cloud-sync', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        endpoint: document.getElementById('cloudEndpoint').value.trim(), crawl_id: Number(document.getElementById('cloudCrawlId').value), access_token: document.getElementById('cloudToken').value
    })});
    document.getElementById('cloudResult').textContent = JSON.stringify(await response.json(), null, 2);
}

async function loadAnalysisSummary() {
    const response = await fetch('/api/analysis/summary');
    const data = await response.json();
    const target = document.getElementById('analysisSummary');
    if (!data.success) { target.textContent = data.error || 'Analysis unavailable'; return; }
    target.innerHTML = Object.entries(data.summary).map(([key, value]) => `<p><strong>${escapeHtml(key)}:</strong> ${escapeHtml(typeof value === 'object' ? JSON.stringify(value) : String(value))}</p>`).join('');
}

async function loadOrphans() {
    const data = await (await fetch('/api/analysis/orphans')).json();
    document.getElementById('analysisDetails').textContent = JSON.stringify({count: (data.orphans || []).length, orphans: data.orphans || []}, null, 2);
}
async function loadLinkMetrics() {
    const data = await (await fetch('/api/analysis/link-metrics')).json();
    document.getElementById('analysisDetails').textContent = JSON.stringify(data.metrics || data, null, 2);
}
async function loadHttpAudit() {
    const data = await (await fetch('/api/analysis/http-audit')).json();
    document.getElementById('analysisDetails').textContent = JSON.stringify(data.audit || data, null, 2);
}
async function loadChangeDetection() {
    const response = await fetch('/api/analysis/changes', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({old_crawl_id: Number(document.getElementById('oldCrawlId').value), new_crawl_id: Number(document.getElementById('newCrawlId').value)})});
    const data = await response.json();
    document.getElementById('analysisDetails').textContent = JSON.stringify(data.changes ? {count: data.count, changes: data.changes} : data, null, 2);
}

async function runRobotsTest() {
    const site = document.getElementById('robotsSite').value.trim();
    const target = document.getElementById('robotsUrl').value.trim();
    const response = await fetch('/api/seo/robots-test', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({robots_text: document.getElementById('robotsText').value, url: site || target, target_url: target})});
    document.getElementById('robotsResult').textContent = JSON.stringify(await response.json(), null, 2);
}

async function runSegment() {
    const response = await fetch('/api/analysis/segment', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expression: document.getElementById('segmentExpression').value})});
    const data = await response.json();
    document.getElementById('segmentResult').textContent = JSON.stringify({count: (data.urls || []).length, urls: (data.urls || []).slice(0, 100)}, null, 2);
}

async function runCdnRewrite() {
    const urls = (crawlState.urls || []).map(item => item.url);
    const response = await fetch('/api/seo/cdn-rewrite', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({cdn_host: document.getElementById('cdnHost').value, urls})});
    document.getElementById('cdnResult').textContent = JSON.stringify(await response.json(), null, 2);
}

async function runUrlRewrite() {
    const response = await fetch('/api/seo/rewrite', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: document.getElementById('rewriteUrl').value, rules: [{pattern: document.getElementById('rewritePattern').value, replacement: document.getElementById('rewriteReplacement').value}]})});
    document.getElementById('rewriteResult').textContent = JSON.stringify(await response.json(), null, 2);
}

async function downloadGeneratedSitemap() {
    const response = await fetch('/api/seo/sitemap', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({urls: crawlState.urls || [], base_url: crawlState.base_url || ''})});
    if (!response.ok) { showNotification('Sitemap generation failed', 'error'); return; }
    const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'librecrawl-sitemap.xml'; link.click(); URL.revokeObjectURL(link.href);
}

async function runPriorityTool(tool, payload) {
    const output=document.getElementById('priorityResults');
    try { const response=await fetch(`/api/seo/research/${tool}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data=await response.json(); if(!response.ok||data.error) throw new Error(data.error||`HTTP ${response.status}`); output.textContent=JSON.stringify(data,null,2); }
    catch(error) { output.textContent=`Errore: ${error.message}`; }
}
function priorityJsonRows() { const raw=document.getElementById('priorityRows').value.trim(); if(!raw) return []; try{return JSON.parse(raw);}catch(error){throw new Error('Rows JSON non valido');} }
async function runPriorityCron() { return runPriorityTool('cron-next',{expression:document.getElementById('priorityCron').value,timezone:document.getElementById('priorityTimezone').value}); }
async function runPriorityResourceAudit() { try{return runPriorityTool('resource-audit',{rows:priorityJsonRows()});}catch(error){document.getElementById('priorityResults').textContent=`Errore: ${error.message}`;} }
async function runPrioritySpaAudit() { try{return runPriorityTool('spa-detection',{row:priorityJsonRows()[0]||{}});}catch(error){document.getElementById('priorityResults').textContent=`Errore: ${error.message}`;} }

async function loadNativeSeoDashboard() {
    const data = await (await fetch('/api/seo/dashboard')).json();
    document.getElementById('nativeSeoDashboard').textContent = JSON.stringify(data, null, 2);
}

async function runNativeSeoScore() {
    const response = await fetch('/api/seo/strategy/score', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({rows: crawlState.urls || [], issues: crawlState.issues || []})});
    document.getElementById('nativeSeoDashboard').textContent = JSON.stringify(await response.json(), null, 2);
}

async function runNativeKeywordTools() {
    const keywords = document.getElementById('nativeKeywords').value.split(',').map(keyword => keyword.trim()).filter(Boolean);
    const cluster = await (await fetch('/api/native-seo-tools/keyword-cluster', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({keywords})})).json();
    const cannibalization = await (await fetch('/api/native-seo-tools/cannibalization', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({rows:crawlState.urls || []})})).json();
    document.getElementById('nativeKeywordResults').textContent = JSON.stringify({cluster, cannibalization}, null, 2);
}

async function saveNativeRankSnapshot() {
    const response = await fetch('/api/seo/history/rank', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        keyword:document.getElementById('rankKeyword').value, url:document.getElementById('rankUrl').value,
        competitor:document.getElementById('rankCompetitor')?.value || '',
        position:Number(document.getElementById('rankPosition').value), country:document.getElementById('rankCountry').value,
        device:document.getElementById('rankDevice').value})});
    document.getElementById('nativeRankResults').textContent = JSON.stringify(await response.json(), null, 2);
}

function parseAdvancedSeoJson(id, fallback) {
    const raw = document.getElementById(id)?.value?.trim();
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (error) { throw new Error(`${id}: JSON non valido`); }
}

async function runAdvancedSeoTool(path, payload) {
    const output = document.getElementById('advancedSeoResults');
    try {
        output.textContent = 'Loading...';
        const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
        output.textContent = JSON.stringify(data, null, 2);
    } catch (error) { output.textContent = `Errore: ${error.message}`; }
}

async function runRankHistoryReport() {
    try { return runAdvancedSeoTool('/api/native-seo-tools/rank-tracker', {snapshots:parseAdvancedSeoJson('rankHistoryJson', [])}); }
    catch (error) { document.getElementById('advancedSeoResults').textContent = `Errore: ${error.message}`; }
}

async function runLighthouseRegression() {
    try { return runAdvancedSeoTool('/api/seo/realtime/lighthouse-regression', {
        before:parseAdvancedSeoJson('lighthouseBefore', {}), after:parseAdvancedSeoJson('lighthouseAfter', {})
    }); } catch (error) { document.getElementById('advancedSeoResults').textContent = `Errore: ${error.message}`; }
}
