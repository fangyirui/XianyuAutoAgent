import { useEffect, useState } from 'react'
import { getConversations, getMessages } from '@/api/logs'

interface Conversation { id: number; chat_id: string; user_id: string; item_id: string | null; bargain_count: number; updated_at: string }
interface Message { id: number; role: string; content: string; created_at: string }

export default function LogsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedChat, setSelectedChat] = useState<string | null>(null)

  useEffect(() => { getConversations().then(setConversations) }, [])

  const selectConversation = async (chatId: string) => {
    setSelectedChat(chatId)
    setMessages(await getMessages(chatId))
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">对话日志</h2>
      <div className="flex gap-4 h-[calc(100vh-12rem)]">
        <div className="w-72 overflow-auto space-y-1 border-r border-gray-700 pr-4">
          {conversations.map((c) => (
            <button key={c.chat_id} onClick={() => selectConversation(c.chat_id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm ${selectedChat === c.chat_id ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'}`}>
              <p className="truncate">{c.chat_id}</p>
              <p className="text-xs text-gray-500">{c.updated_at}</p>
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto space-y-3">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === 'assistant' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[70%] px-3 py-2 rounded-lg text-sm ${m.role === 'assistant' ? 'bg-emerald-900/50 text-emerald-100' : 'bg-gray-700 text-gray-200'}`}>
                {m.content}
              </div>
            </div>
          ))}
          {!selectedChat && <p className="text-gray-500 text-sm">选择一个会话查看消息</p>}
        </div>
      </div>
    </div>
  )
}
