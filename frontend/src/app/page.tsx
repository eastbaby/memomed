'use client'

import { useState, useEffect, useRef } from 'react'
import { useChat } from '@ai-sdk/react'
import { TextStreamChatTransport } from 'ai'
import { Streamdown } from 'streamdown'
import 'streamdown/styles.css'
import { Send, User, Bot, Loader2, PlusCircle, Copy, Trash2, Check } from 'lucide-react'

export default function Home() {
  const [input, setInput] = useState('')
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const {
    messages,
    sendMessage,
    status,
    error,
    setMessages,
  } = useChat({
    transport: new TextStreamChatTransport({ api: '/api/chat' }),
    onError: (err) => {
      console.error('Chat error:', err)
      // 可以在这里添加错误提示逻辑
    },
  })

  // Auto scroll to bottom when new messages arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight
    }
  }, [messages, status])

  const handleSend = () => {
    sendMessage({ text: input })
    setInput('')
  }

  const handleClearChat = () => {
    if (confirm('确定要清空聊天记录吗？')) {
      setMessages([])
    }
  }

  const isLoading = status === 'streaming' || status === 'submitted'

  const handleCopyMessage = (id: number, content: string) => {
    navigator.clipboard.writeText(content)
    setCopiedMessageId(id)
    setTimeout(() => setCopiedMessageId(null), 2000)
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100 font-sans">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/50 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/20">
            <span className="text-white font-bold text-lg">M</span>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Memomed <span className="text-blue-500 text-sm font-normal">v0.0.1</span></h1>
        </div>
        <div className="flex items-center gap-4">
          <button 
            onClick={handleClearChat}
            className="text-slate-400 hover:text-white transition-colors"
            title="清空聊天记录"
          >
            <Trash2 size={24} />
          </button>
          <button className="text-slate-400 hover:text-white transition-colors" title="添加">
            <PlusCircle size={24} />
          </button>
        </div>
      </header>

      {/* Chat Area */}
      <main 
        ref={chatContainerRef}
        className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scroll-smooth"
      >
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, i) => {
            // Extract text content from message parts
            const content = msg.parts?.map(part => {
              if (typeof part === 'string') return part;
              if ('text' in part) return part.text;
              return '';
            }).join('') || '';
            
            return (
              <div
                key={i}
                className={`flex items-start gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 border 
                  ${msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-blue-900/30 border-blue-500/30'}`}
                >
                  {msg.role === 'user' ? <User size={20} className="text-slate-300" /> : <Bot size={20} className="text-blue-400" />}
                </div>

                <div className="flex-1 max-w-[80%]">
                  <div className={`px-4 py-3 rounded-2xl leading-relaxed shadow-sm relative
                    ${msg.role === 'user'
                      ? 'bg-blue-600 text-white rounded-tr-none'
                      : 'bg-slate-800 text-slate-100 rounded-tl-none border border-slate-700'}`}
                  >
                    {msg.role === 'assistant' ? (
                      <Streamdown animated>{content}</Streamdown>
                    ) : (
                      content
                    )}
                    <div className="absolute top-2 right-2 flex items-center gap-2">
                      <button
                        onClick={() => handleCopyMessage(i, content)}
                        className="text-xs opacity-50 hover:opacity-100 transition-opacity"
                        title="复制消息"
                      >
                        {copiedMessageId === i ? <Check size={16} /> : <Copy size={16} />}
                      </button>
                    </div>
                  </div>
                  <div className={`text-xs text-slate-500 mt-1 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                    {new Date().toLocaleTimeString()}
                  </div>
                </div>
              </div>
            );
          })}
          {isLoading && (
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 bg-blue-900/30 border border-blue-500/30">
                <Bot size={20} className="text-blue-400" />
              </div>
              <div className="px-4 py-3 bg-slate-800 rounded-2xl rounded-tl-none border border-slate-700 flex items-center">
                <Loader2 className="animate-spin text-blue-400" size={20} />
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Input Area */}
      <footer className="p-4 md:p-8 bg-gradient-to-t from-slate-950 to-transparent">
        <div className="max-w-3xl mx-auto relative group">
          <div className="absolute -inset-1 bg-gradient-to-r from-blue-600 to-indigo-600 rounded-2xl blur opacity-20 group-focus-within:opacity-40 transition-opacity duration-300"></div>
          <div className="relative flex items-center bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="问问 Memomed，例如：如何查看我的报告？"
              className="flex-1 bg-transparent px-6 py-4 text-slate-100 placeholder:text-slate-500 focus:outline-none"
            />
            <button
              onClick={handleSend}
              disabled={!input?.trim() || isLoading}
              className="p-3 mr-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-xl transition-all duration-200 active:scale-95 shadow-lg shadow-blue-500/20"
            >
              <Send size={20} />
            </button>
          </div>
          <p className="text-center text-xs text-slate-600 mt-4">
            Memomed 提供的健康建议仅供参考，请以医嘱为准。
          </p>
        </div>
      </footer>
    </div>
  )
}
