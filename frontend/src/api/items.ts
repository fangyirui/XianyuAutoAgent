import request from '@/utils/request'

export async function getItems(params: { page?: number; page_size?: number; keyword?: string }) {
  const { data } = await request.get('/items', { params })
  return data
}
