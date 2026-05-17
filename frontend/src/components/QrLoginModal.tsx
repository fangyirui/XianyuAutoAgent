import { useEffect, useRef, useState } from 'react'
import { startQrLogin, pollQrStatus } from '@/api/qrlogin'
import { QRCodeSVG } from 'qrcode.react'

interface Props { onClose: () => void }

export default function QrLoginModal({ onClose }: Props) {
  const [codeContent, setCodeContent] = useState('')
  const [status, setStatus] = useState<'loading' | 'ready' | 'scaned' | 'confirmed' | 'expired' | 'error'>('loading')
  const [error, setError] = useState('')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tRef = useRef('')

  const startLogin = async () => {
    setStatus('loading')
    setError('')
    const res = await startQrLogin()
    if (res.error) { setStatus('error'); setError(res.error); return }
    setCodeContent(res.codeContent)
    tRef.current = res.t
    setStatus('ready')
    startPolling(res.t)
  }

  const startPolling = (t: string) => {
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(async () => {
      const res = await pollQrStatus(t)
      if (res.status === 'CONFIRMED') {
        setStatus('confirmed')
        stopPolling()
        setTimeout(onClose, 1500)
      } else if (res.status === 'SCANED') {
        setStatus('scaned')
      } else if (res.status === 'EXPIRED') {
        setStatus('expired')
        stopPolling()
      }
    }, 2000)
  }

  const stopPolling = () => { if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null } }

  useEffect(() => { startLogin(); return stopPolling }, [])

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 px-4" onClick={onClose}>
      <div className="glass-card w-full max-w-sm p-6 space-y-4 animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-center text-gray-50">扫码登录闲鱼</h3>

        <div className="flex justify-center">
          {status === 'loading' && <div className="w-48 h-48 flex items-center justify-center text-dark-400">加载中…</div>}
          {(status === 'ready' || status === 'scaned') && codeContent && (
            <div className="bg-white p-3 rounded-2xl shadow-lg">
              <QRCodeSVG value={codeContent} size={180} />
            </div>
          )}
          {status === 'confirmed' && <div className="w-48 h-48 flex items-center justify-center text-emerald-400 text-lg font-medium">登录成功</div>}
          {status === 'expired' && <div className="w-48 h-48 flex items-center justify-center text-red-400">二维码已过期</div>}
          {status === 'error' && <div className="w-48 h-48 flex items-center justify-center text-red-400 text-sm text-center">{error}</div>}
        </div>

        <p className="text-center text-sm text-dark-400">
          {status === 'ready' && '请使用闲鱼 App 扫描二维码'}
          {status === 'scaned' && '已扫码，请在手机上确认'}
          {status === 'confirmed' && 'Cookie 已自动保存'}
        </p>

        <div className="flex justify-center gap-3">
          {(status === 'expired' || status === 'error') && (
            <button onClick={startLogin} className="btn btn-primary">重新获取</button>
          )}
          <button onClick={onClose} className="btn btn-secondary">关闭</button>
        </div>
      </div>
    </div>
  )
}
