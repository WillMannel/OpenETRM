class OpenEtrmError(Exception):
    """Base class for domain errors that should map to a 4xx API response."""


class NotFoundError(OpenEtrmError):
    def __init__(self, entity: str, identifier: object):
        super().__init__(f"{entity} not found: {identifier}")


class ValidationFailedError(OpenEtrmError):
    pass


class ForbiddenError(OpenEtrmError):
    """Raised when an authenticated, correctly-roled user is nonetheless not entitled
    to the specific book/desk they're trying to read or act on -- see
    app.modules.entitlements. Distinct from a 401 (not authenticated) and from
    require_role's 403 (wrong role): this is a data-scoping failure, not a
    capability failure -- a TRADER role can confirm trades in general, but not on a
    desk they aren't a member of."""


class InsufficientMarketDataError(OpenEtrmError):
    """Raised when a curve cannot be bootstrapped because required quotes are missing."""
