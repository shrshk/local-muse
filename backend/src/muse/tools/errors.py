class ToolExecutionError(Exception):
    """Expected executor failure. The message is shown to the model, so keep it free of secrets."""


class ToolDeferred(Exception):
    """The call cannot run now (e.g. a human has the browser). The workflow waits and resumes."""

    def __init__(self, metadata: dict[str, str]) -> None:
        super().__init__(metadata.get("reason", "deferred"))
        self.metadata = metadata
