import asyncio
import collections
from loguru import logger

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>XianyuAutoAgent 日志</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            color: #e0e0e0;
            font-family: 'Courier New', monospace;
            font-size: 13px;
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
    </style>
</head>
<body>
    <header>
        <h1>XianyuAutoAgent 日志监控</h1>
        <span id="status">未连接</span>
    </header>
    <div id="log-container"></div>
    <script>
        const logContainer = document.getElementById('log-container');
        const status = document.getElementById('status');
        let autoScroll = true;

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

            ws.onopen = () => {
                status.textContent = '已连接';
                status.className = 'connected';
            };

            ws.onmessage = (event) => {
                const div = document.createElement('div');
                div.className = 'log-line';
                div.innerHTML = colorize(event.data);
                logContainer.appendChild(div);
                while (logContainer.children.length > 2000) {
                    logContainer.removeChild(logContainer.firstChild);
                }
                if (autoScroll) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            };

            ws.onclose = () => {
                status.textContent = '已断开 (重连中...)';
                status.className = '';
                setTimeout(connect, 3000);
            };
            ws.onerror = () => ws.close();
        }
        connect();
    </script>
</body>
</html>
"""

# 日志缓冲区，保留最近 200 条供新连接回放
log_buffer = collections.deque(maxlen=200)
clients: list = []


def create_app():
    if not HAS_FASTAPI:
        return None

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTML_PAGE

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
