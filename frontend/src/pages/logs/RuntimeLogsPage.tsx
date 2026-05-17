import { useEffect, useRef, useState } from 'react'
import { ScrollText, Pause, Play, Trash2, Search } from 'lucide-react'

interface LogEntry { time: string; level: string; message: string; module: string }

const LEVEL_COLORS: Record<string, string> = {
  ERROR: 'text-red-400',
  WARNING: 'text-amber-400',
  INFO: 'text-gray-200',
  DEBUG: 'text-dark-400',
}

const LEVEL_BG: Record<string, string> = {
  ERROR: 'bg-red-500/15 text-red-300',
  WARNING: 'bg-amber-500/15 text-amber-300',
  INFO: 'bg-primary-500/15 text-primary-300',
  DEBUG: 'bg-dark-700 text-dark-300',
}

export default function RuntimeLogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [paused, setPaused] = useState(false)
  const [filter, setFilter] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(false)

  useEffect(() => { pausedRef.current = paused }, [paused])

  useEffect(() => {
    const token = localStorage.getItem('access_token') || ''

    fetch('/api/logs/runtime/history?limit=200', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((data) => setLogs(data))
      .catch(() => {})

    const evtSource = new EventSource(`/api/logs/runtime/stream?token=${token}`)
    evtSource.onmessage = (e) => {
      if (pausedRef.current) return
      try {
        const entry: LogEntry = JSON.parse(e.data)
        setLogs((prev) => [...prev.slice(-499), entry])
      } catch { /* ignore parse error */ }
    }
    evtSource.onerror = () => { evtSource.close() }
    return () => evtSource.close()
  }, [])

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, paused])

  const filtered = filter
    ? logs.filter((l) => l.message.toLowerCase().includes(filter.toLowerCase()) || l.level.includes(filter.toUpperCase()))
    : logs

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] space-y-4 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-gray-50 flex items-center gap-2">
            <ScrollText size={22} className="text-primary-400" />
            运行日志
          </h2>
          <p className="text-sm text-dark-400 mt-1">实时查看 websocket 服务日志流</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-400 pointer-events-none" />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索关键字 / 级别…"
              className="input pl-9 !py-2 !text-sm w-56"
            />
          </div>
          <button onClick={() => setPaused(!paused)} className={paused ? 'btn btn-success btn-sm' : 'btn btn-secondary btn-sm'}>
            {paused ? <Play size={14} /> : <Pause size={14} />}
            {paused ? '继续' : '暂停'}
          </button>
          <button onClick={() => setLogs([])} className="btn btn-secondary btn-sm">
            <Trash2 size={14} />清空
          </button>
        </div>
      </div>

      <div className="card flex-1 overflow-hidden">
        <div className="h-full overflow-auto font-mono text-xs leading-6 p-4 bg-dark-950/50">
          {filtered.map((l, i) => (
            <div key={i} className="flex gap-3 hover:bg-dark-800/30 -mx-2 px-2 rounded">
              <span className="text-dark-500 shrink-0">{l.time}</span>
              <span className={`shrink-0 inline-flex items-center justify-center min-w-[60px] px-1.5 rounded text-[10px] font-semibold ${LEVEL_BG[l.level] || 'bg-dark-700 text-dark-300'}`}>
                {l.level}
              </span>
              <span className="text-dark-400 shrink-0">{l.module}</span>
              <span className={`break-all ${LEVEL_COLORS[l.level] || 'text-gray-300'}`}>{l.message}</span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  )
}
