import request from '@/utils/request'

export async function getConversations(page = 1, pageSize = 20) {
  const { data } = await request.get('/logs/conversations', { params: { page, page_size: pageSize } })
  return data as { items: any[]; total: number; page: number; page_size: number }
}

export async function getMessages(chatId: string, opts?: { beforeId?: number; limit?: number }) {
  const { data } = await request.get(`/logs/conversations/${chatId}/messages`, {
    params: { before_id: opts?.beforeId, limit: opts?.limit ?? 50 },
  })
  return data as { items: any[]; has_more: boolean }
}

export interface IntentItem {
  name: string
  count: number
}

export interface DashboardStats {
  realtime: {
    manual_active: number
  }
  today: {
    conversations: number
    messages: number
    ai_replies: number
    user_messages: number
    new_buyers: number
    manual_takeover_triggered: number
    ai_calls: number
    tokens: number
    ai_errors: number
    ai_error_rate: number
    avg_latency_ms: number
    intent_distribution: IntentItem[]
    agent_distribution: IntentItem[]
  }
  cumulative: {
    conversations: number
    messages: number
    buyers: number
    bargain_sessions: number
    ai_calls: number
    tokens: number
  }
  total_conversations: number
  total_messages: number
}

export async function getStats(): Promise<DashboardStats> {
  const { data } = await request.get('/logs/stats')
  return data as DashboardStats
}

export async function deleteConversation(chatId: string) {
  await request.delete(`/logs/conversations/${chatId}`)
}

export async function batchDeleteConversations(chatIds: string[]) {
  await request.post('/logs/conversations/batch-delete', { chat_ids: chatIds })
}

// 从控制台人工发送消息给买家。仅发送并落库 role=assistant，不改动人工接管等会话状态（与手机端手动回复一致）。
export async function sendMessage(chatId: string, text: string) {
  const { data } = await request.post(`/ws/send-message/${chatId}`, { text })
  return data as { status: string; detail?: string; chat_id?: string }
}
