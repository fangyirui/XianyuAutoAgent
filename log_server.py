import asyncio
import collections
import os
import secrets
import sys
import requests
from loguru import logger

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 认证 token 存储（内存，重启失效）
_active_tokens: set = set()

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - XianyuAutoAgent</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-box {
            background: #16213e;
            padding: 40px;
            border-radius: 12px;
            border: 1px solid #0f3460;
            width: 360px;
        }
        .login-box h2 { color: #4ecca3; margin-bottom: 24px; font-size: 18px; text-align: center; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; margin-bottom: 6px; color: #4ecca3; font-size: 13px; }
        .form-group input {
            width: 100%;
            padding: 10px 12px;
            background: #0f3460;
            border: 1px solid #1a4a7a;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
        }
        .form-group input:focus { outline: none; border-color: #4ecca3; }
        .login-btn {
            width: 100%;
            padding: 12px;
            background: #4ecca3;
            color: #1a1a2e;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 8px;
        }
        .login-btn:hover { opacity: 0.85; }
        .login-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .error-msg { color: #e94560; font-size: 13px; margin-top: 12px; text-align: center; display: none; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>XianyuAutoAgent</h2>
        <form onsubmit="doLogin(event)">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="username" autocomplete="username" required>
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="password" autocomplete="current-password" required>
            </div>
            <button type="submit" class="login-btn" id="login-btn">登录</button>
        </form>
        <div class="error-msg" id="error-msg"></div>
    </div>
    <script>
        if (localStorage.getItem('auth_token')) {
            window.location.href = '/';
        }
        async function doLogin(e) {
            e.preventDefault();
            const btn = document.getElementById('login-btn');
            const errEl = document.getElementById('error-msg');
            btn.disabled = true;
            errEl.style.display = 'none';
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username: document.getElementById('username').value,
                        password: document.getElementById('password').value
                    })
                });
                const data = await res.json();
                if (data.token) {
                    localStorage.setItem('auth_token', data.token);
                    window.location.href = '/';
                } else {
                    errEl.textContent = data.error || '登录失败';
                    errEl.style.display = 'block';
                }
            } catch(err) {
                errEl.textContent = '网络错误';
                errEl.style.display = 'block';
            }
            btn.disabled = false;
        }
    </script>
</body>
</html>
"""

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>XianyuAutoAgent</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            color: #e0e0e0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 14px;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        header {
            background: #16213e;
            padding: 12px 20px;
            border-bottom: 1px solid #0f3460;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        header h1 { font-size: 16px; color: #4ecca3; }
        .tabs {
            display: flex;
            gap: 4px;
            background: #16213e;
            padding: 0 20px;
            border-bottom: 1px solid #0f3460;
        }
        .tab-btn {
            padding: 10px 20px;
            background: transparent;
            border: none;
            color: #888;
            cursor: pointer;
            font-size: 14px;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        .tab-btn:hover { color: #e0e0e0; }
        .tab-btn.active { color: #4ecca3; border-bottom-color: #4ecca3; }
        .tab-content { display: none; flex: 1; overflow: hidden; }
        .tab-content.active { display: flex; flex-direction: column; }
        #status {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            background: #e94560;
            color: white;
        }
        #status.connected { background: #4ecca3; color: #1a1a2e; }
        #log-container {
            flex: 1;
            overflow-y: auto;
            padding: 12px 20px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }
        .log-line {
            padding: 2px 0;
            white-space: pre-wrap;
            word-break: break-all;
            line-height: 1.5;
        }
        .log-line .time { color: #4ecca3; }
        .log-line .error { color: #e94560; }
        .log-line .warning { color: #f0a500; }
        .log-line .info { color: #4ecca3; }
        .config-panel {
            flex: 1;
            overflow-y: auto;
            padding: 30px 20px;
            max-width: 600px;
            margin: 0 auto;
            width: 100%;
        }
        .form-group { margin-bottom: 20px; }
        .form-group label {
            display: block;
            margin-bottom: 6px;
            color: #4ecca3;
            font-size: 13px;
            font-weight: 500;
        }
        .form-group input, .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            background: #0f3460;
            border: 1px solid #1a4a7a;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
            font-family: 'Courier New', monospace;
            transition: border-color 0.2s;
        }
        .form-group input:focus, .form-group textarea:focus {
            outline: none;
            border-color: #4ecca3;
        }
        .form-group textarea { resize: vertical; min-height: 80px; }
        .input-wrapper {
            position: relative;
            display: flex;
            align-items: center;
        }
        .input-wrapper input { padding-right: 40px; }
        .toggle-vis {
            position: absolute;
            right: 10px;
            background: none;
            border: none;
            color: #888;
            cursor: pointer;
            font-size: 16px;
        }
        .toggle-vis:hover { color: #4ecca3; }
        .save-btn {
            padding: 10px 24px;
            background: #4ecca3;
            color: #1a1a2e;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .save-btn:hover { opacity: 0.85; }
        .save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .qr-section {
            margin-bottom: 24px;
            padding: 20px;
            background: #16213e;
            border-radius: 8px;
            border: 1px solid #0f3460;
            text-align: center;
        }
        .qr-section h3 { color: #4ecca3; margin-bottom: 12px; font-size: 14px; }
        .qr-btn {
            padding: 10px 24px;
            background: #4ecca3;
            color: #1a1a2e;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .qr-btn:hover { opacity: 0.85; }
        .qr-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .qr-container { display: none; margin-top: 16px; }
        .qr-container img { width: 200px; height: 200px; border-radius: 8px; background: white; padding: 8px; }
        .qr-status { margin-top: 10px; font-size: 13px; color: #888; }
        .qr-status.scaned { color: #f0a500; }
        .qr-status.confirmed { color: #4ecca3; }
        .qr-status.expired { color: #e94560; }
        .divider { display: flex; align-items: center; margin: 20px 0; color: #555; font-size: 12px; }
        .divider::before, .divider::after { content: ''; flex: 1; border-top: 1px solid #0f3460; }
        .divider span { padding: 0 12px; }
        .sub-tabs {
            display: flex;
            gap: 0;
            padding: 0 20px;
            border-bottom: 1px solid #0f3460;
            background: #16213e;
        }
        .sub-tab-btn {
            padding: 10px 20px;
            background: transparent;
            border: none;
            color: #888;
            cursor: pointer;
            font-size: 13px;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        .sub-tab-btn:hover { color: #e0e0e0; }
        .sub-tab-btn.active { color: #4ecca3; border-bottom-color: #4ecca3; }
        .sub-tab-content { display: none; flex: 1; overflow-y: auto; }
        .sub-tab-content.active { display: block; }
        .toast {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            border-radius: 6px;
            font-size: 13px;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s;
        }
        .toast.show { opacity: 1; }
        .toast.success { background: #4ecca3; color: #1a1a2e; }
        .toast.error { background: #e94560; color: white; }
    </style>
</head>
<body>
    <header>
        <h1>XianyuAutoAgent</h1>
        <span id="status">未连接</span>
    </header>
    <div class="tabs">
        <button class="tab-btn active" data-tab="logs">日志</button>
        <button class="tab-btn" data-tab="config">配置</button>
    </div>
    <div id="tab-logs" class="tab-content active">
        <div id="log-container"></div>
    </div>
    <div id="tab-config" class="tab-content">
        <div class="sub-tabs">
            <button class="sub-tab-btn active" data-subtab="cookie">Cookie 设置</button>
            <button class="sub-tab-btn" data-subtab="ai">AI 设置</button>
            <button class="sub-tab-btn" data-subtab="prompts">提示词</button>
        </div>
        <div id="subtab-cookie" class="sub-tab-content active">
            <div class="config-panel">
                <div class="qr-section">
                    <h3>扫码登录</h3>
                    <p style="font-size:12px; color:#888; margin-bottom:12px;">使用淘宝/闲鱼 App 扫码，自动获取 Cookie</p>
                    <button class="qr-btn" id="qr-start-btn" onclick="startQrLogin()">获取二维码</button>
                    <div class="qr-container" id="qr-container">
                        <img id="qr-img" src="" alt="二维码">
                        <div class="qr-status" id="qr-status">等待扫码...</div>
                    </div>
                </div>
                <div class="divider"><span>或手动填写 Cookie</span></div>
                <div class="form-group">
                    <label>Cookies</label>
                    <textarea id="cfg-cookies" placeholder="浏览器 F12 获取的 Cookie 字符串"></textarea>
                    <p style="margin-top:8px; font-size:12px; color:#888;">获取方式：打开 <a href="https://www.goofish.com" target="_blank" style="color:#4ecca3;">闲鱼网页版</a> 登录成功后，点到消息页面，按 F12 打开开发者工具，在 Network 面板中任选一个请求，复制 Request Headers 中的 Cookie 值粘贴到此处</p>
                </div>
                <button class="save-btn" onclick="saveCookieConfig()">保存 Cookie</button>
            </div>
        </div>
        <div id="subtab-ai" class="sub-tab-content">
            <div class="config-panel">
                <div class="form-group">
                    <label>API Key</label>
                    <div class="input-wrapper">
                        <input type="password" id="cfg-api-key" placeholder="输入 API Key">
                        <button class="toggle-vis" onclick="toggleVis('cfg-api-key')">&#128065;</button>
                    </div>
                </div>
                <div class="form-group">
                    <label>Model Base URL</label>
                    <input type="text" id="cfg-base-url" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1">
                </div>
                <div class="form-group">
                    <label>Model Name</label>
                    <input type="text" id="cfg-model-name" placeholder="qwen-max">
                </div>
                <div style="display:flex; gap:10px;">
                    <button class="save-btn" onclick="saveAiConfig()">保存 AI 配置</button>
                    <button class="save-btn" style="background:#0f3460; color:#4ecca3; border:1px solid #4ecca3;" onclick="testAiConnection()">测试连接</button>
                </div>
                <div id="test-result" style="margin-top:12px; font-size:13px; display:none;"></div>
            </div>
        </div>
        <div id="subtab-prompts" class="sub-tab-content">
            <div class="config-panel">
                <div class="form-group">
                    <label>意图分类提示词 (classify)</label>
                    <textarea id="cfg-prompt-classify" rows="6" placeholder="意图分类提示词"></textarea>
                </div>
                <div class="form-group">
                    <label>通用回复提示词 (default)</label>
                    <textarea id="cfg-prompt-default" rows="6" placeholder="通用客服回复提示词"></textarea>
                </div>
                <div class="form-group">
                    <label>议价提示词 (price)</label>
                    <textarea id="cfg-prompt-price" rows="6" placeholder="议价策略提示词"></textarea>
                </div>
                <div class="form-group">
                    <label>技术咨询提示词 (tech)</label>
                    <textarea id="cfg-prompt-tech" rows="6" placeholder="技术支持提示词"></textarea>
                </div>
                <button class="save-btn" onclick="savePrompts()">保存提示词</button>
            </div>
        </div>
    </div>
    <div class="toast" id="toast"></div>
    <script>
        const AUTH_TOKEN = localStorage.getItem('auth_token');
        if (!AUTH_TOKEN) { window.location.href = '/login'; }

        function authHeaders(extra = {}) {
            return { 'Authorization': 'Bearer ' + AUTH_TOKEN, ...extra };
        }
        async function authFetch(url, opts = {}) {
            opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
            const res = await fetch(url, opts);
            if (res.status === 401) { localStorage.removeItem('auth_token'); window.location.href = '/login'; }
            return res;
        }

        const logContainer = document.getElementById('log-container');
        const status = document.getElementById('status');
        let autoScroll = true;

        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
                if (btn.dataset.tab === 'config') loadConfig();
            });
        });

        // Sub-tab switching
        document.querySelectorAll('.sub-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.sub-tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('subtab-' + btn.dataset.subtab).classList.add('active');
                if (btn.dataset.subtab === 'prompts') loadPrompts();
            });
        });

        logContainer.addEventListener('scroll', () => {
            const { scrollTop, scrollHeight, clientHeight } = logContainer;
            autoScroll = scrollHeight - scrollTop - clientHeight < 50;
        });

        function colorize(text) {
            text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            text = text.replace(/(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d+)/g, '<span class="time">$1</span>');
            text = text.replace(/(ERROR\\s*)/gi, '<span class="error">$1</span>');
            text = text.replace(/(WARNING\\s*)/gi, '<span class="warning">$1</span>');
            text = text.replace(/(INFO\\s*)/gi, '<span class="info">$1</span>');
            return text;
        }

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//${location.host}/ws/logs?token=${AUTH_TOKEN}`);
            ws.onopen = () => { status.textContent = '已连接'; status.className = 'connected'; };
            ws.onmessage = (event) => {
                const div = document.createElement('div');
                div.className = 'log-line';
                div.innerHTML = colorize(event.data);
                logContainer.appendChild(div);
                while (logContainer.children.length > 2000) logContainer.removeChild(logContainer.firstChild);
                if (autoScroll) logContainer.scrollTop = logContainer.scrollHeight;
            };
            ws.onclose = () => { status.textContent = '已断开 (重连中...)'; status.className = ''; setTimeout(connect, 3000); };
            ws.onerror = () => ws.close();
        }
        connect();

        function toggleVis(id) {
            const input = document.getElementById(id);
            input.type = input.type === 'password' ? 'text' : 'password';
        }

        async function loadConfig() {
            try {
                const res = await authFetch('/api/config');
                const data = await res.json();
                document.getElementById('cfg-api-key').value = data.API_KEY || '';
                document.getElementById('cfg-base-url').value = data.MODEL_BASE_URL || '';
                document.getElementById('cfg-model-name').value = data.MODEL_NAME || '';
                document.getElementById('cfg-cookies').value = data.COOKIES_STR || '';
            } catch(e) { showToast('加载配置失败', 'error'); }
        }

        async function saveCookieConfig() {
            const btn = document.querySelector('#subtab-cookie .save-btn');
            btn.disabled = true;
            try {
                const body = { COOKIES_STR: document.getElementById('cfg-cookies').value };
                const res = await authFetch('/api/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
                if (res.ok) {
                    showToast('Cookie 已保存', 'success');
                    if (confirm('Cookie 已保存，是否立即重启服务使配置生效？')) {
                        await authFetch('/api/restart', { method: 'POST' });
                    }
                } else showToast('保存失败', 'error');
            } catch(e) { showToast('保存失败: ' + e.message, 'error'); }
            finally { btn.disabled = false; }
        }

        async function saveAiConfig() {
            const btn = document.querySelector('#subtab-ai .save-btn');
            btn.disabled = true;
            try {
                const body = {
                    API_KEY: document.getElementById('cfg-api-key').value,
                    MODEL_BASE_URL: document.getElementById('cfg-base-url').value,
                    MODEL_NAME: document.getElementById('cfg-model-name').value
                };
                const res = await authFetch('/api/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
                if (res.ok) {
                    showToast('AI 配置已保存', 'success');
                    if (confirm('AI 配置已保存，是否立即重启服务使配置生效？')) {
                        await authFetch('/api/restart', { method: 'POST' });
                    }
                } else showToast('保存失败', 'error');
            } catch(e) { showToast('保存失败: ' + e.message, 'error'); }
            finally { btn.disabled = false; }
        }

        async function testAiConnection() {
            const resultEl = document.getElementById('test-result');
            resultEl.style.display = 'block';
            resultEl.style.color = '#888';
            resultEl.textContent = '正在测试连接...';
            try {
                const body = {
                    api_key: document.getElementById('cfg-api-key').value,
                    base_url: document.getElementById('cfg-base-url').value,
                    model: document.getElementById('cfg-model-name').value
                };
                const res = await authFetch('/api/ai/test', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
                const data = await res.json();
                if (data.success) {
                    resultEl.style.color = '#4ecca3';
                    resultEl.textContent = '连接成功: ' + (data.message || 'AI 模型响应正常');
                } else {
                    resultEl.style.color = '#e94560';
                    resultEl.textContent = '连接失败: ' + (data.error || '未知错误');
                }
            } catch(e) {
                resultEl.style.color = '#e94560';
                resultEl.textContent = '测试失败: ' + e.message;
            }
        }

        async function loadPrompts() {
            try {
                const res = await authFetch('/api/prompts');
                const data = await res.json();
                document.getElementById('cfg-prompt-classify').value = data.classify || '';
                document.getElementById('cfg-prompt-default').value = data.default || '';
                document.getElementById('cfg-prompt-price').value = data.price || '';
                document.getElementById('cfg-prompt-tech').value = data.tech || '';
            } catch(e) { showToast('加载提示词失败', 'error'); }
        }

        async function savePrompts() {
            const btn = document.querySelector('#subtab-prompts .save-btn');
            btn.disabled = true;
            try {
                const body = {
                    classify: document.getElementById('cfg-prompt-classify').value,
                    default: document.getElementById('cfg-prompt-default').value,
                    price: document.getElementById('cfg-prompt-price').value,
                    tech: document.getElementById('cfg-prompt-tech').value
                };
                const res = await authFetch('/api/prompts', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
                if (res.ok) {
                    showToast('提示词已保存', 'success');
                    if (confirm('提示词已保存，是否立即重启服务使配置生效？')) {
                        await authFetch('/api/restart', { method: 'POST' });
                    }
                } else showToast('保存失败', 'error');
            } catch(e) { showToast('保存失败: ' + e.message, 'error'); }
            finally { btn.disabled = false; }
        }

        function showToast(msg, type) {
            const t = document.getElementById('toast');
            t.textContent = msg; t.className = 'toast show ' + type;
            setTimeout(() => t.className = 'toast', 3000);
        }

        let qrPollingTimer = null;
        async function startQrLogin() {
            const btn = document.getElementById('qr-start-btn');
            const container = document.getElementById('qr-container');
            const img = document.getElementById('qr-img');
            const statusEl = document.getElementById('qr-status');
            btn.disabled = true;
            btn.textContent = '获取中...';
            try {
                const res = await authFetch('/api/qrlogin/start', { method: 'POST' });
                const data = await res.json();
                if (data.error) { showToast(data.error, 'error'); btn.disabled = false; btn.textContent = '获取二维码'; return; }
                container.style.display = 'block';
                img.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.codeContent)}`;
                statusEl.textContent = '等待扫码...';
                statusEl.className = 'qr-status';
                btn.textContent = '刷新二维码';
                btn.disabled = false;
                if (qrPollingTimer) clearInterval(qrPollingTimer);
                qrPollingTimer = setInterval(() => pollQrStatus(data.t), 2000);
            } catch(e) { showToast('获取二维码失败: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '获取二维码'; }
        }

        async function pollQrStatus(t) {
            const statusEl = document.getElementById('qr-status');
            try {
                const res = await authFetch(`/api/qrlogin/status?t=${encodeURIComponent(t)}`);
                const data = await res.json();
                if (data.status === 'CONFIRMED') {
                    clearInterval(qrPollingTimer);
                    statusEl.textContent = '登录成功，正在重启服务...';
                    statusEl.className = 'qr-status confirmed';
                    document.getElementById('qr-start-btn').disabled = true;
                } else if (data.status === 'SCANED') {
                    statusEl.textContent = '已扫码，请在手机上确认';
                    statusEl.className = 'qr-status scaned';
                } else if (data.status === 'EXPIRED') {
                    clearInterval(qrPollingTimer);
                    statusEl.textContent = '二维码已过期，请点击刷新';
                    statusEl.className = 'qr-status expired';
                }
            } catch(e) {}
        }

    </script>
</body>
</html>
"""

def _read_env() -> dict:
    """读取 .env 文件为 dict"""
    config = {}
    if not os.path.exists(ENV_PATH):
        return config
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


def _write_env(updates: dict):
    """更新 .env 文件中的指定键值，保留其他行不变"""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    existing_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                existing_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# 日志缓冲区，保留最近 200 条供新连接回放
log_buffer = collections.deque(maxlen=200)
clients: list = []

# QR 登录 session 缓存（generate 和 query 需要同一个 session）
_qr_sessions: dict = {}


def _restart_process():
    """重启当前进程，使新配置生效"""
    logger.info("配置已更新，正在重启服务...")
    os._exit(0)


def create_app():
    if not HAS_FASTAPI:
        return None

    app = FastAPI()

    # 认证中间件：只保护 /api/ 路径
    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if not path.startswith('/api/') or path == '/api/login':
                return await call_next(request)
            if path.startswith('/ws/'):
                return await call_next(request)
            auth = request.headers.get('Authorization', '')
            token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
            if not token or token not in _active_tokens:
                return JSONResponse({"error": "未登录"}, status_code=401)
            return await call_next(request)

    app.add_middleware(AuthMiddleware)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        return LOGIN_PAGE

    @app.post("/api/login")
    async def do_login(request: Request):
        body = await request.json()
        username = body.get('username', '')
        password = body.get('password', '')
        config = _read_env()
        expected_user = config.get('WEB_USERNAME', 'admin')
        expected_pass = config.get('WEB_PASSWORD', 'admin123')
        if username == expected_user and password == expected_pass:
            token = secrets.token_hex(32)
            _active_tokens.add(token)
            return JSONResponse({"token": token})
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTML_PAGE

    @app.get("/api/config")
    async def get_config():
        config = _read_env()
        display_keys = ["API_KEY", "MODEL_BASE_URL", "MODEL_NAME", "COOKIES_STR"]
        result = {}
        for key in display_keys:
            val = config.get(key, "")
            if key == "API_KEY" and len(val) > 4:
                result[key] = val[:4] + "***"
            else:
                result[key] = val
        return JSONResponse(result)

    @app.post("/api/config")
    async def save_config(request: Request):
        body = await request.json()
        allowed = {"API_KEY", "MODEL_BASE_URL", "MODEL_NAME", "COOKIES_STR"}
        updates = {}
        for key in allowed:
            if key in body:
                val = body[key]
                if key == "API_KEY" and val.endswith("***"):
                    continue
                updates[key] = val
        if updates:
            _write_env(updates)
        return JSONResponse({"message": "配置已保存"})

    @app.post("/api/restart")
    async def restart_service():
        asyncio.get_event_loop().call_later(1, _restart_process)
        return JSONResponse({"message": "服务正在重启"})

    @app.get("/api/prompts")
    async def get_prompts():
        import json as _json
        prompts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "prompt.json")
        try:
            with open(prompts_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            return JSONResponse(data)
        except Exception:
            return JSONResponse({"classify": "", "default": "", "price": "", "tech": ""})

    @app.post("/api/prompts")
    async def save_prompts(request: Request):
        import json as _json
        body = await request.json()
        prompts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "prompt.json")
        allowed = {"classify", "default", "price", "tech"}
        data = {k: body.get(k, "") for k in allowed}
        try:
            with open(prompts_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
            return JSONResponse({"message": "提示词已保存"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/qrlogin/start")
    async def qrlogin_start():
        try:
            session = requests.Session()
            session.headers.update({
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            })
            session.get('https://passport.goofish.com/mini_login.htm', params={
                'lang': 'zh_cn', 'appName': 'xianyu', 'appEntrance': 'web',
                'styleType': 'auto', 'bizParams': '', 'isMobile': 'false',
                'returnUrl': 'https://www.goofish.com/', 'fromSite': '77',
            })
            session.headers.update({
                'origin': 'https://passport.goofish.com',
                'referer': 'https://passport.goofish.com/mini_login.htm',
            })
            url = 'https://passport.goofish.com/newlogin/qrcode/generate.do'
            params = {'appName': 'xianyu', 'fromSite': '77'}
            data = {
                'appName': 'xianyu',
                'appEntrance': 'web',
                'isMobile': 'false',
                'lang': 'zh_CN',
                'returnUrl': 'https://www.goofish.com/',
                'fromSite': '77',
                'bizParams': '',
                'mainPage': 'false',
                'isIframe': 'true',
                'documentReferer': 'https://www.goofish.com/',
                'defaultView': 'qrcode',
                'umidTag': 'SERVER',
                'navlanguage': 'zh-CN',
                'navPlatform': 'Win32',
            }
            response = session.post(url, params=params, data=data)
            res_json = response.json()
            content_data = res_json.get('content', {}).get('data', {})
            if not content_data:
                return JSONResponse({"error": "获取二维码失败"}, status_code=500)
            t = str(content_data.get('t', ''))
            ck = content_data.get('ck', '')
            _qr_sessions[t] = {'session': session, 'ck': ck}
            return JSONResponse({
                "codeContent": content_data.get('codeContent', ''),
                "t": t,
            })
        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/qrlogin/status")
    async def qrlogin_status(t: str):
        try:
            qr_data = _qr_sessions.get(t)
            if not qr_data:
                return JSONResponse({"error": "会话已过期，请重新获取二维码"}, status_code=400)
            session = qr_data['session']
            ck = qr_data['ck']
            url = 'https://passport.goofish.com/newlogin/qrcode/query.do'
            params = {'appName': 'xianyu', 'fromSite': '77'}
            data = {
                't': t,
                'ck': ck,
                'appName': 'xianyu',
                'appEntrance': 'web',
                'isMobile': 'false',
                'lang': 'zh_CN',
                'returnUrl': 'https://www.goofish.com/',
                'fromSite': '77',
                'bizParams': '',
                'mainPage': 'false',
                'isIframe': 'true',
                'documentReferer': 'https://www.goofish.com/',
                'defaultView': 'qrcode',
                'umidTag': 'SERVER',
                'navlanguage': 'zh-CN',
                'navPlatform': 'Win32',
            }
            response = session.post(url, params=params, data=data)
            res_json = response.json()
            content_data = res_json.get('content', {}).get('data', {})
            qr_status = content_data.get('qrCodeStatus', '')

            if qr_status == 'CONFIRMED':
                # 从 cookieList 提取（这是最完整的来源）
                all_cookies = {}
                if content_data.get('cookieList'):
                    for item in content_data['cookieList']:
                        all_cookies[item['name']] = item['value']
                # 补充 response.cookies
                for c in response.cookies:
                    if c.name not in all_cookies:
                        all_cookies[c.name] = c.value
                # 补充 session 中已有的 cookie
                for c in session.cookies:
                    if c.name not in all_cookies:
                        all_cookies[c.name] = c.value

                # 用合并后的 cookie 调用一次 H5 API 获取 _m_h5_tk
                try:
                    import time as _time
                    from utils.xianyu_utils import generate_sign
                    h5_session = requests.Session()
                    h5_session.headers.update({
                        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                        'origin': 'https://www.goofish.com',
                        'referer': 'https://www.goofish.com/',
                    })
                    for k, v in all_cookies.items():
                        h5_session.cookies.set(k, v, domain='.goofish.com')
                    ts = str(int(_time.time()) * 1000)
                    data_val = '{"itemId":"0"}'
                    sign = generate_sign(ts, '', data_val)
                    h5_params = {
                        'jsv': '2.7.2', 'appKey': '34839810', 't': ts,
                        'sign': sign, 'v': '1.0', 'type': 'originaljson',
                        'accountSite': 'xianyu', 'dataType': 'json',
                        'timeout': '20000', 'api': 'mtop.taobao.idle.pc.detail',
                        'sessionOption': 'AutoLoginOnly',
                    }
                    h5_resp = h5_session.post(
                        'https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/',
                        params=h5_params, data={'data': data_val}
                    )
                    for c in h5_session.cookies:
                        all_cookies[c.name] = c.value
                except Exception as e:
                    logger.warning(f"获取 _m_h5_tk 失败: {e}")

                cookie_str = '; '.join([f"{k}={v}" for k, v in all_cookies.items()])
                if cookie_str:
                    _write_env({"COOKIES_STR": cookie_str})
                    logger.info(f"扫码登录成功，Cookie 已保存 ({len(all_cookies)} 项)")
                    asyncio.get_event_loop().call_later(2, _restart_process)
                _qr_sessions.pop(t, None)
                return JSONResponse({"status": "CONFIRMED"})
            elif qr_status == 'SCANED':
                return JSONResponse({"status": "SCANED"})
            elif qr_status == 'EXPIRED':
                _qr_sessions.pop(t, None)
                return JSONResponse({"status": "EXPIRED"})
            else:
                return JSONResponse({"status": "NEW"})
        except Exception as e:
            logger.error(f"查询扫码状态失败: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/ai/test")
    async def test_ai_connection(request: Request):
        body = await request.json()
        api_key = body.get('api_key', '')
        base_url = body.get('base_url', '')
        model = body.get('model', '')
        if api_key.endswith('***'):
            config = _read_env()
            api_key = config.get('API_KEY', '')
        if not api_key or not base_url or not model:
            return JSONResponse({"success": False, "error": "请填写完整的 API Key、Base URL 和模型名称"})
        try:
            import openai
            loop = asyncio.get_event_loop()
            def _call_ai():
                client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=15)
                return client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "你好，请回复ok"}],
                    max_tokens=10
                )
            response = await loop.run_in_executor(None, _call_ai)
            reply = response.choices[0].message.content.strip() if response.choices else ''
            return JSONResponse({"success": True, "message": f"模型回复: {reply}"})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    @app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        token = websocket.query_params.get('token', '')
        if not token or token not in _active_tokens:
            await websocket.close(code=4001, reason="Unauthorized")
            return
        await websocket.accept()
        for line in log_buffer:
            await websocket.send_text(line)
        clients.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            clients.remove(websocket)

    return app


def log_sink(message):
    """loguru sink：将日志写入缓冲区并推送给 WebSocket 客户端"""
    text = message.rstrip("\n")
    log_buffer.append(text)
    disconnected = []
    for client in clients:
        try:
            asyncio.get_event_loop().create_task(client.send_text(text))
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        clients.remove(client)


async def start_web_server(port: int = 9966):
    """启动 Web 日志服务"""
    if not HAS_FASTAPI:
        logger.warning("fastapi/uvicorn 未安装，日志页面不可用。pip install fastapi uvicorn 即可启用")
        return

    app = create_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"日志监控页面已启动: http://0.0.0.0:{port}")
    await server.serve()
