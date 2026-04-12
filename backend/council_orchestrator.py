from google.genai import types
from google import genai
from agents import get_tools, AGENTS, get_agent_system_prompt, get_agent_display_name
from typing import Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel
import asyncio
import os


# Data Models
class Vote(BaseModel):
    agent: str
    vote: Literal["approve", "reject"]
    reasoning: str


class CouncilOrchestrator:
    def __init__(self, discussion_id: str, idea: str):
        self.discussion_id = discussion_id
        self.idea = idea
        self.max_messages_per_agent = 3
        self.max_rounds = 3
        
        # Gemini client
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        self.agent_inboxes: Dict[str, List[Dict]] = {agent: [] for agent in AGENTS}
        self.conversation_history: List[Dict] = []
        self.votes: Dict[str, Vote] = {}
        self.debate_complete = False

        self.agent_message_counts: Dict[str, int] = {agent: 0 for agent in AGENTS}
        self.round_count = 0
        
        # SSE
        self.sse_queue: asyncio.Queue = asyncio.Queue()
        
        # Function/tool calling
        self.tool_functions = get_tools()
        self.tools = types.Tool(function_declarations=[types.FunctionDeclaration(**func) for func in self.tool_functions])
    
    async def broadcast_event(self, event_type: str, data: dict):
        """Send event to the SSE stream."""
        await self.sse_queue.put({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
    
    async def deliver_message(self, sender: str, recipient: str, message: str, msg_type: str):
        """Deliver a message from one agent to another."""
        self.agent_inboxes[recipient].append({
            "from": sender,
            "message": message,
            "type": msg_type,
            "timestamp": datetime.now()
        })
        
        await self.broadcast_event("agent_message", {
            "from": get_agent_display_name(sender),
            "to": get_agent_display_name(recipient),
            "message": message,
            "message_type": msg_type
        })
    
    async def call_gemini(self, agent_name: str, messages: List[Dict], enable_tools: bool = True) -> types.GenerateContentResponse:
        """Call Gemini API for an agent."""
        
        # Setup config with tools and system instruction
        config_params = {
            "system_instruction": get_agent_system_prompt(agent_name),
            "max_output_tokens": 150,
            "temperature": 0.7
        }
        
        # Only include tools if enabled (for deliberation phase)
        if enable_tools:
            config_params["tools"] = [self.tools]
        
        config = types.GenerateContentConfig(**config_params)
        
        # Context
        context = f"ORIGINAL PROPOSAL: {self.idea}\n\n"
        if messages:
            context += "YOUR INBOX:\n"
            for msg in messages:
                context += f"- From {msg['from']}: {msg['message']}\n"
        
        # Inference
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=context,
            config=config
        )
        
        return response
    
    async def handle_tool_call(self, agent_name: str, function_call):
        """Handle function calling from Gemini agents."""
        
        func_name = function_call.name
        args = dict(function_call.args)
        
        if func_name == "send_message":
            await self.deliver_message(
                sender=agent_name,
                recipient=args["recipient"],
                message=args["message"],
                msg_type=args.get("message_type", "message")
            )
    
    async def call_gemini_for_vote(self, agent_name: str) -> Vote:
        """Call Gemini to get agent's vote with reasoning."""
        
        config = types.GenerateContentConfig(
            system_instruction=get_agent_system_prompt(agent_name),
            max_output_tokens=200,
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "vote": {
                        "type": "string",
                        "enum": ["approve", "reject"],
                        "description": "Your final vote on the proposal."
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Your justification for this vote based on the debate."
                    }
                },
                "required": ["vote", "reasoning"]
            }
        )
        
        # Debate context
        context = f"""ORIGINAL PROPOSAL: {self.idea}

Based on the debate that has taken place, you must now cast your final vote.

Provide your vote (approve or reject) and provide brief reasoning based on the discussion."""
        
        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=context,
            config=config
        )
        
        # Parse JSON response
        import json
        if response.text is None:
            raise ValueError("No response text received from Gemini")
        vote_data = json.loads(response.text)
        
        return Vote(
            agent=agent_name,
            vote=vote_data["vote"],
            reasoning=vote_data["reasoning"]
        )
    
    async def conduct_voting_phase(self):
        """Voting phase where all agents must vote."""
        
        await self.broadcast_event("phase_start", {
            "phase": "voting",
            "description": "All agents will now cast their final votes on the idea."
        })
        
        for agent_name in AGENTS:
            try:
                vote = await self.call_gemini_for_vote(agent_name)
                self.votes[agent_name] = vote
                
                await self.broadcast_event("vote_cast", {
                    "agent": get_agent_display_name(agent_name),
                    "vote": vote.vote,
                    "reasoning": vote.reasoning
                })
                
                await asyncio.sleep(10)  # Prevent rate limiting
                
            except Exception as e:
                # If vote fails, auto-reject
                self.votes[agent_name] = Vote(
                    agent=agent_name,
                    vote="reject",
                    reasoning=f"Failed to cast vote: {str(e)}"
                )
                await self.broadcast_event("error", {
                    "agent": get_agent_display_name(agent_name),
                    "error": f"Vote failed: {str(e)}"
                })
        
        await self.finalize_debate()
    
    async def finalize_debate(self):
        """Tally votes and conclude debate"""
        self.debate_complete = True
        
        # Tally votes
        approve = sum(1 for v in self.votes.values() if v.vote == "approve")
        reject = sum(1 for v in self.votes.values() if v.vote == "reject")
        
        decision = "approved" if approve > reject else "rejected"
        
        await self.broadcast_event("debate_concluded", {
            "decision": decision,
            "votes": {
                "approve": approve,
                "reject": reject
            },
            "detailed_votes": [
                {
                    "agent": v.agent,
                    "vote": v.vote,
                    "reasoning": v.reasoning
                }
                for v in self.votes.values()
            ]
        })

    async def process_agent_turn(self, agent_name: str, enable_tools: bool = True):
        """Process a turn for an agent."""
        
        # check msg limit
        if self.agent_message_counts[agent_name] >= self.max_messages_per_agent:
            return
        
        # Recieve messages
        inbox = self.agent_inboxes[agent_name].copy()
        self.agent_inboxes[agent_name].clear()
        
        if not inbox and self.agent_message_counts[agent_name] > 0:
            return
        
        # Call Gemini
        try:
            response = await self.call_gemini(agent_name, inbox, enable_tools=enable_tools)
            
            if not response.candidates:
                return
            
            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                return
            
            self.agent_message_counts[agent_name] += 1
            
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    await self.broadcast_event("agent_thinking", {
                        "agent": get_agent_display_name(agent_name),
                        "content": part.text
                    })
                
                # Handle function calls
                elif hasattr(part, 'function_call') and part.function_call:
                    await self.handle_tool_call(agent_name, part.function_call)
        
        except Exception as e:
            await self.broadcast_event("error", {
                "agent": get_agent_display_name(agent_name),
                "error": str(e)
            })

    async def run_debate(self):
        """Main debate loop."""
        
        # initial round, agent provides an initial perspective
        await self.broadcast_event("phase_start", {
            "phase": "opening_statements",
            "description": "Each agent will now provide their initial perspective."
        })
        
        for agent_name in AGENTS:
            self.agent_inboxes[agent_name].append({
                "from": "system",
                "message": f"Please provide your initial analysis of this proposal: {self.idea}",
                "type": "system",
                "timestamp": datetime.now()
            })
        
        for agent_name in AGENTS:
            await self.process_agent_turn(agent_name, enable_tools=False)
            await asyncio.sleep(10)  # Prevent rate limiting
        
        # the actual debate
        await self.broadcast_event("phase_start", {
            "phase": "deliberation",
            "description": "The agents will now discuss their perspectives."
        })

        # Send all agents a message to start deliberating
        for agent_name in AGENTS:
            self.agent_inboxes[agent_name].append({
                "from": "system",
                "message": "Now that all agents have provided their initial perspectives, please respond to their points and engage in discussion. Use the send_message tool to communicate with specific agents.",
                "type": "system",
                "timestamp": datetime.now()
            })
        
        while (not self.debate_complete and 
               self.round_count < self.max_rounds):
            
            self.round_count += 1
            
            # inbox stuff
            agents_with_messages = [
                agent for agent, inbox in self.agent_inboxes.items()
                if inbox
            ]
            
            if not agents_with_messages:
                # Debate has naturally concluded, proceed to voting
                break
            
            for agent_name in agents_with_messages:
                await self.process_agent_turn(agent_name, enable_tools=True)
                await asyncio.sleep(10)  # Prevent rate limiting
        
        # Deliberation complete - now conduct voting phase
        await self.conduct_voting_phase()
        
        await self.broadcast_event("complete", {"discussion_id": self.discussion_id})