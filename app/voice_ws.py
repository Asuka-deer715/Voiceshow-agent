"""Server-side streaming ASR/TTS boundary."""

import uuid

from .graph import agent_graph

async def voice_session(socket, user):
    session_id = await open_session(user.id)
    asr = asr_client.start_stream()
    tts = tts_client.start_stream()

    async for event in socket:
        if event.type == "audio_chunk":
            partial = await asr.push(event.bytes)
            await socket.send_json({"type": "asr_partial", "text": partial})
        elif event.type == "speech_end":
            query = await asr.finalize()
            result = await agent_graph.ainvoke({"session_id": session_id, "user_id": user.id, "trace_id": str(uuid.uuid4()), "query": query, "trace": [], "llm_used": False, "status": "processing"})
            for sentence in sentence_split(result.get("response", "")):
                await socket.send_bytes(await tts.synthesize(sentence))
            await socket.send_json({"type": "answer_end"})
