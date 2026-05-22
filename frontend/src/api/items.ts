import request from '@/utils/request'

export async function getItems(params: { page?: number; page_size?: number; keyword?: string }) {
  const { data } = await request.get('/items', { params })
  return data
}

export async function syncItems() {
  const { data } = await request.post('/items/sync')
  return data
}

export async function updateItemPrompt(itemId: string, customPrompt: string) {
  const { data } = await request.patch(`/items/${itemId}`, { custom_prompt: customPrompt })
  return data
}

export interface ItemDefaultReplyPatch {
  default_reply?: string
  default_reply_enabled?: boolean
}

export async function updateItemDefaultReply(itemId: string, patch: ItemDefaultReplyPatch) {
  const { data } = await request.patch(`/items/${itemId}`, patch)
  return data as {
    ok: boolean
    custom_prompt: string
    default_reply: string
    default_reply_enabled: boolean
  }
}
