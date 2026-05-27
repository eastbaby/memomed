import type { AgentEvent, AgentRunResult } from '@/types/agent'

export function formatElapsedSeconds(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds))
  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds.toString().padStart(2, '0')}s`
}

export function elapsedSecondsSince(startedAt: number, now: number = Date.now()) {
  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

export function elapsedSecondsFromLatestRunEvent(events: AgentEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.event_type !== 'run.elapsed') continue
    const elapsedSeconds = event.payload.elapsed_seconds
    if (typeof elapsedSeconds === 'number') return Math.max(0, Math.floor(elapsedSeconds))
  }
  return 0
}

export function startedAtFromElapsedSeconds(elapsedSeconds: number, now: number = Date.now()) {
  return now - Math.max(0, Math.floor(elapsedSeconds)) * 1000
}

export function shouldKeepElapsedTimerRunning(result: AgentRunResult) {
  return result.status === 'interrupted' || Boolean(result.interrupt)
}
