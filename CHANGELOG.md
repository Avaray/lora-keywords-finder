# Changelog

All notable changes to this project will be documented in this file.

## 2.0.0 - 2026-09-15

### Added
- **Name field** — displays the model name fetched from CivitAI JSON (`model.name`), positioned between Keywords and CivitAI URL.
- **SHA-256 hash field** — always-visible read-only textbox showing the hash of the selected LoRA file.
- **CivitAI URL field** — always-visible read-only textbox displaying the direct link to the model page (`https://civitai.com/models/<id>`), or `URL not available` when the model was not found on CivitAI.
- **📋 Copy-to-clipboard buttons** between each field and its action button (Keywords, Name, CivitAI URL, SHA-256); enabled only when the field contains actual data.
- **🌐 Open-in-browser button** next to CivitAI URL — opens the model page in the browser; disabled when URL is unavailable.
- **🌐 Open-in-browser button** next to SHA-256 — opens the CivitAI API hash-lookup endpoint (`https://civitai.com/api/v1/model-versions/by-hash/<hash>`) in the browser.
- **Labels** added to the LoRA dropdown (`LoRA`) and keywords textbox (`Keywords`).
- **Advanced Options accordion** (collapsed by default) containing:
  - **🗑️ Clear Cache** — removes all cached `.json` files from the `known/` directory and reports how many were deleted.
  - **⬇️ Fetch All Metadata** — hashes every LoRA file on disk, skips already-cached entries, then fetches metadata for the rest using the CivitAI bulk endpoint (`POST /api/v1/model-versions/by-hash`) in chunks of up to 100 hashes per request; falls back to individual per-hash requests if the batch call fails. Live progress is shown in a status textbox.

### Changed
- **Cache format** upgraded from a plain JSON array of keywords to a rich JSON object containing `hash`, `model_id`, `version_id`, `model_name`, `model_url`, `keywords`, and `not_found`. This is a **breaking change** — existing plain-array cache files are treated as stale and re-fetched automatically on next selection.
- **Error messages** are now more descriptive and user-friendly:
  - HTTP 404 from CivitAI → `This LoRA was not found on CivitAI` (instead of the misleading `Failed to fetch keywords from CivitAI API`).
  - Other non-200 HTTP responses → `CivitAI API error (HTTP <code>)`.
  - Network / connection errors → `Network error — could not reach CivitAI`.
- Models returning HTTP 404 now have their `not_found` status persisted to cache, preventing unnecessary repeat API calls on subsequent selections.
- **Action buttons** (⚡️ copy-to-prompt, 🌐 open URL) are now **disabled** when their field contains no data; enabled only when valid data is available. Copy buttons follow the same rule.
- **Batch fetch** (`_fetch_batch_chunk`) now returns `(success, result_map)` tuple — distinguishes a real API failure from an empty-but-valid response; on failure falls back to individual requests instead of wrongly marking all hashes as not found.
- **CivitAI URL field** is positioned above the SHA-256 hash field.
- **Dropdown padding** normalised to match textbox fields via CSS (`wrap-inner` padding set to 10px, `input` margin removed).
- JavaScript copy-guard and Python non-copyable prefix list updated to reflect all new message strings.

## 1.0.0 - 2024-01-01

### Added
- Initial release.
- LoRA file dropdown with reload button, listing all `.pt` and `.safetensors` files from the LoRA directory (including subdirectories).
- Automatic SHA-256 hashing of selected files and lookup via CivitAI API (`GET /api/v1/model-versions/by-hash/<hash>`).
- Keyword caching to disk (`known/<hash>.json`) to avoid redundant API calls.
- **⚡️ Copy to Prompt** button — appends fetched keywords to the active txt2img or img2img prompt textarea.
- Support for ForgeUI and other AUTOMATIC1111-based UIs.
