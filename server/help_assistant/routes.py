"""Private API: both the gateway key and the original caller JWT are required."""
import asyncio
import time
from uuid import UUID, uuid4
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .context import Caller
from .grounding import guides, selection_payload, grounded_answer, NOTICE, OFF_TOPIC, is_system_question, knowledge_query
from .knowledge import combine_facts, knowledge_version
from .speech_service import speech
from .spoken_reply import spoken_summary, spoken_parts
from .speech_cache import SpeechCache
from .model_policy import CHAT_MODEL, LIVE_MODEL, model_for

class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=2000)
    projectId: UUID | None = None
    history: list[str] = Field(default_factory=list, max_length=3)
    requestId: UUID
    mode: Literal['chat', 'live'] = 'chat'

class Audio(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audio: str = Field(min_length=44, max_length=1_500_000)

class Reply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    replyId: UUID
    part: int | None = Field(default=None, ge=0, le=3)

def make_router(queue):
    router = APIRouter(prefix='/api/help-assistant', tags=['help-assistant'])
    replies = {}
    in_flight = set()
    audio_cache = SpeechCache()

    async def caller(request):
        owner = request.headers.get('X-eFlow-User-Id', '')
        if not owner:
            raise HTTPException(401, 'A current eFlow session is required.')
        return await Caller(request.headers.get('X-eFlow-Session', '')).verify(owner)

    @router.get('/status')
    async def status(request: Request):
        await caller(request)
        return {'model': CHAT_MODEL, 'liveModel': LIVE_MODEL, 'speechInstalled': speech.available(), 'asr': 'moondream/parakeet-redux', 'tts': 'KittenML/kitten-tts-2', 'notice': NOTICE, 'readOnly': True}

    @router.get('/projects')
    async def projects(request: Request):
        return {'projects': await (await caller(request)).projects(), 'limit': 100}

    @router.post('/chat')
    async def chat(payload: Question, request: Request):
        current = await caller(request)
        owner = current.profile['id']
        if owner in in_flight:
            raise HTTPException(429, 'Your previous help request is still processing.')
        in_flight.add(owner)
        job_id = None
        try:
            observed = time.time()
            original_role = current.profile['role']
            selected_model = model_for(payload.mode)
            if any(len(question) > 2000 for question in payload.history):
                raise HTTPException(422, 'The previous questions are too long.')
            in_scope = is_system_question(payload.question, payload.history)
            live = await current.project_facts(str(payload.projectId)) if payload.projectId and in_scope else []
            facts = combine_facts(live, guides(knowledge_query(payload.question, payload.history), current.profile['role'])) if in_scope else []
            if not facts:
                answer = grounded_answer('{}', [], selected_model)
                if not in_scope:
                    answer['answer'] = OFF_TOPIC
            else:
                body = selection_payload(payload.question, facts, payload.history, selected_model)
                try:
                    snapshot = await queue.submit(owner, body, request_id='help-' + str(payload.requestId))
                except ValueError as exc:
                    raise HTTPException(429, 'The AI queue is busy. Please try again shortly.') from exc
                job_id = snapshot['job_id']
                deadline = time.monotonic() + 180
                while snapshot['status'] in ('queued', 'processing'):
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                    if time.monotonic() > deadline:
                        raise HTTPException(504, 'Help is taking too long. Please try again shortly.')
                    await asyncio.sleep(.25)
                    snapshot = await queue.snapshot(job_id, owner)
                if snapshot['status'] != 'completed':
                    raise HTTPException(503, 'The AI could not finish this reply. Please try again.')
                answer = grounded_answer(snapshot['result']['message']['content'], facts, selected_model)
            # A request waiting in the model queue must not deliver data after
            # the caller has lost account/project access.
            await current.verify(owner)
            if current.profile['role'] != original_role:
                raise HTTPException(409, 'Your account role changed. Ask again with your current access.')
            await current.recheck(answer['sources'])
            reply_id = str(uuid4())
            now = time.monotonic()
            for key in list(replies):
                if replies[key]['expires'] < now:
                    del replies[key]
            if len(replies) >= 200:
                del replies[next(iter(replies))]
            replies[reply_id] = {'owner': owner, 'role': original_role, 'text': answer['answer'], 'expires': now + 300, 'sources': answer['sources']}
            return {**answer, 'replyId': reply_id, 'observedAt': observed, 'knowledgeVersion': knowledge_version()}
        finally:
            in_flight.discard(owner)
            if job_id:
                await queue.cancel(job_id, owner)

    @router.post('/transcribe')
    async def transcribe(payload: Audio, request: Request):
        await caller(request)
        return await speech.call('transcribe', {'audio': payload.audio})

    @router.post('/speech')
    async def speak(payload: Reply, request: Request):
        current = await caller(request)
        record = replies.get(str(payload.replyId))
        if not record or record['owner'] != current.profile['id'] or record['expires'] < time.monotonic():
            raise HTTPException(404, 'This spoken reply expired. Ask the question again.')
        if current.profile['role'] != record['role']:
            raise HTTPException(409, 'Your account role changed. Ask again with your current access.')
        await current.recheck(record['sources'])
        spoken = spoken_summary(record['text'])
        metadata = {}
        if payload.part is not None:
            parts = spoken_parts(record['text'])
            if payload.part >= len(parts):
                raise HTTPException(422, 'This spoken reply part does not exist.')
            spoken = parts[payload.part]
            metadata = {'part': payload.part, 'parts': len(parts)}
        cache_key = (current.profile['id'], record['role'], spoken)
        cached = audio_cache.get(cache_key)
        if cached:
            # Reuse never skips the same current-account and source checks
            # required after native generation.
            await current.verify(current.profile['id'])
            if current.profile['role'] != record['role']:
                raise HTTPException(409, 'Your account role changed. Ask again with your current access.')
            await current.recheck(record['sources'])
            return {**cached, **metadata, 'cached': True}
        operation = str(uuid4())
        owner = current.profile['id']
        try:
            job = await queue.submit(owner, {'model': 'kitten-tts-2', '_help_speech': {'id': operation, 'text': spoken}})
        except ValueError as exc:
            raise HTTPException(429, 'The AI queue is busy. The written answer is available.') from exc
        try:
            deadline = time.monotonic() + 190
            while job['status'] in ('queued', 'processing'):
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
                if time.monotonic() > deadline:
                    raise HTTPException(504, 'Speech is taking too long. The written answer is available.')
                await asyncio.sleep(.25)
                job = await queue.snapshot(job['job_id'], owner)
            if job['status'] != 'completed' or operation not in speech.results:
                raise HTTPException(503, 'Speech could not finish. The written answer is available.')
            await current.verify(owner)
            if current.profile['role'] != record['role']:
                raise HTTPException(409, 'Your account role changed. Ask again with your current access.')
            await current.recheck(record['sources'])
            audio_cache.put(cache_key, speech.results[operation])
            return {**speech.results[operation], **metadata, 'cached': False}
        finally:
            await queue.cancel(job['job_id'], owner)
            speech.results.pop(operation, None)

    return router
