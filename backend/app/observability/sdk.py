"""One seam over the two observability SDKs.

`splunk_ao` is the Splunk Agent Observability rebrand of the same core: it imports `galileo_core`
internally and its span methods have identical names. The differences are a handful of renames,
so a backend is a namespace of the few symbols the application actually uses rather than a wrapper
class per SDK.

Imports stay lazy and per-backend. Importing both eagerly would pull the OTLP exporter stack into
every process that only ever talks to Galileo, and an SDK that is not installed should fail when
someone selects it, not at startup.
"""

from dataclasses import dataclass
from typing import Any

GALILEO = "galileo"
SPLUNK_AO = "splunk_ao"
BACKENDS = (GALILEO, SPLUNK_AO)

# What each backend calls the stream a trace is written to. The concept is identical; only the
# word differs, and it reaches the env vars, the portal labels and the Agent Control target.
STREAM_LABEL = {GALILEO: "log stream", SPLUNK_AO: "agent stream"}
# What to call each backend on screen and in a status message.
DISPLAY_NAME = {GALILEO: "Galileo", SPLUNK_AO: "Splunk AO"}
# Backends whose support is not finished. Traces arrive, but the OTLP transport drops the trace
# output the custom judges read, cannot carry an Agent Control stream target, and exports spans
# before a fault can be masked out of them. The portal says so rather than letting a presenter
# discover it live. See issues #1, #2 and #3.
BETA = frozenset({SPLUNK_AO})


@dataclass(frozen=True)
class Backend:
    """The symbols the application needs from one SDK, already resolved."""

    name: str
    Logger: Any
    Callback: Any
    ControlResult: Any
    Scorers: Any
    Traces: Any
    _enable: Any
    _get_stream: Any
    _stream_kwarg: str
    _stream_attr: str
    _logger_kwarg: str

    def enable_metrics(self, *, project_name, stream_name, metrics):
        """Enable evaluators on a stream. The two SDKs differ only in the keyword's name."""
        return self._enable(
            project_name=project_name, metrics=metrics, **{self._stream_kwarg: stream_name}
        )

    def get_stream(self, **kwargs):
        return self._get_stream(**kwargs)

    def traces(self, *, project_id, stream_id):
        """The trace-reading client. The stream keyword differs with the rest of the vocabulary."""
        return self.Traces(**{"project_id": project_id, self._stream_attr: stream_id})

    def stream_id(self, logger):
        """`log_stream_id` on Galileo, `agent_stream_id` on Splunk AO."""
        return getattr(logger, self._stream_attr, None)

    def new_logger(self, *, project, stream):
        return self.Logger(**{"project": project, self._stream_kwarg.removesuffix("_name"): stream})

    def callback(self, logger):
        """The LangChain handler, bound to this turn's logger.

        Both take the same two flags and differ only in the logger's keyword name. `start_new_trace`
        is False because the trace is started here, not by the callback, and `flush_on_chain_end` is
        False because the turn is flushed once in `finish`.
        """
        return self.Callback(
            **{self._logger_kwarg: logger}, start_new_trace=False, flush_on_chain_end=False
        )


def stream_id_of(logger):
    """The stream id from either SDK's logger, without needing to know which one it is.

    Callers that hold a logger but not the active backend -- the action gate, the turn record --
    should not have to thread one through to read an id the logger already has.
    """
    for attribute in ("log_stream_id", "agent_stream_id"):
        value = getattr(logger, attribute, None)
        if value:
            return value
    return None


def _galileo():
    from galileo import GalileoLogger
    from galileo.handlers.langchain import GalileoAsyncCallback
    from galileo.log_streams import enable_metrics, get_log_stream
    from galileo.scorers import Scorers
    from galileo.traces import Traces
    from galileo_core.schemas.logging.control import ControlResult

    return Backend(
        name=GALILEO,
        Logger=GalileoLogger,
        Callback=GalileoAsyncCallback,
        ControlResult=ControlResult,
        Scorers=Scorers,
        Traces=Traces,
        _enable=enable_metrics,
        _get_stream=get_log_stream,
        _stream_kwarg="log_stream_name",
        _stream_attr="log_stream_id",
        _logger_kwarg="galileo_logger",
    )


def _splunk_ao():
    from splunk_ao import SplunkAOLogger
    from splunk_ao.agent_streams import enable_evaluators, get_agent_stream
    from splunk_ao.handlers.langchain import SplunkAOAsyncCallback
    from splunk_ao.logger.control import ControlResult
    from splunk_ao.schema.metrics import SplunkAOEvaluators
    from splunk_ao.traces import Traces

    return Backend(
        name=SPLUNK_AO,
        Logger=SplunkAOLogger,
        Callback=SplunkAOAsyncCallback,
        ControlResult=ControlResult,
        Scorers=SplunkAOEvaluators,
        Traces=Traces,
        _enable=enable_evaluators,
        _get_stream=get_agent_stream,
        _stream_kwarg="agent_stream_name",
        _stream_attr="agent_stream_id",
        _logger_kwarg="splunk_ao_logger",
    )


_RESOLVERS = {GALILEO: _galileo, SPLUNK_AO: _splunk_ao}


def backend(name):
    """Resolve one backend by name, raising a message a presenter can act on."""
    resolver = _RESOLVERS.get(name)
    if resolver is None:
        raise ValueError(f"Unknown observability backend {name!r}; expected one of {BACKENDS}")
    try:
        return resolver()
    except ImportError as error:
        package = "splunk-ao" if name == SPLUNK_AO else "galileo"
        raise RuntimeError(f"Backend {name!r} selected but {package} is not installed") from error
