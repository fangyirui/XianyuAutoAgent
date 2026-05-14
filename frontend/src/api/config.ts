import request from '@/utils/request'

export async function getPrompts() {
  const { data } = await request.get('/config/prompts')
  return data
}

export async function updatePrompt(name: string, content: string) {
  const { data } = await request.put('/config/prompts', { name, content })
  return data
}

export async function getWsStatus() {
  const { data } = await request.get('/ws/status')
  return data
}

export async function reconnectWs() {
  const { data } = await request.post('/ws/reconnect')
  return data
}
