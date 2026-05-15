import { useEffect, useState } from 'react'
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
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">对话日志</h2>
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        <div className="w-80 overflow-auto space-y-1 border-r border-gray-700 pr-4">
          {conversations.length === 0 && <p className="text-gray-500 text-sm py-4">暂无对话记录</p>}
          {conversations.map((c) => (
            <button key={c.chat_id} onClick={() => selectConversation(c)}
              className={`w-full text-left px-3 py-2.5 rounded-lg text-sm ${selectedChat === c.chat_id ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'}`}>
              <div className="flex items-center justify-between">
                <span className="font-medium truncate max-w-[180px]">{c.item_title || '未知商品'}</span>
                {c.item_price != null && c.item_price > 0 && (
                  <span className="text-xs text-emerald-400 shrink-0">¥{c.item_price}</span>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-0.5 truncate">买家: {c.user_nickname || c.user_id}</p>
              {c.last_message && (
                <p className="text-xs text-gray-500 mt-1 truncate">{c.last_message}</p>
              )}
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-gray-600">{new Date(c.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                <span className="text-xs text-gray-600">{c.message_count}条</span>
                {c.last_intent && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-600 text-gray-300">{INTENT_LABELS[c.last_intent] || c.last_intent}</span>
                )}
                {c.bargain_count > 0 && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-300">议{c.bargain_count}次</span>
                )}
              </div>
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col overflow-hidden">
          {selectedConv && (
            <div className="pb-3 mb-3 border-b border-gray-700 shrink-0">
              <p className="text-sm font-medium">{selectedConv.item_title || '未知商品'}{selectedConv.item_price ? ` · ¥${selectedConv.item_price}` : ''}</p>
              <p className="text-xs text-gray-400">买家 {selectedConv.user_nickname || selectedConv.user_id} · 商品 {selectedConv.item_id}</p>
            </div>
          )}
          <div className="flex-1 overflow-auto space-y-3">
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === 'assistant' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[70%] px-3 py-2 rounded-lg text-sm ${m.role === 'assistant' ? 'bg-emerald-900/50 text-emerald-100' : 'bg-gray-700 text-gray-200'}`}>
                  <p>{m.content}</p>
                  <p className={`text-xs mt-1 ${m.role === 'assistant' ? 'text-emerald-400/50' : 'text-gray-500'}`}>
                    {new Date(m.created_at).toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </p>
                </div>
              </div>
            ))}
            {!selectedChat && <p className="text-gray-500 text-sm">选择一个会话查看消息</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
