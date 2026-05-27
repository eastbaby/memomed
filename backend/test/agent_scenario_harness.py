from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Iterable
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.agent.api.schemas import AgentEvent, AgentRunResult, ChatRequest, ResumeRequest
from app.agent.events.service import assign_conversation_seq
from app.agent.runtime import AgentStreamPacket, stream_resume_chat, stream_start_chat
from app.agent.tools.patient import PatientGrounding, SubjectCandidate


@dataclass(frozen=True)
class SubjectFixture:
    subject_id: str
    patient_code: str
    display_name: str
    patient_type: str = "human"

    def to_candidate(self) -> SubjectCandidate:
        return SubjectCandidate(
            subject_id=self.subject_id,
            patient_code=self.patient_code,
            display_name=self.display_name,
            patient_type=self.patient_type,  # type: ignore[arg-type]
            aliases=[self.display_name, self.patient_code],
        )


@dataclass(frozen=True)
class ScenarioRun:
    live_events: list[AgentEvent]
    result: AgentRunResult


class FakeScriptedLLM:
    def __init__(self, responses: Iterable[AIMessage]) -> None:
        self._responses = list(responses)
        self.bound_call_count = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.bound_call_count += 1
        if not self._responses:
            raise AssertionError("FakeScriptedLLM received more calls than scripted responses.")
        return self._responses.pop(0)


class ScenarioEventStore:
    def __init__(self) -> None:
        self._events_by_thread: dict[str, list[AgentEvent]] = {}

    async def persist(self, result: AgentRunResult, *, trigger_type: str, **kwargs) -> AgentRunResult:
        existing = self._events_by_thread.setdefault(result.thread_id, [])
        if trigger_type == "resume_interrupt":
            existing[:] = [
                event.model_copy(update={"status": "completed"})
                if event.event_type == "interrupt.requested" and event.status == "pending"
                else event
                for event in existing
            ]
        persisted = assign_conversation_seq(result, seq_offset=len(existing))
        existing.extend(event.model_copy(deep=True) for event in persisted.events)
        return persisted

    def events(self, thread_id: str) -> list[AgentEvent]:
        return list(self._events_by_thread.get(thread_id, []))


async def collect_stream_with_store(stream, store: ScenarioEventStore | None = None) -> ScenarioRun:
    return await _collect_stream(stream)


class ScenarioRunner:
    def __init__(
        self,
        *,
        llm: FakeScriptedLLM,
        event_store: ScenarioEventStore,
        subjects: list[SubjectFixture],
    ) -> None:
        self.llm = llm
        self.event_store = event_store
        self.subjects = subjects

    async def stream_start(self, request: ChatRequest) -> ScenarioRun:
        async with self._patch_runtime():
            return await _collect_stream(stream_start_chat(request))

    async def stream_resume(self, request: ResumeRequest) -> ScenarioRun:
        async with self._patch_runtime():
            return await _collect_stream(stream_resume_chat(request))

    def _candidates(self) -> list[SubjectCandidate]:
        return [subject.to_candidate() for subject in self.subjects]

    def _ambiguous_grounding(self, user_text: str, candidates: list[SubjectCandidate]) -> PatientGrounding:
        return PatientGrounding(
            intent="unknown",
            resolution_status="ambiguous",
            candidate_subject_ids=[candidate.subject_id for candidate in candidates],
            confidence="low",
            reason="scenario fixture asks the user to choose the subject.",
            next_action="ask_patient_selection",
        )

    def _patch_runtime(self) -> AsyncExitStack:
        stack = AsyncExitStack()
        stack.enter_context(patch("app.agent.graph.get_openai_llm_stream", return_value=self.llm))
        stack.enter_context(patch("app.agent.runtime.persist_run_result", side_effect=self.event_store.persist))
        stack.enter_context(patch("app.agent.tools.patient.list_subject_candidates", side_effect=self._list_candidates))
        stack.enter_context(
            patch("app.agent.tools.patient.classify_patient_grounding", side_effect=self._ambiguous_grounding)
        )
        return stack

    async def _list_candidates(self, *args, **kwargs) -> list[SubjectCandidate]:
        return self._candidates()


async def _collect_stream(stream) -> ScenarioRun:
    live_events: list[AgentEvent] = []
    final_result: AgentRunResult | None = None
    async for packet in stream:
        if packet.event:
            live_events.append(packet.event)
        if packet.result:
            final_result = packet.result
    if final_result is None:
        raise AssertionError("Scenario stream ended without a final AgentRunResult.")
    return ScenarioRun(live_events=live_events, result=final_result)


def summarize_events(events: list[AgentEvent]) -> list[str]:
    return [_summarize_event(event) for event in events]


def _summarize_event(event: AgentEvent) -> str:
    prefix = f"{event.seq:03d} " if event.seq is not None else f"{event.ordinal:03d} "
    if event.event_type == "run.elapsed":
        return f"{prefix}run.elapsed"
    if event.event_type == "process.group.started":
        return f"{prefix}process.group.started[{event.work_item_type}]: {event.title}"
    if event.event_type == "process.step":
        step_type = event.payload.get("step_type")
        return f"{prefix}process.step[{event.work_item_type}/{step_type}]: {event.content}"
    if event.event_type == "interrupt.requested":
        return f"{prefix}interrupt.requested: {event.title}"
    if event.event_type == "interrupt.resumed":
        return f"{prefix}interrupt.resumed: {event.title}"
    return f"{prefix}{event.event_type}: {event.content}"
