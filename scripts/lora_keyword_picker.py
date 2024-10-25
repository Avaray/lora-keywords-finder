import os
import hashlib
import requests
import gradio as gr
from modules import scripts
import json

class LoraWordScript(scripts.Script):

    def __init__(self):
        super().__init__()

    def title(self):
        return "LoRA Keyword Picker"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Group():
            with gr.Accordion("LoRA Keyword Picker", open=False):
                with gr.Row():
                    lora_dropdown = gr.Dropdown(
                        choices=self.list_lora_files(),
                        label="Select LoRA",
                        type="value"
                    )
                    
                    # Text field to display trained words
                    trained_words_display = gr.Textbox(
                        label="Trained Words",
                        interactive=False,  # Make it read-only
                        placeholder="Selected keywords will appear here..."
                    )

                # Event handler for dropdown change
                lora_dropdown.change(
                    fn=self.get_trained_words,
                    inputs=[lora_dropdown],
                    outputs=[trained_words_display]
                )

        return [lora_dropdown, trained_words_display]

    def list_lora_files(self):
        """Lists all LoRA files in the specified directory."""
        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        lora_files = []
        for filename in os.listdir(lora_dir):
            if filename.endswith((".pt", ".safetensors")):
                lora_files.append(filename)
        return lora_files

    def get_trained_words(self, lora_file):
        """Gets trained words for a LoRA file by making an API request."""
        if not lora_file:
            return gr.update(value="")

        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        with open(os.path.join(lora_dir, lora_file), "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        print(f"File hash for {lora_file}: {file_hash}")  # Print the file hash to the console

        api_url = f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}"

        try:
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                words = data.get("trainedWords", [])
                # Save the trained words into a file located inside extensions dir under known folder as hash filename json
                with open(os.path.join(scripts.basedir(), "extensions", "lora-keyword-picker", "known", f"{file_hash}.json"), "w") as f:
                    json.dump(words, f)  # Convert list to JSON string
                # Join the words into a single string for the textbox
                return gr.update(value=', '.join(words))  # Display keywords in the textbox
        except Exception as e:
            print(f"Error fetching trained words: {e}")

        return gr.update(value="")
