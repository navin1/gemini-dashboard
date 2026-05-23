import { MessageCircle, X } from 'lucide-react'

interface Props {
  isOpen: boolean
  onToggle: () => void
  unread?: number
}

export function ChatBubble({ isOpen, onToggle, unread = 0 }: Props) {
  return (
    <button
      onClick={onToggle}
      title={isOpen ? 'Close AI Analyst' : 'Open AI Analyst'}
      className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-brand-600 hover:bg-brand-700 text-white shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center"
      style={{ bottom: isOpen ? '82vh' : '1.5rem' }}
    >
      <div className="relative">
        {isOpen ? <X size={22} /> : <MessageCircle size={22} />}
        {!isOpen && unread > 0 && (
          <span className="absolute -top-2 -right-2 h-4 w-4 bg-red-500 rounded-full text-[10px] font-bold flex items-center justify-center">
            {unread}
          </span>
        )}
      </div>
    </button>
  )
}
