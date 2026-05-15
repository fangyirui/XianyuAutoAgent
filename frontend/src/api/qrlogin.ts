import request from '@/utils/request'

export async function startQrLogin() {
  const { data } = await request.post('/qrlogin/start')
  return data
}

export async function pollQrStatus(t: string) {
  const { data } = await request.get('/qrlogin/status', { params: { t } })
  return data
}
