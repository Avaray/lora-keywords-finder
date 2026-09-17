import os
import re
import json
import html
import time
import threading
import hashlib
import requests
import gradio as gr  # type: ignore
from modules import scripts
from modules import shared

cache_dir = os.path.join(scripts.basedir(), "metadata_cache")
os.makedirs(cache_dir, exist_ok=True)
config_file = os.path.join(scripts.basedir(), "config.json")

# True once the directory has been scanned; only the first scan waits for
# symlink targets that are not mounted yet (see _wait_for_symlinks).
symlink_wait_done = False


DEFAULT_CONFIG = {
    "show_images": True,
    "show_advanced": False,
    "include_community_images": False,
    "show_nsfw_images": False,
    "skip_dialog": False,
    "follow_symlinks": False,
}


def load_config():
    """
    Read config.json on top of DEFAULT_CONFIG.

    Missing keys fall back to their default, but keys that *are* stored always
    win — a config written by an older version never silently resets the rest
    of the settings. A damaged file is reported instead of being swallowed.
    """
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                config.update(stored)
                # Migrate the old "gallery_mode" radio setting ("Official" /
                # "Community") to the "Include community images" checkbox.
                if "gallery_mode" in config:
                    if "include_community_images" not in stored:
                        config["include_community_images"] = (
                            config["gallery_mode"] == "Community"
                        )
                    config.pop("gallery_mode", None)
            else:
                print(
                    "[🧙 LoRA Keywords Finder] config.json has an unexpected format"
                    " — falling back to defaults"
                )
        except Exception as e:
            print(
                f"[🧙 LoRA Keywords Finder] Could not read config.json ({e}) — using defaults"
            )
    return config


def save_config(config):
    """Write config.json atomically so a crash can never leave a truncated file."""
    import time
    tmp_file = f"{config_file}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
            
        for attempt in range(5):
            try:
                os.replace(tmp_file, config_file)
                break
            except Exception as e:
                win_err = getattr(e, "winerror", None)
                errno = getattr(e, "errno", None)
                if win_err == 32 or errno in (11, 13, 16):
                    if attempt < 4:
                        time.sleep(0.05)
                        continue
                raise
                
    except Exception as e:
        # File locked / sharing violation (Windows + Linux)
        win_err = getattr(e, "winerror", None)
        errno = getattr(e, "errno", None)
        if win_err == 32 or errno in (11, 13, 16):  # EAGAIN, EACCES, EBUSY
            print(
                "[🧙 LoRA Keywords Finder] Could not save config.json — "
                "the file is locked by another process. Close any other Stable Diffusion windows or editors and try again."
            )
        else:
            print(f"[🧙 LoRA Keywords Finder] Could not save config.json: {e}")
        try:
            os.remove(tmp_file)
        except OSError:
            pass


def plural(count: int, word: str, suffix: str = "s") -> str:
    """
    Append the optional plural suffix when needed.

    plural(1, "file")        -> "file"
    plural(3, "file")        -> "files"
    plural(2, "hash", "es")  -> "hashes"
    """
    return word if abs(count) == 1 else f"{word}{suffix}"


def hashing_status_message(total: int) -> str:
    """
    Status text for the "hashing files" phase, scaled to how long it will
    likely take so small libraries don't get an unnecessary "this may take
    a while" caveat, and large ones get an honest heads-up.

      1-49   -> no time estimate
      50-199 -> "This may take a moment."
      200-249-> "This may take a few minutes."
      250+   -> "This may take a long time."
    """
    base = f"🔍 Hashing {total} {plural(total, 'file')}."
    if total < 50:
        return base
    if total < 200:
        return f"{base} This may take a moment."
    if total < 250:
        return f"{base} This may take a few minutes."
    return f"{base} This may take a long time."


def attr_text(text: str) -> str:
    """Escape text so it can be safely used inside an HTML attribute."""
    return html.escape(text, quote=True).replace("\n", "&#10;")


# Hover tooltips for the Advanced Options checkboxes — edit the texts here.
# "\n" inside a text becomes a line break in the tooltip.
OPTION_TOOLTIPS = {
    "show-adv-fields": "Show additional information about the model.",
    "follow-symlinks": "Respect and follow symbolic links.",
    "skip-dialog": "Skip the confirmation dialog when replacing the prompt using image gallery buttons.",
    "show-images": "Display the image gallery.",
    "include-community": "Also show images created by the community, in addition to the model author's own images. Community images may have incorrect or missing metadata, so use with caution.",
    "show-nsfw": "Show NSFW (Not Safe For Work) images in the gallery.",
}


def option_classes(key: str) -> list:
    """elem_classes for an Advanced Options checkbox: spacing + tooltip hook."""
    return ["lkf-margin-cb", "lkf-opt", f"lkf-opt-{key}"]


def option_tooltip_css() -> str:
    """
    Build the hover-tooltip CSS from OPTION_TOOLTIPS.

    Gradio components cannot carry a plain title="" attribute, so the text is
    drawn with a ::after pseudo-element that fades in on hover.
    """
    rules = [
        ".lkf-opt { position: relative !important; overflow: visible !important; }",
        ".lkf-opt::after {"
        " position: absolute !important; left: 0 !important; top: 100% !important;"
        " z-index: 1000 !important; width: max-content !important;"
        " max-width: 280px !important; padding: 6px 9px !important;"
        " margin-top: 4px !important; border-radius: 6px !important;"
        " background: rgba(0, 0, 0, 0.88) !important; color: #fff !important;"
        " font-size: 12px !important; font-weight: 400 !important;"
        " line-height: 1.4 !important; white-space: pre-wrap !important;"
        " text-align: left !important; pointer-events: none !important;"
        " opacity: 0 !important; visibility: hidden !important;"
        " transition: opacity 0.15s ease !important; }",
        ".lkf-opt:hover::after {"
        " opacity: 1 !important; visibility: visible !important;"
        " transition-delay: 0.4s !important; }",
    ]
    for key, text in OPTION_TOOLTIPS.items():
        content = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\A ")
        rules.append(f'.lkf-opt-{key}::after {{ content: "{content}" !important; }}')
    return "\n            ".join(rules)


CIVITAI_SINGLE_URL = "https://civitai.com/api/v1/model-versions/by-hash/{hash}"
CIVITAI_BATCH_URL = "https://civitai.com/api/v1/model-versions/by-hash"

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

# CivitAI sometimes stores a placeholder word instead of a real prompt (e.g.
# metadata scrubbed by the uploader's tool). Treated as "no prompt" only when
# the ENTIRE trimmed prompt is just one of these words — case-insensitive.
# Edit this set to add/remove placeholder words.
_PLACEHOLDER_PROMPT_WORDS = frozenset(
    {
        "unknown",
        "not specified",
        "null",
        "false",
        "no",
        "undefined",
        "embedded",
        "empty",
        "placeholder",
        "n/a",
    }
)


def _is_placeholder_prompt(text: str) -> bool:
    """True when `text` is entirely one of the known placeholder words."""
    return bool(text) and text.strip().lower() in _PLACEHOLDER_PROMPT_WORDS


class LoraKeywordsFinder(scripts.Script):
    def __init__(self):
        super().__init__()
        self._cancel_fetch = threading.Event()

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

        try:
            nsfw_level = int(api_data.get("nsfwLevel", 1))
        except (ValueError, TypeError):
            nsfw_level = 1

        domain = "civitai.red" if nsfw_level > 2 else "civitai.com"
        base_url = f"https://{domain}/models/{model_id}"

        model_url = (
            f"{base_url}?modelVersionId={version_id}"
            if model_id and version_id
            else base_url
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
                    "nsfwLevel": img.get("nsfwLevel"),
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

    def _walk_error(self, err):
        """os.walk ignores filesystem errors by default — report them instead."""
        path = getattr(err, "filename", "?")
        print(f"[🧙 LoRA Keywords Finder] Could not read '{path}': {err}")

    def _dir_key(self, path: str):
        """(device, inode) identity of a directory, or None when unreadable."""
        try:
            st = os.stat(path)
            return (st.st_dev, st.st_ino)
        except OSError as e:
            print(f"[🧙 LoRA Keywords Finder] Could not stat '{path}': {e}")
            return None

    def _wait_for_symlinks(self, lora_dir: str, attempts: int = 4, delay: float = 0.5):
        """
        A symlink pointing at a network share, an external drive or a mount that
        is still coming up resolves to nothing right after startup — the scan
        then silently skips it. Give such targets a moment before walking, and
        report the ones that never showed up.

        Only the first scan waits; later scans (🔄, toggling the checkbox) just
        report, so a permanently broken link never stalls the UI.
        """
        global symlink_wait_done
        if symlink_wait_done:
            attempts = 1
        symlink_wait_done = True

        pending = []
        for attempt in range(attempts):
            pending = []
            try:
                with os.scandir(lora_dir) as entries:
                    for entry in entries:
                        if entry.is_symlink() and not os.path.exists(entry.path):
                            pending.append(entry.path)
            except Exception as e:
                print(f"[🧙 LoRA Keywords Finder] Could not scan '{lora_dir}': {e}")
                return
            if not pending:
                return
            if attempt < attempts - 1:
                print(
                    f"[🧙 LoRA Keywords Finder] Waiting for {len(pending)}"
                    f" unresolved symlink {plural(len(pending), 'target')}…"
                )
                time.sleep(delay)
        for path in pending:
            try:
                target = os.readlink(path)
            except OSError:
                target = "?"
            print(
                f"[🧙 LoRA Keywords Finder] Symlink target unavailable (broken or not"
                f" mounted): '{path}' -> '{target}'"
            )

    _cached_lora_files = None
    _cached_lora_time = 0.0
    _cached_symlink_state = None

    def _list_lora_files(self, force_reload=False):
        import time
        lora_dir = shared.cmd_opts.lora_dir
        follow_symlinks = load_config().get("follow_symlinks", False)
        
        if not force_reload and LoraKeywordsFinder._cached_lora_files is not None:
            if LoraKeywordsFinder._cached_symlink_state == follow_symlinks:
                if time.time() - LoraKeywordsFinder._cached_lora_time < 5.0:
                    return list(LoraKeywordsFinder._cached_lora_files)

        if follow_symlinks:
            self._wait_for_symlinks(lora_dir)

        visited_dirs = set()
        root_key = self._dir_key(lora_dir)
        if root_key:
            visited_dirs.add(root_key)

        root_files, subdir_files = [], []
        for root, dirs, files in os.walk(
            lora_dir, followlinks=follow_symlinks, onerror=self._walk_error
        ):
            if follow_symlinks:
                # Following links can revisit a directory through a second path
                # or loop forever — keep each real directory exactly once.
                keep = []
                for d in dirs:
                    key = self._dir_key(os.path.join(root, d))
                    if key is None or key in visited_dirs:
                        continue
                    visited_dirs.add(key)
                    keep.append(d)
                dirs[:] = keep
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
        result = root_files + subdir_files
        print(
            f"[🧙 LoRA Keywords Finder] Listed {len(result)} {plural(len(result), 'file')}"
            f" in '{lora_dir}' (follow symlinks: {'on' if follow_symlinks else 'off'})"
        )
        
        LoraKeywordsFinder._cached_lora_files = list(result)
        LoraKeywordsFinder._cached_symlink_state = follow_symlinks
        import time
        LoraKeywordsFinder._cached_lora_time = time.time()
        
        return result

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

    _ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

    @staticmethod
    def _is_allowed_image_url(url: str) -> bool:
        """Return True only if the URL's path ends with an allowed image extension."""
        if not url:
            return False
        from urllib.parse import urlparse

        path = urlparse(url).path.lower()
        # Strip query parameters that some CDNs append (e.g. /image.jpeg?width=…)
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        return ext in LoraKeywordsFinder._ALLOWED_IMAGE_EXTS

    def _fetch_community_images(
        self, version_id: str, show_nsfw: bool = False
    ) -> tuple:
        import requests

        str_version_id = str(version_id)
        try:
            url = f"https://civitai.com/api/v1/images?modelVersionId={version_id}&sort=Most%20Reactions&period=AllTime&limit=100&withMeta=true"
            if show_nsfw:
                url += "&nsfw=true"
            else:
                url += "&browsingLevel=3"

            resp = requests.get(
                url,
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    print(
                        f"[🧙 LoRA Keywords Finder] API error fetching community images: {data['error']}"
                    )
                    return [], "", data["error"]

                items = data.get("items", [])
                next_page = data.get("metadata", {}).get("nextPage", "")
                valid_images = []
                for item in items:
                    meta = item.get("meta")
                    if not meta or not (
                        meta.get("prompt") or meta.get("negativePrompt")
                    ):
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
                            "id": item.get("id"),
                            "url": item.get("url", ""),
                            "prompt": meta.get("prompt", ""),
                            "negativePrompt": meta.get("negativePrompt", ""),
                            "nsfw": item.get("nsfw"),
                            "nsfwLevel": item.get("nsfwLevel"),
                        }
                    )
                    if len(valid_images) >= 21:
                        break
                return valid_images, next_page, ""
            else:
                msg = f"HTTP {resp.status_code}"
                print(
                    f"[🧙 LoRA Keywords Finder] {msg} fetching community images: {resp.text[:200]!r}"
                )
                return [], "", msg
        except Exception as e:
            print(f"[🧙 LoRA Keywords Finder] Error fetching community images: {e}")
            return [], "", str(e)

    def _fetch_batch_chunk(self, chunk: list) -> tuple:
        """
        POST up to 100 hashes to the batch endpoint.

        CivitAI expects the request body to be a bare JSON array of hash
        strings (e.g. ["hash1", "hash2", ...]) — NOT an object like
        {"hashes": [...]}. Sending the wrong shape gets every request
        rejected with HTTP 400 ("expected array"), which used to make
        batch mode silently fall back to per-hash requests every single
        time instead of actually batching.

        Retries once after 1 s on genuine failure.
        Returns (True, {lowercase_hash: api_object}) on HTTP 200,
        or (False, {}) when both attempts fail for a real error.

        An empty result_map with success=True means none of the hashes
        were found on CivitAI (not an error). CivitAI's by-hash endpoint
        answers with HTTP 404 — instead of 200 + an empty body — when
        *none* of the hashes in the request match anything, which is the
        normal, expected outcome whenever a whole batch happens to consist
        of LoRAs that just aren't on CivitAI. That case is treated as a
        clean success here (no retry, no "failed" logging) so the UI never
        reports it as a batch failure.
        """
        for attempt in range(2):
            try:
                resp = requests.post(
                    CIVITAI_BATCH_URL,
                    json=chunk,
                    timeout=30,
                )
                if resp.status_code == 200:
                    return True, self._parse_batch_response(resp.json())
                if resp.status_code == 404:
                    # No hash in this batch matched anything on CivitAI —
                    # not a failure, nothing to retry.
                    return True, {}
                print(
                    f"[🧙 LoRA Keywords Finder] Batch attempt {attempt + 1} failed:"
                    f" HTTP {resp.status_code} — {resp.text[:200]!r}"
                )
            except Exception as e:
                print(
                    f"[🧙 LoRA Keywords Finder] Batch attempt {attempt + 1} exception: {e}"
                )
            if attempt == 0:
                time.sleep(1)
        return False, {}

    # ── UI action handlers ─────────────────────────────────────────────────────

    def _entry_to_ui(
        self,
        entry: dict,
        file_hash: str,
        show_images: bool = True,
        include_community: bool = False,
        show_nsfw: bool = False,
    ):
        images = []
        next_page_attr = ""
        using_community = False
        if show_images:
            official_images = entry.get("images") or []
            if not show_nsfw:
                filtered_official = []
                for item in official_images:
                    if isinstance(item, dict):
                        lvl = item.get("nsfwLevel")
                        if lvl in ("None", "Soft", "PG", "PG-13", 1, 2, None):
                            filtered_official.append(item)
                    else:
                        filtered_official.append(item)
                official_images = filtered_official

            community_images = []
            next_page = ""
            community_err = ""
            if include_community and entry.get("version_id"):
                community_images, next_page, community_err = (
                    self._fetch_community_images(entry.get("version_id"), show_nsfw)
                )
                using_community = bool(community_images)

            # Author images always come first; community images (when
            # requested) are appended after them. Skip any community image
            # whose URL already appeared among the author's own images so
            # the same picture never shows up twice.
            seen_urls = set()
            for item in (*official_images, *community_images):
                url = item if isinstance(item, str) else item.get("url", "")
                if not self._is_allowed_image_url(url):
                    continue
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                images.append(item)

            if using_community and next_page:
                import urllib.parse

                next_page_attr = f' data-next-page="{next_page.replace('"', "&quot;")}"'

        if show_images:
            import urllib.parse

            img_tags_list = []
            for item in images:
                if isinstance(item, str):
                    url = item
                    pos_prompt, neg_prompt = "", ""
                    image_id = None
                    is_nsfw = False
                else:
                    url = item.get("url", "")
                    pos_prompt = item.get("prompt", "")
                    neg_prompt = item.get("negativePrompt", "")

                    image_id = item.get("id")
                    if not image_id and url:
                        basename = url.rsplit("/", 1)[-1]
                        name = basename.rsplit(".", 1)[0]
                        if name.isdigit():
                            image_id = int(name)

                    is_nsfw = False
                    if "nsfw" in item:
                        is_nsfw = bool(item.get("nsfw"))
                    elif "nsfwLevel" in item:
                        lvl = item.get("nsfwLevel")
                        try:
                            lvl = int(lvl)
                            is_nsfw = lvl > 2
                        except (ValueError, TypeError):
                            pass

                if _is_placeholder_prompt(pos_prompt):
                    pos_prompt = ""
                if _is_placeholder_prompt(neg_prompt):
                    neg_prompt = ""

                if not url:
                    continue

                # An image needs at least one real prompt (positive or
                # negative) to be worth showing — without either one, there's
                # nothing useful to send to the UI.
                if not pos_prompt and not neg_prompt:
                    continue

                link_html = ""
                if image_id:
                    domain = "civitai.red" if is_nsfw else "civitai.com"
                    link_url = f"https://{domain}/images/{image_id}"
                    link_html = f'<div class="lkf-img-link-container"><a href="{link_url}" class="lkf-img-link-btn" target="_blank" title="Open post on CivitAI">🌐</a></div>'

                btn_html = '<div class="lkf-img-prompt-container">'
                if pos_prompt:
                    pos_enc = urllib.parse.quote(pos_prompt)
                    pos_title = attr_text(f"Send positive prompt to UI\n\n{pos_prompt}")
                    btn_html += f'<div class="lkf-img-prompt-btn lkf-pos-btn" data-pos="{pos_enc}" title="{pos_title}">😇</div>'
                if neg_prompt:
                    neg_enc = urllib.parse.quote(neg_prompt)
                    neg_title = attr_text(f"Send negative prompt to UI\n\n{neg_prompt}")
                    btn_html += f'<div class="lkf-img-prompt-btn lkf-neg-btn" data-neg="{neg_enc}" title="{neg_title}">😈</div>'
                btn_html += "</div>"

                # Carousel classes — based on position among the KEPT images,
                # not the raw list, since some images above may have been skipped.
                visible_cls = " lkf-visible" if len(img_tags_list) < 3 else ""
                tag = f'<div class="lkf-carousel-slide{visible_cls}"><div class="lkf-img-wrapper"><a href="{url}" class="lkf-img-link-main" target="_blank"><img src="{url}" loading="lazy"/></a>{link_html}{btn_html}</div></div>'
                img_tags_list.append(tag)

            img_tags = "".join(img_tags_list)

            # Add carousel arrows
            arrows_html = ""
            if len(img_tags_list) > 3:
                arrows_html = '<div class="lkf-carousel-nav left-arrow" style="color:white !important; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center;">🠈</div><div class="lkf-carousel-nav right-arrow" style="color:white !important; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center;">🠊</div>'

            has_official = bool(official_images)
            if using_community and has_official:
                mode_label = "Images from the model's creator + Community"
            elif using_community:
                mode_label = "Community Images (Popular)"
            else:
                mode_label = "Images from the model's creator"
                if include_community and community_err:
                    mode_label += " (Community images temporarily unavailable)"
            mode_attr = 'data-mode="community"' if using_community else ""
            version_id_attr = (
                f' data-version-id="{entry.get("version_id", "")}"'
                if using_community
                else ""
            )
            html_content = f'<span style="display: block; font-size: 14px; font-weight: 500;">{mode_label}</span><div class="lkf-carousel-container" data-current-index="0" {mode_attr}{version_id_attr}{next_page_attr}>{img_tags}{arrows_html}</div>'
            if not img_tags_list:
                msg = (
                    "Model not found on CivitAI."
                    if entry.get("not_found")
                    else "No example images found for this model."
                )
                if community_err and not entry.get("not_found"):
                    msg = "CivitAI API is currently overloaded or unavailable. Could not fetch images."
                html_content = f'<div style="padding: 20px; text-align: center; color: #888; border: 1px dashed #555; border-radius: 8px;">{msg}</div>'

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
        files = self._list_lora_files(force_reload=True)
        choices = [""] + files
        return gr.update(
            choices=choices, value="", label=f"File ({len(files)} available)"
        )

    def get_trained_words(
        self, lora_file, show_images=True, include_community=False, show_nsfw=False
    ):
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
            print(f"[🧙 LoRA Keywords Finder] File not found: {full_path}")
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
            print(f"[🧙 LoRA Keywords Finder] Error hashing {full_path}: {e}")
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

        print(f"[🧙 LoRA Keywords Finder] Selected '{lora_file}', hash: {file_hash}")

        cached = self._load_cache(file_hash)
        if cached is not None:
            print(f"[🧙 LoRA Keywords Finder] Loaded from cache for '{lora_file}'")
            return self._entry_to_ui(
                cached, file_hash, show_images, include_community, show_nsfw
            )

        # Not cached — fetch from CivitAI
        try:
            entry = self._fetch_single(file_hash)
            self._save_cache(entry)
            return self._entry_to_ui(
                entry, file_hash, show_images, include_community, show_nsfw
            )
        except Exception as e:
            err = str(e)
            print(f"[🧙 LoRA Keywords Finder] Fetch error for '{lora_file}': {err}")
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
                    print(f"[🧙 LoRA Keywords Finder] Could not delete {fname}: {e}")
        removed_files = f"{removed} {plural(removed, 'file')}"
        print(f"[🧙 LoRA Keywords Finder] Cache cleared: {removed_files} removed")
        return gr.update(value=f"✔️ Cache cleared — {removed_files} removed")

    def cancel_fetch(self):
        """Signal the running fetch_all_metadata generator to stop."""
        self._cancel_fetch.set()
        return gr.update(value="⛔ Cancelling…")

    def fetch_all_metadata(self):
        """
        Generator: hashes all LoRA files, fetches metadata in batches of 100,
        yields gr.update objects to the status textbox after each step.
        Respects self._cancel_fetch — when set, stops cleanly without writing
        any partial/incomplete cache files.
        """
        # Clear any leftover cancel signal from a previous run.
        self._cancel_fetch.clear()

        lora_files = self._list_lora_files(force_reload=True)
        total = len(lora_files)
        if total == 0:
            yield gr.update(value="No LoRA files found.")
            return

        yield gr.update(value=hashing_status_message(total))

        to_fetch = {}  # {hash: lora_file} — only uncached ones
        skipped = 0
        hash_errors = 0

        for lora_file in lora_files:
            if self._cancel_fetch.is_set():
                yield gr.update(
                    value="⛔ Cancelled during hashing. No files were modified."
                )
                return
            full_path = os.path.join(shared.cmd_opts.lora_dir, lora_file)
            try:
                h = self._hash_file(full_path)
            except Exception as e:
                print(f"[🧙 LoRA Keywords Finder] Cannot hash '{lora_file}': {e}")
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
                    f" ({hash_errors} {plural(hash_errors, 'file')} could not be read)"
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
            if self._cancel_fetch.is_set():
                yield gr.update(
                    value=f"⛔ Cancelled after {done} of {n_to_fetch} {plural(n_to_fetch, 'LoRA')}."
                    f" Already-completed entries were saved."
                )
                return

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
                    f"[🧙 LoRA Keywords Finder] Batch {chunk_index + 1} failed;"
                    f" falling back to individual requests for {len(chunk)}"
                    f" {plural(len(chunk), 'hash', 'es')}"
                )
                yield gr.update(
                    value=f"⚠️ Batch {chunk_index + 1} hit a snag — checking those"
                    f" {len(chunk)} {plural(len(chunk), 'hash', 'es')} one by one…"
                )
                for h in chunk:
                    if self._cancel_fetch.is_set():
                        yield gr.update(
                            value=f"⛔ Cancelled after {done} of {n_to_fetch} {plural(n_to_fetch, 'LoRA')}."
                            f" Already-completed entries were saved."
                        )
                        return
                    try:
                        entry = self._fetch_single(h)
                    except Exception as e:
                        print(
                            f"[🧙 LoRA Keywords Finder] Individual fetch failed for {h}: {e}"
                        )
                        entry = self._not_found_entry(h)
                        api_errors += 1
                    self._save_cache(entry)
                    done += 1
            else:
                for h in chunk:
                    if self._cancel_fetch.is_set():
                        yield gr.update(
                            value=f"⛔ Cancelled after {done} of {n_to_fetch} {plural(n_to_fetch, 'LoRA')}."
                            f" Already-completed entries were saved."
                        )
                        return
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
        print(f"[🧙 LoRA Keywords Finder] Fetch all complete — {status}")
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

        with gr.Accordion(
            "🧙 LoRA Keywords Finder", open=False, elem_id="lkf_container"
        ):
            # CSS: fix dropdown padding/margin to match textboxes
            gr.HTML(
                """<style>
            #lkf_lora_dropdown .wrap-inner { padding: 10px !important; }
            #lkf_lora_dropdown .wrap-inner input { margin: 0 !important; }
            .lkf-custom-gallery { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; justify-content: flex-start !important; gap: 8px !important; width: 100% !important; box-sizing: border-box !important; }
            
            .lkf-custom-gallery img { width: 100% !important; height: 250px !important; object-fit: cover !important; display: block !important; }
            .lkf-img-wrapper { position: relative !important; flex: 1 1 0 !important; max-width: 33.33% !important; overflow: hidden !important; border-radius: 0.5em !important; }
            .lkf-img-wrapper a.lkf-img-link-main { display: block !important; width: 100% !important; height: 100% !important; overflow: hidden !important; border-radius: 0.5em !important; position: relative !important; z-index: 0 !important; }
            .lkf-img-link-container { position: absolute !important; top: 6px !important; left: 6px !important; display: flex !important; z-index: 10 !important; pointer-events: auto !important; }
            .lkf-img-link-container a.lkf-img-link-btn { background: rgba(0,0,0,0.6) !important; color: white !important; border-radius: 4px !important; padding: 0 !important; text-decoration: none !important; font-size: 16px !important; transition: background 0.2s !important; display: flex !important; align-items: center !important; justify-content: center !important; width: 32px !important; height: 32px !important; aspect-ratio: 1/1 !important; box-sizing: border-box !important; pointer-events: auto !important; }
            .lkf-img-link-container a.lkf-img-link-btn:hover { background: rgba(0,0,0,0.9) !important; }
            .lkf-img-prompt-container { position: absolute !important; top: 6px !important; right: 6px !important; display: flex !important; gap: 4px !important; z-index: 10 !important; pointer-events: auto !important; }
            .lkf-img-prompt-container .lkf-img-prompt-btn { background: rgba(0,0,0,0.6) !important; color: white !important; border: none !important; border-radius: 4px !important; padding: 0 !important; cursor: pointer !important; font-size: 16px !important; transition: background 0.2s !important; display: flex !important; align-items: center !important; justify-content: center !important; width: 32px !important; height: 32px !important; aspect-ratio: 1/1 !important; box-sizing: border-box !important; pointer-events: auto !important; }
            .lkf-img-prompt-container .lkf-img-prompt-btn:hover { background: rgba(0,0,0,0.9) !important; }
            .lkf-opt-row { row-gap: 8px !important; margin-bottom: 8px !important; }
            .lkf-opt-col { gap: 8px !important; }
            .lkf-opt-col .lkf-margin-cb { margin: 0 !important; }
            .lkf-field label > span, 
            .lkf-field span[data-testid="block-info"] {
                margin-bottom: 4px !important;
                display: inline-block !important;
            }
            .lkf-field textarea {
                resize: none !important;
            }
            #lkf_fetch_all_btn {
                white-space: nowrap !important;
                flex-shrink: 0 !important;
            }
            """
                + option_tooltip_css()
                + """
            </style>"""
            )

            # ── Row 1: File selector + reload ────────────────────────────────

            with gr.Row(variant="compact"):
                files = self._list_lora_files()
                choices = [""] + files
                lora_dropdown = gr.Dropdown(
                    label=f"File ({len(files)} available)",
                    elem_id="lkf_lora_dropdown",
                    elem_classes=["lkf-field"],
                    choices=choices,
                    value="",
                    type="value",
                )
                reload_loras = gr.Button(
                    "🔄", scale=0, elem_classes=["tool", "lkf-reload-btn"]
                )

            gr.HTML("<div style='height: 8px'></div>")

            # ── Row 2: Keywords [📋 copy] [⚡️ to prompt] ────────────────────
            with gr.Row(variant="compact"):
                trained_words_display = gr.Textbox(
                    label="Keywords",
                    interactive=False,
                    lines=1,
                    value="",
                    placeholder="Select a file to find its keywords",
                    elem_classes=["lkf-field"],
                )
                copy_kw_btn = gr.Button(
                    "📋", scale=0, elem_classes=["tool"], interactive=False
                )
                copy_to_prompt_btn = gr.Button(
                    "⚡️", scale=0, elem_classes=["tool"], interactive=False
                )

            gr.HTML("<div style='height: 8px'></div>")

            with gr.Column(
                visible=load_config().get("show_advanced", False)
            ) as adv_fields_col:
                # ── Row 3: Name [📋 copy] ─────────────────────────────────────────
                with gr.Row(variant="compact"):
                    name_display = gr.Textbox(
                        label="Model Name",
                        interactive=False,
                        lines=1,
                        value="",
                        placeholder="",
                        elem_classes=["lkf-field"],
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
                        elem_classes=["lkf-field"],
                    )
                    model_type_display = gr.Textbox(
                        label="Model Type",
                        interactive=False,
                        max_lines=1,
                        do_not_save_to_config=True,
                        elem_classes=["lkf-field"],
                    )
                    price_display = gr.Textbox(
                        label="Access",
                        interactive=False,
                        max_lines=1,
                        do_not_save_to_config=True,
                        elem_classes=["lkf-field"],
                    )

                gr.HTML("<div style='height: 8px'></div>")

                # ── Row 4: CivitAI URL [📋 copy] [🌐 open] ───────────────────────
                with gr.Row(variant="compact"):
                    url_display = gr.Textbox(
                        label="Model Page",
                        interactive=False,
                        max_lines=1,
                        value="",
                        placeholder="",
                        elem_classes=["lkf-field"],
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
                        elem_classes=["lkf-field"],
                    )
                    copy_dl_url_btn = gr.Button(
                        "📋",
                        elem_classes=["lkf-btn-copy", "tool"],
                        scale=0,
                        min_width=40,
                        interactive=False,
                    )
                    open_dl_url_btn = gr.Button(
                        "🌐",
                        elem_classes=["lkf-btn-open-browser", "tool"],
                        scale=0,
                        min_width=40,
                        interactive=False,
                    )

                gr.HTML("<div style='height: 8px'></div>")

                # ── Row 5: SHA-256 hash [📋 copy] [🔍 open API] ──────────────────
                with gr.Row(variant="compact"):
                    hash_display = gr.Textbox(
                        label="SHA-256",
                        interactive=False,
                        max_lines=1,
                        value="",
                        placeholder="",
                        elem_classes=["lkf-field"],
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
                with gr.Row(elem_classes=["lkf-opt-row"]):
                    with gr.Column(elem_classes=["lkf-opt-col"]):
                        show_adv_fields_cb = gr.Checkbox(
                            label="Show advanced fields",
                            value=lambda: load_config().get("show_advanced", False),
                            elem_classes=option_classes("show-adv-fields"),
                        )
                        follow_symlinks_cb = gr.Checkbox(
                            label="Follow symbolic links",
                            value=lambda: load_config().get("follow_symlinks", False),
                            do_not_save_to_config=True,
                            elem_classes=option_classes("follow-symlinks"),
                        )
                        skip_dialog_cb = gr.Checkbox(
                            label="Skip paste prompt dialog",
                            value=lambda: load_config().get("skip_dialog", False),
                            do_not_save_to_config=True,
                            elem_classes=option_classes("skip-dialog"),
                        )
                    with gr.Column(elem_classes=["lkf-opt-col"]):
                        show_images_cb = gr.Checkbox(
                            label="Show image gallery",
                            value=lambda: load_config().get("show_images", True),
                            elem_classes=option_classes("show-images"),
                        )
                        include_community_cb = gr.Checkbox(
                            label="Include community images",
                            value=lambda: load_config().get(
                                "include_community_images", False
                            ),
                            do_not_save_to_config=True,
                            elem_classes=option_classes("include-community"),
                        )
                        show_nsfw_cb = gr.Checkbox(
                            label="Show NSFW images",
                            value=lambda: load_config().get("show_nsfw_images", False),
                            do_not_save_to_config=True,
                            elem_classes=option_classes("show-nsfw"),
                        )

                with gr.Row():
                    clear_cache_btn = gr.Button("🗑️ Clear Cache", variant="secondary")
                    fetch_all_btn = gr.Button(
                        "⬇️ Fetch All Metadata",
                        variant="secondary",
                        elem_id="lkf_fetch_all_btn",
                    )
                    cancel_fetch_btn = gr.Button(
                        "⛔ Cancel", variant="stop", visible=False
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

            def on_show_images_change(
                lora_file, show_images, include_community, show_nsfw
            ):
                cfg = load_config()
                cfg["show_images"] = show_images
                cfg["include_community_images"] = include_community
                cfg["show_nsfw_images"] = show_nsfw
                save_config(cfg)
                return self.get_trained_words(
                    lora_file, show_images, include_community, show_nsfw
                )

            show_images_cb.change(
                fn=on_show_images_change,
                inputs=[
                    lora_dropdown,
                    show_images_cb,
                    include_community_cb,
                    show_nsfw_cb,
                ],
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

            include_community_cb.change(
                fn=on_show_images_change,
                inputs=[
                    lora_dropdown,
                    show_images_cb,
                    include_community_cb,
                    show_nsfw_cb,
                ],
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

            show_nsfw_cb.change(
                fn=on_show_images_change,
                inputs=[
                    lora_dropdown,
                    show_images_cb,
                    include_community_cb,
                    show_nsfw_cb,
                ],
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
                inputs=[
                    lora_dropdown,
                    show_images_cb,
                    include_community_cb,
                    show_nsfw_cb,
                ],
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
                fn=lambda: (gr.update(visible=False), gr.update(visible=True)),
                outputs=[fetch_all_btn, cancel_fetch_btn],
            ).then(
                fn=self.fetch_all_metadata,
                outputs=[adv_status],
            ).then(
                fn=lambda: (gr.update(visible=True), gr.update(visible=False)),
                outputs=[fetch_all_btn, cancel_fetch_btn],
            )

            cancel_fetch_btn.click(
                fn=self.cancel_fetch,
                outputs=[adv_status],
            )

        return [
            lora_dropdown,
            trained_words_display,
            name_display,
            hash_display,
            url_display,
        ]


# Reaching this line means the whole module — including the class body above —
# executed without raising, so the extension is actually usable. A print inside
# __init__ would fire once per tab (txt2img/img2img) instead of once at startup.
print("[🧙 LoRA Keywords Finder] Extension loaded successfully.")
