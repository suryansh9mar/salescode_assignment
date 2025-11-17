"""
Intelligent Speech Interruption Handler for LiveKit Agents

This module provides a filtering layer that intelligently handles user speech interruptions
based on whether the agent is currently speaking. It filters out configurable "filler words"
only when the agent is speaking, while allowing all speech (including fillers) when the
agent is quiet.

Key Features:
- Tracks agent TTS state (speaking/listening)
- Configurable filler word list from environment variables
- Confidence threshold filtering for low-confidence transcripts
- Minimum word count threshold to filter background noise
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
    3. Confidence score of the transcription (if available)
    4. Minimum word count threshold

    Scenarios:
    - Agent Speaking + User says "umm" → IGNORE (continue speaking)
    - Agent Speaking + User says "wait one second" → INTERRUPT (stop speaking)
    - Agent Quiet + User says "umm" → PROCESS (register as valid speech)
    - Agent Speaking + User says "umm okay stop" → INTERRUPT (contains non-filler words)
    - Agent Speaking + Low confidence "hmm yeah" → IGNORE (likely background noise)
    """

    def __init__(
        self,
        session: AgentSession,
        ignored_words: Set[str] | None = None,
        env_var_name: str = "FILLER_WORDS",
        min_confidence: float = 0.0,
        min_words_to_interrupt: int = 0,
    ):
        """
        Initialize the intelligent interruption handler.

        Args:
            session: The AgentSession to attach to
            ignored_words: Set of filler words to ignore when agent is speaking.
                          If None, loads from environment variable.
            env_var_name: Name of environment variable containing comma-separated filler words
            min_confidence: Minimum confidence score (0.0-1.0) to allow interruption when agent is speaking.
                          Set to 0.0 to disable confidence filtering. Default: 0.0
            min_words_to_interrupt: Minimum number of words required to interrupt agent when speaking.
                                   Set to 0 to disable word count filtering. Default: 0
        """
        self.session = session
        self._is_agent_speaking = False
        self._lock = asyncio.Lock()  # Thread-safe state updates
        self.min_confidence = min_confidence
        self.min_words_to_interrupt = min_words_to_interrupt

        # Load filler words from environment or use provided set
        if ignored_words is None:
            filler_words_str = os.getenv(env_var_name, "uh,umm,hmm,haan,um,er,ah")
            self.ignored_words = {word.strip().lower() for word in filler_words_str.split(",")}
        else:
            self.ignored_words = {word.lower() for word in ignored_words}

        # Track last transcript confidence for logging
        self._last_confidence: float | None = None

        logger.info(
            f"Initialized IntelligentInterruptionHandler with {len(self.ignored_words)} filler words",
            extra={
                "filler_words": sorted(self.ignored_words),
                "min_confidence": self.min_confidence,
                "min_words_to_interrupt": self.min_words_to_interrupt,
            }
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

        This is the core filtering logic that implements the filtering scenarios.

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

        # Count words in transcript
        word_count = len(re.findall(r'\b\w+\b', transcript))

        # Note: UserInputTranscribedEvent doesn't include confidence score
        # We use self._last_confidence if available from STT events
        confidence = self._last_confidence if self._last_confidence is not None else 1.0

        # Apply filtering logic based on scenarios
        should_interrupt = self._should_allow_interruption(
            is_agent_speaking=is_speaking,
            contains_only_fillers=contains_only_fillers,
            transcript=transcript,
            word_count=word_count,
            confidence=confidence,
        )

        # Log the decision
        self._log_interruption_decision(
            transcript=transcript,
            is_agent_speaking=is_speaking,
            contains_only_fillers=contains_only_fillers,
            should_interrupt=should_interrupt,
            word_count=word_count,
            confidence=confidence,
        )

        # Reset confidence for next transcript
        self._last_confidence = None
    
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
        word_count: int,
        confidence: float,
    ) -> bool:
        """
        Determine whether to allow interruption based on the filtering logic.

        Implements enhanced filtering with multiple criteria:
        1. Agent Speaking + Only Fillers → IGNORE (return False)
        2. Agent Speaking + Real Words → INTERRUPT (return True)
        3. Agent Quiet + Only Fillers → PROCESS (return True)
        4. Agent Quiet + Real Words → PROCESS (return True)
        5. Agent Speaking + Low Confidence → IGNORE (return False)
        6. Agent Speaking + Too Few Words → IGNORE (return False)

        Args:
            is_agent_speaking: Whether the agent is currently speaking
            contains_only_fillers: Whether transcript contains only filler words
            transcript: The transcribed text
            word_count: Number of words in the transcript
            confidence: Confidence score of the transcription (0.0-1.0)

        Returns:
            True if interruption should be allowed, False otherwise
        """
        if is_agent_speaking:
            # Agent is speaking - apply strict filtering

            # Check 1: Ignore filler-only speech
            if contains_only_fillers:
                return False

            # Check 2: Ignore low-confidence transcripts (likely background noise)
            if self.min_confidence > 0.0 and confidence < self.min_confidence:
                return False

            # Check 3: Ignore very short utterances (likely noise or partial words)
            if self.min_words_to_interrupt > 0 and word_count < self.min_words_to_interrupt:
                return False

            # All checks passed - allow interruption
            return True
        else:
            # Agent is quiet - allow all speech (scenarios 3 & 4)
            return True

    def _log_interruption_decision(
        self,
        transcript: str,
        is_agent_speaking: bool,
        contains_only_fillers: bool,
        should_interrupt: bool,
        word_count: int,
        confidence: float,
    ) -> None:
        """
        Log the interruption decision for debugging.

        Args:
            transcript: The transcribed text
            is_agent_speaking: Whether agent is speaking
            contains_only_fillers: Whether transcript is only fillers
            should_interrupt: Whether interruption is allowed
            word_count: Number of words in transcript
            confidence: Confidence score of transcription
        """
        if should_interrupt:
            logger.info(
                "VALID INTERRUPTION: User speech will be processed",
                extra={
                    "transcript": transcript,
                    "agent_speaking": is_agent_speaking,
                    "only_fillers": contains_only_fillers,
                    "word_count": word_count,
                    "confidence": round(confidence, 3),
                    "action": "INTERRUPT" if is_agent_speaking else "PROCESS",
                }
            )
        else:
            # Determine the reason for ignoring
            reason = "Unknown"
            if contains_only_fillers:
                reason = "Filler words only"
            elif self.min_confidence > 0.0 and confidence < self.min_confidence:
                reason = f"Low confidence ({confidence:.3f} < {self.min_confidence})"
            elif self.min_words_to_interrupt > 0 and word_count < self.min_words_to_interrupt:
                reason = f"Too few words ({word_count} < {self.min_words_to_interrupt})"

            logger.info(
                f"IGNORED INTERRUPTION: {reason}",
                extra={
                    "transcript": transcript,
                    "agent_speaking": is_agent_speaking,
                    "only_fillers": contains_only_fillers,
                    "word_count": word_count,
                    "confidence": round(confidence, 3),
                    "reason": reason,
                    "action": "IGNORE",
                }
            )


# Example usage function
def create_session_with_intelligent_interruption(
    ignored_words: Set[str] | None = None,
    min_confidence: float = 0.0,
    min_words_to_interrupt: int = 0,
    **session_kwargs,
) -> tuple[AgentSession, IntelligentInterruptionHandler]:
    """
    Create an AgentSession with intelligent interruption handling.

    Args:
        ignored_words: Optional set of filler words to ignore
        min_confidence: Minimum confidence score (0.0-1.0) to allow interruption when agent is speaking
        min_words_to_interrupt: Minimum number of words required to interrupt agent when speaking
        **session_kwargs: Arguments to pass to AgentSession constructor

    Returns:
        Tuple of (AgentSession, IntelligentInterruptionHandler)

    Example:
        >>> session, handler = create_session_with_intelligent_interruption(
        ...     ignored_words={"uh", "umm", "hmm"},
        ...     min_confidence=0.7,
        ...     min_words_to_interrupt=2,
        ...     stt="deepgram/nova-3",
        ...     llm="openai/gpt-4.1-mini",
        ...     tts="cartesia/sonic-2",
        ... )
    """
    session = AgentSession(**session_kwargs)
    handler = IntelligentInterruptionHandler(
        session,
        ignored_words=ignored_words,
        min_confidence=min_confidence,
        min_words_to_interrupt=min_words_to_interrupt,
    )
    return session, handler

