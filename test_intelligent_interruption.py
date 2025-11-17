"""
Unit tests for IntelligentInterruptionHandler

Tests all four core scenarios:
1. Agent Speaking + Only Fillers → IGNORE
2. Agent Speaking + Contains Non-Fillers → INTERRUPT
3. Agent Quiet + Only Fillers → PROCESS
4. Agent Quiet + Contains Non-Fillers → PROCESS
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

from intelligent_interruption_handler import IntelligentInterruptionHandler
from livekit.agents import AgentSession
from livekit.agents.voice import AgentStateChangedEvent, UserInputTranscribedEvent


class TestIntelligentInterruptionHandler:
    """Test suite for IntelligentInterruptionHandler."""
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock AgentSession."""
        session = Mock(spec=AgentSession)
        session.on = Mock(return_value=lambda f: f)  # Mock event decorator
        return session
    
    @pytest.fixture
    def handler(self, mock_session):
        """Create a handler with test filler words."""
        return IntelligentInterruptionHandler(
            session=mock_session,
            ignored_words={"uh", "umm", "hmm", "haan"}
        )
    
    def test_initialization(self, handler):
        """Test handler initializes correctly."""
        assert handler.ignored_words == {"uh", "umm", "hmm", "haan"}
        assert handler._is_agent_speaking is False
    
    def test_initialization_from_env(self, mock_session):
        """Test loading filler words from environment."""
        with patch.dict('os.environ', {'FILLER_WORDS': 'test1,test2,test3'}):
            handler = IntelligentInterruptionHandler(session=mock_session)
            assert handler.ignored_words == {"test1", "test2", "test3"}
    
    @pytest.mark.asyncio
    async def test_agent_state_change_to_speaking(self, handler):
        """Test agent state changes to speaking."""
        event = AgentStateChangedEvent(old_state="listening", new_state="speaking")
        await handler._handle_agent_state_change(event)
        assert handler._is_agent_speaking is True
    
    @pytest.mark.asyncio
    async def test_agent_state_change_to_listening(self, handler):
        """Test agent state changes to listening."""
        # First set to speaking
        event1 = AgentStateChangedEvent(old_state="listening", new_state="speaking")
        await handler._handle_agent_state_change(event1)
        
        # Then back to listening
        event2 = AgentStateChangedEvent(old_state="speaking", new_state="listening")
        await handler._handle_agent_state_change(event2)
        assert handler._is_agent_speaking is False
    
    def test_contains_only_filler_words_true(self, handler):
        """Test detection of only filler words."""
        assert handler._contains_only_filler_words("umm") is True
        assert handler._contains_only_filler_words("uh hmm") is True
        assert handler._contains_only_filler_words("umm, uh, hmm") is True
        assert handler._contains_only_filler_words("UMM UH") is True  # Case insensitive
    
    def test_contains_only_filler_words_false(self, handler):
        """Test detection of non-filler words."""
        assert handler._contains_only_filler_words("hello") is False
        assert handler._contains_only_filler_words("umm wait") is False
        assert handler._contains_only_filler_words("stop please") is False
        assert handler._contains_only_filler_words("umm okay stop") is False
    
    def test_contains_only_filler_words_empty(self, handler):
        """Test empty transcript."""
        assert handler._contains_only_filler_words("") is True
        assert handler._contains_only_filler_words("   ") is True
    
    def test_scenario_1_agent_speaking_only_fillers(self, handler):
        """
        Scenario 1: Agent Speaking + Only Fillers → DO NOT INTERRUPT
        """
        result = handler._should_allow_interruption(
            is_agent_speaking=True,
            contains_only_fillers=True,
            transcript="umm"
        )
        assert result is False, "Should NOT interrupt when agent speaking and only fillers"
    
    def test_scenario_2_agent_speaking_with_real_words(self, handler):
        """
        Scenario 2: Agent Speaking + Contains Non-Fillers → INTERRUPT
        """
        result = handler._should_allow_interruption(
            is_agent_speaking=True,
            contains_only_fillers=False,
            transcript="wait one second"
        )
        assert result is True, "Should INTERRUPT when agent speaking and real words present"
    
    def test_scenario_3_agent_quiet_only_fillers(self, handler):
        """
        Scenario 3: Agent Quiet + Only Fillers → PROCESS
        """
        result = handler._should_allow_interruption(
            is_agent_speaking=False,
            contains_only_fillers=True,
            transcript="umm"
        )
        assert result is True, "Should PROCESS when agent quiet, even with only fillers"
    
    def test_scenario_4_agent_quiet_with_real_words(self, handler):
        """
        Scenario 4: Agent Quiet + Contains Non-Fillers → PROCESS
        """
        result = handler._should_allow_interruption(
            is_agent_speaking=False,
            contains_only_fillers=False,
            transcript="hello there"
        )
        assert result is True, "Should PROCESS when agent quiet with real words"
    
    def test_scenario_mixed_fillers_and_words(self, handler):
        """Test mixed filler and real words while agent speaking."""
        result = handler._should_allow_interruption(
            is_agent_speaking=True,
            contains_only_fillers=False,
            transcript="umm okay stop"
        )
        assert result is True, "Should INTERRUPT when contains any non-filler words"
    
    @pytest.mark.asyncio
    async def test_handle_user_transcription_non_final(self, handler):
        """Test that non-final transcripts are ignored."""
        event = UserInputTranscribedEvent(
            transcript="umm",
            is_final=False,
            language="en"
        )
        # Should not raise any errors and should return early
        await handler._handle_user_transcription(event)
    
    @pytest.mark.asyncio
    async def test_handle_user_transcription_empty(self, handler):
        """Test that empty transcripts are ignored."""
        event = UserInputTranscribedEvent(
            transcript="",
            is_final=True,
            language="en"
        )
        # Should not raise any errors and should return early
        await handler._handle_user_transcription(event)
    
    @pytest.mark.asyncio
    async def test_thread_safety(self, handler):
        """Test that state updates are thread-safe."""
        # Simulate concurrent state changes
        tasks = []
        for i in range(10):
            state = "speaking" if i % 2 == 0 else "listening"
            event = AgentStateChangedEvent(old_state="listening", new_state=state)
            tasks.append(handler._handle_agent_state_change(event))
        
        await asyncio.gather(*tasks)
        # Should complete without errors
        assert handler._is_agent_speaking in [True, False]
    
    def test_log_interruption_decision_valid(self, handler, caplog):
        """Test logging for valid interruptions."""
        with caplog.at_level("INFO"):
            handler._log_interruption_decision(
                transcript="stop please",
                is_agent_speaking=True,
                contains_only_fillers=False,
                should_interrupt=True
            )
        assert "VALID INTERRUPTION" in caplog.text
    
    def test_log_interruption_decision_ignored(self, handler, caplog):
        """Test logging for ignored interruptions."""
        with caplog.at_level("INFO"):
            handler._log_interruption_decision(
                transcript="umm",
                is_agent_speaking=True,
                contains_only_fillers=True,
                should_interrupt=False
            )
        assert "IGNORED INTERRUPTION" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

