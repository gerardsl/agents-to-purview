class IntegrationError(RuntimeError):
    """Purview connectivity or enforcement could not be verified."""


class PolicyBlocked(IntegrationError):
    def __init__(self, stage: str, correlation_id: str) -> None:
        self.stage = stage
        self.correlation_id = correlation_id
        super().__init__(
            f"Purview blocked the {stage}. No blocked content was released. "
            f"Correlation ID: {correlation_id}"
        )


class PolicyVerificationError(IntegrationError):
    """The service did not provide a usable decision when one was required."""
