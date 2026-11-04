"""Pinned toolchain identities and the language-selection contract."""

from typing import Any, Final

from .errors import TemplateValidationError

TOOLCHAIN_CATALOG: Final = (
    {
        "language": "c",
        "toolchain_id": "gnu-gcc",
        "versions": ({"version": "12.2.0", "default": True},),
        "default_standard": "c17",
        "standards": ("c17",),
        "entrypoint": "main.c",
        "available": True,
    },
    {
        "language": "cpp",
        "toolchain_id": "gnu-g++",
        "versions": ({"version": "12.2.0", "default": True},),
        "default_standard": "c++20",
        "standards": ("c++20",),
        "entrypoint": "main.cpp",
        "available": True,
    },
    {
        "language": "java",
        "toolchain_id": "openjdk",
        "versions": ({"version": "17.0.21", "default": True},),
        "default_standard": "17",
        "standards": ("17",),
        "entrypoint": "Main.java",
        "available": True,
    },
    {
        "language": "python",
        "toolchain_id": "cpython",
        "versions": ({"version": "3.14.0", "default": True},),
        "default_standard": "3",
        "standards": ("3",),
        "entrypoint": "main.py",
        "available": True,
    },
    {
        "language": "go",
        "toolchain_id": "go",
        "versions": ({"version": "1.25.1", "default": True},),
        "default_standard": "1.25",
        "standards": ("1.25",),
        "entrypoint": "main.go",
        "available": True,
    },
)

TOOLCHAINS_BY_LANGUAGE: Final = {item["language"]: item for item in TOOLCHAIN_CATALOG}


def resolve_language_policy(
    *, language: str | None, toolchain_version: str | None, language_standard: str | None
) -> dict[str, Any]:
    if language is None:
        if toolchain_version is not None or language_standard is not None:
            raise TemplateValidationError(
                detail={"toolchain": "language_required_for_version_or_standard"}
            )
        available = [item for item in TOOLCHAIN_CATALOG if item["available"]]
        return {
            "mode": "STUDENT_SELECT",
            "language": None,
            "toolchain_id": None,
            "toolchain_version": None,
            "language_standard": None,
            "allowed_languages": [item["language"] for item in available],
            "default_versions": {
                item["language"]: next(
                    version["version"] for version in item["versions"] if version["default"]
                )
                for item in available
            },
        }

    toolchain = TOOLCHAINS_BY_LANGUAGE.get(language)
    if toolchain is None:
        raise TemplateValidationError(detail={"language": "unsupported"})
    default_version = next(
        item["version"] for item in toolchain["versions"] if item["default"]
    )
    selected_version = toolchain_version or default_version
    if selected_version not in {item["version"] for item in toolchain["versions"]}:
        raise TemplateValidationError(detail={"toolchain_version": "unsupported"})
    selected_standard = language_standard or toolchain["default_standard"]
    if selected_standard not in toolchain["standards"]:
        raise TemplateValidationError(detail={"language_standard": "unsupported"})
    return {
        "mode": "FIXED",
        "language": language,
        "toolchain_id": toolchain["toolchain_id"],
        "toolchain_version": selected_version,
        "language_standard": selected_standard,
        "allowed_languages": [language],
        "default_versions": {language: selected_version},
    }


def validate_frozen_language_policy(value: Any, *, language: str | None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "mode",
        "language",
        "toolchain_id",
        "toolchain_version",
        "language_standard",
        "allowed_languages",
        "default_versions",
    }:
        raise TemplateValidationError(detail={"toolchain": "invalid_frozen_policy"})
    allowed_languages = value["allowed_languages"]
    default_versions = value["default_versions"]
    if not isinstance(allowed_languages, list) or not allowed_languages:
        raise TemplateValidationError(detail={"toolchain": "invalid_frozen_languages"})
    if len(set(allowed_languages)) != len(allowed_languages) or not isinstance(
        default_versions, dict
    ):
        raise TemplateValidationError(detail={"toolchain": "invalid_frozen_defaults"})
    if set(default_versions) != set(allowed_languages):
        raise TemplateValidationError(detail={"toolchain": "invalid_frozen_defaults"})
    for selected_language in allowed_languages:
        entry = TOOLCHAINS_BY_LANGUAGE.get(selected_language)
        version = default_versions[selected_language]
        if (
            entry is None
            or not isinstance(version, str)
            or version not in {item["version"] for item in entry["versions"]}
        ):
            raise TemplateValidationError(detail={"toolchain": "unknown_frozen_toolchain"})
    if language is None:
        if (
            value["mode"] != "STUDENT_SELECT"
            or value["language"] is not None
            or value["toolchain_id"] is not None
            or value["toolchain_version"] is not None
            or value["language_standard"] is not None
        ):
            raise TemplateValidationError(detail={"toolchain": "invalid_student_select_policy"})
    else:
        entry = TOOLCHAINS_BY_LANGUAGE.get(language)
        if (
            entry is None
            or value["mode"] != "FIXED"
            or value["language"] != language
            or value["toolchain_id"] != entry["toolchain_id"]
            or value["toolchain_version"] not in {
                item["version"] for item in entry["versions"]
            }
            or value["language_standard"] not in entry["standards"]
            or allowed_languages != [language]
            or default_versions.get(language) != value["toolchain_version"]
        ):
            raise TemplateValidationError(detail={"toolchain": "invalid_frozen_policy"})
    return value
