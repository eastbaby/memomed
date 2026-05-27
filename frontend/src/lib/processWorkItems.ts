import type { AgentEvent } from '../types/agent'
import { eventSortValue } from './agentEventOrder.ts'

export type ProcessWorkItem = {
  firstGroupId: string
  group: AgentEvent
  children: AgentEvent[]
}

export function buildProcessWorkItems(events: AgentEvent[]) {
  const sortedEvents = [...events].sort((left, right) => eventSortValue(left) - eventSortValue(right))
  const groupKeyByWorkItemKey = new Map<string, string>()
  const grouped = new Map<string, ProcessWorkItem>()

  for (const event of sortedEvents) {
    if (event.event_type !== 'process.group.started') continue
    const key = workItemKey(event)
    groupKeyByWorkItemKey.set(workItemKey(event), key)
    const current = grouped.get(key)
    if (current) {
      current.group = event
      continue
    }
    grouped.set(key, { firstGroupId: event.id, group: event, children: [] })
  }

  for (const event of sortedEvents) {
    if (event.event_type !== 'process.step') continue
    const key = groupKeyByWorkItemKey.get(workItemKey(event))
    if (!key) continue
    const current = grouped.get(key)
    if (!current) continue
    current.children.push(event)
  }

  for (const item of grouped.values()) {
    item.children.sort(compareProcessSteps)
  }

  return grouped
}

function compareProcessSteps(left: AgentEvent, right: AgentEvent) {
  return processStepOrder(left) - processStepOrder(right) || eventSortValue(left) - eventSortValue(right)
}

function processStepOrder(event: AgentEvent) {
  const stepType = readStringPayload(event, 'step_type')
  if (stepType === 'agent.progress') return 0
  if (stepType === 'tool.started') return 1
  if (stepType === 'tool.observation') return 2
  if (stepType === 'tool.error') return 3
  return 9
}

function readStringPayload(event: AgentEvent, key: string) {
  const value = event.payload[key]
  return typeof value === 'string' ? value : null
}

export function workItemKey(event: AgentEvent) {
  return event.work_item_id ?? event.parent_event_id ?? event.id
}
