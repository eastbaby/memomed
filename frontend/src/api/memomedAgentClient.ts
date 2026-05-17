import type { AgentConversation, AgentEventHistory, AgentRunResult } from '@/types/agent'
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
