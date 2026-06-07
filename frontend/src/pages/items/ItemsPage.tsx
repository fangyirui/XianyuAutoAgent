import { useEffect, useState } from 'react'
import { Package, RefreshCw, Search, Pencil, ChevronDown, ChevronRight } from 'lucide-react'
import { getItems, syncItems, updateItemPrompt, updateItemDefaultReply } from '@/api/items'

interface Item {
  id: number
  item_id: string
  seller_id: string
  title: string
  price: number
  description: string
  custom_prompt: string
  default_reply: string
  default_reply_enabled: boolean
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
  const [editingReplyId, setEditingReplyId] = useState<number | null>(null)
  const [replyDraft, setReplyDraft] = useState('')
  const [replyEnabledDraft, setReplyEnabledDraft] = useState(false)
  const [savingReplyId, setSavingReplyId] = useState<number | null>(null)
  const [replyErr, setReplyErr] = useState('')
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

  const startEditReply = (item: Item) => {
    setEditingReplyId(item.id)
    setReplyDraft(item.default_reply || '')
    setReplyEnabledDraft(item.default_reply_enabled)
    setReplyErr('')
  }

  const cancelEditReply = () => {
    setEditingReplyId(null)
    setReplyDraft('')
    setReplyEnabledDraft(false)
    setReplyErr('')
  }

  const saveReply = async (item: Item) => {
    if (replyEnabledDraft && !replyDraft.trim()) {
      setReplyErr('启用默认回复时必须填写回复内容')
      return
    }
    setSavingReplyId(item.id)
    setReplyErr('')
    try {
      const res = await updateItemDefaultReply(item.item_id, {
        default_reply: replyDraft,
        default_reply_enabled: replyEnabledDraft,
      })
      setItems((prev) => prev.map((it) => it.id === item.id
        ? { ...it, default_reply: res.default_reply ?? replyDraft, default_reply_enabled: res.default_reply_enabled }
        : it,
      ))
      setEditingReplyId(null)
      setReplyDraft('')
      setReplyEnabledDraft(false)
    } catch (e: any) {
      setReplyErr(e?.response?.data?.detail || '保存失败')
    } finally {
      setSavingReplyId(null)
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-bold text-gray-50 flex items-center gap-2">
            <Package size={22} className="text-primary-400" />
            商品配置
          </h2>
          <p className="text-sm text-dark-400 mt-1">
            已缓存 <span className="text-gray-200 font-medium">{total}</span> 件商品。可单独为某商品配置 AI 提示词作为系统提示词的补充。
          </p>
        </div>
        <button onClick={handleSync} disabled={syncing} className="btn btn-primary">
          <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
          {syncing ? '同步中…' : '从闲鱼同步商品'}
        </button>
      </div>

      {/* Toolbar */}
      <div className="card card-body !p-4 flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-400 pointer-events-none" />
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="搜索商品标题…"
            className="input pl-10"
          />
        </div>
        <button onClick={handleSearch} className="btn btn-secondary">搜索</button>
      </div>

      {syncMsg && (
        <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/30 px-4 py-2.5 text-sm text-emerald-300">
          {syncMsg}
        </div>
      )}
      {error && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/30 px-4 py-2.5 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="text-dark-400 text-sm py-12 text-center">加载中…</div>
        ) : items.length === 0 && !error ? (
          <div className="text-dark-400 text-sm py-12 text-center">暂无商品缓存</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>商品 ID</th>
                  <th>卖家 ID</th>
                  <th>标题</th>
                  <th className="!text-right">价格</th>
                  <th>描述</th>
                  <th>AI 提示词</th>
                  <th>默认回复</th>
                  <th>缓存时间</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const expanded = expandedIds.has(item.id)
                  const hasDesc = !!item.description
                  const editing = editingPromptId === item.id
                  const saving = savingPromptId === item.id
                  const hasPrompt = !!(item.custom_prompt && item.custom_prompt.trim())
                  const editingReply = editingReplyId === item.id
                  const savingReply = savingReplyId === item.id
                  const hasReply = !!(item.default_reply && item.default_reply.trim())
                  return (
                    <tr key={item.id}>
                      <td className="font-mono text-xs text-dark-400 whitespace-nowrap">{item.item_id}</td>
                      <td className="font-mono text-xs text-dark-400 whitespace-nowrap">{item.seller_id || '-'}</td>
                      <td className="max-w-xs text-gray-100">{item.title || '-'}</td>
                      <td className="text-right text-primary-400 whitespace-nowrap font-medium">{item.price > 0 ? `¥${item.price}` : '-'}</td>
                      <td
                        onClick={() => hasDesc && toggleExpand(item.id)}
                        className={`max-w-md text-soft text-xs ${hasDesc ? 'cursor-pointer select-none' : ''} ${expanded ? 'whitespace-pre-line break-words' : ''}`}
                        title={hasDesc ? (expanded ? '点击收起' : '点击展开') : ''}
                      >
                        {hasDesc ? (
                          <span className="inline-flex items-start gap-1">
                            <span className="text-dark-500 mt-0.5 flex-shrink-0">
                              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            </span>
                            <span>
                              {expanded
                                ? item.description
                                : item.description.length > 30
                                  ? `${item.description.slice(0, 30)}…`
                                  : item.description}
                            </span>
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="max-w-md text-xs">
                        {editing ? (
                          <div className="space-y-2">
                            <textarea
                              value={promptDraft}
                              onChange={(e) => setPromptDraft(e.target.value)}
                              maxLength={2000}
                              rows={4}
                              className="input !p-2.5 text-xs"
                              placeholder="为该商品单独配置额外提示词（可空），AI 生成回复时追加在系统提示词之后"
                            />
                            <div className="flex gap-2 items-center">
                              <button onClick={() => savePrompt(item)} disabled={saving} className="btn btn-primary btn-sm">
                                {saving ? '保存中…' : '保存'}
                              </button>
                              <button onClick={cancelEditPrompt} disabled={saving} className="btn btn-secondary btn-sm">
                                取消
                              </button>
                              <span className="text-dark-500 ml-auto">{promptDraft.length}/2000</span>
                            </div>
                            {promptErr && <div className="text-red-400 text-xs">{promptErr}</div>}
                          </div>
                        ) : (
                          <button
                            onClick={() => startEditPrompt(item)}
                            className="inline-flex items-start gap-1.5 text-left text-soft hover:text-primary-300 transition-colors"
                            title="点击编辑"
                          >
                            <Pencil size={12} className="text-dark-500 mt-0.5 flex-shrink-0" />
                            <span className="break-words">
                              {hasPrompt ? (
                                item.custom_prompt.length > 20 ? `${item.custom_prompt.slice(0, 20)}…` : item.custom_prompt
                              ) : (
                                <span className="text-dark-500">未设置（点击配置）</span>
                              )}
                            </span>
                          </button>
                        )}
                      </td>
                      <td className="max-w-md text-xs">
                        {editingReply ? (
                          <div className="space-y-2">
                            <label className="inline-flex items-center gap-2 text-xs cursor-pointer select-none">
                              <input
                                type="checkbox"
                                checked={replyEnabledDraft}
                                onChange={(e) => setReplyEnabledDraft(e.target.checked)}
                                className="h-3.5 w-3.5 accent-primary-500"
                              />
                              <span className={replyEnabledDraft ? 'text-emerald-300' : 'text-dark-400'}>
                                {replyEnabledDraft ? '已启用（每会话首条消息回复一次，之后转 AI）' : '已禁用'}
                              </span>
                            </label>
                            <textarea
                              value={replyDraft}
                              onChange={(e) => setReplyDraft(e.target.value)}
                              maxLength={2000}
                              rows={3}
                              className="input !p-2.5 text-xs"
                              placeholder="启用后，仅对每个会话的第一条买家消息回复这段固定文本，之后交给 AI。插入 {$分隔符} 可把内容拆成多条消息分别发送。"
                            />
                            <div className="text-[10px] text-dark-500 leading-relaxed">
                              提示：在文本中插入 <code className="px-1 py-0.5 rounded bg-dark-700 text-primary-300">{'{$分隔符}'}</code> 占位符，发送时会按它把内容切割成多条消息依次发给买家。
                            </div>
                            <div className="flex gap-2 items-center">
                              <button onClick={() => saveReply(item)} disabled={savingReply} className="btn btn-primary btn-sm">
                                {savingReply ? '保存中…' : '保存'}
                              </button>
                              <button onClick={cancelEditReply} disabled={savingReply} className="btn btn-secondary btn-sm">
                                取消
                              </button>
                              <span className="text-dark-500 ml-auto">{replyDraft.length}/2000</span>
                            </div>
                            {replyErr && <div className="text-red-400 text-xs">{replyErr}</div>}
                          </div>
                        ) : (
                          <button
                            onClick={() => startEditReply(item)}
                            className="inline-flex items-start gap-1.5 text-left text-soft hover:text-primary-300 transition-colors w-full"
                            title="点击编辑"
                          >
                            <Pencil size={12} className="text-dark-500 mt-0.5 flex-shrink-0" />
                            <span className="break-words space-y-0.5">
                              <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium mr-1.5 ${item.default_reply_enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-dark-700 text-dark-400'}`}>
                                {item.default_reply_enabled ? '启用' : '禁用'}
                              </span>
                              {hasReply ? (
                                <span>
                                  {item.default_reply.length > 20 ? `${item.default_reply.slice(0, 20)}…` : item.default_reply}
                                </span>
                              ) : (
                                <span className="text-dark-500">未设置（点击配置）</span>
                              )}
                            </span>
                          </button>
                        )}
                      </td>
                      <td className="text-xs text-dark-500 whitespace-nowrap">
                        {item.fetched_at ? new Date(item.fetched_at).toLocaleString('zh-CN') : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-sm text-dark-400">第 {page}/{totalPages} 页</span>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="btn btn-secondary btn-sm">
              上一页
            </button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="btn btn-secondary btn-sm">
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
