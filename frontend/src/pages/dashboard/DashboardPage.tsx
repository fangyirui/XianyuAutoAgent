import { useEffect, useState } from 'react'
import { getStats } from '@/api/logs'
import { getWsStatus, reconnectWs } from '@/api/config'

export default function DashboardPage() {
  const [stats, setStats] = useState({ total_conversations: 0, total_messages: 0 })
  const [wsStatus, setWsStatus] = useState<{ connected: boolean }>({ connected: false })

  useEffect(() => {
    getStats().then(setStats).catch(() => {})
    getWsStatus().then(setWsStatus).catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">仪表盘</h2>
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">连接状态</p>
          <p className={`text-lg font-semibold ${wsStatus.connected ? 'text-emerald-400' : 'text-red-400'}`}>
            {wsStatus.connected ? '已连接' : '未连接'}
          </p>
          {!wsStatus.connected && (
            <button onClick={() => reconnectWs()} className="mt-2 text-xs text-emerald-400 hover:underline">重新连接</button>
          )}
        </div>
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">总会话数</p>
          <p className="text-lg font-semibold">{stats.total_conversations}</p>
        </div>
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <p className="text-sm text-gray-400">总消息数</p>
          <p className="text-lg font-semibold">{stats.total_messages}</p>
        </div>
      </div>
    </div>
  )
}
