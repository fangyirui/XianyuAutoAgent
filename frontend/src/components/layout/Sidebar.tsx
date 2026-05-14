import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Settings, MessageSquare, LogOut } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '仪表盘' },
  { to: '/logs', icon: MessageSquare, label: '对话日志' },
  { to: '/settings', icon: Settings, label: '设置' },
]

export default function Sidebar() {
  const logout = useAuthStore((s) => s.logout)
  return (
    <aside className="w-56 bg-gray-800 border-r border-gray-700 flex flex-col">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-semibold text-emerald-400">XianyuAutoAgent</h1>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} end={to === '/'}
            className={({ isActive }) => `flex items-center gap-3 px-3 py-2 rounded-lg text-sm ${isActive ? 'bg-gray-700 text-emerald-400' : 'text-gray-300 hover:bg-gray-700/50'}`}>
            <Icon size={18} />{label}
          </NavLink>
        ))}
      </nav>
      <button onClick={logout} className="flex items-center gap-3 px-5 py-3 text-sm text-gray-400 hover:text-red-400 border-t border-gray-700">
        <LogOut size={18} />退出登录
      </button>
    </aside>
  )
}
