import asyncio
import collections
import os
import sys
from loguru import logger

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

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
            <div class="form-group">
                <label>Cookies</label>
                <textarea id="cfg-cookies" placeholder="浏览器 F12 获取的 Cookie 字符串"></textarea>
                <p style="margin-top:8px; font-size:12px; color:#888;">获取方式：打开 <a href="https://www.goofish.com" target="_blank" style="color:#4ecca3;">闲鱼网页版</a> 登录成功后，点到消息页面，按 F12 打开开发者工具，在 Network 面板中任选一个请求，复制 Request Headers 中的 Cookie 值粘贴到此处</p>
            </div>
            <button class="save-btn" onclick="saveConfig()">保存配置</button>
        </div>
    </div>
    <div class="toast" id="toast"></div>
    <script>
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
            const ws = new WebSocket(`${protocol}//${location.host}/ws/logs`);
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
                const res = await fetch('/api/config');
                const data = await res.json();
                document.getElementById('cfg-api-key').value = data.API_KEY || '';
                document.getElementById('cfg-base-url').value = data.MODEL_BASE_URL || '';
                document.getElementById('cfg-model-name').value = data.MODEL_NAME || '';
                document.getElementById('cfg-cookies').value = data.COOKIES_STR || '';
            } catch(e) { showToast('加载配置失败', 'error'); }
        }

        async function saveConfig() {
            const btn = document.querySelector('.save-btn');
            btn.disabled = true;
            try {
                const body = {
                    API_KEY: document.getElementById('cfg-api-key').value,
                    MODEL_BASE_URL: document.getElementById('cfg-base-url').value,
                    MODEL_NAME: document.getElementById('cfg-model-name').value,
                    COOKIES_STR: document.getElementById('cfg-cookies').value
                };
                const res = await fetch('/api/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
                if (res.ok) {
                    showToast('配置已保存', 'success');
                    if (confirm('配置已保存，是否立即重启服务使配置生效？')) {
                        await fetch('/api/restart', { method: 'POST' });
                    }
                }
                else showToast('保存失败', 'error');
            } catch(e) { showToast('保存失败: ' + e.message, 'error'); }
            finally { btn.disabled = false; }
        }

        function showToast(msg, type) {
            const t = document.getElementById('toast');
            t.textContent = msg; t.className = 'toast show ' + type;
            setTimeout(() => t.className = 'toast', 3000);
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


def _restart_process():
    """重启当前进程，使新配置生效"""
    logger.info("配置已更新，正在重启服务...")
    os._exit(0)


def create_app():
    if not HAS_FASTAPI:
        return None

    app = FastAPI()

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

    @app.websocket("/ws/logs")
    async def websocket_logs(websocket: WebSocket):
        await websocket.accept()
        # 发送历史日志
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
