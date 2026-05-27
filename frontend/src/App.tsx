import { useEffect, useState } from 'react'
import {
  getAgentConversationEvents,
  listAgentConversations,
  streamAgentChat,
  streamAgentResume,
} from '@/api/memomedAgentClient'
import { ChatTimeline } from '@/components/agent/ChatTimeline'
import { Composer } from '@/components/agent/Composer'
import { InterruptCard } from '@/components/agent/InterruptCard'
import { SubjectRegistryPage } from '@/components/subjects/SubjectRegistryPage'
import { mergeAgentEvents } from '@/lib/agentEventTimeline'
import { elapsedSecondsFromLatestRunEvent, elapsedSecondsSince, shouldKeepElapsedTimerRunning, startedAtFromElapsedSeconds } from '@/lib/elapsedTime'
import { createOptimisticTimelineUi, type OptimisticTimelineUi } from '@/lib/optimisticTimelineUi'
import type { AgentConversation, AgentEvent, AgentRunResult, InteractionRequest } from '@/types/agent'

type AppPage = 'chat' | 'subjects'

export default function App() {
  const [activePage, setActivePage] = useState<AppPage>('chat')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<AgentConversation[]>([])
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [optimisticUi, setOptimisticUi] = useState<OptimisticTimelineUi | null>(null)
  const [interrupt, setInterrupt] = useState<InteractionRequest | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [runStartedAt, setRunStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [conversationListError, setConversationListError] = useState<string | null>(null)

  useEffect(() => {
    void refreshConversations()
  }, [])

  useEffect(() => {
    if (runStartedAt === null) {
      return
    }

    const timer = window.setInterval(() => {
      setElapsedSeconds(elapsedSecondsSince(runStartedAt))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [runStartedAt])

  async function refreshConversations() {
    try {
      setConversations(await listAgentConversations())
      setConversationListError(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : '历史列表加载失败'
      console.warn('Failed to refresh agent conversations', err)
      setConversationListError(message)
    }
  }

  async function handleLoadConversation(conversationId: string) {
    setIsLoading(true)
    setRunStartedAt(null)
    setError(null)
    try {
      const history = await getAgentConversationEvents(conversationId)
      setThreadId(history.conversation_id)
      setEvents(mergeAgentEvents([], history.events))
      setOptimisticUi(null)
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
    setOptimisticUi(null)
    setInterrupt(null)
    setRunStartedAt(null)
    setError(null)
  }

  async function handleSend(message: string) {
    let shouldStopTimer = true
    setIsLoading(true)
    setElapsedSeconds(0)
    setRunStartedAt(Date.now())
    setError(null)
    const nextThreadId = threadId ?? createThreadId()
    setThreadId(nextThreadId)
    setOptimisticUi(createOptimisticTimelineUi(nextThreadId, message))

    try {
      const result = await streamAgentChat({ thread_id: nextThreadId, message }, handleStreamEvent)
      applyResult(result)
      shouldStopTimer = !shouldKeepElapsedTimerRunning(result)
      void refreshConversations()
    } catch (err) {
      setOptimisticUi(null)
      setError(err instanceof Error ? err.message : '发送失败')
    } finally {
      setIsLoading(false)
      if (shouldStopTimer) setRunStartedAt(null)
    }
  }

  async function handleDecision(decision: Record<string, unknown>) {
    if (!threadId) return
    let shouldStopTimer = true
    const previousElapsedSeconds = elapsedSecondsFromLatestRunEvent(events)
    setIsLoading(true)
    if (runStartedAt === null) {
      setElapsedSeconds(previousElapsedSeconds)
      setRunStartedAt(startedAtFromElapsedSeconds(previousElapsedSeconds))
    }
    setError(null)
    setInterrupt(null)

    try {
      const result = await streamAgentResume({ thread_id: threadId, decision }, handleStreamEvent)
      applyResult(result)
      shouldStopTimer = !shouldKeepElapsedTimerRunning(result)
      void refreshConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交选择失败')
    } finally {
      setIsLoading(false)
      if (shouldStopTimer) setRunStartedAt(null)
    }
  }

  function applyResult(result: AgentRunResult) {
    setThreadId(result.thread_id)
    setEvents((current) => mergeAgentEvents(current, result.events))
    setOptimisticUi(null)
    setInterrupt(result.interrupt)
    if (result.status === 'error') {
      setError(result.error ?? 'Agent 没有返回最终回复，请稍后重试。')
    }
  }

  function handleStreamEvent(event: AgentEvent) {
    if (event.event_type === 'message.user') {
      setOptimisticUi(null)
    }
    setEvents((current) => mergeAgentEvents(current, [event]))
    if (event.event_type === 'interrupt.requested' && event.status === 'pending') {
      const interaction = event.payload?.interaction
      if (isInteractionRequest(interaction)) setInterrupt(interaction)
    }
  }

  return (
    <div className="min-h-screen bg-[#fbfaf6] text-stone-950">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-72 flex-col border-r border-stone-200 bg-[#f3f1e9] md:flex">
        <div className="flex h-16 items-center justify-between px-5">
          <div>
            <p className="text-lg font-black tracking-tight">Memomed</p>
            <p className="text-xs font-medium text-stone-500">Agent Lab</p>
          </div>
          <button
            onClick={handleNewConversation}
            className="rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm font-bold text-stone-700 shadow-sm transition hover:bg-stone-50"
          >
            新聊天
          </button>
        </div>

        <nav className="space-y-2 px-3">
          <button
            onClick={() => setActivePage('chat')}
            className={`w-full rounded-2xl px-4 py-3 text-left text-sm font-bold transition ${activePage === 'chat' ? 'bg-white text-stone-950 shadow-sm' : 'text-stone-600 hover:bg-white/70'}`}
          >
            聊天测试台
          </button>
          <button
            onClick={() => setActivePage('subjects')}
            className={`w-full rounded-2xl px-4 py-3 text-left text-sm font-bold transition ${activePage === 'subjects' ? 'bg-white text-teal-900 shadow-sm' : 'text-stone-600 hover:bg-white/70'}`}
          >
            成员与宠物
          </button>
        </nav>

        <div className="mt-6 flex min-h-0 flex-1 flex-col px-3">
          <div className="mb-2 flex items-center justify-between px-2">
            <h2 className="text-xs font-black tracking-[0.18em] text-stone-500">最近</h2>
            <span className="rounded-full bg-white px-2 py-0.5 text-xs font-bold text-stone-500">{conversations.length}</span>
          </div>
          {conversationListError ? (
            <p className="mb-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
              历史列表暂时无法刷新
            </p>
          ) : null}
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pb-4">
            {conversations.length === 0 ? (
              <p className="rounded-2xl bg-white/70 px-3 py-3 text-sm text-stone-500">暂无历史会话。</p>
            ) : (
              conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => {
                    setActivePage('chat')
                    void handleLoadConversation(conversation.id)
                  }}
                  disabled={isLoading}
                  className={`w-full rounded-2xl px-3 py-3 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${
                    conversation.id === threadId
                      ? 'bg-white text-stone-950 shadow-sm'
                      : 'text-stone-700 hover:bg-white/70'
                  }`}
                >
                  <span className="line-clamp-2 font-semibold">{conversation.title ?? '新的健康咨询'}</span>
                  <span className="mt-1 block text-xs text-stone-400">{formatConversationTime(conversation.updated_at)}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="border-t border-stone-200 p-4 text-xs text-stone-500">
          <p className="truncate">Thread: {threadId ?? '未开始'}</p>
        </div>
      </aside>

      <main className="min-h-screen md:ml-72">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-stone-200/70 bg-[#fbfaf6]/85 px-4 backdrop-blur-xl md:px-8">
          <div>
            <p className="text-sm font-black text-stone-950">{activePage === 'chat' ? '家庭医疗助手测试台' : '家庭成员与宠物档案'}</p>
            <p className="text-xs text-stone-500">{activePage === 'chat' ? 'Agent Loop / Interrupt / Streaming' : 'Subject Registry'}</p>
          </div>
          <div className="flex items-center gap-2 md:hidden">
            <button
              onClick={() => setActivePage('chat')}
              className={`rounded-xl px-3 py-2 text-xs font-bold ${activePage === 'chat' ? 'bg-stone-950 text-white' : 'bg-white text-stone-600'}`}
            >
              聊天
            </button>
            <button
              onClick={() => setActivePage('subjects')}
              className={`rounded-xl px-3 py-2 text-xs font-bold ${activePage === 'subjects' ? 'bg-teal-700 text-white' : 'bg-white text-stone-600'}`}
            >
              成员
            </button>
          </div>
        </header>

        {activePage === 'chat' ? (
          <section className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-3xl flex-col px-4 pb-40 pt-6 md:px-8">
            <div className="flex-1">
              <ChatTimeline events={events} optimisticUi={optimisticUi} runningElapsedSeconds={runStartedAt !== null ? elapsedSeconds : null} />
              {interrupt ? (
                <div className="mt-5">
                  <InterruptCard interaction={interrupt} disabled={isLoading} onDecision={handleDecision} />
                </div>
              ) : null}
              {error ? <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
            </div>
          </section>
        ) : (
          <div className="px-4 py-6 md:px-8">
            <SubjectRegistryPage />
          </div>
        )}
      </main>

      {activePage === 'chat' ? (
        <div className="fixed inset-x-0 bottom-0 z-30 bg-gradient-to-t from-[#fbfaf6] via-[#fbfaf6]/95 to-transparent px-4 pb-5 pt-10 md:left-72">
          <div className="mx-auto max-w-3xl">
            <Composer disabled={isLoading || Boolean(interrupt)} onSend={handleSend} />
            {interrupt ? <p className="mt-2 text-center text-xs text-stone-500">请先完成上方确认，再继续输入新消息。</p> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
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

function createThreadId() {
  if (globalThis.crypto?.randomUUID) {
    return `thread-${globalThis.crypto.randomUUID().replaceAll('-', '')}`
  }
  throw new Error('当前浏览器不支持 crypto.randomUUID，无法创建新会话')
}
