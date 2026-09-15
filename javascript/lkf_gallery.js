document.addEventListener("click", function(e) {
    const btn = e.target.closest(".lkf-img-prompt-btn");
    if (!btn) return;

    console.log("LKF: Image prompt button clicked!");

    const pos = decodeURIComponent(btn.getAttribute("data-pos") || "");
    const neg = decodeURIComponent(btn.getAttribute("data-neg") || "");
    
    if (!pos && !neg) {
        console.warn("LKF: Both positive and negative prompts are empty for this image.");
        return;
    }
    
    // Niezawodne poszukiwanie okien promptów we wszystkich dostepnych formach
    const gradioApp = typeof window.gradioApp === 'function' ? window.gradioApp() : document;
    
    // Pobierzmy wszystkie pola textarea dla promptow w calym webui
    const allPos = gradioApp.querySelectorAll('#txt2img_prompt textarea, #img2img_prompt textarea');
    const allNeg = gradioApp.querySelectorAll('#txt2img_neg_prompt textarea, #img2img_neg_prompt textarea');
    
    if (allPos.length === 0 && allNeg.length === 0) {
        console.error("LKF ERROR: Could not find any prompt textareas in the UI! Ensure IDs are #txt2img_prompt / #img2img_prompt.");
        alert("LKF Error: Could not locate prompt textareas in this WebUI version.");
        return;
    }

    let confirmOverwrite = true;
    
    // Sprawdzmy, czy którekolwiek z widocznych pol jest juz zapelnione (żeby zapytać o zgode)
    let hasExistingText = false;
    [...allPos, ...allNeg].forEach(el => {
        if (el && el.offsetParent !== null && el.value.trim() !== "") {
            hasExistingText = true;
        }
    });

    if (hasExistingText) {
        confirmOverwrite = confirm("Do you want to overwrite your current prompts with the ones from this image?");
    }
    
    if (confirmOverwrite) {
        let updatedCount = 0;
        // Aktualizujemy tylko widoczne (aktywne) pola tekstowe
        allPos.forEach(posTextarea => {
            if (posTextarea.offsetParent !== null) { // sprawdzanie czy widoczne na ekranie (aktywny tab)
                posTextarea.value = pos;
                posTextarea.dispatchEvent(new Event('input', { bubbles: true }));
                posTextarea.dispatchEvent(new Event('change', { bubbles: true }));
                updatedCount++;
            }
        });
        
        allNeg.forEach(negTextarea => {
            if (negTextarea.offsetParent !== null) {
                negTextarea.value = neg;
                negTextarea.dispatchEvent(new Event('input', { bubbles: true }));
                negTextarea.dispatchEvent(new Event('change', { bubbles: true }));
                updatedCount++;
            }
        });
        
        console.log(`LKF: Successfully updated ${updatedCount} prompt textareas!`);
    } else {
        console.log("LKF: User cancelled prompt overwrite.");
    }
});
