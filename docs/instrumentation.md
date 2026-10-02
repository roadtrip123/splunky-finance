# How traces reach Galileo

A workshop reference: what the application does to put a turn in front of the evaluators. The
same shape works for Splunk Agent Observability — only the class names change, and
[docs/evaluators.md](evaluators.md) lists those.

## The shape

**One logger per turn. Everything buffered in memory. One HTTP call at the end.**

```
POST /api/chat
   │
   ├─ begin()      create a logger, start a session, start a trace
   ├─ agent runs   spans accumulate in logger.traces — nothing sent yet
   ├─ finish()     conclude, then flush  ──►  one request to Galileo
   └─ reply to the customer
```

Nothing goes over the wire until `flush()`. That single request carries every span, nested, plus
the session id:

```python
TracesIngestRequest(traces=logged_traces, session_id=..., session_external_id=...)
```

## The whole thing, in twenty lines

This is the real sequence, with the plumbing removed. It runs as written.

```python
from galileo import GalileoLogger
from galileo.handlers.langchain import GalileoAsyncCallback

# One per turn, not one per process: the SDK's "current trace" is a ContextVar, so a shared
# logger would let two concurrent customers write into the same trace.
logger = GalileoLogger(project="splunky-finance", log_stream="my-bank-agent")
logger.start_session(name="My Bank Agent", external_id=conversation_id)
logger.start_trace(input=question, name="bank-chat-turn")

# The callback logs the agent's own spans — model calls, tool calls, middleware — as they happen.
# Both flags are off because we start the trace ourselves and flush once, at the end.
callback = GalileoAsyncCallback(
    galileo_logger=logger, start_new_trace=False, flush_on_chain_end=False
)
result = await agent.ainvoke({"messages": history}, config={"callbacks": [callback]})

# Spans we add by hand, because the callback cannot know about them.
logger.add_llm_span(
    input=[{"role": "user", "content": question}],
    output=answer,
    model="gpt-4o-mini",
    name="customer-visible-answer",
)

logger.conclude(output=json.dumps(record), conclude_all=True)
logger.flush()          # ← the only network call
```

## Which spans come from where

| Source | Spans |
| --- | --- |
| The LangChain callback, automatically | the agent, both model calls, tool calls, middleware |
| Added by hand | the policy retriever, `customer-visible-answer`, the injected fault, control verdicts |

Four are explicit because the callback cannot know what they mean:

- **The retriever span** carries the retrieved policy chunks. Without it the RAG evaluators have
  no input and score nothing.
- **`customer-visible-answer`** carries the turn's evidence as context. Logged with the question
  alone it reported every claim unsupported, correct answers included.
- **The fault pass** is logged as an ordinary model call, so nothing in the trace announces the
  injection.
- **Control spans** record the guardrail's verdict at the `pre` stage.

## Two things worth saying out loud

**Buffering is not an implementation detail.** Because nothing is sent until `flush()`, the spans
can still be edited. That is what lets the application rewrite the agent's complete answer out of
the trace when a fault is injected — otherwise a judge reads the pre-injection draft and passes a
deliberately broken answer. On a transport that streams spans as they close, the same code does
nothing.

**Telemetry never changes the answer.** `flush` is wrapped in a timeout and an error callback; a
failure sets an export status and nothing else. SDK error text is never surfaced, because it can
carry URLs and credential headers.
