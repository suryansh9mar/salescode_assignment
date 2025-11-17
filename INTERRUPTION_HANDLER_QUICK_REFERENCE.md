# Intelligent Interruption Handler - Quick Reference

## 🎯 One-Minute Setup

```python
from intelligent_interruption_handler import IntelligentInterruptionHandler
from livekit.agents import AgentSession

# 1. Create your session
session = AgentSession(stt="deepgram/nova-3", llm="openai/gpt-4.1-mini", tts="cartesia/sonic-2")

# 2. Attach the handler
handler = IntelligentInterruptionHandler(session)

# 3. Done! It now filters interruptions automatically
```

## 📋 Four Core Scenarios

| # | Agent State | User Says | Result | Why |
|---|-------------|-----------|--------|-----|
| 1 | 🗣️ Speaking | "umm" | ❌ **IGNORE** | Just filler noise |
| 2 | 🗣️ Speaking | "wait stop" | ✅ **INTERRUPT** | Real words = real intent |
| 3 | 👂 Quiet | "umm" | ✅ **PROCESS** | User thinking, valid speech |
| 4 | 👂 Quiet | "hello" | ✅ **PROCESS** | Normal conversation |

## 🔧 Configuration

### Via Environment Variable (.env)
```bash
FILLER_WORDS=uh,umm,hmm,haan,um,er,ah,like,you know
```

### Via Code
```python
handler = IntelligentInterruptionHandler(
    session,
    ignored_words={"uh", "umm", "hmm", "haan"}
)
```

## 📊 Decision Flow

```
User speaks
    ↓
STT transcribes → "umm wait"
    ↓
Handler checks:
    ├─ Is agent speaking? → YES
    ├─ Only filler words? → NO (contains "wait")
    └─ Decision: INTERRUPT ✅
```

## 🔍 Key Methods

### `_contains_only_filler_words(transcript: str) -> bool`
Checks if transcript contains ONLY filler words.

```python
handler._contains_only_filler_words("umm")           # True
handler._contains_only_filler_words("umm wait")      # False
handler._contains_only_filler_words("hello")         # False
```

### `_should_allow_interruption(...) -> bool`
Core decision logic.

```python
# Agent speaking + only fillers
handler._should_allow_interruption(
    is_agent_speaking=True,
    contains_only_fillers=True,
    transcript="umm"
)  # Returns False (IGNORE)

# Agent speaking + real words
handler._should_allow_interruption(
    is_agent_speaking=True,
    contains_only_fillers=False,
    transcript="stop"
)  # Returns True (INTERRUPT)
```

## 🎤 Event Hooks

The handler automatically registers these event listeners:

### 1. Agent State Tracking
```python
@session.on("agent_state_changed")
def _on_agent_state_changed(ev):
    # Updates self._is_agent_speaking
    # "speaking" → True
    # "listening" → False
```

### 2. Transcription Interception
```python
@session.on("user_input_transcribed")
def _on_user_input_transcribed(ev):
    # Analyzes transcript
    # Applies filtering logic
    # Logs decision
```

## 📝 Logging Output

### Valid Interruption
```
INFO: VALID INTERRUPTION: User speech will be processed
  transcript: "wait one second"
  agent_speaking: True
  only_fillers: False
  action: INTERRUPT
```

### Ignored Interruption
```
INFO: IGNORED INTERRUPTION: Filler words while agent speaking
  transcript: "umm"
  agent_speaking: True
  only_fillers: True
  action: IGNORE
```

## 🧪 Testing

```bash
# Run all tests
pytest test_intelligent_interruption.py -v

# Run specific scenario
pytest test_intelligent_interruption.py::TestIntelligentInterruptionHandler::test_scenario_1_agent_speaking_only_fillers -v
```

## 🚀 Complete Example

```python
from intelligent_interruption_handler import IntelligentInterruptionHandler
from livekit.agents import Agent, AgentSession, JobContext, cli

class MyAgent(Agent):
    def __init__(self):
        super().__init__(instructions="You are a helpful assistant")
    
    async def on_enter(self):
        self.session.generate_reply()

async def entrypoint(ctx: JobContext):
    # Create session
    session = AgentSession(
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-2",
        allow_interruptions=True,
    )
    
    # Attach intelligent handler
    handler = IntelligentInterruptionHandler(session)
    
    # Start session
    await session.start(agent=MyAgent(), room=ctx.room)

if __name__ == "__main__":
    cli.run_app(entrypoint)
```

## 🔒 Thread Safety

The handler uses `asyncio.Lock` for thread-safe state updates:

```python
async with self._lock:
    self._is_agent_speaking = (ev.new_state == "speaking")
```

## ⚡ Performance

- **Minimal overhead**: Only processes final transcripts
- **Fast word matching**: Uses set lookup (O(1) per word)
- **Async-friendly**: All operations are non-blocking

## 🐛 Debugging Tips

### Enable Debug Logging
```python
import logging
logging.getLogger("intelligent_interruption_handler").setLevel(logging.DEBUG)
```

### Check Handler State
```python
print(f"Agent speaking: {handler._is_agent_speaking}")
print(f"Filler words: {handler.ignored_words}")
```

### Monitor Events
```python
@session.on("agent_state_changed")
def debug_state(ev):
    print(f"State: {ev.old_state} → {ev.new_state}")

@session.on("user_input_transcribed")
def debug_transcript(ev):
    print(f"Transcript: {ev.transcript} (final={ev.is_final})")
```

## 📚 Related Documentation

- **LiveKit Agents**: https://docs.livekit.io/agents/
- **Interruption Handling**: https://docs.livekit.io/agents/build/interruptions/
- **Turn Detection**: https://docs.livekit.io/agents/build/turns/

## 💡 Pro Tips

1. **Start with default filler words** - They work well for English
2. **Monitor logs initially** - Understand what's being filtered
3. **Adjust per use case** - Add domain-specific fillers if needed
4. **Test all scenarios** - Use the test suite as a guide
5. **Combine with min_interruption_words** - Set to 0 to let handler control

## ⚠️ Common Pitfalls

❌ **Don't** set `min_interruption_words` too high - it conflicts with the handler
✅ **Do** set it to 0 and let the handler manage filtering

❌ **Don't** modify VAD settings to filter fillers
✅ **Do** use this handler as an extension layer

❌ **Don't** forget to set `allow_interruptions=True`
✅ **Do** enable interruptions and let handler filter them

## 🎓 Advanced Usage

### Custom Filler Detection
```python
class CustomHandler(IntelligentInterruptionHandler):
    def _contains_only_filler_words(self, transcript):
        # Add custom logic, e.g., check pause duration
        if self._pause_duration > 2.0:
            return False  # Long pause = intentional speech
        return super()._contains_only_filler_words(transcript)
```

### Language-Specific Fillers
```python
# Spanish fillers
handler_es = IntelligentInterruptionHandler(
    session,
    ignored_words={"eh", "este", "pues", "bueno"}
)

# French fillers
handler_fr = IntelligentInterruptionHandler(
    session,
    ignored_words={"euh", "ben", "alors", "donc"}
)
```

---

**Need help?** Check the full README or join the LiveKit Slack community!

