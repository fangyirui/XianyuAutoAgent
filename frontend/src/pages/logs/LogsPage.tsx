import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MessageSquare, Trash2, Send } from 'lucide-react'
import { batchDeleteConversations, deleteConversation, getConversations, getMessages, sendMessage } from '@/api/logs'

const PAGE_SIZE = 20

interface Conversation {
  id: number
  chat_id: string
  user_id: string
  user_nickname: string | null
  item_id: string | null
  item_title: string | null
  item_price: number | null
  bargain_count: number
  last_intent: string | null
  last_message: string | null
  message_count: number
  updated_at: string
}
interface Message { id: number; role: string; content: string; created_at: string }

const INTENT_LABELS: Record<string, string> = {
  price: '议价',
  tech: '技术',
  default: '通用',
  no_reply: '未回复',
}

// 今天的消息只显示时间，其他日期的消息额外带上日期（跨年再带上年份）
function formatMsgTime(value: string, withSeconds = false): string {
  const d = new Date(value)
  const now = new Date()
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const time = d.toLocaleString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  })
  if (isToday) return time
  const date = d.toLocaleString('zh-CN', {
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
    month: '2-digit',
    day: '2-digit',
  })
  return `${date} ${time}`
}

export default function LogsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedChat, setSelectedChat] = useState<string | null>(null)
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [msgHasMore, setMsgHasMore] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const msgListRef = useRef<HTMLDivElement | null>(null)
  const msgTopRef = useRef<HTMLDivElement | null>(null)
  const countRef = useRef(0)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  // SSE 长连里的回调闭包会捕获旧 state，故用 ref 持有"当前打开的会话"和"已加载会话 id 集合"
  const selectedConvRef = useRef<Conversation | null>(null)
  const convIdsRef = useRef<Set<number>>(new Set())

  useEffect(() => {
    countRef.current = conversations.length
  }, [conversations.length])

  useEffect(() => {
    selectedConvRef.current = selectedConv
  }, [selectedConv])

  useEffect(() => {
    convIdsRef.current = new Set(conversations.map((c) => c.id))
  }, [conversations])

  const hasMore = conversations.length < total

  // 按当前已加载数量推算下一页，使删除后页码自动修正
  const loadMore = useCallback(async () => {
    setLoading(true)
    try {
      const nextPage = Math.floor(countRef.current / PAGE_SIZE) + 1
      const data = await getConversations(nextPage, PAGE_SIZE)
      setConversations((cur) => {
        const seen = new Set(cur.map((c) => c.chat_id))
        const merged = [...cur]
        for (const it of data.items as Conversation[]) {
          if (!seen.has(it.chat_id)) merged.push(it)
        }
        return merged
      })
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }, [])

  // 拉取第一页并与已加载列表合并去重，用于新会话（新买家首条消息）实时冒出来。
  // 第一页按 updated_at 倒序，刚活跃的会话必在其中；合并后整体按 updated_at 重排。
  const refreshFirstPage = useCallback(async () => {
    const data = await getConversations(1, PAGE_SIZE)
    setConversations((cur) => {
      const byChat = new Map(cur.map((c) => [c.chat_id, c]))
      for (const it of data.items as Conversation[]) byChat.set(it.chat_id, it)
      return Array.from(byChat.values()).sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      )
    })
    setTotal(data.total)
  }, [])

  const allLoadedSelected = useMemo(
    () => conversations.length > 0 && conversations.every((c) => selected.has(c.chat_id)),
    [conversations, selected],
  )

  const toggleSelect = (chatId: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(chatId)) next.delete(chatId)
      else next.add(chatId)
      return next
    })
  }

  const toggleSelectAllLoaded = () => {
    setSelected((prev) => {
      if (conversations.every((c) => prev.has(c.chat_id))) {
        const next = new Set(prev)
        conversations.forEach((c) => next.delete(c.chat_id))
        return next
      }
      const next = new Set(prev)
      conversations.forEach((c) => next.add(c.chat_id))
      return next
    })
  }

  const applyDelete = (chatIds: string[]) => {
    const set = new Set(chatIds)
    setConversations((prev) => prev.filter((c) => !set.has(c.chat_id)))
    setTotal((t) => Math.max(0, t - chatIds.length))
    setSelected((prev) => {
      const next = new Set(prev)
      chatIds.forEach((id) => next.delete(id))
      return next
    })
    if (selectedChat && set.has(selectedChat)) {
      setSelectedChat(null)
      setSelectedConv(null)
      setMessages([])
    }
  }

  const handleDeleteOne = async (conv: Conversation) => {
    if (!window.confirm(`确定删除与「${conv.user_nickname || conv.user_id}」的会话？此操作不可恢复。`)) return
    setDeleting(true)
    try {
      await deleteConversation(conv.chat_id)
      applyDelete([conv.chat_id])
    } finally {
      setDeleting(false)
    }
  }

  const handleBatchDelete = async () => {
    const ids = Array.from(selected)
    if (ids.length === 0) return
    if (!window.confirm(`确定批量删除 ${ids.length} 个会话？此操作不可恢复。`)) return
    setDeleting(true)
    try {
      await batchDeleteConversations(ids)
      applyDelete(ids)
    } finally {
      setDeleting(false)
    }
  }

  // 初始加载
  useEffect(() => {
    loadMore()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 会话消息实时增量流（SSE）：新消息落库即推送，刷新当前对话框 + 会话列表
  useEffect(() => {
    let cancelled = false
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let retries = 0
    const MAX_RETRIES = 5

    const handleEvent = (ev: { conversation_id: number; message: Message }) => {
      const { conversation_id, message } = ev
      // 1) 命中当前打开的会话 → 按 id 去重追加到消息面板
      if (selectedConvRef.current && selectedConvRef.current.id === conversation_id) {
        setMessages((prev) => (prev.some((m) => m.id === message.id) ? prev : [...prev, message]))
      }
      // 2) 列表里没有这个会话（新买家）→ 拉第一页带出来；有则就地更新预览+置顶
      if (!convIdsRef.current.has(conversation_id)) {
        refreshFirstPage().catch(() => {})
        return
      }
      setConversations((prev) => {
        const idx = prev.findIndex((c) => c.id === conversation_id)
        if (idx === -1) return prev
        const hit = {
          ...prev[idx],
          last_message: message.role === 'user' ? message.content : prev[idx].last_message,
          message_count: prev[idx].message_count + 1,
          updated_at: message.created_at,
        }
        const rest = prev.filter((_, i) => i !== idx)
        return [hit, ...rest]
      })
    }

    const openStream = () => {
      if (cancelled) return
      const token = localStorage.getItem('access_token') || ''
      if (!token) return
      es = new EventSource(`/api/logs/conversations/stream?token=${encodeURIComponent(token)}`)
      es.onopen = () => { retries = 0 }
      es.onmessage = (e) => {
        try { handleEvent(JSON.parse(e.data)) } catch { /* ignore parse error */ }
      }
      es.onerror = async () => {
        es?.close()
        es = null
        if (cancelled || retries >= MAX_RETRIES) return
        retries += 1
        // 触发一次 axios 调用，让 401 拦截器在需要时刷新 access token
        try { await getConversations(1, 1) } catch { return }
        if (cancelled) return
        const backoff = Math.min(1000 * 2 ** (retries - 1), 15000)
        retryTimer = setTimeout(openStream, backoff)
      }
    }

    openStream()
    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      es?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 当前对话框收到新消息时滚到底部。
  // - 首次点进一个会话：瞬间跳转（behavior:'auto'），避免历史多时平滑动画从顶部慢慢滚到底；
  // - 已打开的会话里追加新消息（末条 id 变化）：平滑滚动；
  // - 上滚加载更早消息（前插，末条 id 不变）：不滚动，由 loadOlder 自行补偿滚动位置。
  const scrolledChatRef = useRef<string | null>(null)
  const lastMsgIdRef = useRef<number | null>(null)
  // 用户是否停在消息面板底部附近（阈值 80px）。上滚看历史时即视为“不在底部”
  const msgAtBottomRef = useRef(true)
  const handleMsgScroll = () => {
    const el = msgListRef.current
    if (!el) return
    msgAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }
  useEffect(() => {
    if (!bottomRef.current) return
    const isNewConv = scrolledChatRef.current !== selectedChat
    const lastId = messages.length ? messages[messages.length - 1].id : null
    const lastChanged = lastMsgIdRef.current !== lastId
    scrolledChatRef.current = selectedChat
    lastMsgIdRef.current = lastId
    if (isNewConv) {
      bottomRef.current.scrollIntoView({ behavior: 'auto' })
      msgAtBottomRef.current = true
    } else if (lastChanged && msgAtBottomRef.current) {
      // 已打开的会话追加新消息，且用户本就贴底时才跟随滚动；正在看上方历史时不打断
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, selectedChat])

  // 向上滚到顶部哨兵时加载更早的消息，前插后补偿滚动高度差以保持视口位置不跳
  const loadOlder = useCallback(async () => {
    if (!selectedChat || loadingOlder || !msgHasMore) return
    const oldest = messages[0]
    if (!oldest) return
    setLoadingOlder(true)
    const el = msgListRef.current
    const prevHeight = el ? el.scrollHeight : 0
    try {
      const data = await getMessages(selectedChat, { beforeId: oldest.id })
      setMessages((cur) => {
        const seen = new Set(cur.map((m) => m.id))
        const older = (data.items as Message[]).filter((m) => !seen.has(m.id))
        return [...older, ...cur]
      })
      setMsgHasMore(data.has_more)
      requestAnimationFrame(() => {
        if (el) el.scrollTop += el.scrollHeight - prevHeight
      })
    } finally {
      setLoadingOlder(false)
    }
  }, [selectedChat, loadingOlder, msgHasMore, messages])

  // 滚动到底部哨兵元素时自动加载下一页
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading) {
          loadMore()
        }
      },
      { root: el.parentElement, threshold: 0.1 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [hasMore, loading, loadMore])

  // 消息面板滚到顶部哨兵时加载更早消息
  useEffect(() => {
    const el = msgTopRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && msgHasMore && !loadingOlder) {
          loadOlder()
        }
      },
      { root: msgListRef.current, threshold: 0.1 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [msgHasMore, loadingOlder, loadOlder])

  const selectConversation = async (conv: Conversation) => {
    setSelectedChat(conv.chat_id)
    setSelectedConv(conv)
    setDraft('')
    const data = await getMessages(conv.chat_id)
    setMessages(data.items)
    setMsgHasMore(data.has_more)
  }

  const ERR_MESSAGES: Record<string, string> = {
    not_running: 'WebSocket 服务未运行',
    ws_not_connected: '闲鱼连接已断开，无法发送',
    conversation_not_found: '会话不存在',
    empty_text: '消息内容不能为空',
    send_failed: '发送失败，请重试',
  }

  const handleSend = async () => {
    const text = draft.trim()
    if (!text || !selectedChat || sending) return
    setSending(true)
    try {
      const res = await sendMessage(selectedChat, text)
      if (res.status !== 'ok') {
        window.alert(ERR_MESSAGES[res.detail || ''] || `发送失败：${res.detail || '未知错误'}`)
        return
      }
      setDraft('')
      // 刷新消息列表带出刚发的这条（回到最近一页）
      const data = await getMessages(selectedChat)
      setMessages(data.items)
      setMsgHasMore(data.has_more)
    } catch {
      window.alert('发送失败，请检查服务状态')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h2 className="text-2xl font-bold text-gray-50 flex items-center gap-2">
          <MessageSquare size={22} className="text-primary-400" />
          对话日志
        </h2>
        <p className="text-sm text-dark-400 mt-1">
          查看历史买家对话与 AI 回复记录
          {total > 0 && <span className="ml-2 text-dark-500">· 共 {total} 个会话</span>}
        </p>
      </div>

      <div className="card overflow-hidden">
        <div className="flex h-[calc(100vh-14rem)] min-h-[480px]">
          {/* Conversation list */}
          <div className="w-80 flex flex-col border-r border-dark-700/60">
            {/* 批量操作栏 */}
            <div className="px-3 py-2 border-b border-dark-700/60 flex items-center justify-between gap-2 shrink-0">
              <label className="flex items-center gap-2 text-xs text-dark-300 cursor-pointer select-none">
                <input
                  type="checkbox"
                  className="accent-primary-500"
                  checked={allLoadedSelected}
                  onChange={toggleSelectAllLoaded}
                  disabled={conversations.length === 0}
                />
                {selected.size > 0 ? `已选 ${selected.size}` : '全选当前'}
              </label>
              <button
                onClick={handleBatchDelete}
                disabled={selected.size === 0 || deleting}
                className="text-xs px-2 py-1 rounded-md text-red-400 hover:bg-red-500/10 disabled:opacity-40 disabled:hover:bg-transparent disabled:cursor-not-allowed flex items-center gap-1"
              >
                <Trash2 size={13} />删除选中
              </button>
            </div>

            <div className="flex-1 overflow-auto p-2 space-y-1">
              {conversations.length === 0 && !loading && (
                <p className="text-dark-400 text-sm py-8 text-center">暂无对话记录</p>
              )}
              {conversations.map((c) => {
                const isSelectedForDelete = selected.has(c.chat_id)
                return (
                  <div
                    key={c.chat_id}
                    onClick={() => selectConversation(c)}
                    className={`group relative w-full text-left pl-9 pr-9 py-2.5 rounded-xl text-sm transition-all cursor-pointer ${
                      selectedChat === c.chat_id
                        ? 'bg-primary-500/15 text-primary-100 border border-primary-500/30'
                        : 'text-gray-200 border border-transparent hover:bg-dark-800/60'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelectedForDelete}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => toggleSelect(c.chat_id)}
                      className="absolute left-3 top-3 accent-primary-500 cursor-pointer"
                    />
                    <button
                      type="button"
                      title="删除此会话"
                      onClick={(e) => { e.stopPropagation(); handleDeleteOne(c) }}
                      disabled={deleting}
                      className="absolute right-2 top-2 p-1 rounded text-dark-400 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-40"
                    >
                      <Trash2 size={14} />
                    </button>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium truncate">{c.item_title || '未知商品'}</span>
                      {c.item_price != null && c.item_price > 0 && (
                        <span className="text-xs text-primary-400 shrink-0 font-medium">¥{c.item_price}</span>
                      )}
                    </div>
                    <p className="text-xs text-dark-400 mt-0.5 truncate">买家：{c.user_nickname || c.user_id}</p>
                    {c.last_message && (
                      <p className="text-xs text-dark-500 mt-1 truncate">{c.last_message}</p>
                    )}
                    <div className="flex items-center flex-wrap gap-1.5 mt-1.5">
                      <span className="text-[11px] text-dark-500">
                        {new Date(c.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span className="text-[11px] text-dark-500">·</span>
                      <span className="text-[11px] text-dark-500">{c.message_count} 条</span>
                      {c.last_intent && (
                        <span className="badge badge-muted !text-[10px] !py-0">{INTENT_LABELS[c.last_intent] || c.last_intent}</span>
                      )}
                      {c.bargain_count > 0 && (
                        <span className="badge badge-warning !text-[10px] !py-0">议 {c.bargain_count}</span>
                      )}
                    </div>
                  </div>
                )
              })}
              {/* 哨兵：滚动到此处时加载下一页 */}
              <div ref={sentinelRef} />
              {loading && (
                <p className="text-dark-500 text-xs py-3 text-center">加载中…</p>
              )}
              {!loading && !hasMore && conversations.length > 0 && (
                <p className="text-dark-600 text-xs py-3 text-center">— 已加载全部 —</p>
              )}
            </div>
          </div>

          {/* Message panel */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {selectedConv && (
              <div className="px-5 py-3 border-b border-dark-700/60 shrink-0">
                <p className="text-sm font-medium text-gray-100">
                  {selectedConv.item_title || '未知商品'}
                  {selectedConv.item_price ? <span className="text-primary-400 ml-2">¥{selectedConv.item_price}</span> : null}
                </p>
                <p className="text-xs text-dark-400 mt-0.5">
                  买家 {selectedConv.user_nickname || selectedConv.user_id} · 商品 {selectedConv.item_id}
                </p>
              </div>
            )}
            <div ref={msgListRef} onScroll={handleMsgScroll} className="flex-1 overflow-auto p-5 space-y-3">
              {!selectedChat && (
                <p className="text-dark-400 text-sm text-center pt-8">选择一个会话查看消息</p>
              )}
              {selectedChat && <div ref={msgTopRef} />}
              {selectedChat && loadingOlder && (
                <p className="text-dark-500 text-xs py-2 text-center">加载更早消息…</p>
              )}
              {selectedChat && !msgHasMore && messages.length > 0 && (
                <p className="text-dark-600 text-xs py-2 text-center">— 已经到顶啦 —</p>
              )}
              {messages.map((m) => {
                if (m.role === 'system') {
                  return (
                    <div key={m.id} className="flex justify-center">
                      <div className="px-3 py-1 rounded-full text-[11px] text-dark-400 bg-dark-800/60 border border-dark-700/50">
                        <span className="mr-1.5">{m.content}</span>
                        <span className="text-dark-500">
                          {formatMsgTime(m.created_at)}
                        </span>
                      </div>
                    </div>
                  )
                }
                return (
                  <div key={m.id} className={`flex ${m.role === 'assistant' ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[70%] px-3.5 py-2 rounded-2xl text-sm ${
                        m.role === 'assistant'
                          ? 'bg-gradient-primary text-white shadow-md shadow-primary-500/20'
                          : 'bg-dark-800 text-gray-100 border border-dark-700/60'
                      }`}
                    >
                      <p className="whitespace-pre-wrap break-words">{m.content}</p>
                      <p className={`text-[10px] mt-1 ${m.role === 'assistant' ? 'text-white/60' : 'text-dark-500'}`}>
                        {formatMsgTime(m.created_at, true)}
                      </p>
                    </div>
                  </div>
                )
              })}
              <div ref={bottomRef} />
            </div>
            {selectedChat && (
              <div className="border-t border-dark-700/60 p-3 shrink-0">
                <div className="flex items-end gap-2">
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                    rows={1}
                    placeholder="输入消息，Enter 发送 / Shift+Enter 换行（发送后将切换为人工接管）"
                    className="flex-1 resize-none max-h-32 px-3 py-2 rounded-xl bg-dark-800 border border-dark-700/60 text-sm text-gray-100 placeholder:text-dark-500 focus:outline-none focus:border-primary-500/50"
                  />
                  <button
                    type="button"
                    onClick={handleSend}
                    disabled={!draft.trim() || sending}
                    className="btn-primary !px-3 !py-2 flex items-center gap-1.5 shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Send size={15} />
                    {sending ? '发送中' : '发送'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
