"""Errors intended for concise presentation to Script users."""


class ScriptUserError(RuntimeError):
    """SDK or Client API failure with an already user-facing message."""
