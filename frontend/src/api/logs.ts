import request from '@/utils/request'

export async function getConversations(page = 1, pageSize = 20) {
  const { data } = await request.get('/logs/conversations', { params: { page, page_size: pageSize } })
  return data as { items: any[]; total: number; page: number; page_size: number }
}

export async function getMessages(chatId: string) {
  const { data } = await request.get(`/logs/conversations/${chatId}/messages`)
  return data
}

export async function getStats() {
  const { data } = await request.get('/logs/stats')
  return data
}

export async function deleteConversation(chatId: string) {
  await request.delete(`/logs/conversations/${chatId}`)
}

export async function batchDeleteConversations(chatIds: string[]) {
  await request.post('/logs/conversations/batch-delete', { chat_ids: chatIds })
}
