"""C2PA manifest helpers for embedding AI training permissions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from c2pa import Builder, Signer
from c2pa.c2pa import C2paSignerInfo, C2paSigningAlg
from cryptography import x509
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from PIL import Image, PngImagePlugin

DEFAULT_LICENSE_TEXT = (
    "AI Training License (ArtScraper) v1.0 - Short Form\n"
    "Licensor grants to any user a worldwide, non-exclusive, transferable, "
    "sublicensable, irrevocable, royalty-free license to reproduce, analyze, "
    "text- and data-mine, and use the Work to train, fine-tune, evaluate, and "
    "improve machine-learning models and related systems, and to generate and "
    "use outputs from such models. This license includes rights in any "
    "database or sui generis database rights and, to the maximum extent "
    "permitted, a waiver of moral rights and analogous rights. No endorsement "
    "implied. No removal of provenance or Content Credentials. Full terms, "
    "definitions, and limitations of liability: "
    "https://artscraper.local/licenses/ai-training-v1. Effective date: "
    "2025-09-18. License ID: LicenseRef-AI-Training-Permissive-1.0."
)


@dataclass
class LicenseDocument:
    """Represents the canonical license that is hashed into the manifest."""

    license_id: str = "LicenseRef-AI-Training-Permissive-1.0"
    license_url: str = "https://artscraper.local/licenses/ai-training-v1"
    offered_by: str = "did:web:artscraper.local"
    effective_date: str = "2025-09-18"
    text: str = DEFAULT_LICENSE_TEXT
    sha256_override: Optional[str] = None
    text_path: Optional[Path] = None
    _cached_text: Optional[str] = field(default=None, init=False, repr=False)

    def resolve_text(self) -> str:
        """Return the license text from the configured source."""
        if self._cached_text is not None:
            return self._cached_text
        if self.text_path:
            self._cached_text = Path(self.text_path).read_text(encoding="utf-8")
        else:
            self._cached_text = self.text
        return self._cached_text

    def checksum(self) -> str:
        """Compute the SHA-256 hash for the license text."""
        if self.sha256_override:
            return self.sha256_override
        digest = hashlib.sha256(self.resolve_text().encode("utf-8"))
        return digest.hexdigest()


@dataclass
class C2PAManifestConfig:
    """Configuration for synthesising the manifest and signer."""

    claim_generator: str = "artscraper/c2pa-python/1.0"
    title_prefix: str = "ArtScraper Protected Asset"
    policy_url: str = "https://artscraper.local/licenses/ai-training-v1"
    identity_did: Optional[str] = "did:web:artscraper.local"
    certificate_path: Optional[Path] = None
    private_key_path: Optional[Path] = None
    signing_algorithm: str = "PS256"
    timestamp_authority_url: Optional[str] = None
    license: LicenseDocument = field(default_factory=LicenseDocument)
    _signing_material_cache: Optional[tuple[str, str]] = field(
        default=None, init=False, repr=False
    )

    def _resolve_algorithm(self) -> C2paSigningAlg:
        try:
            return getattr(C2paSigningAlg, self.signing_algorithm.upper())
        except AttributeError as err:
            raise ValueError(
                f"Unsupported signing algorithm: {self.signing_algorithm}"
            ) from err

    def ensure_signing_material(self) -> tuple[str, str]:
        """Load or lazily create the signing certificate and key."""
        if self._signing_material_cache:
            return self._signing_material_cache
        if self.certificate_path and self.private_key_path:
            cert_pem = Path(self.certificate_path).read_text(encoding="utf-8")
            key_pem = Path(self.private_key_path).read_text(encoding="utf-8")
            self._signing_material_cache = (cert_pem, key_pem)
            return self._signing_material_cache
        common_name = self.identity_did or "did:web:artscraper.local"
        cert_pem, key_pem = _generate_self_signed(common_name)
        self._signing_material_cache = (cert_pem, key_pem)
        return self._signing_material_cache

    def create_signer(self) -> tuple[Signer, str]:
        """Instantiate a c2pa Signer and return it with the certificate."""
        cert_pem, key_pem = self.ensure_signing_material()
        signer_info = C2paSignerInfo(
            self._resolve_algorithm(),
            cert_pem.encode("utf-8"),
            key_pem.encode("utf-8"),
            (self.timestamp_authority_url or "").encode("utf-8"),
        )
        signer = Signer.from_info(signer_info)
        return signer, cert_pem

    def build_manifest(self, *, asset_title: str, asset_id: Optional[str] = None) -> Dict[str, Any]:
        """Assemble the training manifest as a JSON-serialisable dict."""
        title = f"{self.title_prefix}: {asset_title}" if self.title_prefix else asset_title
        license_hash = self.license.checksum()
        assertions: list[Dict[str, Any]] = [
            {
                "label": "cawg.training-mining",
                "data": {
                    "entries": {
                        "cawg.ai_generative_training": {
                            "use": "allowed",
                            "policy": self.policy_url,
                        },
                        "cawg.ai_inference": {"use": "allowed"},
                    }
                },
            },
            {
                "label": "com.artscraper.license",
                "data": {
                    "license_id": self.license.license_id,
                    "license_url": self.license.license_url,
                    "license_sha256": license_hash,
                    "effective_date": self.license.effective_date,
                    "offered_by": self.license.offered_by,
                },
            },
            {
                "label": "com.artscraper.license-text",
                "data": {
                    "content_type": "text/plain",
                    "text": self.license.resolve_text(),
                },
            },
        ]
        if self.identity_did:
            assertions.append(
                {
                    "label": "cawg.identity",
                    "data": {
                        "did": self.identity_did,
                        "scope": "asset",
                    },
                }
            )
        manifest: Dict[str, Any] = {
            "claim_generator": self.claim_generator,
            "title": title,
            "assertions": assertions,
        }
        if asset_id:
            manifest["instance_id"] = asset_id
        return manifest

    def build_xmp_packet(self, *, asset_title: str) -> str:
        """Create an IPTC/XMP payload expressing the same permission."""
        rights_statement = (
            f"AI training and inference allowed under {self.license.license_id} "
            f"({self.license.license_url})."
        )
        xmp = f"""
<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:iptcExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"
 xmlns:plus="http://ns.useplus.org/ldf/xmp/1.0/">
 <rdf:RDF>
  <rdf:Description rdf:about=""
   plus:DataMining="allowed"
   plus:LicensorCopyrightNotice="{self.license.license_id}"
   plus:LicensorURL="{self.license.license_url}">
   <dc:title>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{asset_title}</rdf:li>
    </rdf:Alt>
   </dc:title>
   <dc:rights>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{rights_statement}</rdf:li>
    </rdf:Alt>
   </dc:rights>
   <iptcExt:ModelReleaseTerms>{self.license.license_url}</iptcExt:ModelReleaseTerms>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
""".strip()
        return xmp


def embed_c2pa_manifest(
    *,
    source_path: Path,
    dest_dir: Path,
    manifest_config: C2PAManifestConfig,
    asset_id: Optional[str] = None,
) -> Dict[str, Path | str]:
    """Generate the XMP payload, sign the asset, and write manifest artefacts."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    asset_title = source_path.stem

    staging_path = dest_dir / f"{source_path.stem}_stage{source_path.suffix}"
    _write_with_xmp(source_path, staging_path, manifest_config.build_xmp_packet(asset_title=asset_title))

    manifest_dict = manifest_config.build_manifest(asset_title=asset_title, asset_id=asset_id)
    builder = Builder.from_json(manifest_dict)
    signer, certificate_pem = manifest_config.create_signer()
    signed_path = dest_dir / source_path.name

    try:
        builder.sign_file(str(staging_path), str(signed_path), signer)
    finally:
        builder.close()
        signer.close()
        if staging_path.exists():
            staging_path.unlink()

    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

    certificate_path = dest_dir / "certificate.pem"
    certificate_path.write_text(certificate_pem, encoding="utf-8")

    license_text = manifest_config.license.resolve_text().strip()
    license_path: Optional[Path] = None
    if license_text:
        license_path = dest_dir / "license.txt"
        license_path.write_text(license_text + "\n", encoding="utf-8")

    sidecar_path = dest_dir / f"{source_path.stem}.xmp"
    sidecar_path.write_text(
        manifest_config.build_xmp_packet(asset_title=asset_title) + "\n",
        encoding="utf-8",
    )

    return {
        "signed_path": signed_path,
        "manifest_path": manifest_path,
        "certificate_path": certificate_path,
        "license_path": license_path,
        "xmp_path": sidecar_path,
    }


def _generate_self_signed(common_name: str) -> tuple[str, str]:
    """Create a self-signed certificate for quick-start usage."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    now = datetime.now(tz=timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365 * 5))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, crypto_hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    return cert_pem, key_pem


def _write_with_xmp(source_path: Path, dest_path: Path, xmp_packet: str) -> None:
    """Copy the source image while embedding the supplied XMP block."""
    with Image.open(source_path) as img:
        img.load()
        image_format = (img.format or source_path.suffix.lstrip(".")).upper()
        xmp_bytes = xmp_packet.encode("utf-8")
        if image_format == "PNG":
            metadata = PngImagePlugin.PngInfo()
            for key, value in img.info.items():
                if isinstance(value, str):
                    metadata.add_text(key, value)
            metadata.add_text("XML:com.adobe.xmp", xmp_packet)
            img.save(dest_path, pnginfo=metadata)
        elif image_format in {"JPEG", "JPG", "JFIF"}:
            exif = img.getexif()
            img.save(dest_path, exif=exif.tobytes(), xmp=xmp_bytes)
        else:
            img.save(dest_path)
