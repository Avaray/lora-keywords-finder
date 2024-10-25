import os
import hashlib
import requests
import gradio as gr
from modules import scripts, script_callbacks
from modules.shared import opts

class LoraWordScript(scripts.Script):
    def __init__(self):
        super().__init__()

    def title(self):
        return "LoRA Words Helper"

    def show(self, is_img2img):
        # Show in both txt2img and img2img tabs
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Group():
            with gr.Accordion("LoRA Words Helper", open=False):
                with gr.Row():
                    lora_dropdown = gr.Dropdown(
                        choices=self.list_lora_files(), 
                        label="Select LoRA",
                        type="value"
                    )
                    
                trained_words_display = gr.CheckboxGroup(
                    label="Trained Words",
                    choices=[],
                    value=[]
                )
                
                with gr.Row():
                    add_word_button = gr.Button("Add Selected to Prompt")
                    add_all_words_button = gr.Button("Add All Words")

                # Event handlers
                lora_dropdown.change(
                    fn=self.get_trained_words,
                    inputs=[lora_dropdown],
                    outputs=[trained_words_display]
                )

                add_word_button.click(
                    fn=self.update_prompt,
                    inputs=[trained_words_display],
                    outputs=[]  # We'll handle prompt updating differently
                )

                add_all_words_button.click(
                    fn=self.update_prompt_all,
                    inputs=[trained_words_display],
                    outputs=[]  # We'll handle prompt updating differently
                )

        return [lora_dropdown, trained_words_display, add_word_button, add_all_words_button]

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
            return gr.update(choices=[], value=[])
            
        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        with open(os.path.join(lora_dir, lora_file), "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            
        api_url = f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}"
        try:
            response = requests.get(api_url)
            if response.status_code == 200:
                data = response.json()
                words = data.get("trainedWords", [])
                return gr.update(choices=words, value=[])
        except Exception as e:
            print(f"Error fetching trained words: {e}")
        return gr.update(choices=[], value=[])

    def update_prompt(self, selected_words):
        """Updates the positive prompt in the AUTOMATIC1111 interface."""
        if not selected_words:
            return
        # You'll need to implement the actual prompt updating logic here
        print(f"Selected words to add: {', '.join(selected_words)}")

    def update_prompt_all(self, choices):
        """Updates the prompt with all available words."""
        if not choices:
            return
        # You'll need to implement the actual prompt updating logic here
        print(f"All words to add: {', '.join(choices)}")
