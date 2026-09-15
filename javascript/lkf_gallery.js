// Global event listener for image prompt buttons generated dynamically in LKF extension
document.addEventListener("click", function(e) {
    // Find if the clicked element is our button (or inside it)
    const btn = e.target.closest(".lkf-img-prompt-btn");
    if (!btn) return;

    // Decode prompts safely stored in data attributes
    const pos = decodeURIComponent(btn.getAttribute("data-pos") || "");
    const neg = decodeURIComponent(btn.getAttribute("data-neg") || "");
    
    if (!pos && !neg) return;
    
    // Find active tab (txt2img or img2img)
    const tabs = document.querySelector('#tabs');
    if (!tabs) return;
    
    const tabButtons = tabs.querySelectorAll('.tab-nav > button, .tab-nav button[role="tab"]');
    let activeTabIndex = 0; // Default to txt2img
    tabButtons.forEach((b, idx) => {
        if (b.classList.contains('selected')) activeTabIndex = idx;
    });

    let posTextarea, negTextarea;
    if (activeTabIndex === 0) {
        posTextarea = document.querySelector('#txt2img_prompt textarea');
        negTextarea = document.querySelector('#txt2img_neg_prompt textarea');
    } else if (activeTabIndex === 1) {
        posTextarea = document.querySelector('#img2img_prompt textarea');
        negTextarea = document.querySelector('#img2img_neg_prompt textarea');
    }

    if (posTextarea || negTextarea) {
        const curPos = (posTextarea ? posTextarea.value.trim() : "");
        const curNeg = (negTextarea ? negTextarea.value.trim() : "");
        
        let confirmOverwrite = true;
        if (curPos !== "" || curNeg !== "") {
            confirmOverwrite = confirm("Do you want to overwrite your current prompts with the ones from this image?");
        }
        
        if (confirmOverwrite) {
            if (posTextarea) {
                posTextarea.value = pos;
                posTextarea.dispatchEvent(new Event('input', { bubbles: true }));
                posTextarea.dispatchEvent(new Event('change', { bubbles: true }));
            }
            if (negTextarea) {
                negTextarea.value = neg;
                negTextarea.dispatchEvent(new Event('input', { bubbles: true }));
                negTextarea.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }
});
