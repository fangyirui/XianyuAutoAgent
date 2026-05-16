import { useEffect, useState } from 'react'
import { getPrompts, updatePrompt, getEnvConfig, updateEnvConfig, testAiConnection } from '@/api/config'
import QrLoginModal from '@/components/QrLoginModal'

type Tab = 'cookie' | 'ai' | 'prompts' | 'filter'
interface Prompt { name: string; content: string }
interface EnvConfig { API_KEY: string; MODEL_BASE_URL: string; MODEL_NAME: string; COOKIES_STR: string; SKIP_KEYWORDS: string }

const PROMPT_LABELS: Record<string, string> = {
  classify_prompt: '意图分类',
  price_prompt: '议价策略',
  tech_prompt: '技术支持',
  default_prompt: '通用回复',
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('cookie')
  const [env, setEnv] = useState<EnvConfig>({ API_KEY: '', MODEL_BASE_URL: '', MODEL_NAME: '', COOKIES_STR: '', SKIP_KEYWORDS: '' })
  const [cookieInput, setCookieInput] = useState('')
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null)
  const [promptEditing, setPromptEditing] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [msgType, setMsgType] = useState<'success' | 'error'>('success')
  const [showQr, setShowQr] = useState(false)
  const [aiTesting, setAiTesting] = useState(false)

  useEffect(() => {
    getEnvConfig().then((data) => { setEnv(data); setCookieInput(data.COOKIES_STR) }).catch(() => {})
    getPrompts().then((data) => {
      setPrompts(data)
      if (data.length > 0) { setSelectedPrompt(data[0]); setPromptEditing(data[0].content) }
    })
  }, [])

  const showMsg = (msg: string, type: 'success' | 'error' = 'success') => {
    setMessage(msg); setMsgType(type); setTimeout(() => setMessage(''), type === 'error' ? 8000 : 5000)
  }

  const handleSaveCookie = async () => {
    setSaving(true)
    await updateEnvConfig({ COOKIES_STR: cookieInput })
    showMsg('Cookie 已保存，服务正在重载')
    const fresh = await getEnvConfig()
    setEnv(fresh); setCookieInput(fresh.COOKIES_STR)
    setSaving(false)
  }

  const handleSaveAi = async () => {
    setSaving(true)
    await updateEnvConfig({ API_KEY: env.API_KEY, MODEL_BASE_URL: env.MODEL_BASE_URL, MODEL_NAME: env.MODEL_NAME })
    showMsg('AI 配置已保存，服务正在重载')
    const fresh = await getEnvConfig()
    setEnv(fresh)
    setSaving(false)
  }

  const handleTestAi = async () => {
    setAiTesting(true)
    const res = await testAiConnection({ api_key: env.API_KEY, base_url: env.MODEL_BASE_URL, model: env.MODEL_NAME })
    if (res.success) showMsg(`连接成功: ${res.reply}`)
    else showMsg(`连接失败: ${res.error}`, 'error')
    setAiTesting(false)
  }

  const handleSavePrompt = async () => {
    if (!selectedPrompt) return
    setSaving(true)
    await updatePrompt(selectedPrompt.name, promptEditing)
    setPrompts((prev) => prev.map((p) => (p.name === selectedPrompt.name ? { ...p, content: promptEditing } : p)))
    showMsg('提示词已保存')
    setSaving(false)
  }

  const handleSaveFilter = async () => {
    setSaving(true)
    await updateEnvConfig({ SKIP_KEYWORDS: env.SKIP_KEYWORDS })
    showMsg('过滤词已保存，服务正在重载')
    const fresh = await getEnvConfig()
    setEnv(fresh)
    setSaving(false)
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'cookie', label: 'Cookie 设置' },
    { key: 'ai', label: 'AI 配置' },
    { key: 'prompts', label: '提示词编辑' },
    { key: 'filter', label: '消息过滤' },
  ]

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">设置</h2>
      {message && <div className={`px-4 py-2 rounded-lg text-sm ${msgType === 'error' ? 'bg-red-900/50 text-red-300' : 'bg-emerald-900/50 text-emerald-300'}`}>{message}</div>}

      <div className="flex gap-2 border-b border-gray-700 pb-2">
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-t-lg text-sm ${tab === t.key ? 'bg-gray-700 text-emerald-400' : 'text-gray-400 hover:text-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'cookie' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Cookie 字符串（浏览器 F12 获取）</label>
            <textarea value={cookieInput} onChange={(e) => setCookieInput(e.target.value)} rows={6}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:border-emerald-400" />
          </div>
          <div className="flex gap-3">
            <button onClick={handleSaveCookie} disabled={saving}
              className="px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
              {saving ? '保存中...' : '保存 Cookie'}
            </button>
            <button onClick={() => setShowQr(true)}
              className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg text-sm hover:bg-gray-600">
              扫码登录
            </button>
          </div>
        </div>
      )}

      {tab === 'ai' && (
        <div className="space-y-4 max-w-xl">
          <div>
            <label className="block text-sm text-gray-400 mb-1">API Key</label>
            <input value={env.API_KEY} onChange={(e) => setEnv({ ...env, API_KEY: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-400" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Base URL</label>
            <input value={env.MODEL_BASE_URL} onChange={(e) => setEnv({ ...env, MODEL_BASE_URL: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-400" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">模型名称</label>
            <input value={env.MODEL_NAME} onChange={(e) => setEnv({ ...env, MODEL_NAME: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-400" />
          </div>
          <div className="flex gap-3">
            <button onClick={handleSaveAi} disabled={saving}
              className="px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
              {saving ? '保存中...' : '保存'}
            </button>
            <button onClick={handleTestAi} disabled={aiTesting}
              className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg text-sm hover:bg-gray-600 disabled:opacity-50">
              {aiTesting ? '测试中...' : '测试连接'}
            </button>
          </div>
        </div>
      )}

      {tab === 'prompts' && (
        <div className="flex gap-4 h-[calc(100vh-16rem)]">
          <div className="w-48 space-y-1">
            {prompts.map((p) => (
              <button key={p.name} onClick={() => { setSelectedPrompt(p); setPromptEditing(p.content) }}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm ${selectedPrompt?.name === p.name ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'}`}>
                {PROMPT_LABELS[p.name] || p.name}
              </button>
            ))}
          </div>
          <div className="flex-1 flex flex-col">
            <textarea value={promptEditing} onChange={(e) => setPromptEditing(e.target.value)}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:border-emerald-400" />
            <button onClick={handleSavePrompt} disabled={saving}
              className="mt-3 self-end px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      )}

      {tab === 'filter' && (
        <div className="space-y-4 max-w-xl">
          <div>
            <label className="block text-sm text-gray-400 mb-1">跳过关键词</label>
            <textarea value={env.SKIP_KEYWORDS} onChange={(e) => setEnv({ ...env, SKIP_KEYWORDS: e.target.value })} rows={6}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm font-mono resize-none focus:outline-none focus:border-emerald-400" />
            <p className="mt-2 text-xs text-gray-500 leading-relaxed">
              多个关键词用英文逗号分隔；命中任一关键词（子串匹配）的买家消息将被直接忽略，不写入对话历史也不调用 AI。
              <br />常用：<span className="font-mono text-gray-400">快给ta一个评价吧,有蚂蚁森林能量可领</span>
            </p>
          </div>
          <button onClick={handleSaveFilter} disabled={saving}
            className="px-4 py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      )}

      {showQr && <QrLoginModal onClose={() => { setShowQr(false); getEnvConfig().then((d) => { setEnv(d); setCookieInput(d.COOKIES_STR) }) }} />}
    </div>
  )
}
