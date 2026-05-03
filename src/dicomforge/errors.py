"""Exception types with actionable messages."""


class DicomForgeError(Exception):
    """Base class for package-specific errors."""


class MissingBackendError(DicomForgeError):
    """Raised when an optional backend is required but not installed."""


class UnsupportedTransferSyntaxError(DicomForgeError):
    """Raised when no registered codec can handle a transfer syntax."""


class DicomValidationError(DicomForgeError, ValueError):
    """Raised when a dataset is not valid enough for the requested operation."""


class InvalidTagError(DicomForgeError, ValueError):
    """Raised when a DICOM tag cannot be parsed."""
