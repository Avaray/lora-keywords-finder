# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [2.3.0] - 2026-09-16

### Added
- **Price field** — shows `Free` or `Paid` for each model based on the CivitAI `licensingFee` value.
- **Community image carousel** — new "Community" gallery mode fetches the most-reacted community images for the selected model version from CivitAI (`withMeta=true`), filtered strictly by `modelVersionId` to show only images that used the exact version.
- **Infinite background fetching** — while browsing the community carousel, the next page of images is pre-fetched silently in the background when approaching the last visible slide; images accumulate without resetting the current position.
- **Skip paste prompt dialog** option in Advanced Options — when enabled, clicking a prompt button skips the overwrite-confirmation dialog and pastes immediately.
- **Separate positive / negative prompt buttons** — replaced the single 📝 button on gallery images with two distinct buttons: 😇 for the positive prompt and 😈 for the negative prompt; each button only appears when its respective prompt exists; each targets only its own textarea.
- **Follow symbolic links** option in Advanced Options — when enabled, the LoRA file scanner follows directory symlinks (e.g. NTFS junctions). Toggling it immediately refreshes the file dropdown. Disabled by default to avoid infinite loops on circular symlinks.

### Changed
- Renamed the ambiguous `known/` cache directory to `metadata_cache/`.
- Official example images limit raised from 3 to 21 cached per model.
- Carousel upgraded to support infinite loop scrolling; community mode locks the right arrow while a background fetch is in progress to prevent duplicate slides.
- CivitAI model URL now includes `?modelVersionId=<id>` to link directly to the selected version.

### Fixed
- Fixed an issue where read-only textboxes (`Base model`, `Type`, etc.) would display ghost data like `Unknown` on startup because WebUI forced cached `ui-config.json` values.
- Fixed the gallery mode radio button not being wired to UI update events (switching Official ↔ Community had no effect).
- Fixed community image prompts being empty because the API was called without `withMeta=true`.
- Fixed community images including unrelated model versions — images are now verified against `civitaiResources` before being shown.
- Fixed the carousel showing duplicate slides when looping without exhausting all pages.
- Fixed unequal horizontal spacing between `Base model`, `Type`, and `Price` fields caused by a redundant `margin-right` CSS class stacking with the container `gap`.
- Fixed gallery images not rendering when switching back from a model that had no images (incorrect `display: none` persisting on the HTML element).
- Fixed positive and negative prompt buttons overlapping on top of each other due to a stale `position: absolute` rule from a previously injected `<style>` tag surviving Gradio's "Reload UI".

### Performance
- Added `loading="lazy"` to all gallery images (initial and dynamically fetched), preventing the browser from downloading all hidden carousel slides simultaneously.
- Replaced the O(n) `slides.forEach` on each carousel click with a targeted O(1) index-based toggle that only touches the 6 slides involved in each transition, eliminating lag that grew unboundedly as community images accumulated.

## [2.2.0] - 2026-09-15

### Added
- **Extended Metadata Fields**: Introduced dedicated UI textboxes for "Base model", "Type", and "Download URL" providing deeper insight into loaded LoRA models.
- **Send Prompts from Images**: Clicking the 📝 overlay button directly on gallery images instantly routes their embedded generation prompts (both positive and negative) to your active txt2img or img2img fields, featuring an automatic overwrite-protection dialog.
- **Advanced UI Toggle**: Added a persistent "Show advanced fields" checkbox within the settings block, enabling users to effortlessly collapse all technical metadata for a cleaner, minimalist interface.
- Complete metadata caching architecture to automatically download and persist prompts and negative prompts securely along with new fields into `.json` cache files.

### Changed
- Refactored UI layout to utilize native `style.css` loading within the Forge extension root, bypassing aggressive Gradio 4/Svelte security constraints (DOMPurify).
- Migrated global Javascript integration to an independent `lkf_gallery.js` file leveraging global event delegation, fully immunizing prompt operations against WebUI UI DOM stripping policies.

### Fixed
- Fixed an issue causing "Base model" fields to inappropriately display the literal text "Unknown" rather than appearing cleanly empty when API data was absent.
- Resolved various component layout desyncs and visual collisions including dynamic visibility toggles remaining out-of-sync across independent tabs.
- Re-established missing horizontal / vertical CSS gaps and fixed Flexbox layout bounds that incorrectly forced image buttons outside the bounds of their wrappers.
- Restored Javascript click-bindings to newly added URL copy/browser buttons.
- Fixed an issue causing ValueError crashing operations while toggling "Show example images" on a blank state.

## [2.1.0] - 2026-09-15

### Added
- **Example Images Preview** — extracts and caches up to 3 image URLs from the CivitAI API payload, displaying them as a clean, responsive horizontal strip directly in the UI. 
- The image preview handles varying aspect ratios perfectly using a fixed height (`250px`) and `object-fit: cover`.
- Image previews are clickable, allowing users to open the full uncropped original image in a new browser tab.
- Support for additional LoRA file extensions: `.ckpt`, `.gguf`, `.onnx`, `.pkl`, and `.pth` (in addition to `.pt` and `.safetensors`).

### Changed
- The Advanced Options buttons (`Clear Cache` and `Fetch All Metadata`) now have rounded corners (`border-radius: 0.5em`) to match the style of action buttons in the UI.
- Replaced the default Gradio `gr.Gallery` component with a highly customized HTML/CSS implementation for a much cleaner and more integrated look.

## [2.0.0] - 2026-09-15

### Added
- **Name field** — displays the model name fetched from CivitAI JSON (`model.name`), positioned between Keywords and CivitAI URL.
- **SHA-256 hash field** — always-visible read-only textbox showing the hash of the selected LoRA file.
- **CivitAI URL field** — always-visible read-only textbox displaying the direct link to the model page (`https://civitai.com/models/<id>`), or `URL not available` when the model was not found on CivitAI.
- **📋 Copy-to-clipboard buttons** between each field and its action button (Keywords, Name, CivitAI URL, SHA-256); enabled only when the field contains actual data.
- **🌐 Open-in-browser button** next to CivitAI URL — opens the model page in the browser; disabled when URL is unavailable.
- **🌐 Open-in-browser button** next to SHA-256 — opens the CivitAI API hash-lookup endpoint (`https://civitai.com/api/v1/model-versions/by-hash/<hash>`) in the browser.
- **Labels** added to the LoRA dropdown and keywords textbox. The dropdown label now displays the total number of found models, e.g., `File (127 available)`, and updates automatically on UI load and when clicking the reload button.
- **Advanced Options accordion** (collapsed by default) containing:
  - **🗑️ Clear Cache** — removes all cached `.json` files from the `known/` directory and reports how many were deleted.
  - **⬇️ Fetch All Metadata** — hashes every LoRA file on disk, skips already-cached entries, then fetches metadata for the rest using the CivitAI bulk endpoint (`POST /api/v1/model-versions/by-hash`) in chunks of up to 100 hashes per request; falls back to individual per-hash requests if the batch call fails. Live progress is shown in a status textbox.

### Changed
- **Cache format** upgraded from a plain JSON array of keywords to a rich JSON object containing `hash`, `model_id`, `version_id`, `model_name`, `model_url`, `keywords`, and `not_found`. This is a **breaking change** — existing plain-array cache files are treated as stale and re-fetched automatically on next selection.
- **Error messages** are now more descriptive and user-friendly:
  - HTTP 404 from CivitAI → `Not found on CivitAI` (instead of the misleading `Failed to fetch keywords from CivitAI API`).
  - Other non-200 HTTP responses → `CivitAI API error (HTTP <code>)`.
  - Network / connection errors → `Network error — could not reach CivitAI`.
- Models returning HTTP 404 now have their `not_found` status persisted to cache, preventing unnecessary repeat API calls on subsequent selections.
- **Action buttons** (⚡️ copy-to-prompt, 🌐 open URL) are now **disabled** when their field contains no data; enabled only when valid data is available. Copy buttons follow the same rule.
- **Batch fetch** (`_fetch_batch_chunk`) now returns `(success, result_map)` tuple — distinguishes a real API failure from an empty-but-valid response; on failure falls back to individual requests instead of wrongly marking all hashes as not found.
- **CivitAI URL field** is positioned above the SHA-256 hash field.
- **Dropdown padding** normalised to match textbox fields via CSS (`wrap-inner` padding set to 10px, `input` margin removed).
- JavaScript copy-guard (preventing error strings from being sent to the prompt) and URL validators updated to reflect all new message strings (`Not found on CivitAI`, `Not available`, etc.).
- Missing `model_name` from CivitAI is gracefully handled by displaying `Not available`, maintaining UI consistency and correctly disabling action buttons.

## [1.0.0] - 2024-01-01

### Added
- Initial release.
- LoRA file dropdown with reload button, listing all `.pt` and `.safetensors` files from the LoRA directory (including subdirectories).
- Automatic SHA-256 hashing of selected files and lookup via CivitAI API (`GET /api/v1/model-versions/by-hash/<hash>`).
- Keyword caching to disk (`known/<hash>.json`) to avoid redundant API calls.
- **⚡️ Copy to Prompt** button — appends fetched keywords to the active txt2img or img2img prompt textarea.
- Support for ForgeUI and other AUTOMATIC1111-based UIs.

[Unreleased]: https://github.com/Avaray/lora-keywords-finder/compare/v2.3.0...main
[2.3.0]: https://github.com/Avaray/lora-keywords-finder/compare/0239519...4c0deaf
[2.2.0]: https://github.com/Avaray/lora-keywords-finder/compare/ead5668...0239519
[2.1.0]: https://github.com/Avaray/lora-keywords-finder/compare/cb2d011...ead5668
[2.0.0]: https://github.com/Avaray/lora-keywords-finder/compare/961a028...cb2d011
[1.0.0]: https://github.com/Avaray/lora-keywords-finder/commit/961a028
