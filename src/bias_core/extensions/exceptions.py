from __future__ import annotations


class ExtensionStateError(Exception):
    pass


class ExtensionNotFoundError(Exception):
    pass


class ExtensionValidationError(Exception):
    pass


class ExtensionLoadError(Exception):
    pass


class ExtensionManifestError(Exception):
    pass


class ExtensionCompatibilityError(Exception):
    pass


class ExtensionBootError(Exception):
    pass
