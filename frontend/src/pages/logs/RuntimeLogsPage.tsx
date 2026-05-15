import { useEffect, useRef, useState } from 'react'

interface LogEntry { time: string; level: string; message: string; module: string }

const LEVEL_COLORS: Record<string, string> = {
  ERROR: 'text-red-400',
  WARNING: 'text-yellow-400',
  INFO: 'text-gray-200',
  DEBUG: 'text-gray-500',
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
      } catch {}
    }
    evtSource.onerror = () => { evtSource.close() }
    return () => evtSource.close()
  }, [])

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, paused])

  const filtered = filter ? logs.filter((l) => l.message.toLowerCase().includes(filter.toLowerCase()) || l.level.includes(filter.toUpperCase())) : logs

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-semibold">运行日志</h2>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="搜索..."
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1 text-sm w-48 focus:outline-none focus:border-emerald-400" />
        <button onClick={() => setPaused(!paused)}
          className={`px-3 py-1 rounded-lg text-sm ${paused ? 'bg-emerald-500 text-gray-900' : 'bg-gray-700 text-gray-200'}`}>
          {paused ? '继续' : '暂停'}
        </button>
        <button onClick={() => setLogs([])} className="px-3 py-1 rounded-lg text-sm bg-gray-700 text-gray-200">清空</button>
      </div>
      <div className="flex-1 overflow-auto bg-gray-900 rounded-lg p-3 font-mono text-xs leading-5">
        {filtered.map((l, i) => (
          <div key={i} className="flex gap-2">
            <span className="text-gray-500 shrink-0">{l.time}</span>
            <span className={`shrink-0 w-16 ${LEVEL_COLORS[l.level] || 'text-gray-300'}`}>{l.level}</span>
            <span className="text-gray-400 shrink-0">{l.module}</span>
            <span className={LEVEL_COLORS[l.level] || 'text-gray-300'}>{l.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
