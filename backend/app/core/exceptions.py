"""Core exceptions matching Odoo's exception hierarchy for AI modules."""


class UserError(Exception):
    """User-facing error (refactored from odoo.exceptions.UserError)."""


class ValidationError(Exception):
    """Schema or parameter validation error (refactored from odoo.exceptions.ValidationError)."""


class AccessError(Exception):
    """Access control error (refactored from odoo.exceptions.AccessError)."""


class UnresolvedQuery(UserError):
    """Raised when an AI field cannot be resolved from context (refactored from odoo.addons.ai_fields.tools.UnresolvedQuery)."""

