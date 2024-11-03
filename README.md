# 🧙‍♂️ LoRA Keywords Finder

![Image of extension lora-keywords-finder](/public/image_of_extension.jpg "Image of extension lora-keywords-finder")

This Extension lets you find keywords for your [LoRA](https://wiki.civitai.com/wiki/Low-Rank_Adaptation) models using [CivitAI API](https://developer.civitai.com/docs/api/public-rest).  
Primarily created for [ForgeUI](https://github.com/lllyasviel/stable-diffusion-webui-forge), it should also work with other UIs based on [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui).

## Installation

### From Extensions List

1. Open "Extensions" tab.
2. Open "Available" tab.
3. Click "Load from" button.
4. Find "LoRA Keywords Finder" in the list.
5. Click "Install" button.
6. When the installation is done, reload UI.

### From URL

1. Open "Extensions" tab.
2. Open "Install from URL" tab.
3. Paste the following URL: `https://github.com/Avaray/lora-keywords-finder`
4. Click "Install" button.
5. When the installation is done, reload UI.

## Usage

1. Extension will be visible in **txt2img** and **img2img** tabs as **LoRA Keywords Finder**.
2. Select LoRA file from dropdown list.
3. Fetched keywords will be displayed below the dropdown list.

## Notes

- It only works with models that are available on [CivitAI](https://civitai.com/models).
- It only returns the keywords if author specified them in the model description.
- It saves the keywords on disk after fetching them for the first time. 
- If CivitAI API is down, you won't get any new keywords.
