import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MessageSquare, Trash2 } from 'lucide-react'
import { batchDeleteConversations, deleteConversation, getConversations, getMessages } from '@/api/logs'

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

export default function LogsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedChat, setSelectedChat] = useState<string | null>(null)
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const countRef = useRef(0)

  useEffect(() => {
    countRef.current = conversations.length
  }, [conversations.length])

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

  const selectConversation = async (conv: Conversation) => {
    setSelectedChat(conv.chat_id)
    setSelectedConv(conv)
    setMessages(await getMessages(conv.chat_id))
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
            <div className="flex-1 overflow-auto p-5 space-y-3">
              {!selectedChat && (
                <p className="text-dark-400 text-sm text-center pt-8">选择一个会话查看消息</p>
              )}
              {messages.map((m) => (
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
                      {new Date(m.created_at).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
