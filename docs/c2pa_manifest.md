# C2PA AI Training Certificate

Use the built-in `c2pa` stage in `artscraper_runner` to attach an AI training
permission manifest and mirror it in IPTC/XMP metadata. Install the native
library before running the workflow:

```bash
pip install c2pa-python
```

## Manifest assertions

The manifest serialised by `C2PAManifestConfig` aligns with the CAI/CAWG
recommendations:

- `cawg.training-mining` set to `allowed` for both `cawg.ai_generative_training`
  and `cawg.ai_inference`, with a policy link at
  `https://artscraper.local/licenses/ai-training-v1`.
- `com.artscraper.license` captures the license identifier, policy URL, offered
  by DID, effective date, and a SHA-256 checksum of the canonical license text.
- `com.artscraper.license-text` embeds the full human-readable notice inside the
  manifest for tamper-evident record keeping.
- `cawg.identity` (optional) binds the assertion set to the configured DID for
  provenance.

The pipeline writes three artefacts alongside the signed image:

- `manifest.json` – the JSON manifest handed to the C2PA builder.
- `certificate.pem` – the certificate used for signing (self-signed if no
  credentials are provided).
- `<asset>.xmp` – the IPTC/XMP packet that mirrors the same grant with
  `plus:DataMining="allowed"` and a linked policy URL.

## License text (canonical copy)

> AI Training License (ArtScraper) v1.0 - Short Form
> Licensor grants to any user a worldwide, non-exclusive, transferable,
> sublicensable, irrevocable, royalty-free license to reproduce, analyze,
> text- and data-mine, and use the Work to train, fine-tune, evaluate, and
> improve machine-learning models and related systems, and to generate and use
> outputs from such models. This license includes rights in any database or sui
> generis database rights and, to the maximum extent permitted, a waiver of moral
> rights and analogous rights. No endorsement implied. No removal of provenance
> or Content Credentials. Full terms, definitions, and limitations of liability:
> https://artscraper.local/licenses/ai-training-v1. Effective date: 2025-09-18.
> License ID: LicenseRef-AI-Training-Permissive-1.0.

Update the URL, effective date, and DID to match your production policy before
shipping. The checksum recorded in the manifest automatically tracks any edits
when the workflow runs again.

## Applying the metadata tagging

Running `artscraper_runner.protection_pipeline` now performs the following for
each asset:

1. Writes a staging copy with the generated XMP packet embedded (PNG text chunk
   or JPEG XMP segment).
2. Calls `embed_c2pa_manifest` to sign the staging copy and write a
   C2PA-compliant asset with the AI training permission manifest.
3. Stores the manifest, certificate, license text, and XMP sidecar inside the
   per-image `c2pa/` folder next to the other protection layers.

If you would rather sign with a managed certificate, point
`ProtectionWorkflowConfig.c2pa_manifest.certificate_path` and
`private_key_path` at your PEM files; the helper will skip generating a
self-signed fallback.

## Verifying the result

Run a verifier such as `c2patool` against the signed output directory. The
manifest should show the `cawg.training-mining` assertion with `allowed` usage
and reference the hashed license payload. Most crawlers will also surface the
IPTC Data Mining flag directly from the embedded XMP.

*Standard disclaimer: this document is information, not legal advice.*
