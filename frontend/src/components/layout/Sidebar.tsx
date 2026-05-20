import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Settings, MessageSquare, ScrollText, Package, LogOut, Bot, X } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '仪表盘' },
  { to: '/runtime-logs', icon: ScrollText, label: '运行日志' },
  { to: '/logs', icon: MessageSquare, label: '对话日志' },
  { to: '/items', icon: Package, label: '商品配置' },
  { to: '/settings', icon: Settings, label: '设置' },
]

interface SidebarProps {
  open?: boolean
  onClose?: () => void
}

export default function Sidebar({ open = false, onClose }: SidebarProps) {
  const logout = useAuthStore((s) => s.logout)

  const handleNavClick = () => {
    onClose?.()
  }

  const handleLogout = () => {
    onClose?.()
    logout()
  }

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={`fixed inset-0 z-30 bg-black/60 backdrop-blur-sm transition-opacity duration-300 lg:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={`fixed left-0 top-0 z-40 flex h-screen w-64 flex-col bg-dark-900/90 backdrop-blur-xl border-r border-dark-700/60 transition-transform duration-300 lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand */}
        <div className="flex items-center gap-3 px-5 py-5 border-b border-dark-700/60">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-primary shadow-glow">
            <Bot size={20} className="text-white" />
          </div>
          <div className="flex flex-col leading-tight flex-1">
            <span className="text-base font-bold text-gray-50">XianyuAutoAgent</span>
            <span className="text-xs text-dark-400">闲鱼自动客服</span>
          </div>
          <button
            onClick={onClose}
            className="lg:hidden -mr-1 flex h-8 w-8 items-center justify-center rounded-lg text-dark-400 hover:bg-dark-800 hover:text-gray-100"
            aria-label="关闭菜单"
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          <div className="px-2 pt-2 pb-1 text-[11px] uppercase tracking-wider text-dark-400">
            导航
          </div>
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={handleNavClick}
              className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
            >
              <Icon size={18} className="flex-shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-dark-700/60 p-3">
          <button
            onClick={handleLogout}
            className="sidebar-link w-full text-dark-400 hover:text-red-400 hover:bg-red-500/10"
          >
            <LogOut size={18} className="flex-shrink-0" />
            <span>退出登录</span>
          </button>
        </div>
      </aside>
    </>
  )
}
