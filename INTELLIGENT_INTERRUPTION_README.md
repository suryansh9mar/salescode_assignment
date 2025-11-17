# Intelligent Speech Interruption Handler for LiveKit Agents

## Overview

The `IntelligentInterruptionHandler` is an extension layer for LiveKit Agents that intelligently filters user speech based on whether the agent is currently speaking. It solves the problem of unwanted interruptions from filler words while ensuring genuine user speech always gets through.

## Problem Statement

In voice AI applications, users often say filler words like "uh", "umm", "hmm" while the agent is speaking. These should typically be ignored to prevent unnecessary interruptions. However, the same filler words should be registered as valid speech when the agent is quiet (e.g., when the user is thinking).

## Solution

This handler implements a **state-aware filtering layer** that:

1. **Tracks Agent State**: Monitors when the agent's TTS is active (speaking) or inactive (listening)
2. **Filters Intelligently**: Applies different rules based on agent state
3. **Preserves VAD**: Works as an extension layer without modifying core Voice Activity Detection

## Core Scenarios

| Scenario | Agent State | User Input | Action | Reason |
|----------|-------------|------------|--------|--------|
| 1 | Speaking | "umm" | **IGNORE** | Filler word while agent talks |
| 2 | Speaking | "wait one second" | **INTERRUPT** | Contains real words |
| 3 | Quiet | "umm" | **PROCESS** | Valid speech when agent quiet |
| 4 | Speaking | "umm okay stop" | **INTERRUPT** | Contains non-filler words |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Speech Input                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    VAD (Voice Activity)                      │
│              (Detects speech vs silence)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  STT (Speech-to-Text)                        │
│              (Transcribes audio to text)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│         IntelligentInterruptionHandler (THIS MODULE)         │
│                                                              │
│  1. Receives transcription event                            │
│  2. Checks agent state (speaking/listening)                 │
│  3. Analyzes transcript for filler words                    │
│  4. Decides: INTERRUPT, IGNORE, or PROCESS                  │
│  5. Logs decision for debugging                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              AgentSession Interruption Logic                 │
│         (Handles actual interruption if allowed)             │
└─────────────────────────────────────────────────────────────┘
```

## Installation

1. Copy `intelligent_interruption_handler.py` to your project root
2. Set filler words in your `.env` file:

```bash
# .env
FILLER_WORDS=uh,umm,hmm,haan,um,er,ah
```

## Usage

### Basic Usage

```python
from intelligent_interruption_handler import IntelligentInterruptionHandler
from livekit.agents import AgentSession

# Create your AgentSession
session = AgentSession(
    stt="deepgram/nova-3",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-2",
    # ... other options
)

# Attach the intelligent interruption handler
handler = IntelligentInterruptionHandler(session)

# That's it! The handler will now filter interruptions automatically
```

### Custom Filler Words

```python
# Override filler words programmatically
handler = IntelligentInterruptionHandler(
    session,
    ignored_words={"uh", "umm", "hmm", "haan", "like", "you know"}
)
```

### Using the Helper Function

```python
from intelligent_interruption_handler import create_session_with_intelligent_interruption

# Create session and handler in one call
session, handler = create_session_with_intelligent_interruption(
    ignored_words={"uh", "umm", "hmm"},
    stt="deepgram/nova-3",
    llm="openai/gpt-4.1-mini",
    tts="cartesia/sonic-2",
)
```

## Complete Example

See `examples/voice_agents/intelligent_interruption_agent.py` for a full working example.

```bash
# Run the example
python examples/voice_agents/intelligent_interruption_agent.py console
```

## How It Works

### 1. State Tracking

The handler listens to `agent_state_changed` events to track when the agent is speaking:

```python
@session.on("agent_state_changed")
def _on_agent_state_changed(ev: AgentStateChangedEvent):
    self._is_agent_speaking = (ev.new_state == "speaking")
```

### 2. Transcription Interception

It intercepts `user_input_transcribed` events to analyze user speech:

```python
@session.on("user_input_transcribed")
def _on_user_input_transcribed(ev: UserInputTranscribedEvent):
    # Analyze and filter the transcript
    self._handle_user_transcription(ev)
```

### 3. Filtering Logic

The core decision logic:

```python
def _should_allow_interruption(self, is_agent_speaking, contains_only_fillers, transcript):
    if is_agent_speaking:
        if contains_only_fillers:
            return False  # IGNORE: Agent speaking + only fillers
        else:
            return True   # INTERRUPT: Agent speaking + real words
    else:
        return True       # PROCESS: Agent quiet, allow all speech
```

### 4. Filler Word Detection

Uses regex to extract words and check against the filler set:

```python
def _contains_only_filler_words(self, transcript):
    words = re.findall(r'\b\w+\b', transcript.lower())
    return all(word in self.ignored_words for word in words)
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FILLER_WORDS` | `uh,umm,hmm,haan,um,er,ah` | Comma-separated list of filler words |

### Constructor Parameters

```python
IntelligentInterruptionHandler(
    session: AgentSession,           # Required: The session to attach to
    ignored_words: Set[str] | None,  # Optional: Override filler words
    env_var_name: str = "FILLER_WORDS"  # Optional: Custom env var name
)
```

## Logging

The handler provides comprehensive logging for debugging:

```python
# Valid interruption
logger.info("VALID INTERRUPTION: User speech will be processed", extra={
    "transcript": "wait one second",
    "agent_speaking": True,
    "only_fillers": False,
    "action": "INTERRUPT"
})

# Ignored interruption
logger.info("IGNORED INTERRUPTION: Filler words while agent speaking", extra={
    "transcript": "umm",
    "agent_speaking": True,
    "only_fillers": True,
    "action": "IGNORE"
})
```

## Thread Safety

The handler uses `asyncio.Lock` to ensure thread-safe state updates:

```python
async with self._lock:
    self._is_agent_speaking = (ev.new_state == "speaking")
```

## Testing

See `test_intelligent_interruption.py` for unit tests covering all scenarios.

```bash
pytest test_intelligent_interruption.py -v
```

## Limitations

1. **Text-based filtering only**: Filters based on transcribed text, not audio characteristics
2. **Language-specific**: Word splitting works best for space-separated languages
3. **No context awareness**: Doesn't consider conversation context (e.g., "umm" as part of a longer thought)

## Future Enhancements

- [ ] Multi-language support with language-specific filler words
- [ ] Context-aware filtering (e.g., pause duration before filler)
- [ ] Confidence score integration from STT
- [ ] Adaptive filler word learning
- [ ] Integration with sentiment analysis

## License

Same as LiveKit Agents (Apache 2.0)

## Support

For issues or questions, please refer to the LiveKit Agents documentation:
- https://docs.livekit.io/agents/
- https://livekit.io/join-slack

