# 🔍 LoRA Keywords Finder

![Image of extension lora-keywords-finder](/public/image_of_extension.jpg "Image of extension lora-keywords-finder")

This Extension lets you easily find trained words, example images, and metadata for your local [LoRA](https://wiki.civitai.com/wiki/Low-Rank_Adaptation) models by querying the [CivitAI API](https://developer.civitai.com/docs/api/public-rest).  
Primarily created for [Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge), it also works seamlessly with other UIs based on [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui).

## ✨ Features

- **Instant Keywords**: Fetches and lists the trained words associated with your models.
- **Visual Previews**: Displays example images from CivitAI right in your WebUI.
- **One-Click Prompts**: Click the 📝 button on any example image to instantly send its original positive and negative prompts directly to your active textboxes (txt2img/img2img).
- **Deep Metadata**: Access the Base Model version, Model Type, direct Download URLs, and SHA-256 hashes. Hide them instantly with the minimalist view toggle.
- **Smart Caching**: Fetched data is saved locally on your disk for instantaneous, offline access in the future.
- **Format Support**: Works out of the box with `.safetensors`, `.ckpt`, `.pt`, and `.gguf` files.

## ⚙️ Installation

### From Extensions List

1. Open the **Extensions** tab.
2. Go to the **Available** tab.
3. Click the **Load from** button.
4. Find **LoRA Keywords Finder** in the list.
5. Click the **Install** button.
6. When the installation is done, restart the WebUI (or Reload UI).

### From URL

1. Open the **Extensions** tab.
2. Go to the **Install from URL** tab.
3. Paste the following URL: `https://github.com/Avaray/lora-keywords-finder`
4. Click the **Install** button.
5. When the installation is done, restart the WebUI.

## 🚀 Usage

1. The extension will be visible in your **txt2img** and **img2img** tabs under the **🧙 LoRA Keywords Finder** accordion.
2. Select any local LoRA file from the dropdown list.
3. Fetched keywords, example images, and technical details will magically appear below. Use the quick-action buttons to copy or send text directly to your prompt!

## 📝 Notes

- The extension only works with models that are publicly available on [CivitAI](https://civitai.com/).
- Prompts and keywords will only be returned if the author specified them during the model upload.
- If the CivitAI API goes down, new models cannot be fetched, but your previously cached models will continue to work perfectly.
- Clear cache from the *Advanced Options* menu to force a re-fetch of any model's metadata.
