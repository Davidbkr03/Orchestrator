// Fusion Orchestrator Dashboard – Frontend Logic

document.addEventListener('DOMContentLoaded', () => {
    const healthDot = document.getElementById('healthDot');
    const healthText = document.getElementById('healthText');
    const normalWorkersEl = document.getElementById('normalWorkers');
    const normalJudgeEl = document.getElementById('normalJudge');
    const advancedWorkersEl = document.getElementById('advancedWorkers');
    const advancedJudgeEl = document.getElementById('advancedJudge');
    const uptimeEl = document.getElementById('uptime');
    const routesEl = document.getElementById('routes');
    const serverTimeEl = document.getElementById('serverTime');
    const councilSelect = document.getElementById('councilSelect');
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const responseArea = document.getElementById('responseArea');

    // Model swapper elements
    const refreshModelsBtn = document.getElementById('refreshModelsBtn');
    const applySwapBtn = document.getElementById('applySwapBtn');
    const resetSwapBtn = document.getElementById('resetSwapBtn');
    const swapStatus = document.getElementById('swapStatus');

    let serverStartTime = null;
    let availableModels = {};  // { provider: [model1, model2, ...] }

    function setHealth(ok) {
        healthDot.className = 'dot ' + (ok ? 'healthy' : 'unhealthy');
        healthText.textContent = ok ? 'Online' : 'Offline';
        if (!ok) healthDot.style.background = '#f85149';
        else healthDot.style.background = '#3fb950';
    }

    function renderCouncilInfo(workers, judge, workersEl, judgeEl) {
        workersEl.innerHTML = workers.map(w =>
            `<div class=\"worker-item\">
                <span class=\"provider\">${w.provider}</span>
                <span class=\"model-name\">${w.model}</span>
            </div>`
        ).join('');
        const thinkingBadge = judge.thinking ? `<span class=\"badge\">thinking ON</span>` : '';
        judgeEl.innerHTML = `<div class=\"judge-item\">🧑‍⚖️ ${judge.provider} / ${judge.model} ${thinkingBadge}</div>`;
    }

    function formatUptime(seconds) {
        const d = Math.floor(seconds / 86400);
        const h = Math.floor((seconds % 86400) / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (d > 0) return `${d}d ${h}h ${m}m ${s}s`;
        if (h > 0) return `${h}h ${m}m ${s}s`;
        return `${m}m ${s}s`;
    }

    function updateInfo(info) {
        renderCouncilInfo(info.normal_workers, info.normal_judge, normalWorkersEl, normalJudgeEl);
        renderCouncilInfo(info.advanced_workers, info.advanced_judge, advancedWorkersEl, advancedJudgeEl);

        serverStartTime = info.server_start_time;
        uptimeEl.textContent = formatUptime(info.uptime_seconds);
        routesEl.textContent = info.routes.join(', ');
        serverTimeEl.textContent = new Date(info.server_time * 1000).toLocaleString();

        setHealth(true);

        // Sync the swap panel dropdowns with current config
        syncSwapPanelToConfig(info);
    }

    function syncSwapPanelToConfig(info) {
        // Normal council
        setDropdownValue('swapNormalWorker0', info.normal_workers[0]?.model || '');
        setDropdownValue('swapNormalWorker1', info.normal_workers[1]?.model || '');
        setDropdownValue('swapNormalWorker2', info.normal_workers[2]?.model || '');
        setDropdownValue('swapNormalJudge', info.normal_judge?.model || '');
        const normalThinking = document.getElementById('swapNormalJudgeThinking');
        if (normalThinking) normalThinking.checked = info.normal_judge?.thinking || false;

        // Advanced council
        setDropdownValue('swapAdvancedWorker0', info.advanced_workers[0]?.model || '');
        setDropdownValue('swapAdvancedWorker1', info.advanced_workers[1]?.model || '');
        setDropdownValue('swapAdvancedWorker2', info.advanced_workers[2]?.model || '');
        setDropdownValue('swapAdvancedJudge', info.advanced_judge?.model || '');
        const advancedThinking = document.getElementById('swapAdvancedJudgeThinking');
        if (advancedThinking) advancedThinking.checked = info.advanced_judge?.thinking || false;
    }

    function setDropdownValue(id, value) {
        const el = document.getElementById(id);
        if (el) el.value = value;
    }

    // Populate all model dropdowns with grouped options
    function populateModelDropdowns(models) {
        const dropdownIds = [
            'swapNormalWorker0', 'swapNormalWorker1', 'swapNormalWorker2', 'swapNormalJudge',
            'swapAdvancedWorker0', 'swapAdvancedWorker1', 'swapAdvancedWorker2', 'swapAdvancedJudge'
        ];

        dropdownIds.forEach(id => {
            const select = document.getElementById(id);
            if (!select) return;
            const currentValue = select.value;
            select.innerHTML = '';

            // Collect all providers sorted
            const providers = Object.keys(models).sort();
            providers.forEach(provider => {
                const modelsList = models[provider];
                if (!modelsList || modelsList.length === 0) return;
                const optgroup = document.createElement('optgroup');
                optgroup.label = provider;
                modelsList.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    option.dataset.provider = provider;
                    optgroup.appendChild(option);
                });
                select.appendChild(optgroup);
            });

            // Restore previously selected value if possible
            if (currentValue) {
                try { select.value = currentValue; } catch (_) {}
            }
        });
    }

    // Fetch models from API and populate dropdowns
    async function loadModels() {
        try {
            const resp = await fetch('/api/models');
            if (!resp.ok) throw new Error('Failed to fetch models');
            const data = await resp.json();
            availableModels = data;
            populateModelDropdowns(data);
            // Now sync dropdowns to current config
            const infoResp = await fetch('/api/info');
            if (infoResp.ok) {
                const info = await infoResp.json();
                syncSwapPanelToConfig(info);
            }
            setSwapStatus('Models loaded', 'success');
        } catch (err) {
            console.error('Failed to load models:', err);
            setSwapStatus('Error loading models', 'error');
        }
    }

    function setSwapStatus(msg, type) {
        swapStatus.textContent = msg;
        swapStatus.className = 'swap-status ' + (type || '');
        setTimeout(() => {
            swapStatus.textContent = '';
            swapStatus.className = 'swap-status';
        }, 5000);
    }

    // Apply swap changes
    async function applySwap() {
        const swaps = [];
        const councils = ['normal', 'advanced'];

        councils.forEach(council => {
            const prefix = council === 'normal' ? 'swapNormal' : 'swapAdvanced';

            // Workers
            for (let i = 0; i < 3; i++) {
                const select = document.getElementById(`${prefix}Worker${i}`);
                if (!select) continue;
                const model = select.value;
                const selectedOption = select.options[select.selectedIndex];
                const provider = selectedOption ? selectedOption.dataset.provider : '';
                if (!model || !provider) continue;
                swaps.push({
                    council: council,
                    slot_type: 'worker',
                    slot_index: i,
                    provider: provider,
                    model: model,
                    thinking: false
                });
            }

            // Judge
            const judgeSelect = document.getElementById(`${prefix}Judge`);
            const thinkingCheck = document.getElementById(`${prefix}JudgeThinking`);
            if (judgeSelect) {
                const model = judgeSelect.value;
                const selectedOption = judgeSelect.options[judgeSelect.selectedIndex];
                const provider = selectedOption ? selectedOption.dataset.provider : '';
                const thinking = thinkingCheck ? thinkingCheck.checked : false;
                if (model && provider) {
                    swaps.push({
                        council: council,
                        slot_type: 'judge',
                        provider: provider,
                        model: model,
                        thinking: thinking
                    });
                }
            }
        });

        if (swaps.length === 0) {
            setSwapStatus('No changes to apply', 'warning');
            return;
        }

        applySwapBtn.disabled = true;
        applySwapBtn.textContent = 'Applying...';

        let successCount = 0;
        let errorCount = 0;

        for (const swap of swaps) {
            try {
                const resp = await fetch('/api/swap-models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(swap)
                });
                if (resp.ok) {
                    successCount++;
                } else {
                    const errData = await resp.json();
                    console.error('Swap error:', errData);
                    errorCount++;
                }
            } catch (err) {
                console.error('Swap request failed:', err);
                errorCount++;
            }
        }

        applySwapBtn.disabled = false;
        applySwapBtn.textContent = 'Apply Changes';

        if (errorCount === 0) {
            setSwapStatus(`✓ Applied ${successCount} change(s)`, 'success');
        } else {
            setSwapStatus(`Applied ${successCount}, ${errorCount} error(s)`, 'error');
        }

        // Refresh info to show new config
        await loadInfo();
    }

    // Reset to defaults
    async function resetSwap() {
        resetSwapBtn.disabled = true;
        resetSwapBtn.textContent = 'Resetting...';

        try {
            const resp = await fetch('/api/reset-models', { method: 'POST' });
            if (resp.ok) {
                setSwapStatus('✓ Reset to defaults', 'success');
                await loadInfo();
                // Reload models dropdowns to match
                await loadModels();
            } else {
                const errData = await resp.json();
                setSwapStatus('Reset failed: ' + (errData.detail || 'Unknown'), 'error');
            }
        } catch (err) {
            setSwapStatus('Reset error: ' + err.message, 'error');
        } finally {
            resetSwapBtn.disabled = false;
            resetSwapBtn.textContent = 'Reset to Defaults';
        }
    }

    // Fetch info from API
    async function loadInfo() {
        try {
            const resp = await fetch('/api/info');
            if (!resp.ok) throw new Error('API returned ' + resp.status);
            const info = await resp.json();
            updateInfo(info);
        } catch (err) {
            console.error('Failed to fetch /api/info:', err);
            setHealth(false);
            healthText.textContent = 'Error';
        }
    }

    // Refresh uptime periodically
    function updateUptime() {
        if (serverStartTime) {
            const elapsed = Math.floor((Date.now() / 1000) - serverStartTime);
            uptimeEl.textContent = formatUptime(elapsed);
        }
    }

    // Send test query
    async function sendQuery() {
        const council = councilSelect.value;
        const message = messageInput.value.trim();
        if (!message) return;

        sendBtn.disabled = true;
        sendBtn.textContent = 'Sending...';
        responseArea.innerHTML = '<p class=\"loading\">⟳ Processing...</p>';

        const endpoint = council === 'advanced' ? '/v1/advanced' : '/v1/normal';

        try {
            const resp = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [{ role: 'user', content: message }],
                    system_prompt: 'You are a helpful assistant.',
                    max_tokens: 128000,
                    temperature: 0.7
                })
            });

            if (!resp.ok) {
                const errData = await resp.json();
                throw new Error(errData.detail || `HTTP ${resp.status}`);
            }

            const data = await resp.json();
            responseArea.innerHTML = `<p><strong>Response (${data.model_used}):</strong></p><p>${data.content}</p>`;
        } catch (err) {
            responseArea.innerHTML = `<p class=\"error\">Error: ${err.message}</p>`;
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = 'Send';
        }
    }

    // Event listeners
    sendBtn.addEventListener('click', sendQuery);
    messageInput.addEventListener('keypress', e => {
        if (e.key === 'Enter') sendQuery();
    });

    if (refreshModelsBtn) refreshModelsBtn.addEventListener('click', loadModels);
    if (applySwapBtn) applySwapBtn.addEventListener('click', applySwap);
    if (resetSwapBtn) resetSwapBtn.addEventListener('click', resetSwap);

    // Initial load
    loadInfo();
    loadModels();  // Will also sync dropdowns
    setInterval(updateUptime, 1000);
});