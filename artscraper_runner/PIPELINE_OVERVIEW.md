# Artscraper Python Core Pipeline

This document summarises the end-to-end pipeline implemented in `artscraper_runner` and the processors that power the per-image analysis. It complements `PROCESSOR_PIPELINE.md` by focusing on how the Python core orchestrates each stage, what artefacts are produced, and where you can extend the workflow.

## Entry Points

- `artscraper_runner.protection_pipeline.run_full_workflow` - high-level helper that walks every file in an input directory, applies protection layers, and (optionally) runs the analysis stack. Pass a custom `ProtectionWorkflowConfig` to toggle layers or switch watermark strategies.
- `artscraper_runner.cli.build_processors` - constructs the ordered list of analysis processors that back the CLI and the pipeline's `include_hash_analysis` mode.
- `artscraper_runner.cli.main` / the `artscraper_runner.protection_pipeline` module - provide CLI access via `python -m artscraper_runner.protection_pipeline` or `python -m artscraper_runner.cli`.

## Default Protection Workflow

The pipeline processes images in this order by default:

1. **Load & normalise** - original image is saved untouched (`00-original`). Working copy is resized to max 512 px longest side for deterministic perturbations.
2. **Fawkes** (`01-fawkes`) - seeded Gaussian noise mimic of cloaking (`_apply_fawkes_like`).
3. **PhotoGuard** (`02-photoguard`) - blur + edge fusion attack approximation.
4. **Mist** (`03-mist`) - colour/contrast/sharpness amplification.
5. **Nightshade** (`04-nightshade`) - structured spatial poison perturbation.
6. **Watermark** (`05-invisible-watermark`) - injects ASCII text into RGB LSBs.

Optional layers controlled by `ProtectionWorkflowConfig`:

- **Tree-Ring watermark** - sinusoidal radial intensity modulation (`_apply_tree_ring`).
- **Stegano embed** - LSB payload write-back for provenance tags (`_apply_stegano_embed`).

For every non-original stage the pipeline emits a grayscale `<stage>_mask.png` that highlights per-pixel modifications vs. the previous step.

## ProtectionWorkflowConfig

`ProtectionWorkflowConfig` coordinates the layer stack. Key switches:

| Field | Default | Purpose |
| --- | --- | --- |
| `enable_fawkes` | `True` | Toggle the cloaking perturbation stage. |
| `enable_photoguard` | `True` | Enable/disable the blur-edge blend stage. |
| `enable_mist` | `True` | Include Mist-style colour amplification. |
| `enable_nightshade` | `True` | Keep or skip the Nightshade-inspired perturbation. |
| `watermark_strategy` | `"invisible-watermark"` | Choose between LSB text (`"invisible-watermark"`) and radial `"tree-ring"`. |
| `watermark_text` | `"artscraper"` | Payload for the invisible watermark. |
| `tree_ring_frequency` / `tree_ring_amplitude` | `9.0` / `18.0` | Controls ring density and strength. |
| `enable_stegano_embed` | `False` | Append the Stegano export layer when `True`. |
| `stegano_message` | `"Protected by artscraper"` | Message written into the steganographic payload. |

## Analysis Processor Stack

`build_processors` produces the analysis sequence consumed by the CLI and the optional pipeline analysis pass. Processors execute in order and record JSON entries in `analysis.json` and `summary.json`.

| Processor | Module | Description | Key Dependencies |
| --- | --- | --- | --- |
| `metadata` | `processors/metadata.py` | Extracts Pillow metadata + EXIF tags. | Pillow |
| `imagehash` | `processors/imagehashes.py` | Computes average, perceptual, difference, and Haar wavelet hashes. | Pillow, imagehash |
| `dhash` | `processors/dhash_proc.py` | Emits Ben Hoyt dhash row/column plus hex encoding. | Pillow, dhash |
| `blockhash` | `processors/blockhash_proc.py` | Generates 8x8 and 16x16 blockhash fingerprints. | Pillow, blockhash |
| `stegano` | `processors/stegano_proc.py` | Attempts LSB message reveal (non-blocking on failure). | Stegano |
| `tineye` *(optional)* | `processors/tineye_proc.py` | Reverse image search when `TINEYE_API_KEY` is set. | pytineye, network access |

Set `include_hash_analysis=False` when calling `run_full_workflow` to skip this stack entirely. TinEye is only added when you explicitly request it.

## Artefacts & Output Layout

For each input `<stem>` the pipeline writes:

```
outputs/<stem>/
  analysis.json          # analysis processor results (optional)
  summary.json           # manifest referencing layers, masks, and project coverage
  layers/
    00-original/<stem>.<ext>
    01-fawkes/
      <stem>.<ext>
      <stem>_fawkes_mask.png
    02-photoguard/
      <stem>.<ext>
      <stem>_photoguard_mask.png
    03-mist/
      <stem>.<ext>
      <stem>_mist_mask.png
    04-nightshade/
      <stem>.<ext>
      <stem>_nightshade_mask.png
    05-invisible-watermark/
      <stem>.<ext>
      <stem>_invisible-watermark_mask.png
    06-tree-ring/ (optional)
      ...
    07-stegano-embed/ (optional)
      ...
```

`summary.json` also tracks project coverage (Fawkes, PhotoGuard, Mist, Nightshade, watermark flavour, Stegano embed, etc.) so you can demonstrate which research implementations inspired the generated artefacts.

## Extending the Pipeline

- **New protection stage**: create a function `Image.Image -> Image.Image`, add a guard flag to `ProtectionWorkflowConfig`, and register it inside `_build_stage_sequence`.
- **Alternate masks**: modify `_generate_layer_mask` if you want perceptual difference maps instead of absolute RGB deltas.
- **Custom processors**: subclass `BaseProcessor`, export it from `artscraper_runner.processors`, and append it in `build_processors`.
- **Headless runs**: disable analysis and configure outputs via `run_full_workflow` parameters to embed the pipeline in larger systems or CI flows.

## Related Files

- `artscraper_runner/protection_pipeline.py` - core workflow, configuration, and stage definitions.
- `artscraper_runner/cli.py` - CLI glue and processor factory.
- `artscraper_runner/processors/` - individual analysis processor implementations.
- `artscraper_runner/PROCESSOR_PIPELINE.md` - broader operational guide for running the stack.



