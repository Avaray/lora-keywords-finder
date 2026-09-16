# 🧙 LoRA Keywords Finder

![Image of extension lora-keywords-finder](/assets/image_of_extension.jpg "Image of extension lora-keywords-finder")

This Extension lets you easily find trained keywords, example images, and metadata for your local [LoRA](https://en.wikipedia.org/wiki/LoRA_(machine_learning)) models by querying the [CivitAI API](https://developer.civitai.com/docs/api/public-rest). Primarily created for [Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo), it also should work with other UIs based on [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui).

## ✨ Features

- **Instant Keywords**: Fetches and lists the trained words associated with your models.
- **Visual Previews**: Displays example images from CivitAI right in your WebUI.
- **One-Click Prompts**: Click the 📝 button on any example image to instantly send its original positive and negative prompts directly to your active textboxes (txt2img/img2img).
- **Deep Metadata**: Access the Base Model version, Model Type, direct Download URLs, and SHA-256 hashes. Hide them instantly with the minimalist view toggle.
- **Smart Caching**: Fetched data is saved locally on your disk for instantaneous, offline access in the future.
- **Format Support**: Works out of the box with `.safetensors`, `.ckpt`, `.pt`, `.gguf` and `.onnx` files.

## ⚙️ Installation

### From Extensions List

1. Open the **Extensions** tab.
2. Go to the **Available** tab.
3. Click the **Load from** button.
4. Find **LoRA Keywords Finder** in the list.
5. Click the **Install** button.
6. When the installation is done, reload the UI.

### From URL

1. Open the **Extensions** tab.
2. Go to the **Install from URL** tab.
3. Paste the following URL: `https://github.com/Avaray/lora-keywords-finder`
4. Click the **Install** button.
5. When the installation is done, reload the UI.

## 🚀 Usage

1. The extension will be visible in your **txt2img** and **img2img** tabs under the **🧙 LoRA Keywords Finder** accordion.
2. Select any local LoRA file from the dropdown list.
3. Fetched keywords, example images, and technical details will appear below.
4. Optionally, expand the **Advanced Options** section for customization.

## 📝 Notes

- The extension only works with models that are publicly available on [CivitAI](https://civitai.com/). Currently, there are no other services that allow searching for models metadata by their hash values. If such services become available in the future, I will be happy to extend support beyond CivitAI.
- Prompts and keywords will only be returned if the author specified them during the model upload.
- If the [CivitAI API](https://developer.civitai.com/site/reference/) goes down, new models cannot be fetched, but your previously cached models will continue to work perfectly.
- The extension was tested with [Forge Neo 2.29.0](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo) ([Gradio 4.40.0](https://gradio.app/changelog#4-40-0)) on Windows.

## 🧾 Changelog

All notable changes to this project will be documented in the [CHANGELOG.md](CHANGELOG.md) file.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
