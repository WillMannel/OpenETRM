class OpenEtrmError(Exception):
    """Base class for domain errors that should map to a 4xx API response."""


class NotFoundError(OpenEtrmError):
    def __init__(self, entity: str, identifier: object):
        super().__init__(f"{entity} not found: {identifier}")


class ValidationFailedError(OpenEtrmError):
    pass


class InsufficientMarketDataError(OpenEtrmError):
    """Raised when a curve cannot be bootstrapped because required quotes are missing."""
