import { useEffect, useState } from 'react'
import {
  getAgentConversationEvents,
  listAgentConversations,
  resumeAgentChat,
  startAgentChat,
} from '@/api/memomedAgentClient'
import { ChatTimeline } from '@/components/agent/ChatTimeline'
import { Composer } from '@/components/agent/Composer'
import { InterruptCard } from '@/components/agent/InterruptCard'
import { SubjectRegistryPage } from '@/components/subjects/SubjectRegistryPage'
import type { AgentConversation, AgentEvent, AgentRunResult, InteractionRequest } from '@/types/agent'

type AppPage = 'chat' | 'subjects'

export default function App() {
  const [activePage, setActivePage] = useState<AppPage>('chat')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<AgentConversation[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [interrupt, setInterrupt] = useState<InteractionRequest | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void refreshConversations()
  }, [])

  async function refreshConversations() {
    try {
      setConversations(await listAgentConversations())
    } catch {
      // 历史列表不应该阻断当前聊天主流程。
    }
  }

  async function handleLoadConversation(conversationId: string) {
    setIsLoading(true)
    setError(null)
    try {
      const history = await getAgentConversationEvents(conversationId)
      setThreadId(history.conversation_id)
      setEvents(history.events)
      setInterrupt(extractPendingInterrupt(history.events))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载历史会话失败')
    } finally {
      setIsLoading(false)
    }
  }

  function handleNewConversation() {
    setThreadId(null)
    setEvents([])
    setInterrupt(null)
    setError(null)
  }

  async function handleSend(message: string) {
    setIsLoading(true)
    setError(null)

    try {
      const result = await startAgentChat({ thread_id: threadId ?? undefined, message })
      applyResult(result)
      void refreshConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleDecision(decision: Record<string, unknown>) {
    if (!threadId) return
    setIsLoading(true)
    setError(null)
    setInterrupt(null)

    try {
      const result = await resumeAgentChat({ thread_id: threadId, decision })
      applyResult(result)
      void refreshConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交选择失败')
    } finally {
      setIsLoading(false)
    }
  }

  function applyResult(result: AgentRunResult) {
    setThreadId(result.thread_id)
    setEvents((current) => mergeAgentEvents(current, result.events))
    setInterrupt(result.interrupt)
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#d9f99d_0,#f7f3ea_34%,#fdfaf3_100%)] text-stone-950">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-5 py-6">
        <header className="mb-6 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-800">Memomed Agent Lab</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight md:text-5xl">家庭医疗助手测试台</h1>
            <p className="mt-2 max-w-2xl text-sm text-stone-600">
              第一版专注测试 Agent Loop、过程展示、interrupt 选择题，以及成员/宠物事实源管理。
            </p>
          </div>
          <div className="flex flex-col items-stretch gap-3 sm:items-end">
            <div className="grid grid-cols-2 rounded-2xl border border-stone-200 bg-white/70 p-1 text-sm font-bold shadow-sm">
              <button
                onClick={() => setActivePage('chat')}
                className={`rounded-xl px-4 py-2 transition ${activePage === 'chat' ? 'bg-stone-950 text-white' : 'text-stone-600 hover:bg-white'}`}
              >
                聊天测试台
              </button>
              <button
                onClick={() => setActivePage('subjects')}
                className={`rounded-xl px-4 py-2 transition ${activePage === 'subjects' ? 'bg-teal-700 text-white' : 'text-stone-600 hover:bg-white'}`}
              >
                成员管理
              </button>
            </div>
            <div className="rounded-2xl border border-stone-200 bg-white/70 px-4 py-3 text-xs text-stone-600 shadow-sm">
              Thread: {threadId ?? '未开始'}
            </div>
            {activePage === 'chat' ? (
              <button
                onClick={handleNewConversation}
                className="rounded-2xl border border-stone-200 bg-white/80 px-4 py-3 text-sm font-bold text-stone-700 shadow-sm transition hover:bg-white"
              >
                新建会话
              </button>
            ) : null}
          </div>
        </header>

        {activePage === 'chat' ? (
          <>
            <div className="grid flex-1 gap-4 lg:grid-cols-[17rem_1fr]">
              <aside className="rounded-[2rem] border border-white/70 bg-white/55 p-4 shadow-xl shadow-stone-300/30 backdrop-blur">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-black tracking-[0.18em] text-teal-800">历史会话</h2>
                  <span className="rounded-full bg-white/80 px-2 py-1 text-xs font-bold text-stone-500">{conversations.length}</span>
                </div>
                <div className="mt-4 space-y-2">
                  {conversations.length === 0 ? (
                    <p className="rounded-2xl bg-white/70 px-3 py-3 text-sm text-stone-500">暂无历史会话。</p>
                  ) : (
                    conversations.map((conversation) => (
                      <button
                        key={conversation.id}
                        onClick={() => handleLoadConversation(conversation.id)}
                        disabled={isLoading}
                        className={`w-full rounded-2xl border px-3 py-3 text-left text-sm shadow-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${
                          conversation.id === threadId
                            ? 'border-teal-300 bg-teal-50 text-teal-950'
                            : 'border-stone-200 bg-white/75 text-stone-700 hover:bg-white'
                        }`}
                      >
                        <span className="line-clamp-2 font-bold">{conversation.title ?? '新的健康咨询'}</span>
                        <span className="mt-1 block text-xs text-stone-400">{formatConversationTime(conversation.updated_at)}</span>
                      </button>
                    ))
                  )}
                </div>
              </aside>

              <section className="rounded-[2rem] border border-white/70 bg-white/55 p-4 shadow-2xl shadow-stone-300/40 backdrop-blur">
                <ChatTimeline events={events} />
                {interrupt ? (
                  <div className="mt-5">
                    <InterruptCard interaction={interrupt} disabled={isLoading} onDecision={handleDecision} />
                  </div>
                ) : null}
                {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
              </section>
            </div>

            <footer className="mt-5">
              <Composer disabled={isLoading || Boolean(interrupt)} onSend={handleSend} />
              {interrupt ? <p className="mt-2 text-center text-xs text-stone-500">请先完成上方确认，再继续输入新消息。</p> : null}
            </footer>
          </>
        ) : (
          <SubjectRegistryPage />
        )}
      </div>
    </main>
  )
}

function mergeAgentEvents(current: AgentEvent[], incoming: AgentEvent[]) {
  if (incoming.length === 0) return current

  const indexById = new Map(current.map((event, index) => [event.id, index]))
  const merged = [...current]

  for (const event of incoming) {
    const index = indexById.get(event.id)
    if (index !== undefined) {
      merged[index] = { ...merged[index], ...event }
      continue
    }
    indexById.set(event.id, merged.length)
    merged.push(event)
  }

  return merged
}

function extractPendingInterrupt(events: AgentEvent[]) {
  const pendingInterrupt = [...events].reverse().find((event) => event.event_type === 'interrupt.requested' && event.status === 'pending')
  const interaction = pendingInterrupt?.payload?.interaction
  if (!isInteractionRequest(interaction)) return null
  return interaction
}

function isInteractionRequest(value: unknown): value is InteractionRequest {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<InteractionRequest>
  return (
    (candidate.type === 'select_one' || candidate.type === 'confirm' || candidate.type === 'text_input') &&
    typeof candidate.title === 'string'
  )
}

function formatConversationTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
