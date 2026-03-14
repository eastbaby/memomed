import { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { Send, User, Bot, Loader2, PlusCircle } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const API_BASE = 'http://localhost:8010';

function App() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '您好！我是 Memomed 健康助手。我可以帮您管理病历报告、记录用药提醒，或者回答您的健康疑问。今天有什么我可以帮您的吗？' }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMsg: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await axios.post(`${API_BASE}/chat`, {
        message: input,
        history: messages.map(m => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content
        }))
      });

      setMessages(prev => [...prev, { role: 'assistant', content: response.data.reply }]);
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, { role: 'assistant', content: '抱歉，系统暂时出现了一点问题，请稍后再试。' }]);
    } finally {
      setIsLoading(false);
    }
  };

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
        <button className="text-slate-400 hover:text-white transition-colors">
          <PlusCircle size={24} />
        </button>
      </header>

      {/* Chat Area */}
      <main
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scroll-smooth"
      >
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex items-start gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 border 
                ${msg.role === 'user' ? 'bg-slate-800 border-slate-700' : 'bg-blue-900/30 border-blue-500/30'}`}
              >
                {msg.role === 'user' ? <User size={20} className="text-slate-300" /> : <Bot size={20} className="text-blue-400" />}
              </div>

              <div className={`max-w-[80%] px-4 py-3 rounded-2xl leading-relaxed shadow-sm
                ${msg.role === 'user'
                  ? 'bg-blue-600 text-white rounded-tr-none'
                  : 'bg-slate-800 text-slate-100 rounded-tl-none border border-slate-700'}`}
              >
                {msg.content}
              </div>
            </div>
          ))}
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
              disabled={!input.trim() || isLoading}
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
  );
}

export default App;
