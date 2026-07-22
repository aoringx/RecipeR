"""User-facing application errors and their CLI exit codes."""


class RecipeRError(Exception):
    """Base class for expected RecipeR failures."""

    exit_code = 1


class ConfigurationError(RecipeRError):
    exit_code = 2


class UnsafeURLError(RecipeRError):
    exit_code = 3


class FetchError(RecipeRError):
    exit_code = 4


class ExtractionError(RecipeRError):
    exit_code = 5


class NormalizationError(RecipeRError):
    exit_code = 6


class OutputError(RecipeRError):
    exit_code = 7
