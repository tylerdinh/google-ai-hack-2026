from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime
import asyncio
import json
import uuid

from council_orchestrator import CouncilOrchestrator
from agents import get_all_agents_info, AGENTS

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active discussions
active_discussions: Dict[str, CouncilOrchestrator] = {}

# Data Models
class IdeaSubmission(BaseModel):
    idea: str

# Endpoints
@app.get("/api/council/agents")
async def get_agents():
    """Get the list of available agents."""
    return {"agents": get_all_agents_info()}


@app.post("/api/council/discuss")
async def start_discussion(submission: IdeaSubmission):
    """Start a new council discussion."""
    
    discussion_id = str(uuid.uuid4())
    
    orchestrator = CouncilOrchestrator(discussion_id, submission.idea)
    active_discussions[discussion_id] = orchestrator
    
    # Start debate (in background)
    asyncio.create_task(orchestrator.run_debate())
    
    return {
        "discussion_id": discussion_id,
        "idea": submission.idea,
        "agents": list(AGENTS.keys())
    }

@app.get("/api/council/discussion/{discussion_id}/stream")
async def stream_discussion(discussion_id: str):
    """SSE for real-time debate updates for a given discussion."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    async def event_generator():
        try:
            while True:
                event = await orchestrator.sse_queue.get()
                
                yield f"data: {json.dumps(event)}\n\n"
                
                if event["type"] == "complete":
                    break
        
        except asyncio.CancelledError:
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.get("/api/council/discussion/{discussion_id}")
async def get_discussion(discussion_id: str):
    """Get a complete discussion history."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    return {
        "discussion_id": discussion_id,
        "idea": orchestrator.idea,
        "status": "complete" if orchestrator.debate_complete else "active",
        "votes": [
            {
                "agent": v.agent,
                "vote": v.vote,
                "reasoning": v.reasoning
            }
            for v in orchestrator.votes.values()
        ] if orchestrator.votes else []
    }