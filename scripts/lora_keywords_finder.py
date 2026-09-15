import os
import re
import json
import time
import hashlib
import requests
import gradio as gr  # type: ignore
from modules import scripts
from modules import shared

known_dir = os.path.join(scripts.basedir(), "known")
os.makedirs(known_dir, exist_ok=True)
config_file = os.path.join(scripts.basedir(), "config.json")


def load_config():
    if os.path.exists(config_file):
        try:
            import json

            with open(config_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"show_images": True}


def save_config(config):
    import json

    with open(config_file, "w") as f:
        json.dump(config, f)


CIVITAI_SINGLE_URL = "https://civitai.com/api/v1/model-versions/by-hash/{hash}"
CIVITAI_BATCH_URL = "https://civitai.com/api/v1/model-versions/by-hash"
CIVITAI_MODEL_URL = "https://civitai.com/models/{model_id}"

MSG_NOT_ON_CIVITAI = "Not found on CivitAI"
MSG_NO_KEYWORDS = "No keywords provided for this LoRA"
MSG_NO_NAME = "Not available"
MSG_NO_URL = "Not available"

# Prefixes that should NOT be copied to the prompt
_NON_COPYABLE_PREFIXES = (
    MSG_NOT_ON_CIVITAI,
    MSG_NO_KEYWORDS,
    "Network error",
    "CivitAI API error",
    "Error:",
    "Error reading",
)


class LoraKeywordsFinder(scripts.Script):
    def __init__(self):
        super().__init__()

    def title(self):
        return "LoRA Keywords Finder"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    # ── Cache helpers ──────────────────────────────────────────────────────────

    def _cache_path(self, file_hash: str) -> str:
        return os.path.join(known_dir, f"{file_hash}.json")

    def _load_cache(self, file_hash: str):
        """Return cache dict, or None if missing / old plain-list format."""
        path = self._cache_path(file_hash)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Old format was a plain list — treat as stale
            if isinstance(data, list):
                return None
            return data
        except Exception:
            return None

    def _save_cache(self, entry: dict):
        path = self._cache_path(entry["hash"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)

    def _build_entry_from_api(self, file_hash: str, api_data: dict) -> dict:
        model_id = api_data.get("modelId")
        version_id = api_data.get("id")
        model_url = CIVITAI_MODEL_URL.format(model_id=model_id) if model_id else None
        model_name = api_data.get("model", {}).get("name")
        words = api_data.get("trainedWords") or []
        words = [self._normalize_keyword(w) for w in words if w.strip()]
        
        base_model = api_data.get("baseModel")
        model_type = api_data.get("model", {}).get("type")
        
        download_url = None
        file_hash_upper = file_hash.upper()
        for f in api_data.get("files", []):
            if f.get("hashes", {}).get("SHA256", "").upper() == file_hash_upper:
                download_url = f.get("downloadUrl")
                break
        if not download_url and api_data.get("files"):
            download_url = api_data.get("files")[0].get("downloadUrl")

        return {
            "hash": file_hash,
            "model_id": model_id,
            "version_id": version_id,
            "model_name": model_name,
            "model_url": model_url,
            "download_url": download_url,
            "base_model": base_model,
            "model_type": model_type,
            "keywords": words,
            "images": [img.get("url") for img in api_data.get("images", []) if img.get("url")][:3],
            "not_found": False,
        }

    def _not_found_entry(self, file_hash: str) -> dict:
        return {
            "hash": file_hash,
            "model_id": None,
            "version_id": None,
            "model_name": None,
            "model_url": None,
            "keywords": [],
            "images": [],
            "not_found": True,
        }

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _normalize_keyword(self, keyword: str) -> str:
        return re.sub(r",(?=[^\s])", ", ", keyword).strip()

    def _hash_file(self, full_path: str) -> str:
        with open(full_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _list_lora_files(self):
        lora_dir = shared.cmd_opts.lora_dir
        root_files, subdir_files = [], []
        for root, _, files in os.walk(lora_dir):
            for filename in files:
                if filename.lower().endswith(
                    (
                        ".bin",
                        ".ckpt",
                        ".gguf",
                        ".onnx",
                        ".pkl",
                        ".pt",
                        ".pth",
                        ".pwf",
                        ".safetensors",
                    )
                ):
                    rel_path = os.path.relpath(root, lora_dir)
                    if rel_path == ".":
                        root_files.append(filename)
                    else:
                        subdir_files.append(os.path.join(rel_path, filename))
        root_files.sort(key=str.lower)
        subdir_files.sort(
            key=lambda x: tuple(p.lower() for p in os.path.normpath(x).split(os.sep))
        )
        return root_files + subdir_files

    # ── Single-hash API fetch ──────────────────────────────────────────────────

    def _fetch_single(self, file_hash: str) -> dict:
        """Fetch one hash from CivitAI. Raises RuntimeError on unexpected HTTP errors."""
        url = CIVITAI_SINGLE_URL.format(hash=file_hash)
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return self._build_entry_from_api(file_hash, resp.json())
        if resp.status_code == 404:
            return self._not_found_entry(file_hash)
        raise RuntimeError(f"HTTP {resp.status_code}")

    # ── Batch API fetch ────────────────────────────────────────────────────────

    def _parse_batch_response(self, raw) -> dict:
        """
        Normalise the batch response into {lowercase_hash: api_object}.

        CivitAI may return either:
          - A dict keyed by hash (possibly uppercased), or
          - An array of model-version objects, each with a 'files' list.
        Unmatched hashes are silently absent from the result.
        """
        if isinstance(raw, dict):
            return {k.lower(): v for k, v in raw.items()}
        if isinstance(raw, list):
            result = {}
            for item in raw:
                for f in item.get("files", []):
                    sha = f.get("hashes", {}).get("SHA256", "")
                    if sha:
                        result[sha.lower()] = item
            return result
        return {}

    def _fetch_batch_chunk(self, chunk: list) -> tuple:
        """
        POST up to 100 hashes to the batch endpoint.
        Retries once after 1 s on failure.
        Returns (True, {lowercase_hash: api_object}) on HTTP 200,
        or (False, {}) when both attempts fail.
        An empty result_map with success=True means none of the hashes
        were found on CivitAI (not an error).
        """
        for attempt in range(2):
            try:
                resp = requests.post(
                    CIVITAI_BATCH_URL,
                    json={"hashes": chunk},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return True, self._parse_batch_response(resp.json())
                print(
                    f"[LoRA Keywords] Batch attempt {attempt + 1} failed:"
                    f" HTTP {resp.status_code}"
                )
            except Exception as e:
                print(f"[LoRA Keywords] Batch attempt {attempt + 1} exception: {e}")
            if attempt == 0:
                time.sleep(1)
        return False, {}

    # ── UI action handlers ─────────────────────────────────────────────────────

    def _entry_to_ui(self, entry: dict, file_hash: str, show_images: bool = True):
        images = entry.get("images", [])
        if images and show_images:
            img_tags = "".join(
                [
                    f'<a href="{url}" target="_blank"><img src="{url}"/></a>'
                    for url in images
                ]
            )
            html_content = f'<span style="display: block; font-size: 14px; font-weight: 500;">Example Images</span><div class="lkf-custom-gallery">{img_tags}</div>'
            gallery_update = gr.update(value=html_content, visible=True)
        else:
            gallery_update = gr.update(value="", visible=False)
        """
        Convert a cache dict to UI gr.update objects.
        Returns: (kw, name, hash, url,
                  copy_kw_btn, copy_name_btn, copy_hash_btn, copy_url_btn,
                  copy_to_prompt_btn, open_url_btn, open_hash_btn)
        """
        if entry.get("not_found"):
            kw_str = MSG_NOT_ON_CIVITAI
            kw_has_data = False
        else:
            words = entry.get("keywords") or []
            kw_str = ", ".join(words) if words else MSG_NO_KEYWORDS
            kw_has_data = bool(words)

        name_str = entry.get("model_name") or MSG_NO_NAME
        name_has_data = name_str != MSG_NO_NAME
        
        base_model_str = entry.get("base_model") or MSG_NO_NAME
        model_type_str = entry.get("model_type") or MSG_NO_NAME

        url_str = entry.get("model_url") or MSG_NO_URL
        url_has_data = bool(entry.get("model_url"))
        
        dl_url_str = entry.get("download_url") or MSG_NO_URL
        dl_url_has_data = bool(entry.get("download_url"))

        return (
            gr.update(value=kw_str),
            gr.update(value=name_str),
            gr.update(value=base_model_str),
            gr.update(value=model_type_str),
            gr.update(value=url_str),
            gr.update(value=dl_url_str),
            gr.update(value=file_hash),
            gr.update(interactive=kw_has_data),  # copy_kw_btn
            gr.update(interactive=name_has_data),  # copy_name_btn
            gr.update(interactive=url_has_data),  # copy_url_btn
            gr.update(interactive=dl_url_has_data),  # copy_dl_url_btn
            gr.update(interactive=True),  # copy_hash_btn
            gr.update(interactive=kw_has_data),  # copy_to_prompt_btn
            gr.update(interactive=url_has_data),  # open_url_btn
            gr.update(interactive=dl_url_has_data),  # open_dl_url_btn
            gr.update(interactive=True),  # open_hash_btn
            gallery_update,
        )

    def _all_buttons_disabled(self):
        """Return disabled gr.updates for all 7 interactive buttons."""
        return tuple(gr.update(interactive=False) for _ in range(9))

    def reload_lora_list(self):
        files = self._list_lora_files()
        choices = [""] + files
        return gr.update(
            choices=choices, value="", label=f"File ({len(files)} available)"
        )

    def get_trained_words(self, lora_file, show_images=True):
        """Returns (kw, name, hash, url,
        copy_kw_btn, copy_name_btn, copy_hash_btn, copy_url_btn,
        copy_to_prompt_btn, open_url_btn, open_hash_btn)."""
        empty = (
            gr.update(value=""), gr.update(value=""), gr.update(value=""),
            gr.update(value=""), gr.update(value=""), gr.update(value=""),
            gr.update(value=""),
            *self._all_buttons_disabled(),
            gr.update(value="", visible=False),
        )
        if not lora_file:
            return empty

        full_path = os.path.join(shared.cmd_opts.lora_dir, lora_file)
        try:
            file_hash = self._hash_file(full_path)
        except FileNotFoundError:
            print(f"[LoRA Keywords] File not found: {full_path}")
            return (
                gr.update(value="Error: File not found"),
                gr.update(value=""), gr.update(value=""), gr.update(value=""),
                gr.update(value=""), gr.update(value=""), gr.update(value=""),
                *self._all_buttons_disabled(),
                gr.update(value="", visible=False),
            )
        except Exception as e:
            print(f"[LoRA Keywords] Error hashing {full_path}: {e}")
            return (
                gr.update(value="Error reading file"),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                *self._all_buttons_disabled(),
            )

        print(f"[LoRA Keywords] Selected '{lora_file}', hash: {file_hash}")

        cached = self._load_cache(file_hash)
        if cached is not None:
            print(f"[LoRA Keywords] Loaded from cache for '{lora_file}'")
            return self._entry_to_ui(cached, file_hash, show_images)

        # Not cached — fetch from CivitAI
        try:
            entry = self._fetch_single(file_hash)
            self._save_cache(entry)
            return self._entry_to_ui(entry, file_hash, show_images)
        except Exception as e:
            err = str(e)
            print(f"[LoRA Keywords] Fetch error for '{lora_file}': {err}")
            msg = (
                f"CivitAI API error ({err})"
                if err.startswith("HTTP")
                else "Network error — could not reach CivitAI"
            )
            return (
                gr.update(value=msg),
                gr.update(value=""),
                gr.update(value=file_hash),
                gr.update(value=""),
                *self._all_buttons_disabled(),
            )

    def clear_cache(self):
        removed = 0
        for fname in os.listdir(known_dir):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(known_dir, fname))
                    removed += 1
                except Exception as e:
                    print(f"[LoRA Keywords] Could not delete {fname}: {e}")
        print(f"[LoRA Keywords] Cache cleared: {removed} file(s) removed")
        return gr.update(value=f"✔️ Cache cleared — {removed} file(s) removed")

    def fetch_all_metadata(self):
        """
        Generator: hashes all LoRA files, fetches metadata in batches of 100,
        yields gr.update objects to the status textbox after each step.
        """
        lora_files = self._list_lora_files()
        total = len(lora_files)
        if total == 0:
            yield gr.update(value="No LoRA files found.")
            return

        yield gr.update(value=f"🔍 Hashing {total} file(s)…")

        to_fetch = {}  # {hash: lora_file} — only uncached ones
        skipped = 0
        hash_errors = 0

        for lora_file in lora_files:
            full_path = os.path.join(shared.cmd_opts.lora_dir, lora_file)
            try:
                h = self._hash_file(full_path)
            except Exception as e:
                print(f"[LoRA Keywords] Cannot hash '{lora_file}': {e}")
                hash_errors += 1
                continue
            if self._load_cache(h) is not None:
                skipped += 1
            else:
                to_fetch[h] = lora_file

        if not to_fetch:
            msg = f"✔️ All {total} LoRA(s) already cached."
            if hash_errors:
                msg += f" ({hash_errors} file(s) could not be read)"
            yield gr.update(value=msg)
            return

        n_to_fetch = len(to_fetch)
        yield gr.update(
            value=f"⬇️ Fetching metadata for {n_to_fetch} LoRA(s)"
            f" (skipped {skipped} already cached)…"
        )

        CHUNK_SIZE = 100
        all_hashes = list(to_fetch.keys())
        total_chunks = (n_to_fetch + CHUNK_SIZE - 1) // CHUNK_SIZE
        done = 0
        api_errors = 0

        for chunk_index in range(total_chunks):
            chunk = all_hashes[
                chunk_index * CHUNK_SIZE : (chunk_index + 1) * CHUNK_SIZE
            ]
            yield gr.update(
                value=f"⬇️ Batch {chunk_index + 1}/{total_chunks}"
                f" ({len(chunk)} hashes) — fetching…"
            )

            batch_ok, result_map = self._fetch_batch_chunk(chunk)

            if not batch_ok:
                # Batch endpoint failed — fall back to individual requests
                print(
                    f"[LoRA Keywords] Batch {chunk_index + 1} failed;"
                    f" falling back to individual requests for {len(chunk)} hash(es)"
                )
                yield gr.update(
                    value=f"⚠️ Batch {chunk_index + 1} failed, retrying individually…"
                )
                for h in chunk:
                    try:
                        entry = self._fetch_single(h)
                    except Exception as e:
                        print(f"[LoRA Keywords] Individual fetch failed for {h}: {e}")
                        entry = self._not_found_entry(h)
                        api_errors += 1
                    self._save_cache(entry)
                    done += 1
            else:
                for h in chunk:
                    entry = (
                        self._build_entry_from_api(h, result_map[h])
                        if h in result_map
                        else self._not_found_entry(h)
                    )
                    self._save_cache(entry)
                    done += 1

        # Final summary
        not_found_count = sum(
            1
            for h in all_hashes
            if self._load_cache(h) and self._load_cache(h).get("not_found")
        )
        found_count = done - not_found_count
        parts = [f"✔️ Done! Processed {done} LoRA(s)."]
        parts.append(f"Found on CivitAI: {found_count}, not found: {not_found_count}.")
        if skipped:
            parts.append(f"Skipped (cached): {skipped}.")
        if hash_errors:
            parts.append(f"Hashing errors: {hash_errors}.")
        if api_errors:
            parts.append(f"API errors: {api_errors}.")
        status = " ".join(parts)
        print(f"[LoRA Keywords] Fetch all complete — {status}")
        yield gr.update(value=status)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def ui(self, is_img2img):
        # JS: copy keywords text to the active txt2img / img2img prompt textarea
        copy_js = """
        function copyToPrompt(text) {
            const skip = [
                "This LoRA was not found on CivitAI",
                "No keywords provided for this LoRA",
                "Network error",
                "CivitAI API error",
                "Error:",
                "Error reading",
                "URL not available",
            ];
            if (!text || skip.some(s => text.startsWith(s))) return text;

            const tabs = document.querySelector('#tabs')?.querySelector('div');
            if (!tabs) return text;
            const tabButtons = tabs.querySelectorAll('button');
            let activeTabIndex = -1;
            tabButtons.forEach((btn, idx) => {
                if (btn.classList.contains('selected')) activeTabIndex = idx;
            });

            let textarea;
            if (activeTabIndex === 0) {
                textarea = document.querySelector('#txt2img_prompt textarea');
            } else if (activeTabIndex === 1) {
                textarea = document.querySelector('#img2img_prompt textarea');
            }

            if (textarea) {
                const cur = textarea.value.trim();
                textarea.value = cur ? `${cur}, ${text}` : text;
                textarea.dispatchEvent(new Event('input',  { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return text;
        }
        """

        # JS: open the CivitAI model URL in a new browser tab
        open_url_js = """
        function openCivitaiUrl(url) {
            if (!url || url.trim() === "" || url.trim() === "Not available") return url;
            window.open(url.trim(), '_blank');
            return url;
        }
        """

        # JS: open the CivitAI API hash lookup in a new browser tab
        open_hash_js = """
        function openHashUrl(hash) {
            if (!hash || hash.trim() === "") return hash;
            window.open("https://civitai.com/api/v1/model-versions/by-hash/" + hash.trim(), '_blank');
            return hash;
        }
        """

        # JS: copy any text value to the system clipboard
        copy_clipboard_js = """
        function copyToClipboard(text) {
            if (!text) return text;
            navigator.clipboard.writeText(text).catch(() => {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity  = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            });
            return text;
        }
        """

        with gr.Accordion("🧙 LoRA Keywords Finder", open=False):
            # CSS: fix dropdown padding/margin to match textboxes
            gr.HTML("""<style>
            #lkf_lora_dropdown .wrap-inner { padding: 10px !important; }
            #lkf_lora_dropdown .wrap-inner input { margin: 0 !important; }
            .lkf-custom-gallery { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; justify-content: flex-start !important; gap: 8px !important; width: 100% !important; box-sizing: border-box !important; }
            .lkf-custom-gallery a { flex: 1 1 0 !important; max-width: 33.33% !important; display: block !important; overflow: hidden !important; border-radius: 0.5em !important; }
            .lkf-custom-gallery img { width: 100% !important; height: 250px !important; object-fit: cover !important; display: block !important; }
            </style>""")

            # ── Row 1: File selector + reload ────────────────────────────────

            with gr.Row(variant="compact"):
                files = self._list_lora_files()
                choices = [""] + files
                lora_dropdown = gr.Dropdown(
                    label=f"File ({len(files)} available)",
                    elem_id="lkf_lora_dropdown",
                    choices=choices,
                    value="",
                    type="value",
                )
                reload_loras = gr.Button("🔄", scale=0, elem_classes=["tool"])

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 2: Keywords [📋 copy] [⚡️ to prompt] ────────────────────
            with gr.Row(variant="compact"):
                trained_words_display = gr.Textbox(
                    label="Keywords",
                    interactive=False,
                    value="",
                    placeholder="Select a file to find its keywords",
                )
                copy_kw_btn = gr.Button(
                    "📋", scale=0, elem_classes=["tool"], interactive=False
                )
                copy_to_prompt_btn = gr.Button(
                    "⚡️", scale=0, elem_classes=["tool"], interactive=False
                )

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 3: Name [📋 copy] ─────────────────────────────────────────
            with gr.Row(variant="compact"):
                name_display = gr.Textbox(
                    label="Name",
                    interactive=False,
                    value="",
                    placeholder="",
                )
                copy_name_btn = gr.Button(
                    "📋", scale=0, elem_classes=["tool"], interactive=False
                )

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 3.5: Base Model and Type ─────────────────────────────────────
            with gr.Row():
                base_model_display = gr.Textbox(label="Base model", interactive=False, max_lines=1)
                model_type_display = gr.Textbox(label="Type", interactive=False, max_lines=1)

            # ── Row 4: CivitAI URL [📋 copy] [🌐 open] ───────────────────────
            with gr.Row(variant="compact"):
                url_display = gr.Textbox(
                    label="CivitAI URL",
                    interactive=False,
                    value="",
                    placeholder="",
                )
                copy_url_btn = gr.Button(
                    "📋", scale=0, elem_classes=["tool"], interactive=False
                )
                open_url_btn = gr.Button(
                    "🌐", scale=0, elem_classes=["tool"], interactive=False
                )

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 4.5: Download URL [📋 copy] [🌐 open] ──────────────────────
            with gr.Row(variant="compact"):
                download_url_display = gr.Textbox(
                    label="Download URL",
                    show_copy_button=False,
                    interactive=False,
                    max_lines=1,
                    scale=1,
                )
                copy_dl_url_btn = gr.Button(
                    "📋", elem_classes=["lkf-btn-copy", "tool"], scale=0, min_width=40
                )
                open_dl_url_btn = gr.Button(
                    "🌐", elem_classes=["lkf-btn-open-browser", "tool"], scale=0, min_width=40
                )

            # ── Row 5: SHA-256 hash [📋 copy] [🔍 open API] ──────────────────
            with gr.Row(variant="compact"):
                hash_display = gr.Textbox(
                    label="SHA-256",
                    interactive=False,
                    value="",
                    placeholder="",
                )
                copy_hash_btn = gr.Button(
                    "📋", scale=0, elem_classes=["tool"], interactive=False
                )
                open_hash_btn = gr.Button(
                    "🌐", scale=0, elem_classes=["tool"], interactive=False
                )

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 6: Image Gallery ─────────────────────────────────────────
            images_gallery = gr.HTML(visible=False)

            gr.HTML("<div style='height: 8px'></div>")

            # ── Advanced Options ──────────────────────────────────────────────
            with gr.Accordion("⚙️ Advanced Options", open=False):
                show_images_cb = gr.Checkbox(
                    label="Show example images",
                    value=load_config().get("show_images", True),
                    elem_classes=["lkf-margin-cb"],
                )
                gr.HTML(
                    "<style>.lkf-margin-cb { margin-bottom: 12px !important; }</style>"
                )
                with gr.Row():
                    clear_cache_btn = gr.Button("🗑️ Clear Cache", variant="secondary")
                    fetch_all_btn = gr.Button(
                        "⬇️ Fetch All Metadata", variant="secondary"
                    )
                gr.HTML("<div style='height: 8px'></div>")
                adv_status = gr.Textbox(
                    show_label=False,
                    interactive=False,
                    value="",
                    placeholder="Status will appear here…",
                )

            # ── Event handlers ────────────────────────────────────────────────

            def on_show_images_change(lora_file, show_images):
                save_config({"show_images": show_images})
                return self.get_trained_words(lora_file, show_images)

            show_images_cb.change(
                fn=on_show_images_change,
                inputs=[lora_dropdown, show_images_cb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    url_display,
                    download_url_display,
                    hash_display,
                    copy_kw_btn,
                    copy_name_btn,
                    copy_url_btn,
                    copy_dl_url_btn,
                    copy_hash_btn,
                    copy_to_prompt_btn,
                    open_url_btn,
                    open_dl_url_btn,
                    open_hash_btn,
                    images_gallery,
                ],
            )

            lora_dropdown.change(
                fn=self.get_trained_words,
                inputs=[lora_dropdown, show_images_cb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    url_display,
                    download_url_display,
                    hash_display,
                    copy_kw_btn,
                    copy_name_btn,
                    copy_url_btn,
                    copy_dl_url_btn,
                    copy_hash_btn,
                    copy_to_prompt_btn,
                    open_url_btn,
                    open_dl_url_btn,
                    open_hash_btn,
                    images_gallery,
                ],
            )

            reload_loras.click(
                fn=self.reload_lora_list,
                outputs=[lora_dropdown],
            )

            copy_kw_btn.click(
                fn=None,
                inputs=[trained_words_display],
                outputs=None,
                _js=copy_clipboard_js,
            )

            copy_name_btn.click(
                fn=None,
                inputs=[name_display],
                outputs=None,
                _js=copy_clipboard_js,
            )

            copy_url_btn.click(
                fn=None,
                inputs=[url_display],
                outputs=None,
                _js=copy_clipboard_js,
            )

            copy_hash_btn.click(
                fn=None,
                inputs=[hash_display],
                outputs=None,
                _js=copy_clipboard_js,
            )

            copy_to_prompt_btn.click(
                fn=None,
                inputs=[trained_words_display],
                outputs=None,
                _js=copy_js,
            )

            open_url_btn.click(
                fn=None,
                inputs=[url_display],
                outputs=None,
                _js=open_url_js,
            )

            open_hash_btn.click(
                fn=None,
                inputs=[hash_display],
                outputs=None,
                _js=open_hash_js,
            )

            clear_cache_btn.click(
                fn=self.clear_cache,
                outputs=[adv_status],
            )

            fetch_all_btn.click(
                fn=self.fetch_all_metadata,
                outputs=[adv_status],
            )

        return [
            lora_dropdown,
            trained_words_display,
            name_display,
            hash_display,
            url_display,
        ]
