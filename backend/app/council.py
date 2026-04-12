from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.council_agents import (
    AGENTS,
    get_agent_display_name,
    get_agent_system_prompt,
    get_tools,
)
from app.voice import agent_speak, narrator_speak

logger = logging.getLogger(__name__)

# Deliberation rounds removed to stay within free-tier quota (20 req/day).
# Flow: opening statements (4 calls) → voting (4 calls) = 8 Gemini calls total.
MAX_RETRY_ATTEMPTS = 3

# Maps each agent to the display names of the other three, for acknowledgements.
_PEERS: dict[str, str] = {
    "analyst":  "The Diplomat, The Sentinel, and The Explorer",
    "diplomat": "The Analyst, The Sentinel, and The Explorer",
    "sentinel": "The Analyst, The Diplomat, and The Explorer",
    "explorer": "The Analyst, The Diplomat, and The Sentinel",
}

# One peer each agent naturally addresses first.
_FIRST_PEER: dict[str, str] = {
    "analyst":  "The Sentinel",
    "diplomat": "The Analyst",
    "sentinel": "The Diplomat",
    "explorer": "The Sentinel",
}


class Vote(BaseModel):
    agent: str
    vote: Literal["approve", "reject"]
    reasoning: str


async def _call_with_retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with exponential backoff on transient 429/503.
    Daily quota exhaustion (quotaId contains 'PerDay') raises immediately.
    """
    delay = 15.0
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            msg = str(e)
            is_rate_limit = (
                "429" in msg or "503" in msg
                or "RESOURCE_EXHAUSTED" in msg
                or "UNAVAILABLE" in msg
            )
            is_daily_quota = (
                "PerDay" in msg
                or "per_day" in msg.lower()
                or "daily" in msg.lower()
            )

            if is_rate_limit and is_daily_quota:
                raise RuntimeError(
                    "Daily Gemini quota exhausted. Quota resets at midnight Pacific. "
                    "Upgrade to a paid plan at https://ai.google.dev to remove this limit."
                ) from e

            if is_rate_limit and attempt < MAX_RETRY_ATTEMPTS - 1:
                match = re.search(r"retry in (\d+(?:\.\d+)?)s", msg, re.IGNORECASE)
                wait = float(match.group(1)) + 2 if match else delay
                logger.warning(
                    "Rate limit hit, retrying in %.0fs (attempt %d/%d)",
                    wait, attempt + 1, MAX_RETRY_ATTEMPTS,
                )
                await asyncio.sleep(wait)
                delay *= 2
            else:
                raise


class CouncilOrchestrator:
    def __init__(
        self,
        discussion_id: str,
        idea: str,
        event_queue: asyncio.Queue[dict],
    ):
        self.discussion_id = discussion_id
        self.idea = idea

        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        self.agent_inboxes: Dict[str, List[Dict]] = {a: [] for a in AGENTS}
        self.votes: Dict[str, Vote] = {}
        self.debate_complete = False

        self.event_queue = event_queue

        self.tool_functions = get_tools()
        self.tools = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(**func) for func in self.tool_functions
            ]
        )

    async def _emit(self, event_type: str, data: dict):
        await self.event_queue.put({
            "type": event_type,
            **data,
            "timestamp": datetime.now().isoformat(),
        })

    async def _call_gemini(
        self, agent_name: str, context: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        return await _call_with_retry(
            self.client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=context,
            config=config,
        )

    async def _opening_statement(self, agent_name: str):
        peer = _FIRST_PEER[agent_name]
        config = types.GenerateContentConfig(
            system_instruction=get_agent_system_prompt(agent_name),
            max_output_tokens=120,
            temperature=0.85,
        )
        context = (
            f"PROPOSAL:\n{self.idea}\n\n"
            f"You are addressing the council chamber. The other members present are: {_PEERS[agent_name]}.\n"
            f"Speak directly to {peer} first — acknowledge their likely perspective in one short phrase — "
            "then deliver your single most critical insight about this investment.\n"
            "Two sentences maximum. Under 45 words total. No bullet points. "
            "Be dramatic, precise, and cinematic."
        )
        try:
            response = await self._call_gemini(agent_name, context, config)
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            speech = part.text.strip()
                            audio = await agent_speak(speech, agent_name)
                            await self._emit("council_thinking", {
                                "agent_id": agent_name,
                                "agent": get_agent_display_name(agent_name),
                                "content": speech,
                                "audio_b64": audio,
                            })
        except Exception as e:
            await self._emit("council_error", {
                "agent_id": agent_name,
                "agent": get_agent_display_name(agent_name),
                "error": str(e),
            })

    async def _cast_vote(self, agent_name: str) -> Vote:
        config = types.GenerateContentConfig(
            system_instruction=get_agent_system_prompt(agent_name),
            max_output_tokens=120,
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "vote": {
                        "type": "string",
                        "enum": ["approve", "reject"],
                        "description": "Your final vote on the proposal.",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "One powerful sentence — your decisive reason.",
                    },
                },
                "required": ["vote", "reasoning"],
            },
        )
        context = (
            f"PROPOSAL: {self.idea}\n\n"
            "The chamber is silent. Cast your solemn, final vote. "
            "Your reasoning must be one short, commanding sentence — under 20 words."
        )
        response = await self._call_gemini(agent_name, context, config)
        if response.text is None:
            raise ValueError("No response from Gemini")
        vote_data = json.loads(response.text)
        return Vote(
            agent=agent_name,
            vote=vote_data["vote"],
            reasoning=vote_data["reasoning"],
        )

    async def run_debate(self):
        # ── Opening statements ─────────────────────────────────────────────
        await self._emit("council_phase", {
            "phase": "opening_statements",
            "message": "The council convenes. Each member addresses the chamber...",
        })

        for agent_name in AGENTS:
            await self._opening_statement(agent_name)
            await asyncio.sleep(1)

        # ── Voting ─────────────────────────────────────────────────────────
        await self._emit("council_phase", {
            "phase": "voting",
            "message": "The chamber falls silent. The vote begins.",
        })

        for agent_name in AGENTS:
            try:
                vote = await self._cast_vote(agent_name)
                self.votes[agent_name] = vote

                # Build a spoken version of the vote for TTS
                spoken_vote = (
                    f"I cast my vote to {vote.vote}. {vote.reasoning}"
                )
                audio = await agent_speak(spoken_vote, agent_name)

                await self._emit("council_vote", {
                    "agent_id": agent_name,
                    "agent": get_agent_display_name(agent_name),
                    "vote": vote.vote,
                    "reasoning": vote.reasoning,
                    "audio_b64": audio,
                })
            except Exception as e:
                self.votes[agent_name] = Vote(
                    agent=agent_name, vote="reject",
                    reasoning=f"Could not cast vote: {str(e)[:120]}",
                )
                await self._emit("council_vote", {
                    "agent_id": agent_name,
                    "agent": get_agent_display_name(agent_name),
                    "vote": "reject",
                    "reasoning": f"Vote failed: {str(e)[:120]}",
                    "audio_b64": None,
                })
            await asyncio.sleep(1)

        # ── Verdict ────────────────────────────────────────────────────────
        approve = sum(1 for v in self.votes.values() if v.vote == "approve")
        reject  = sum(1 for v in self.votes.values() if v.vote == "reject")
        decision = "approved" if approve > reject else "rejected"

        verdict_text = (
            f"The council has spoken. "
            f"With {approve} in favor and {reject} against... "
            f"the proposal is {'APPROVED' if decision == 'approved' else 'REJECTED'}."
        )
        verdict_audio = await narrator_speak(verdict_text)

        await self._emit("council_verdict", {
            "decision": decision,
            "approve": approve,
            "reject": reject,
            "verdict_text": verdict_text,
            "audio_b64": verdict_audio,
            "votes": [
                {
                    "agent_id": v.agent,
                    "agent": get_agent_display_name(v.agent),
                    "vote": v.vote,
                    "reasoning": v.reasoning,
                }
                for v in self.votes.values()
            ],
        })

        await self._emit("council_done", {"discussion_id": self.discussion_id})
