import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Lock, User } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { login } from '@/api/auth'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const authLogin = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const data = await login(username, password)
      authLogin(data.access_token, data.refresh_token, username)
      navigate('/')
    } catch {
      setError('用户名或密码错误')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="glass-card w-full max-w-sm p-8 space-y-5 animate-fade-in">
        <div className="flex flex-col items-center gap-3 pb-2">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-primary shadow-glow">
            <Bot size={28} className="text-white" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-bold text-gray-50">XianyuAutoAgent</h1>
            <p className="text-xs text-dark-400 mt-1">闲鱼自动客服管理后台</p>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <label className="input-label">用户名</label>
            <div className="relative">
              <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-400 pointer-events-none" />
              <input
                type="text"
                placeholder="请输入用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input pl-10"
                autoFocus
              />
            </div>
          </div>
          <div>
            <label className="input-label">密码</label>
            <div className="relative">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-400 pointer-events-none" />
              <input
                type="password"
                placeholder="请输入密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input pl-10"
              />
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-xl bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-300 text-center">
            {error}
          </div>
        )}

        <button type="submit" disabled={loading} className="btn btn-primary btn-lg w-full">
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  )
}
