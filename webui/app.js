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

    let serverStartTime = null;

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
        // Council configs
        renderCouncilInfo(info.normal_workers, info.normal_judge, normalWorkersEl, normalJudgeEl);
        renderCouncilInfo(info.advanced_workers, info.advanced_judge, advancedWorkersEl, advancedJudgeEl);

        // Server info
        serverStartTime = info.server_start_time;
        uptimeEl.textContent = formatUptime(info.uptime_seconds);
        routesEl.textContent = info.routes.join(', ');
        serverTimeEl.textContent = new Date(info.server_time * 1000).toLocaleString();

        setHealth(true);
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

    // Initial load
    loadInfo();
    setInterval(updateUptime, 1000);
});