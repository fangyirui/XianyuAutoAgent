import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={handleSubmit} className="bg-gray-800 p-8 rounded-xl border border-gray-700 w-80 space-y-4">
        <h2 className="text-center text-lg font-semibold text-emerald-400">XianyuAutoAgent</h2>
        <input type="text" placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-emerald-400" />
        <input type="password" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm focus:outline-none focus:border-emerald-400" />
        {error && <p className="text-red-400 text-xs text-center">{error}</p>}
        <button type="submit" disabled={loading}
          className="w-full py-2 bg-emerald-500 text-gray-900 font-semibold rounded-lg text-sm hover:bg-emerald-400 disabled:opacity-50">
          {loading ? '登录中...' : '登录'}
        </button>
      </form>
    </div>
  )
}
