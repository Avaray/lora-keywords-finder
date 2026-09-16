import os
import re
import json
import html
import time
import hashlib
import requests
import gradio as gr  # type: ignore
from modules import scripts
from modules import shared

cache_dir = os.path.join(scripts.basedir(), "metadata_cache")
os.makedirs(cache_dir, exist_ok=True)
config_file = os.path.join(scripts.basedir(), "config.json")


def load_config():
    if os.path.exists(config_file):
        try:
            import json

            with open(config_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "show_images": True,
        "show_advanced": True,
        "gallery_mode": "Official",
        "skip_dialog": False,
        "follow_symlinks": False,
    }


def save_config(config):
    import json

    with open(config_file, "w") as f:
        json.dump(config, f)


def plural(count: int, word: str, suffix: str = "s") -> str:
    """
    Append the optional plural suffix when needed.

    plural(1, "file")        -> "file"
    plural(3, "file")        -> "files"
    plural(2, "hash", "es")  -> "hashes"
    """
    return word if abs(count) == 1 else f"{word}{suffix}"


def attr_text(text: str) -> str:
    """Escape text so it can be safely used inside an HTML attribute."""
    return html.escape(text, quote=True).replace("\n", "&#10;")


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
        return os.path.join(cache_dir, f"{file_hash}.json")

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
            # Migrate old model_url entries that lack ?modelVersionId
            url = data.get("model_url") or ""
            vid = data.get("version_id")
            if url and vid and "modelVersionId" not in url:
                data["model_url"] = f"{url}?modelVersionId={vid}"
                self._save_cache(data)  # silently update the cache file
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
        model_url = (
            f"{CIVITAI_MODEL_URL.format(model_id=model_id)}?modelVersionId={version_id}"
            if model_id and version_id
            else CIVITAI_MODEL_URL.format(model_id=model_id)
            if model_id
            else None
        )
        model_name = api_data.get("model", {}).get("name")
        words = api_data.get("trainedWords") or []
        words = [self._normalize_keyword(w) for w in words if w.strip()]

        base_model = api_data.get("baseModel")
        model_type = api_data.get("model", {}).get("type")
        licensing_fee = api_data.get("licensingFee")

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
            "licensing_fee": licensing_fee,
            "keywords": words,
            "images": [
                {
                    "url": img.get("url"),
                    "prompt": img.get("meta", {}).get("prompt", "")
                    if isinstance(img.get("meta"), dict)
                    else "",
                    "negativePrompt": img.get("meta", {}).get("negativePrompt", "")
                    if isinstance(img.get("meta"), dict)
                    else "",
                }
                for img in api_data.get("images", [])
                if img.get("url")
            ][:21],
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
        follow_symlinks = load_config().get("follow_symlinks", False)
        root_files, subdir_files = [], []
        for root, _, files in os.walk(lora_dir, followlinks=follow_symlinks):
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

    def _fetch_community_images(self, version_id: str) -> tuple:
        import requests

        str_version_id = str(version_id)
        try:
            resp = requests.get(
                f"https://civitai.com/api/v1/images?modelVersionId={version_id}&sort=Most%20Reactions&period=AllTime&limit=100&withMeta=true",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                next_page = data.get("metadata", {}).get("nextPage", "")
                valid_images = []
                for item in items:
                    meta = item.get("meta")
                    if not meta or not meta.get("prompt"):
                        continue
                    # Verify this image actually used THIS specific version via civitaiResources.
                    # CivitAI may tag images to a model even if a different version was used.
                    resources = meta.get("civitaiResources", [])
                    if resources:
                        used_versions = {
                            str(r.get("modelVersionId"))
                            for r in resources
                            if r.get("modelVersionId")
                        }
                        if str_version_id not in used_versions:
                            continue  # Image was tagged to model but used a different version
                    valid_images.append(
                        {
                            "url": item.get("url", ""),
                            "prompt": meta.get("prompt", ""),
                            "negativePrompt": meta.get("negativePrompt", ""),
                        }
                    )
                    if len(valid_images) >= 21:
                        break
                return valid_images, next_page
        except Exception as e:
            print(f"[LoRA Keywords] Error fetching community images: {e}")
        return [], ""

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

    def _entry_to_ui(
        self,
        entry: dict,
        file_hash: str,
        show_images: bool = True,
        gallery_mode: str = "Official",
    ):
        images = []
        next_page_attr = ""
        if show_images:
            if gallery_mode == "Community" and entry.get("version_id"):
                images, next_page = self._fetch_community_images(
                    entry.get("version_id")
                )
                if next_page:
                    import urllib.parse

                    next_page_attr = (
                        f' data-next-page="{next_page.replace('"', "&quot;")}"'
                    )

            if not images:  # Fallback or Official mode
                images = entry.get("images", [])

        if images and show_images:
            import urllib.parse

            img_tags_list = []
            for idx, item in enumerate(images):
                if isinstance(item, str):
                    url = item
                    pos_prompt, neg_prompt = "", ""
                else:
                    url = item.get("url", "")
                    pos_prompt = item.get("prompt", "")
                    neg_prompt = item.get("negativePrompt", "")

                if not url:
                    continue

                btn_html = ""
                if pos_prompt or neg_prompt:
                    btn_html = '<div class="lkf-img-prompt-container">'
                    if pos_prompt:
                        pos_enc = urllib.parse.quote(pos_prompt)
                        pos_title = attr_text(
                            f"Send positive prompt to UI\n\n{pos_prompt}"
                        )
                        btn_html += f'<div class="lkf-img-prompt-btn lkf-pos-btn" data-pos="{pos_enc}" title="{pos_title}">😇</div>'
                    if neg_prompt:
                        neg_enc = urllib.parse.quote(neg_prompt)
                        neg_title = attr_text(
                            f"Send negative prompt to UI\n\n{neg_prompt}"
                        )
                        btn_html += f'<div class="lkf-img-prompt-btn lkf-neg-btn" data-neg="{neg_enc}" title="{neg_title}">😈</div>'
                    btn_html += "</div>"

                # Carousel classes
                visible_cls = " lkf-visible" if idx < 3 else ""
                tag = f'<div class="lkf-carousel-slide{visible_cls}"><div class="lkf-img-wrapper"><a href="{url}" target="_blank"><img src="{url}" loading="lazy"/></a>{btn_html}</div></div>'
                img_tags_list.append(tag)

            img_tags = "".join(img_tags_list)

            # Add carousel arrows
            arrows_html = ""
            if len(images) > 3:
                arrows_html = '<div class="lkf-carousel-nav left-arrow">◀</div><div class="lkf-carousel-nav right-arrow">▶</div>'

            mode_label = (
                "Community Images (Popular)"
                if gallery_mode == "Community"
                else "Images from the model's creator"
            )
            mode_attr = 'data-mode="community"' if gallery_mode == "Community" else ""
            version_id_attr = (
                f' data-version-id="{entry.get("version_id", "")}"'
                if gallery_mode == "Community"
                else ""
            )
            html_content = f'<span style="display: block; font-size: 14px; font-weight: 500;">{mode_label}</span><div class="lkf-carousel-container" data-current-index="0" {mode_attr}{version_id_attr}{next_page_attr}>{img_tags}{arrows_html}</div>'
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

        base_model_str = entry.get("base_model") or ""
        if base_model_str.lower() == "unknown":
            base_model_str = ""
        model_type_str = entry.get("model_type") or ""
        licensing_fee = entry.get("licensing_fee")
        price_str = "Paid" if (licensing_fee or 0) > 0 else "Free"

        url_str = entry.get("model_url") or MSG_NO_URL
        url_has_data = bool(entry.get("model_url"))

        dl_url_str = entry.get("download_url") or MSG_NO_URL
        dl_url_has_data = bool(entry.get("download_url"))

        return (
            gr.update(value=kw_str),
            gr.update(value=name_str),
            gr.update(value=base_model_str),
            gr.update(value=model_type_str),
            gr.update(value=price_str),
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

    def get_trained_words(self, lora_file, show_images=True, gallery_mode="Official"):
        """Returns (kw, name, hash, url,
        copy_kw_btn, copy_name_btn, copy_hash_btn, copy_url_btn,
        copy_to_prompt_btn, open_url_btn, open_hash_btn)."""
        empty = (
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value=""),
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
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
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
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                *self._all_buttons_disabled(),
                gr.update(value="", visible=False),
            )

        print(f"[LoRA Keywords] Selected '{lora_file}', hash: {file_hash}")

        cached = self._load_cache(file_hash)
        if cached is not None:
            print(f"[LoRA Keywords] Loaded from cache for '{lora_file}'")
            return self._entry_to_ui(cached, file_hash, show_images, gallery_mode)

        # Not cached — fetch from CivitAI
        try:
            entry = self._fetch_single(file_hash)
            self._save_cache(entry)
            return self._entry_to_ui(entry, file_hash, show_images, gallery_mode)
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
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=file_hash),
                *self._all_buttons_disabled(),
                gr.update(value="", visible=False),
            )

    def clear_cache(self):
        removed = 0
        for fname in os.listdir(cache_dir):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                    removed += 1
                except Exception as e:
                    print(f"[LoRA Keywords] Could not delete {fname}: {e}")
        removed_files = f"{removed} {plural(removed, 'file')}"
        print(f"[LoRA Keywords] Cache cleared: {removed_files} removed")
        return gr.update(value=f"✔️ Cache cleared — {removed_files} removed")

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

        yield gr.update(value=f"🔍 Hashing {total} {plural(total, 'file')}…")

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
            msg = f"✔️ All {total} {plural(total, 'LoRA')} already cached."
            if hash_errors:
                msg += (
                    f" ({hash_errors} {plural(hash_errors, 'file')}"
                    f" could not be read)"
                )
            yield gr.update(value=msg)
            return

        n_to_fetch = len(to_fetch)
        yield gr.update(
            value=f"⬇️ Fetching metadata for {n_to_fetch}"
            f" {plural(n_to_fetch, 'LoRA')}"
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
                f" ({len(chunk)} {plural(len(chunk), 'hash', 'es')}) — fetching…"
            )

            batch_ok, result_map = self._fetch_batch_chunk(chunk)

            if not batch_ok:
                # Batch endpoint failed — fall back to individual requests
                print(
                    f"[LoRA Keywords] Batch {chunk_index + 1} failed;"
                    f" falling back to individual requests for {len(chunk)}"
                    f" {plural(len(chunk), 'hash', 'es')}"
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
        parts = [f"✔️ Done! Processed {done} {plural(done, 'LoRA')}."]
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
            
            .lkf-custom-gallery img { width: 100% !important; height: 250px !important; object-fit: cover !important; display: block !important; }
            .lkf-img-wrapper { position: relative !important; flex: 1 1 0 !important; max-width: 33.33% !important; overflow: hidden !important; border-radius: 0.5em !important; }
            .lkf-img-wrapper a { display: block !important; width: 100% !important; height: 100% !important; overflow: hidden !important; border-radius: 0.5em !important; }
            .lkf-img-prompt-container { position: absolute !important; top: 6px !important; right: 6px !important; display: flex !important; gap: 4px !important; z-index: 10 !important; }
.lkf-img-prompt-container .lkf-img-prompt-btn { position: relative !important; top: auto !important; right: auto !important; background: rgba(0,0,0,0.6) !important; color: white !important; border: none !important; border-radius: 4px !important; padding: 4px 8px !important; cursor: pointer !important; font-size: 16px !important; transition: background 0.2s !important; }
            .lkf-img-prompt-container .lkf-img-prompt-btn:hover { background: rgba(0,0,0,0.9) !important; }""")

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

            with gr.Column(
                visible=load_config().get("show_advanced", True)
            ) as adv_fields_col:
                # ── Row 3: Name [📋 copy] ─────────────────────────────────────────
                with gr.Row(variant="compact"):
                    name_display = gr.Textbox(
                        label="Model Name",
                        interactive=False,
                        value="",
                        placeholder="",
                    )
                    copy_name_btn = gr.Button(
                        "📋", scale=0, elem_classes=["tool"], interactive=False
                    )

                gr.HTML("<div style='height: 8px'></div>")

                # ── Row 3.5: Base Model and Type ─────────────────────────────────────
                with gr.Row(elem_classes=["lkf-base-model-row"]):
                    base_model_display = gr.Textbox(
                        label="Base model",
                        interactive=False,
                        max_lines=1,
                    )
                    model_type_display = gr.Textbox(
                        label="Model Type",
                        interactive=False,
                        max_lines=1,
                        do_not_save_to_config=True,
                    )
                    price_display = gr.Textbox(
                        label="Access",
                        interactive=False,
                        max_lines=1,
                        do_not_save_to_config=True,
                    )

                gr.HTML("<div style='height: 8px'></div>")

                # ── Row 4: CivitAI URL [📋 copy] [🌐 open] ───────────────────────
                with gr.Row(variant="compact"):
                    url_display = gr.Textbox(
                        label="Model Page",
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
                        "📋",
                        elem_classes=["lkf-btn-copy", "tool"],
                        scale=0,
                        min_width=40,
                    )
                    open_dl_url_btn = gr.Button(
                        "🌐",
                        elem_classes=["lkf-btn-open-browser", "tool"],
                        scale=0,
                        min_width=40,
                    )

                gr.HTML("<div style='height: 8px'></div>")

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
                with gr.Row():
                    show_images_cb = gr.Checkbox(
                        label="Show example images",
                        value=lambda: load_config().get("show_images", True),
                        elem_classes=["lkf-margin-cb"],
                    )
                    gallery_mode_rb = gr.Radio(
                        choices=["Official", "Community"],
                        value=lambda: load_config().get("gallery_mode", "Official"),
                        label="Gallery Mode",
                        elem_classes=["lkf-margin-cb"],
                    )
                    show_adv_fields_cb = gr.Checkbox(
                        label="Show advanced fields",
                        value=lambda: load_config().get("show_advanced", True),
                        elem_classes=["lkf-margin-cb"],
                    )
                    skip_dialog_cb = gr.Checkbox(
                        label="Skip paste prompt dialog",
                        value=lambda: load_config().get("skip_dialog", False),
                        do_not_save_to_config=True,
                        elem_classes=["lkf-margin-cb"],
                    )
                    follow_symlinks_cb = gr.Checkbox(
                        label="Follow symbolic links",
                        value=lambda: load_config().get("follow_symlinks", False),
                        do_not_save_to_config=True,
                        elem_classes=["lkf-margin-cb"],
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
                # Bridge element: JS reads this to check skip_dialog setting
                init_skip = "1" if load_config().get("skip_dialog", False) else "0"
                skip_dialog_bridge = gr.HTML(
                    value=f'<b class="lkf-cfg-skip-dialog">{init_skip}</b>',
                    visible=False,
                    elem_classes=["lkf-hidden-bridge"],
                )

            # ── Event handlers ────────────────────────────────────────────────

            def on_show_adv_change(show_adv):
                cfg = load_config()
                cfg["show_advanced"] = show_adv
                save_config(cfg)
                return gr.update(visible=show_adv)

            show_adv_fields_cb.change(
                fn=on_show_adv_change,
                inputs=[show_adv_fields_cb],
                outputs=[adv_fields_col],
            )

            def on_skip_dialog_change(skip):
                cfg = load_config()
                cfg["skip_dialog"] = skip
                save_config(cfg)
                bridge_val = "1" if skip else "0"
                return gr.update(
                    value=f'<b class="lkf-cfg-skip-dialog">{bridge_val}</b>'
                )

            skip_dialog_cb.change(
                fn=on_skip_dialog_change,
                inputs=[skip_dialog_cb],
                outputs=[skip_dialog_bridge],
            )

            def on_follow_symlinks_change(follow):
                cfg = load_config()
                cfg["follow_symlinks"] = follow
                save_config(cfg)
                # Reload the file list immediately so new symlinked dirs appear
                files = self._list_lora_files()
                choices = [""] + files
                return gr.update(
                    choices=choices, label=f"File ({len(files)} available)", value=""
                )

            follow_symlinks_cb.change(
                fn=on_follow_symlinks_change,
                inputs=[follow_symlinks_cb],
                outputs=[lora_dropdown],
            )

            def on_show_images_change(lora_file, show_images, gallery_mode):
                cfg = load_config()
                cfg["show_images"] = show_images
                cfg["gallery_mode"] = gallery_mode
                save_config(cfg)
                return self.get_trained_words(lora_file, show_images, gallery_mode)

            show_images_cb.change(
                fn=on_show_images_change,
                inputs=[lora_dropdown, show_images_cb, gallery_mode_rb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    price_display,
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

            gallery_mode_rb.change(
                fn=on_show_images_change,
                inputs=[lora_dropdown, show_images_cb, gallery_mode_rb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    price_display,
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
                inputs=[lora_dropdown, show_images_cb, gallery_mode_rb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    price_display,
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

            gallery_mode_rb.change(
                fn=on_show_images_change,
                inputs=[lora_dropdown, show_images_cb, gallery_mode_rb],
                outputs=[
                    trained_words_display,
                    name_display,
                    base_model_display,
                    model_type_display,
                    price_display,
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

            copy_dl_url_btn.click(
                fn=None,
                inputs=[download_url_display],
                outputs=[],
                _js=copy_clipboard_js,
            )

            open_dl_url_btn.click(
                fn=None, inputs=[download_url_display], outputs=[], _js=open_url_js
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
