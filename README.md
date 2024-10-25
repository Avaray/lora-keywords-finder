# 🧙‍♂️ LoRA Keywords Finder for ForgeUI

![Image of extension lora-keywords-finder](/public/image_of_extension.jpg "Image of extension lora-keywords-finder")

This Extension lets you find keywords for your [LoRA](https://wiki.civitai.com/wiki/Low-Rank_Adaptation) models using [CivitAI API](https://developer.civitai.com/docs/api/public-rest).  
Created for [ForgeUI](https://github.com/lllyasviel/stable-diffusion-webui-forge) without plans to support other UIs.  
I was inspired by [this Redddit post](https://www.reddit.com/r/StableDiffusion/comments/1gbjasv/automatic1111_and_loras_for_generation_is_there/).

## Installation

Currently, the extension is not yet available in the Extensions Browser. I submitted it, but need to wait for approval.  
Until then, you can install it from URL.

1. Open "Extensions" tab in ForgeUI.
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
