import hashlib
import json
import os
import re
import requests
import gradio as gr # type: ignore
from modules import scripts
from modules import shared

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

    def copy_to_prompt(self, text, is_img2img):
        """Copy keywords to the appropriate prompt textarea"""
        if not text or text in ["No keywords provided for this LoRA", "Failed to fetch keywords from CivitAI API", "Error fetching keywords"]:
            return
        
        # Get the current prompt
        if is_img2img:
            current_prompt = getattr(shared.state, 'img2img_prompt', '')
        else:
            current_prompt = getattr(shared.state, 'txt2img_prompt', '')
        
        # Append the new text with a comma if there's existing content
        new_prompt = f"{current_prompt}, {text}" if current_prompt else text
        
        # Update the prompt
        if is_img2img:
            shared.state.img2img_prompt = new_prompt
        else:
            shared.state.txt2img_prompt = new_prompt
            
        return new_prompt

    def reload_lora_list(self):
        """Reload the list of LoRA files and return updated choices"""
        choices = [""] + self.list_lora_files()
        return gr.update(choices=choices, value="")

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

                reload_loras = gr.Button("🔄", scale=0, elem_classes=["tool"])

            # Add gap between rows
            gr.HTML("<div style='height: 8px'></div>")

            with gr.Row(variant="compact"):
                trained_words_display = gr.Textbox(
                    show_label=False,
                    interactive=False,
                    value="",  # Set empty string as initial value
                    placeholder="Select a LoRA to see its keywords..."
                )

                copy_to_prompt = gr.Button("⚡️", scale=0, elem_classes=["tool"])

                # Add JavaScript for copying to prompt with empty check
                copy_js = """
                function copyToPrompt(text) {
                    // Check if text is empty or contains error messages
                    if (!text || text === "" || 
                        text === "No keywords provided for this LoRA" || 
                        text === "Failed to fetch keywords from CivitAI API" || 
                        text === "Error fetching keywords") {
                        return text;
                    }
                    
                    const textarea = document.querySelector('#txt2img_prompt textarea');
                    if (textarea) {
                        const currentText = textarea.value.trim();
                        textarea.value = currentText ? `${currentText}, ${text}` : text;
                        
                        // Create and dispatch input event
                        const event = new Event('input', { bubbles: true });
                        textarea.dispatchEvent(event);
                    }
                    return text;
                }
                """
                
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

                # Event handler for copy button with JavaScript
                copy_to_prompt.click(
                    fn=None,
                    inputs=[trained_words_display],
                    outputs=None,
                    _js=copy_js
                )

        return [lora_dropdown, trained_words_display]

    def normalize_keyword(self, keyword):
        return re.sub(r",(?=[^\s])", ", ", keyword).strip()

    def list_lora_files(self):
        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        root_files = []
        subdir_files = []
        
        # Walk through directory and subdirectories
        for root, _, files in os.walk(lora_dir):
            for filename in files:
                if filename.endswith((".pt", ".safetensors")):
                    # Get the relative path from the lora_dir
                    rel_path = os.path.relpath(root, lora_dir)
                    if rel_path == ".":
                        # File is in root directory
                        root_files.append(filename)
                    else:
                        # File is in subdirectory
                        subdir_files.append(os.path.join(rel_path, filename))
        
        # Sort root files alphabetically (case-insensitive)
        root_files.sort(key=str.lower)
        
        # Sort subdirectory files by path (case-insensitive)
        subdir_files.sort(key=lambda x: tuple(part.lower() for part in os.path.normpath(x).split(os.sep)))
        
        # Combine root files and subdirectory files
        return root_files + subdir_files

    def get_trained_words(self, lora_file):
        # Return empty string if no file is selected or empty string is selected
        if not lora_file:
            return gr.update(value="")

        lora_dir = os.path.join(scripts.basedir(), "..", "..", "models", "Lora")
        # Construct full path using os.path.join to handle subdirectories correctly
        full_path = os.path.join(lora_dir, lora_file)
        
        try:
            with open(full_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
        except FileNotFoundError:
            print(f"File not found: {full_path}")
            return gr.update(value="Error: File not found")
        except Exception as e:
            print(f"Error reading file {full_path}: {e}")
            return gr.update(value="Error reading file")

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
                
                if not words:
                    print(f"No keywords found for {lora_file}")
                    with open(json_file_path, "w") as f:
                        json.dump(words, f)
                    return gr.update(value="No keywords provided for this LoRA")
                
                words = [self.normalize_keyword(word) for word in words]
                print(f"Fetched {len(words)} keywords for {lora_file}")
                
                with open(json_file_path, "w") as f:
                    json.dump(words, f)
                
                return gr.update(value=', '.join(words))
            else:
                print(f"API request failed with status code {response.status_code}")
                return gr.update(value="Failed to fetch keywords from CivitAI API")
        except Exception as e:
            print(f"Error fetching trained words: {e}")
            return gr.update(value="Error fetching keywords")
