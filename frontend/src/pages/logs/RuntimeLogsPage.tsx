import { useCallback, useEffect, useRef, useState } from 'react'
import { ScrollText, Pause, Play, Trash2, Search } from 'lucide-react'
import request from '@/utils/request'

interface LogEntry { id: number; time: string; level: string; message: string; module: string }

const PAGE_SIZE = 500

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
  const [logHasMore, setLogHasMore] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollBoxRef = useRef<HTMLDivElement>(null)
  const topRef = useRef<HTMLDivElement>(null)
  const atBottomRef = useRef(true)
  const didInitialScrollRef = useRef(false)
  const pausedRef = useRef(false)

  useEffect(() => { pausedRef.current = paused }, [paused])

  useEffect(() => {
    let cancelled = false
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let retries = 0
    const MAX_RETRIES = 5

    const loadHistory = async (): Promise<boolean> => {
      try {
        const { data } = await request.get('/logs/runtime/history', { params: { limit: PAGE_SIZE } })
        if (!cancelled) {
          setLogs(data.items)
          setLogHasMore(data.has_more)
        }
        return true
      } catch { /* axios interceptor handles 401 / redirect to /login */ return false }
    }

    const openStream = () => {
      if (cancelled) return
      const token = localStorage.getItem('access_token') || ''
      if (!token) return
      es = new EventSource(`/api/logs/runtime/stream?token=${encodeURIComponent(token)}`)
      es.onopen = () => { retries = 0 }
      es.onmessage = (e) => {
        if (pausedRef.current) return
        try {
          const entry: LogEntry = JSON.parse(e.data)
          // 按 id 去重追加，保留最近 5000 条（与后端环形缓冲上限一致）
          setLogs((prev) => (prev.some((l) => l.id === entry.id) ? prev : [...prev.slice(-4999), entry]))
        } catch { /* ignore parse error */ }
      }
      es.onerror = async () => {
        es?.close()
        es = null
        if (cancelled || retries >= MAX_RETRIES) return
        retries += 1
        // 重连前整体重拉一次历史：既触发 axios 的 401 拦截器按需刷新 token，又用后端最新的
        // id 空间替换本地日志——避免 websocket 进程重启后 _seq 归零、新日志 id 与本地残留旧
        // id 撞车被去重逻辑误判为重复而静默丢弃。失败（网络/刷新失败）则放弃本次重连。
        if (!(await loadHistory()) || cancelled) return
        const backoff = Math.min(1000 * 2 ** (retries - 1), 15000)
        retryTimer = setTimeout(openStream, backoff)
      }
    }

    loadHistory()
    openStream()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      es?.close()
    }
  }, [])

  // 记录用户是否停在底部附近（阈值 80px）。滚到上方看旧日志时即视为“不在底部”
  const handleScroll = () => {
    const el = scrollBoxRef.current
    if (!el) return
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  useEffect(() => {
    if (paused) return
    if (!didInitialScrollRef.current && logs.length > 0) {
      // 首屏加载历史：瞬间跳到底，不走平滑动画（避免上千条从顶部慢慢滚下来）
      didInitialScrollRef.current = true
      bottomRef.current?.scrollIntoView({ behavior: 'auto' })
      atBottomRef.current = true
      return
    }
    // 仅当用户本就在底部附近时才跟随新日志滚动，正在看上方旧日志时不打断
    if (atBottomRef.current) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, paused])

  // 向上滚到顶部哨兵时加载更早的日志（在环形缓冲至多 5000 条范围内翻页），前插后补偿滚动高度差保持视口不跳
  const loadOlder = useCallback(async () => {
    if (loadingOlder || !logHasMore) return
    const oldest = logs[0]
    if (!oldest) return
    setLoadingOlder(true)
    const el = scrollBoxRef.current
    const prevHeight = el ? el.scrollHeight : 0
    try {
      const { data } = await request.get('/logs/runtime/history', {
        params: { limit: PAGE_SIZE, before_id: oldest.id },
      })
      setLogs((cur) => {
        const seen = new Set(cur.map((l) => l.id))
        const older = (data.items as LogEntry[]).filter((l) => !seen.has(l.id))
        return [...older, ...cur]
      })
      setLogHasMore(data.has_more)
      requestAnimationFrame(() => {
        if (el) el.scrollTop += el.scrollHeight - prevHeight
      })
    } catch { /* axios interceptor handles 401 */ } finally {
      setLoadingOlder(false)
    }
  }, [logs, logHasMore, loadingOlder])

  useEffect(() => {
    const el = topRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && logHasMore && !loadingOlder) loadOlder()
      },
      { root: scrollBoxRef.current, threshold: 0.1 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [logHasMore, loadingOlder, loadOlder])

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
        <div ref={scrollBoxRef} onScroll={handleScroll} className="h-full overflow-auto font-mono text-xs leading-6 p-4 bg-dark-950/50">
          <div ref={topRef} />
          {loadingOlder && (
            <p className="text-dark-500 text-[11px] py-1 text-center">加载更早日志…</p>
          )}
          {!logHasMore && logs.length > 0 && (
            <p className="text-dark-600 text-[11px] py-1 text-center">— 已到日志缓冲顶部（最多保留 5000 条）—</p>
          )}
          {filtered.map((l) => (
            <div key={l.id} className="flex gap-3 hover:bg-dark-800/30 -mx-2 px-2 rounded">
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
