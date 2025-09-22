from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, BaseSettings, Field

from .c2pa_metadata import C2PAManifestConfig, LicenseDocument

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None  # type: ignore[assignment]
    try:
        import tomli as tomllib  # type: ignore[assignment]
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        tomllib = None  # type: ignore[assignment]

CONFIG_ENV_VAR = "ARTORIZE_RUNNER_CONFIG"
SUPPORTED_CONFIG_EXTENSIONS = {".json", ".toml"}

_DEFAULT_LICENSE = LicenseDocument()
_DEFAULT_MANIFEST = C2PAManifestConfig()

if TYPE_CHECKING:
    from .protection_pipeline import ProtectionWorkflowConfig

__all__ = [
    "ProcessorRuntimeConfig",
    "ProcessorSettings",
    "load_processor_config",
    "clear_processor_config_cache",
]


class LicenseSettings(BaseModel):
    license_id: str = _DEFAULT_LICENSE.license_id
    license_url: str = _DEFAULT_LICENSE.license_url
    offered_by: str = _DEFAULT_LICENSE.offered_by
    effective_date: str = _DEFAULT_LICENSE.effective_date
    text: str = _DEFAULT_LICENSE.text
    sha256_override: Optional[str] = None
    text_path: Optional[Path] = None

    def to_dataclass(self, base_path: Optional[Path] = None) -> LicenseDocument:
        text_path = self.text_path
        if text_path and base_path and not text_path.is_absolute():
            text_path = (base_path / text_path).resolve()
        data = self.dict()
        data["text_path"] = text_path
        return LicenseDocument(**data)


class ManifestSettings(BaseModel):
    claim_generator: str = _DEFAULT_MANIFEST.claim_generator
    title_prefix: str = _DEFAULT_MANIFEST.title_prefix
    policy_url: str = _DEFAULT_MANIFEST.policy_url
    identity_did: Optional[str] = _DEFAULT_MANIFEST.identity_did
    certificate_path: Optional[Path] = None
    private_key_path: Optional[Path] = None
    signing_algorithm: str = _DEFAULT_MANIFEST.signing_algorithm
    timestamp_authority_url: Optional[str] = None
    license: LicenseSettings = Field(default_factory=LicenseSettings)

    def to_dataclass(self, base_path: Optional[Path] = None) -> C2PAManifestConfig:
        data = self.dict(exclude={"license"})
        for key in ("certificate_path", "private_key_path"):
            value = data.get(key)
            if value and base_path and not value.is_absolute():
                data[key] = (base_path / value).resolve()
        data["license"] = self.license.to_dataclass(base_path=base_path)
        return C2PAManifestConfig(**data)


class WorkflowSettings(BaseModel):
    enable_fawkes: bool = True
    enable_photoguard: bool = True
    enable_mist: bool = True
    enable_nightshade: bool = True
    watermark_strategy: Optional[str] = "invisible-watermark"
    watermark_text: str = "artscraper"
    tree_ring_frequency: float = 9.0
    tree_ring_amplitude: float = 18.0
    enable_stegano_embed: bool = False
    stegano_message: str = "Protected by artscraper"
    enable_c2pa_manifest: bool = True
    c2pa_manifest: ManifestSettings = Field(default_factory=ManifestSettings)

    def to_dataclass(self, base_path: Optional[Path] = None) -> "ProtectionWorkflowConfig":
        from .protection_pipeline import ProtectionWorkflowConfig

        data = self.dict(exclude={"c2pa_manifest"})
        data["c2pa_manifest"] = self.c2pa_manifest.to_dataclass(base_path=base_path)
        return ProtectionWorkflowConfig(**data)


class ProcessorSettings(BaseSettings):
    input_dir: Path = Field(default=Path("input"))
    output_root: Path = Field(default=Path("outputs"))
    include_hash_analysis: bool = True
    include_tineye: bool = False
    max_stage_dim: int = 512
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)

    class Config:
        env_prefix = "ARTORIZE_RUNNER_"
        env_nested_delimiter = "__"
        env_file = ".env"
        case_sensitive = False


@dataclass(frozen=True)
class ProcessorRuntimeConfig:
    input_dir: Path
    output_root: Path
    include_hash_analysis: bool
    include_tineye: bool
    max_stage_dim: int
    workflow: "ProtectionWorkflowConfig"

    def create_workflow_config(self) -> "ProtectionWorkflowConfig":
        return copy.deepcopy(self.workflow)

    @classmethod
    def from_settings(
        cls,
        settings: ProcessorSettings,
        *,
        base_path: Optional[Path],
    ) -> "ProcessorRuntimeConfig":
        workflow = settings.workflow.to_dataclass(base_path=base_path)
        input_dir = _resolve_path(settings.input_dir, base_path)
        output_root = _resolve_path(settings.output_root, base_path)
        return cls(
            input_dir=input_dir,
            output_root=output_root,
            include_hash_analysis=settings.include_hash_analysis,
            include_tineye=settings.include_tineye,
            max_stage_dim=settings.max_stage_dim,
            workflow=workflow,
        )


_CONFIG_CACHE: Dict[Optional[Path], ProcessorRuntimeConfig] = {}


def _resolve_path(path: Path, base_path: Optional[Path]) -> Path:
    if path.is_absolute() or base_path is None:
        return path.resolve()
    return (base_path / path).resolve()


def _resolve_config_path(config_path: Optional[Path | str]) -> Optional[Path]:
    if config_path is not None:
        return Path(config_path)
    env_value = os.getenv(CONFIG_ENV_VAR)
    if env_value:
        return Path(env_value)
    return None


def _load_config_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix == ".toml":
        if tomllib is None:
            raise RuntimeError(
                "TOML config support requires Python 3.11+ or the tomli package."
            )
        return tomllib.loads(path.read_text(encoding="utf-8"))
    raise ValueError(
        f"Unsupported config format '{path.suffix}'. Supported: {sorted(SUPPORTED_CONFIG_EXTENSIONS)}"
    )


def load_processor_config(
    config_path: Path | str | None = None,
    *,
    force_reload: bool = False,
) -> ProcessorRuntimeConfig:
    path = _resolve_config_path(config_path)
    cache_key = path.resolve() if path else None
    if not force_reload and cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    data: Dict[str, Any] = {}
    base_path: Optional[Path] = None
    if path:
        if not path.is_file():
            raise FileNotFoundError(f"Processor config file not found: {path}")
        data = _load_config_file(path)
        base_path = path.parent

    settings = ProcessorSettings(**data)
    runtime = ProcessorRuntimeConfig.from_settings(settings, base_path=base_path)
    _CONFIG_CACHE[cache_key] = runtime
    return runtime


def clear_processor_config_cache() -> None:
    _CONFIG_CACHE.clear()
