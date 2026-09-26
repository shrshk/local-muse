class ToolExecutionError(Exception):
    """Expected executor failure. The message is shown to the model, so keep it free of secrets."""
