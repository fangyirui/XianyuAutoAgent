import { useEffect, useState } from 'react'
import { MessageSquare } from 'lucide-react'
import { getConversations, getMessages } from '@/api/logs'

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

  useEffect(() => { getConversations().then(setConversations) }, [])

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
        <p className="text-sm text-dark-400 mt-1">查看历史买家对话与 AI 回复记录</p>
      </div>

      <div className="card overflow-hidden">
        <div className="flex h-[calc(100vh-14rem)] min-h-[480px]">
          {/* Conversation list */}
          <div className="w-80 overflow-auto border-r border-dark-700/60 p-2 space-y-1">
            {conversations.length === 0 && (
              <p className="text-dark-400 text-sm py-8 text-center">暂无对话记录</p>
            )}
            {conversations.map((c) => (
              <button
                key={c.chat_id}
                onClick={() => selectConversation(c)}
                className={`w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all ${
                  selectedChat === c.chat_id
                    ? 'bg-primary-500/15 text-primary-100 border border-primary-500/30'
                    : 'text-gray-200 border border-transparent hover:bg-dark-800/60'
                }`}
              >
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
              </button>
            ))}
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
