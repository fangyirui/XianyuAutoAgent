import { useEffect, useState } from 'react'
import { getItems, syncItems, updateItemPrompt } from '@/api/items'

interface Item {
  id: number
  item_id: string
  seller_id: string
  title: string
  price: number
  description: string
  custom_prompt: string
  fetched_at: string | null
}

export default function ItemsPage() {
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [error, setError] = useState('')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [editingPromptId, setEditingPromptId] = useState<number | null>(null)
  const [promptDraft, setPromptDraft] = useState('')
  const [savingPromptId, setSavingPromptId] = useState<number | null>(null)
  const [promptErr, setPromptErr] = useState('')
  const pageSize = 20

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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

  const handleSync = async () => {
    if (syncing) return
    setSyncing(true)
    setSyncMsg('')
    try {
      const res = await syncItems()
      const saved = res?.saved ?? 0
      setSyncMsg(`同步完成，已写入 ${saved} 条商品`)
      await fetchItems(page, keyword)
    } catch (e: any) {
      setSyncMsg(e?.response?.data?.detail || '同步失败，请查看 websocket 日志')
    } finally {
      setSyncing(false)
      setTimeout(() => setSyncMsg(''), 6000)
    }
  }

  const startEditPrompt = (item: Item) => {
    setEditingPromptId(item.id)
    setPromptDraft(item.custom_prompt || '')
    setPromptErr('')
  }

  const cancelEditPrompt = () => {
    setEditingPromptId(null)
    setPromptDraft('')
    setPromptErr('')
  }

  const savePrompt = async (item: Item) => {
    setSavingPromptId(item.id)
    setPromptErr('')
    try {
      const res = await updateItemPrompt(item.item_id, promptDraft)
      setItems((prev) => prev.map((it) => it.id === item.id ? { ...it, custom_prompt: res.custom_prompt ?? promptDraft } : it))
      setEditingPromptId(null)
      setPromptDraft('')
    } catch (e: any) {
      setPromptErr(e?.response?.data?.detail || '保存失败')
    } finally {
      setSavingPromptId(null)
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">商品缓存</h2>
        <button onClick={handleSync} disabled={syncing}
          className="px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
          {syncing ? '同步中...' : '从闲鱼同步商品'}
        </button>
      </div>
      <p className="text-sm text-gray-400">
        已缓存 {total} 件归属于当前卖家的商品。点击右上角按钮从闲鱼拉取最新商品列表（"在售"分组）。可单独为某商品配置"AI 提示词"，AI 生成回复时会作为系统提示词的补充。
      </p>

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

      {syncMsg && <div className="text-sm py-2 text-emerald-300">{syncMsg}</div>}
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
                <th className="text-left py-2 px-3">卖家ID</th>
                <th className="text-left py-2 px-3">标题</th>
                <th className="text-right py-2 px-3">价格</th>
                <th className="text-left py-2 px-3">描述</th>
                <th className="text-left py-2 px-3">AI 提示词</th>
                <th className="text-left py-2 px-3">缓存时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const expanded = expandedIds.has(item.id)
                const hasDesc = !!item.description
                const editing = editingPromptId === item.id
                const saving = savingPromptId === item.id
                const hasPrompt = !!(item.custom_prompt && item.custom_prompt.trim())
                return (
                  <tr key={item.id} className="border-b border-gray-700/50 hover:bg-gray-800/50 align-top">
                    <td className="py-2 px-3 font-mono text-xs text-gray-400 whitespace-nowrap">{item.item_id}</td>
                    <td className="py-2 px-3 font-mono text-xs text-gray-400 whitespace-nowrap">{item.seller_id || '-'}</td>
                    <td className="py-2 px-3 max-w-xs">{item.title || '-'}</td>
                    <td className="py-2 px-3 text-right text-emerald-400 whitespace-nowrap">{item.price > 0 ? `¥${item.price}` : '-'}</td>
                    <td
                      onClick={() => hasDesc && toggleExpand(item.id)}
                      className={`py-2 px-3 max-w-md text-gray-300 text-xs ${hasDesc ? 'cursor-pointer select-none' : ''} ${expanded ? 'whitespace-pre-line break-words' : 'truncate'}`}
                      title={hasDesc ? (expanded ? '点击收起' : '点击展开') : ''}
                    >
                      {hasDesc ? (
                        <>
                          <span className="mr-1 text-gray-500">{expanded ? '▼' : '▶'}</span>
                          {item.description}
                        </>
                      ) : '-'}
                    </td>
                    <td className="py-2 px-3 max-w-md text-xs">
                      {editing ? (
                        <div className="space-y-2">
                          <textarea
                            value={promptDraft}
                            onChange={(e) => setPromptDraft(e.target.value)}
                            maxLength={2000}
                            rows={4}
                            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-gray-200 focus:outline-none focus:border-emerald-400"
                            placeholder="为该商品单独配置额外提示词（可空），AI 生成回复时追加在系统提示词之后"
                          />
                          <div className="flex gap-2 items-center">
                            <button
                              onClick={() => savePrompt(item)}
                              disabled={saving}
                              className="px-3 py-1 bg-emerald-500 text-gray-900 font-semibold rounded text-xs hover:bg-emerald-400 disabled:opacity-50"
                            >
                              {saving ? '保存中...' : '保存'}
                            </button>
                            <button
                              onClick={cancelEditPrompt}
                              disabled={saving}
                              className="px-3 py-1 bg-gray-700 text-gray-200 rounded text-xs hover:bg-gray-600 disabled:opacity-50"
                            >
                              取消
                            </button>
                            <span className="text-gray-500">{promptDraft.length}/2000</span>
                          </div>
                          {promptErr && <div className="text-red-400 text-xs">{promptErr}</div>}
                        </div>
                      ) : (
                        <div
                          onClick={() => startEditPrompt(item)}
                          className="cursor-pointer select-none text-gray-300 hover:text-emerald-300"
                          title="点击编辑"
                        >
                          {hasPrompt ? (
                            <>
                              <span className="mr-1 text-gray-500">✎</span>
                              <span className="break-words">
                                {item.custom_prompt.length > 20
                                  ? `${item.custom_prompt.slice(0, 20)}...`
                                  : item.custom_prompt}
                              </span>
                            </>
                          ) : (
                            <span className="text-gray-500">未设置（点击配置）</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="py-2 px-3 text-xs text-gray-500 whitespace-nowrap">{item.fetched_at ? new Date(item.fetched_at).toLocaleString('zh-CN') : '-'}</td>
                  </tr>
                )
              })}
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
