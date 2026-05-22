import { useEffect, useState } from 'react'
import {
  Activity,
  MessageCircle,
  Users,
  RefreshCw,
  UserPlus,
  Hand,
  Cpu,
  Coins,
  Bot,
  Clock,
  AlertTriangle,
  TrendingUp,
  HeartHandshake,
} from 'lucide-react'
import { DashboardStats, getStats } from '@/api/logs'
import { getWsStatus, reconnectWs } from '@/api/config'
import StatCard from '@/components/dashboard/StatCard'
import BarRow from '@/components/dashboard/BarRow'

const EMPTY_STATS: DashboardStats = {
  realtime: { manual_active: 0 },
  today: {
    conversations: 0,
    messages: 0,
    ai_replies: 0,
    user_messages: 0,
    new_buyers: 0,
    manual_takeover_triggered: 0,
    ai_calls: 0,
    tokens: 0,
    ai_errors: 0,
    ai_error_rate: 0,
    avg_latency_ms: 0,
    intent_distribution: [],
    agent_distribution: [],
  },
  cumulative: {
    conversations: 0,
    messages: 0,
    buyers: 0,
    bargain_sessions: 0,
    ai_calls: 0,
    tokens: 0,
  },
  total_conversations: 0,
  total_messages: 0,
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

function formatLatency(ms: number): string {
  if (ms <= 0) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatPercent(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS)
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

  const { realtime, today, cumulative } = stats
  const intentTotal = today.intent_distribution.reduce((s, x) => s + x.count, 0)
  const agentTotal = today.agent_distribution.reduce((s, x) => s + x.count, 0)
  const errorRateClass = today.ai_error_rate > 0.05 ? 'text-red-400' : 'text-gray-50'

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-50">仪表盘</h2>
          <p className="text-sm text-dark-400 mt-1">系统运行状态与对话统计</p>
        </div>
      </div>

      {/* 实时状态 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">实时状态</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

          <StatCard
            label="当前人工接管中"
            value={formatNumber(realtime.manual_active)}
            icon={<Hand size={22} />}
            iconWrapClassName="stat-icon-warning"
            hint="manual_mode=1 的会话数"
          />
        </div>
      </section>

      {/* 今日概览 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">
          今日概览（自零点起，Asia/Shanghai）
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="新增会话" value={formatNumber(today.conversations)} icon={<Users size={22} />} />
          <StatCard label="新增消息" value={formatNumber(today.messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="AI 回复" value={formatNumber(today.ai_replies)} icon={<Bot size={22} />} />
          <StatCard label="买家提问" value={formatNumber(today.user_messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="新增买家" value={formatNumber(today.new_buyers)} icon={<UserPlus size={22} />} />
          <StatCard label="触发接管次数" value={formatNumber(today.manual_takeover_triggered)} icon={<Hand size={22} />} iconWrapClassName="stat-icon-warning" />
          <StatCard label="AI 调用次数" value={formatNumber(today.ai_calls)} icon={<Cpu size={22} />} />
          <StatCard label="Token 消耗" value={formatNumber(today.tokens)} icon={<Coins size={22} />} />
          <StatCard
            label="平均响应时长"
            value={formatLatency(today.avg_latency_ms)}
            icon={<Clock size={22} />}
          />
          <StatCard
            label="AI 错误率"
            value={formatPercent(today.ai_error_rate)}
            icon={<AlertTriangle size={22} />}
            iconWrapClassName={today.ai_error_rate > 0.05 ? 'stat-icon-danger' : 'stat-icon-warning'}
            valueClassName={errorRateClass}
            hint={`失败 ${formatNumber(today.ai_errors)} / 总 ${formatNumber(today.ai_calls)}`}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <div className="card p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-50 mb-2">今日意图分布</p>
            {today.intent_distribution.length === 0 ? (
              <p className="text-sm text-dark-400">暂无数据</p>
            ) : (
              today.intent_distribution.map((item) => (
                <BarRow
                  key={item.name}
                  label={item.name}
                  count={item.count}
                  percent={intentTotal > 0 ? (item.count / intentTotal) * 100 : 0}
                />
              ))
            )}
          </div>
          <div className="card p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-50 mb-2">今日 Agent 调用拆分</p>
            {today.agent_distribution.length === 0 ? (
              <p className="text-sm text-dark-400">暂无数据</p>
            ) : (
              today.agent_distribution.map((item) => (
                <BarRow
                  key={item.name}
                  label={item.name}
                  count={item.count}
                  percent={agentTotal > 0 ? (item.count / agentTotal) * 100 : 0}
                />
              ))
            )}
          </div>
        </div>
      </section>

      {/* 累计 */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-dark-300 uppercase tracking-wide">累计</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <StatCard label="累计会话" value={formatNumber(cumulative.conversations)} icon={<Users size={22} />} />
          <StatCard label="累计消息" value={formatNumber(cumulative.messages)} icon={<MessageCircle size={22} />} />
          <StatCard label="累计买家" value={formatNumber(cumulative.buyers)} icon={<UserPlus size={22} />} />
          <StatCard label="议价会话" value={formatNumber(cumulative.bargain_sessions)} icon={<HeartHandshake size={22} />} iconWrapClassName="stat-icon-warning" />
          <StatCard label="AI 调用次数" value={formatNumber(cumulative.ai_calls)} icon={<Cpu size={22} />} />
          <StatCard label="Token 消耗" value={formatNumber(cumulative.tokens)} icon={<TrendingUp size={22} />} />
        </div>
      </section>
    </div>
  )
}
