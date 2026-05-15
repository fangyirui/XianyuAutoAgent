import request from '@/utils/request'

export async function getPrompts() {
  const { data } = await request.get('/config/prompts')
  return data
}

export async function updatePrompt(name: string, content: string) {
  const { data } = await request.put('/config/prompts', { name, content })
  return data
}

export async function getEnvConfig() {
  const { data } = await request.get('/config/env')
  return data
}

export async function updateEnvConfig(config: Record<string, string>) {
  const { data } = await request.put('/config/env', config)
  return data
}

export async function testAiConnection(params: { api_key: string; base_url: string; model: string }) {
  const { data } = await request.post('/config/ai-test', params)
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
