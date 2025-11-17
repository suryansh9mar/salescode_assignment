"""
Intelligent Speech Interruption Handler for LiveKit Agents

This module provides a filtering layer that intelligently handles user speech interruptions
based on whether the agent is currently speaking. It filters out configurable "filler words"
only when the agent is speaking, while allowing all speech (including fillers) when the
agent is quiet.

Key Features:
- Tracks agent TTS state (speaking/listening)
- Configurable filler word list from environment variables
- Intercepts transcription events before interruption logic
- Thread-safe and async-compatible
- Comprehensive logging for debugging

"""

import asyncio
import logging
import os
import re
from typing import Set

from livekit.agents import AgentSession
from livekit.agents.voice import AgentStateChangedEvent, UserInputTranscribedEvent

logger = logging.getLogger(__name__)


class IntelligentInterruptionHandler:
    """
    Extension layer for AgentSession that filters user speech based on agent state.
    
    This class intercepts transcription events and decides whether to allow interruptions
    based on:
    1. Whether the agent is currently speaking
    2. Whether the user input contains only filler words
    3. Whether the user input contains genuine speech
    
    Scenarios:
    - Agent Speaking + User says "umm" → IGNORE (continue speaking)
    - Agent Speaking + User says "wait one second" → INTERRUPT (stop speaking)
    - Agent Quiet + User says "umm" → PROCESS (register as valid speech)
    - Agent Speaking + User says "umm okay stop" → INTERRUPT (contains non-filler words)
    """
    
    def __init__(
        self,
        session: AgentSession,
        ignored_words: Set[str] | None = None,
        env_var_name: str = "FILLER_WORDS",
    ):
        """
        Initialize the intelligent interruption handler.
        
        Args:
            session: The AgentSession to attach to
            ignored_words: Set of filler words to ignore when agent is speaking.
                          If None, loads from environment variable.
            env_var_name: Name of environment variable containing comma-separated filler words
        """
        self.session = session
        self._is_agent_speaking = False
        self._lock = asyncio.Lock()  # Thread-safe state updates
        
        # Load filler words from environment or use provided set
        if ignored_words is None:
            filler_words_str = os.getenv(env_var_name, "uh,umm,hmm,haan,um,er,ah")
            self.ignored_words = {word.strip().lower() for word in filler_words_str.split(",")}
        else:
            self.ignored_words = {word.lower() for word in ignored_words}
        
        logger.info(
            f"Initialized IntelligentInterruptionHandler with {len(self.ignored_words)} filler words",
            extra={"filler_words": sorted(self.ignored_words)}
        )
        
        # Register event listeners
        self._register_event_handlers()
    
    def _register_event_handlers(self) -> None:
        """Register event handlers for agent state and transcription events."""
        
        # Track agent speaking state
        @self.session.on("agent_state_changed")
        def _on_agent_state_changed(ev: AgentStateChangedEvent):
            asyncio.create_task(self._handle_agent_state_change(ev))
        
        # Intercept user transcription events
        @self.session.on("user_input_transcribed")
        def _on_user_input_transcribed(ev: UserInputTranscribedEvent):
            asyncio.create_task(self._handle_user_transcription(ev))
    
    async def _handle_agent_state_change(self, ev: AgentStateChangedEvent) -> None:
        """
        Handle agent state changes to track when TTS is active.
        
        Args:
            ev: Agent state changed event
        """
        async with self._lock:
            old_state = self._is_agent_speaking
            self._is_agent_speaking = (ev.new_state == "speaking")
            
            if old_state != self._is_agent_speaking:
                logger.debug(
                    f"Agent state changed: {ev.old_state} → {ev.new_state}",
                    extra={
                        "is_speaking": self._is_agent_speaking,
                        "old_state": ev.old_state,
                        "new_state": ev.new_state,
                    }
                )
    
    async def _handle_user_transcription(self, ev: UserInputTranscribedEvent) -> None:
        """
        Handle user transcription events and decide whether to allow interruption.
        
        This is the core filtering logic that implements the four scenarios.
        
        Args:
            ev: User input transcribed event
        """
        # Only process final transcripts for interruption decisions
        if not ev.is_final:
            return
        
        transcript = ev.transcript.strip()
        if not transcript:
            return
        
        async with self._lock:
            is_speaking = self._is_agent_speaking
        
        # Determine if transcript contains only filler words
        contains_only_fillers = self._contains_only_filler_words(transcript)
        contains_non_fillers = not contains_only_fillers
        
        # Apply filtering logic based on scenarios
        should_interrupt = self._should_allow_interruption(
            is_agent_speaking=is_speaking,
            contains_only_fillers=contains_only_fillers,
            transcript=transcript,
        )
        
        # Log the decision
        self._log_interruption_decision(
            transcript=transcript,
            is_agent_speaking=is_speaking,
            contains_only_fillers=contains_only_fillers,
            should_interrupt=should_interrupt,
        )
    
    def _contains_only_filler_words(self, transcript: str) -> bool:
        """
        Check if transcript contains only filler words.

        Args:
            transcript: The transcribed text

        Returns:
            True if transcript contains only filler words, False otherwise
        """
        # Normalize: lowercase, remove punctuation, split into words
        words = re.findall(r'\b\w+\b', transcript.lower())

        if not words:
            return True  # Empty transcript treated as filler

        # Check if all words are in the ignored set
        return all(word in self.ignored_words for word in words)

    def _should_allow_interruption(
        self,
        is_agent_speaking: bool,
        contains_only_fillers: bool,
        transcript: str,
    ) -> bool:
        """
        Determine whether to allow interruption based on the filtering logic.

        Implements the four core scenarios:
        1. Agent Speaking + Only Fillers → DO NOT INTERRUPT
        2. Agent Speaking + Contains Non-Fillers → INTERRUPT
        3. Agent Quiet + Only Fillers → ALLOW (process as valid speech)
        4. Agent Quiet + Contains Non-Fillers → ALLOW (process as valid speech)

        Args:
            is_agent_speaking: Whether the agent is currently speaking
            contains_only_fillers: Whether transcript contains only filler words
            transcript: The transcribed text

        Returns:
            True if interruption should be allowed, False otherwise
        """
        if is_agent_speaking:
            # Agent is speaking
            if contains_only_fillers:
                # Scenario 1: Agent speaking + only fillers → IGNORE
                return False
            else:
                # Scenario 2: Agent speaking + contains real words → INTERRUPT
                return True
        else:
            # Agent is quiet - always process user input
            # Scenarios 3 & 4: Agent quiet → ALLOW all speech
            return True

    def _log_interruption_decision(
        self,
        transcript: str,
        is_agent_speaking: bool,
        contains_only_fillers: bool,
        should_interrupt: bool,
    ) -> None:
        """
        Log the interruption decision for debugging.

        Args:
            transcript: The transcribed text
            is_agent_speaking: Whether agent is speaking
            contains_only_fillers: Whether transcript is only fillers
            should_interrupt: Whether interruption is allowed
        """
        if should_interrupt:
            logger.info(
                "VALID INTERRUPTION: User speech will be processed",
                extra={
                    "transcript": transcript,
                    "agent_speaking": is_agent_speaking,
                    "only_fillers": contains_only_fillers,
                    "action": "INTERRUPT" if is_agent_speaking else "PROCESS",
                }
            )
        else:
            logger.info(
                "IGNORED INTERRUPTION: Filler words while agent speaking",
                extra={
                    "transcript": transcript,
                    "agent_speaking": is_agent_speaking,
                    "only_fillers": contains_only_fillers,
                    "action": "IGNORE",
                }
            )


# Example usage function
def create_session_with_intelligent_interruption(
    ignored_words: Set[str] | None = None,
    **session_kwargs,
) -> tuple[AgentSession, IntelligentInterruptionHandler]:
    """
    Create an AgentSession with intelligent interruption handling.

    Args:
        ignored_words: Optional set of filler words to ignore
        **session_kwargs: Arguments to pass to AgentSession constructor

    Returns:
        Tuple of (AgentSession, IntelligentInterruptionHandler)

    Example:
        >>> session, handler = create_session_with_intelligent_interruption(
        ...     ignored_words={"uh", "umm", "hmm"},
        ...     stt="deepgram/nova-3",
        ...     llm="openai/gpt-4.1-mini",
        ...     tts="cartesia/sonic-2",
        ... )
    """
    session = AgentSession(**session_kwargs)
    handler = IntelligentInterruptionHandler(session, ignored_words=ignored_words)
    return session, handler

