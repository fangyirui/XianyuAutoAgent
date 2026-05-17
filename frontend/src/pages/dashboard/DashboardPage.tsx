import { useEffect, useState } from 'react'
import { Activity, MessageCircle, Users, RefreshCw } from 'lucide-react'
import { getStats } from '@/api/logs'
import { getWsStatus, reconnectWs } from '@/api/config'

export default function DashboardPage() {
  const [stats, setStats] = useState({ total_conversations: 0, total_messages: 0 })
  const [wsStatus, setWsStatus] = useState<{ connected: boolean }>({ connected: false })
  const [reconnecting, setReconnecting] = useState(false)

  const refresh = () => {
    getStats().then(setStats).catch(() => {})
    getWsStatus().then(setWsStatus).catch(() => {})
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 15000)
    return () => clearInterval(t)
  }, [])

  const handleReconnect = async () => {
    if (reconnecting) return
    setReconnecting(true)
    try {
      await reconnectWs()
      setTimeout(refresh, 1000)
    } finally {
      setReconnecting(false)
    }
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-50">仪表盘</h2>
          <p className="text-sm text-dark-400 mt-1">系统运行状态与对话统计</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="stat-card card-hover">
          <div className={`stat-icon ${wsStatus.connected ? 'stat-icon-success' : 'stat-icon-danger'}`}>
            <Activity size={22} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-dark-400">闲鱼连接状态</p>
            <p className={`text-xl font-bold mt-1 ${wsStatus.connected ? 'text-emerald-400' : 'text-red-400'}`}>
              {wsStatus.connected ? '已连接' : '未连接'}
            </p>
            {!wsStatus.connected && (
              <button
                onClick={handleReconnect}
                disabled={reconnecting}
                className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary-400 hover:text-primary-300 disabled:opacity-50"
              >
                <RefreshCw size={12} className={reconnecting ? 'animate-spin' : ''} />
                {reconnecting ? '重连中…' : '重新连接'}
              </button>
            )}
          </div>
        </div>

        <div className="stat-card card-hover">
          <div className="stat-icon stat-icon-primary">
            <Users size={22} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-dark-400">总会话数</p>
            <p className="text-2xl font-bold text-gray-50 mt-1">{stats.total_conversations}</p>
          </div>
        </div>

        <div className="stat-card card-hover">
          <div className="stat-icon stat-icon-warning">
            <MessageCircle size={22} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-dark-400">总消息数</p>
            <p className="text-2xl font-bold text-gray-50 mt-1">{stats.total_messages}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
