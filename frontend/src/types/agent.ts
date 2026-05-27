export type AgentStatus = 'completed' | 'interrupted' | 'error'

export type SelectOption = {
  label: string
  value: string
}

export type PendingAction = {
  id: string
  type: string
  continuation_tool: string
  candidate_payload?: Record<string, unknown>
}

export type InteractionRequest = {
  type: 'select_one' | 'confirm' | 'text_input'
  title: string
  description?: string | null
  options?: SelectOption[]
  placeholder?: string | null
  pending_action?: PendingAction | null
}

export type AgentMessage = {
  role: 'user' | 'assistant'
  content: string
}

export type AgentEvent = {
  id: string
  conversation_id: string
  turn_id?: string | null
  run_id?: string | null
  work_item_id?: string | null
  work_item_type?: string | null
  ordinal: number
  seq: number | null
  event_type: string
  role?: 'user' | 'assistant' | 'tool' | 'system' | null
  visibility: 'visible' | 'collapsed' | 'debug' | 'hidden'
  status: 'pending' | 'streaming' | 'completed' | 'failed'
  parent_event_id?: string | null
  dedupe_key?: string | null
  title?: string | null
  content?: string | null
  payload: Record<string, unknown>
}

export type AgentRunResult = {
  thread_id: string
  status: AgentStatus
  events: AgentEvent[]
  messages: AgentMessage[]
  interrupt: InteractionRequest | null
  error?: string | null
}

export type AgentConversation = {
  id: string
  title?: string | null
  status: string
  langgraph_thread_id: string
  last_event_seq: number
  created_at: string
  updated_at: string
}

export type AgentEventHistory = {
  conversation_id: string
  events: AgentEvent[]
  has_more: boolean
}
