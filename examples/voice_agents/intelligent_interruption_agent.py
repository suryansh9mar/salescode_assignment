"""
Example: Voice Agent with Intelligent Interruption Handling

This example demonstrates how to use the IntelligentInterruptionHandler to filter
user speech based on whether the agent is speaking and whether the input contains
only filler words.

Usage:
    # Set filler words in .env file
    FILLER_WORDS=uh,umm,hmm,haan,um,er,ah
    
    # Run the agent
    python examples/voice_agents/intelligent_interruption_agent.py console
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add parent directory to path to import the handler
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from intelligent_interruption_handler import IntelligentInterruptionHandler

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RunContext,
    cli,
    metrics,
    room_io,
)
from livekit.agents.llm import function_tool
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("intelligent-interruption-agent")
logger.setLevel(logging.DEBUG)  # Enable debug logging

load_dotenv()


class MyIntelligentAgent(Agent):
    """Agent with intelligent interruption handling."""
    
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "Your name is Alex. You are a helpful voice assistant. "
                "You can answer questions, have conversations, and help with various tasks. "
                "You have access to tools to get the current time and set reminders, "
                "but you can also answer general questions and chat naturally. "
                "Keep your responses concise and natural. "
                "Do not use emojis, asterisks, or markdown. "
                "You are friendly and professional."
            )
        )
    
    async def on_enter(self):
        """Called when agent enters the session."""
        logger.info("Agent entered session, generating initial greeting")
        self.session.generate_reply()
    
    @function_tool
    async def get_time(self, context: RunContext):
        """Get the current time.
        
        Returns:
            Current time as a string
        """
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")
        logger.info(f"Time requested: {current_time}")
        return f"The current time is {current_time}"
    
    @function_tool
    async def set_reminder(
        self,
        context: RunContext,
        message: str,
        minutes: int,
    ):
        """Set a reminder for the user.
        
        Args:
            message: The reminder message
            minutes: Number of minutes from now
        """
        logger.info(f"Reminder set: '{message}' in {minutes} minutes")
        return f"I've set a reminder for '{message}' in {minutes} minutes."


server = AgentServer()


def prewarm(proc: JobProcess):
    """Prewarm function to load models before session starts."""
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    """Main entrypoint for the agent session."""
    
    # Configure logging context
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    
    # Create AgentSession with standard configuration
    session = AgentSession(
        # Speech-to-Text
        stt="deepgram/nova-3",

        # Large Language Model (using Google Gemini)
        llm="google/gemini-2.0-flash",

        # Text-to-Speech
        tts="cartesia/sonic-2:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        
        # Voice Activity Detection and Turn Detection
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        
        # Enable preemptive generation for faster responses
        preemptive_generation=True,
        
        # False interruption handling
        resume_false_interruption=True,
        false_interruption_timeout=1.0,
        
        # Interruption settings
        allow_interruptions=True,
        min_interruption_duration=0.5,
        min_interruption_words=0,  # Set to 0 to let our handler control this
    )
    
    # ============================================================
    # ATTACH INTELLIGENT INTERRUPTION HANDLER
    # ============================================================
    # This is where the magic happens!
    # The handler will automatically filter interruptions based on:
    # 1. Filler words (when agent is speaking)
    # 2. Confidence score (optional - filters low-confidence background noise)
    # 3. Word count (optional - filters very short utterances)
    handler = IntelligentInterruptionHandler(
        session=session,
        # Optional: override filler words (otherwise loads from FILLER_WORDS env var)
        # ignored_words={"uh", "umm", "hmm", "haan", "um", "er", "ah"},

        # Optional: Set minimum confidence threshold (0.0-1.0)
        # Transcripts below this confidence will be ignored when agent is speaking
        # Example: min_confidence=0.7 will ignore low-confidence background noise
        min_confidence=0.7,  # Default: 0.0 (disabled)

        # Optional: Set minimum word count to interrupt
        # Utterances with fewer words will be ignored when agent is speaking
        # Example: min_words_to_interrupt=2 will ignore single-word utterances
        min_words_to_interrupt=1,  # Default: 0 (disabled)
    )
    
    logger.info(
        "Intelligent interruption handler attached",
        extra={"filler_words": sorted(handler.ignored_words)}
    )

    # ============================================================
    # METRICS AND USAGE TRACKING
    # ============================================================
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Session usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # ============================================================
    # START THE SESSION
    # ============================================================
    await session.start(
        agent=MyIntelligentAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(),
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)

