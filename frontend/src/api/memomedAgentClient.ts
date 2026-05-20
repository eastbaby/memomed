import type { AgentConversation, AgentEvent, AgentEventHistory, AgentRunResult } from '@/types/agent'
import type {
  CareSubject,
  CreateAliasInput,
  CreateSubjectInput,
  UpdateAliasInput,
  UpdateSubjectInput,
} from '@/types/subjects'

const BACKEND_BASE_URL = import.meta.env.VITE_BACKEND_BASE_URL ?? 'http://localhost:8010'

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BACKEND_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BACKEND_BASE_URL}${path}`)

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BACKEND_BASE_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function startAgentChat(input: { thread_id?: string; message: string }) {
  return postJson<AgentRunResult>('/api/agent/chat', input)
}

export function resumeAgentChat(input: { thread_id: string; decision: Record<string, unknown> }) {
  return postJson<AgentRunResult>('/api/agent/resume', input)
}

export async function streamAgentChat(
  input: { thread_id: string; message: string },
  onEvent: (event: AgentEvent) => void,
) {
  return streamAgentRun(`/api/agent/conversations/${input.thread_id}/runs/stream`, input, onEvent)
}

export async function streamAgentResume(
  input: { thread_id: string; decision: Record<string, unknown> },
  onEvent: (event: AgentEvent) => void,
) {
  return streamAgentRun(`/api/agent/conversations/${input.thread_id}/runs/resume/stream`, input, onEvent)
}

export function listAgentConversations() {
  return getJson<AgentConversation[]>('/api/agent/conversations')
}

export function getAgentConversationEvents(conversationId: string) {
  return getJson<AgentEventHistory>(`/api/agent/conversations/${conversationId}/events?limit=200`)
}

export function listSubjects() {
  return getJson<CareSubject[]>('/api/subjects')
}

export function createSubject(input: CreateSubjectInput) {
  return postJson<CareSubject>('/api/subjects', input)
}

export function updateSubject(subjectId: string, input: UpdateSubjectInput) {
  return patchJson<CareSubject>(`/api/subjects/${subjectId}`, input)
}

export function createSubjectAlias(subjectId: string, input: CreateAliasInput) {
  return postJson<CareSubject>(`/api/subjects/${subjectId}/aliases`, input)
}

export function updateSubjectAlias(subjectId: string, aliasId: string, input: UpdateAliasInput) {
  return patchJson<CareSubject>(`/api/subjects/${subjectId}/aliases/${aliasId}`, input)
}

async function streamAgentRun(
  path: string,
  body: unknown,
  onEvent: (event: AgentEvent) => void,
) {
  const response = await fetch(`${BACKEND_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应')
  }

  const decoder = new TextDecoder()
  const reader = response.body.getReader()
  let buffer = ''
  let finalResult: AgentRunResult | null = null

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parsed = consumeSseBuffer(buffer)
    buffer = parsed.remainder
    for (const event of parsed.events) {
      if (event.event === 'error') {
        throw new Error(readStreamError(event.data))
      }
      if (event.event === 'agent_event') {
        onEvent(event.data as AgentEvent)
      }
      if (event.event === 'run_result') {
        finalResult = event.data as AgentRunResult
      }
    }
  }

  buffer += decoder.decode()
  const parsed = consumeSseBuffer(buffer + '\n\n')
  for (const event of parsed.events) {
    if (event.event === 'error') {
      throw new Error(readStreamError(event.data))
    }
    if (event.event === 'agent_event') {
      onEvent(event.data as AgentEvent)
    }
    if (event.event === 'run_result') {
      finalResult = event.data as AgentRunResult
    }
  }

  if (!finalResult) {
    throw new Error('流式响应缺少最终结果')
  }

  return finalResult
}

function consumeSseBuffer(buffer: string) {
  const events: Array<{ event: string; data: unknown }> = []
  const parts = buffer.split('\n\n')
  const remainder = parts.pop() ?? ''

  for (const part of parts) {
    const parsed = parseSseEvent(part)
    if (parsed) events.push(parsed)
  }

  return { events, remainder }
}

function parseSseEvent(block: string) {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim())
    }
  }

  if (dataLines.length === 0) return null
  return { event, data: JSON.parse(dataLines.join('\n')) }
}

function readStreamError(data: unknown) {
  if (data && typeof data === 'object' && 'message' in data) {
    const message = (data as { message?: unknown }).message
    if (typeof message === 'string' && message.length > 0) return message
  }
  return '流式请求失败'
}
