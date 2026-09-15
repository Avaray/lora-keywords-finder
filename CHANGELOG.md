# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-15

### Added
- **SHA-256 hash field** — always-visible read-only textbox showing the hash of the selected LoRA file, useful for manual CivitAI lookups.
- **CivitAI URL field** — always-visible read-only textbox displaying the direct link to the model page (`https://civitai.com/models/<id>`), or `"URL not available"` when the model was not found on CivitAI.
- **Open-in-browser button (🌐)** — opens the CivitAI model URL in the default browser via `window.open()`; does nothing when URL is unavailable.
- **Advanced Options accordion** (collapsed by default) at the bottom of the extension panel, containing:
  - **🗑️ Clear Cache** — removes all cached `.json` files from the `known/` directory and reports how many were deleted.
  - **⬇️ Fetch All Metadata** — hashes every LoRA file on disk, skips already-cached entries, then fetches metadata for the rest using the CivitAI bulk endpoint (`POST /api/v1/model-versions/by-hash`) in chunks of up to 100 hashes per request. Each chunk retries once after a 1-second pause on failure. Live progress is shown in a status textbox.

### Changed
- **Cache format** upgraded from a plain JSON array of keywords to a rich JSON object containing `hash`, `model_id`, `version_id`, `model_url`, `keywords`, and `not_found`. This is a **breaking change** — existing plain-array cache files are treated as stale and re-fetched automatically on next selection.
- **Error messages** are now more descriptive and user-friendly:
  - HTTP 404 from CivitAI → `"This LoRA was not found on CivitAI"` (instead of the misleading `"Failed to fetch keywords from CivitAI API"`).
  - Other non-200 HTTP responses → `"CivitAI API error (HTTP <code>)"`.
  - Network / connection errors → `"Network error — could not reach CivitAI"`.
- Models returning HTTP 404 now have their `not_found` status persisted to cache, preventing unnecessary repeat API calls on subsequent selections.
- JavaScript copy-guard and Python non-copyable prefix list updated to reflect all new message strings.

## [1.0.0] - 2024-01-01

### Added
- Initial release.
- LoRA file dropdown with reload button, listing all `.pt` and `.safetensors` files from the LoRA directory (including subdirectories).
- Automatic SHA-256 hashing of selected files and lookup via CivitAI API (`GET /api/v1/model-versions/by-hash/<hash>`).
- Keyword caching to disk (`known/<hash>.json`) to avoid redundant API calls.
- **⚡️ Copy to Prompt** button — appends fetched keywords to the active txt2img or img2img prompt textarea.
- Support for ForgeUI and other AUTOMATIC1111-based UIs.

[2.0.0]: https://github.com/Avaray/lora-keywords-finder/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Avaray/lora-keywords-finder/releases/tag/v1.0.0
