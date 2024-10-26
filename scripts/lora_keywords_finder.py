import hashlib
import json
import os
import re
import requests
import gradio as gr # type: ignore
from modules import scripts

class LoraKeywordsFinder(scripts.Script):

    def __init__(self):
        super().__init__()
        # Ensure the known directory exists
        known_dir = os.path.join(scripts.basedir(), "extensions", "lora-keywords-finder", "known")
        os.makedirs(known_dir, exist_ok=True)

    def title(self):
        return "LoRA Keywords Finder"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Accordion("LoRA Keywords Finder", open=False):
            with gr.Row(variant="compact"):
                # Add an empty choice as the default selection
                choices = [""] + self.list_lora_files()
                
                lora_dropdown = gr.Dropdown(
                    show_label=False,
                    choices=choices,
                    value="",  # Set empty string as default value
                    type="value"
                )

                reload_loras = gr.Button("🔄", scale=0, value="Reload list", elem_classes=["tool"])

            # Add gap between rows
            gr.HTML("<div style='height: 8px'></div>")

            with gr.Row(variant="compact"):
                trained_words_display = gr.Textbox(
                    show_label=False,
                    interactive=False,
                    value="",  # Set empty string as initial value
                    placeholder="Select a LoRA to see its keywords..."
                )

                # Event handler for dropdown change
                lora_dropdown.change(
                    fn=self.get_trained_words,
                    inputs=[lora_dropdown],
                    outputs=[trained_words_display]
                )

                # Event handler for reload button
                reload_loras.click(
                    fn=self.reload_lora_list,
                    outputs=[lora_dropdown]
                )

        return [lora_dropdown, trained_words_display]

    def normalize_keyword(self, keyword):
        return re.sub(r",(?=[^\s])", ", ", keyword).strip()

    def list_lora_files(self):
        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        lora_files = []
        for filename in os.listdir(lora_dir):
            if filename.endswith((".pt", ".safetensors")):
                lora_files.append(filename)
        return sorted(lora_files, key=str.lower)  # Sort the files alphabetically

    def reload_lora_list(self):
        """Reload the list of LoRA files and update the dropdown"""
        choices = [""] + self.list_lora_files()
        return gr.update(choices=choices, value="")

    def get_trained_words(self, lora_file):
        # Return empty string if no file is selected or empty string is selected
        if not lora_file:
            return gr.update(value="")

        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        with open(os.path.join(lora_dir, lora_file), "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        print(f"Selected {lora_file}, file hash: {file_hash}")

        known_dir = os.path.join(scripts.basedir(), "extensions", "lora-keywords-finder", "known")
        json_file_path = os.path.join(known_dir, f"{file_hash}.json")

        # Check if the JSON file exists
        if os.path.exists(json_file_path):
            # Load trained words from the JSON file
            with open(json_file_path, "r") as f:
                words = json.load(f)
            print(f"Found cached keywords for {lora_file}: {words}")
            if not words:  # If cached words array is empty
                return gr.update(value="No keywords provided for this LoRA")
            return gr.update(value=', '.join(words))

        # If the JSON file does not exist, fetch from the API
        api_url = f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}"

        try:
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                words = data.get("trainedWords", [])
                
                # Check if words array is empty
                if not words:
                    print(f"No keywords found for {lora_file}")
                    # Save empty array to cache to prevent repeated API calls
                    os.makedirs(known_dir, exist_ok=True)
                    with open(json_file_path, "w") as f:
                        json.dump(words, f)
                    return gr.update(value="No keywords provided for this LoRA")
                
                words = [self.normalize_keyword(word) for word in words]
                print(f"Fetched {len(words)} keywords for {lora_file}")
                
                # Ensure the known directory exists
                os.makedirs(known_dir, exist_ok=True)
                
                # Save the trained words
                with open(json_file_path, "w") as f:
                    json.dump(words, f)
                
                return gr.update(value=', '.join(words))
            else:
                print(f"API request failed with status code {response.status_code}")
                return gr.update(value="Failed to fetch keywords from CivitAI API")
        except Exception as e:
            print(f"Error fetching trained words: {e}")
            return gr.update(value="Error fetching keywords")
