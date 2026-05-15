import { useEffect, useState } from 'react'
import { getItems } from '@/api/items'

interface Item {
  id: number
  item_id: string
  title: string
  price: number
  description: string
  fetched_at: string | null
}

export default function ItemsPage() {
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const pageSize = 20

  const fetchItems = async (p: number, kw: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await getItems({ page: p, page_size: pageSize, keyword: kw || undefined })
      setItems(res.items)
      setTotal(res.total)
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载失败，请稍后重试')
    }
    setLoading(false)
  }

  useEffect(() => { fetchItems(page, keyword) }, [page, keyword])

  const handleSearch = () => { setPage(1); setKeyword(searchInput) }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">商品缓存</h2>
      <p className="text-sm text-gray-400">已缓存 {total} 件商品信息（来自买家咨询时自动拉取）</p>

      <div className="flex gap-2">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="搜索商品标题..."
          className="flex-1 max-w-sm bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-400"
        />
        <button onClick={handleSearch}
          className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg text-sm hover:bg-gray-600">
          搜索
        </button>
      </div>

      {error && <div className="text-red-400 text-sm py-2">{error}</div>}

      {loading ? (
        <div className="text-gray-400 text-sm py-8 text-center">加载中...</div>
      ) : items.length === 0 && !error ? (
        <div className="text-gray-400 text-sm py-8 text-center">暂无商品缓存</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400">
                <th className="text-left py-2 px-3">商品ID</th>
                <th className="text-left py-2 px-3">标题</th>
                <th className="text-right py-2 px-3">价格</th>
                <th className="text-left py-2 px-3">描述</th>
                <th className="text-left py-2 px-3">缓存时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-gray-700/50 hover:bg-gray-800/50">
                  <td className="py-2 px-3 font-mono text-xs text-gray-400">{item.item_id}</td>
                  <td className="py-2 px-3 max-w-xs truncate">{item.title || '-'}</td>
                  <td className="py-2 px-3 text-right text-emerald-400">{item.price > 0 ? `¥${item.price}` : '-'}</td>
                  <td className="py-2 px-3 max-w-xs truncate text-gray-400">{item.description || '-'}</td>
                  <td className="py-2 px-3 text-xs text-gray-500">{item.fetched_at ? new Date(item.fetched_at).toLocaleString('zh-CN') : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-sm text-gray-400">第 {page}/{totalPages} 页</span>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
              上一页
            </button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-sm hover:bg-gray-600 disabled:opacity-50">
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
