import request from '@/utils/request'

export async function login(username: string, password: string) {
  const { data } = await request.post('/auth/login', { username, password })
  return data
}
