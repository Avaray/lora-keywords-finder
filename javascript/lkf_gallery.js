document.addEventListener("click", function(e) {
    // Carousel navigation logic
    const prevBtn = e.target.closest(".lkf-carousel-nav.left-arrow");
    const nextBtn = e.target.closest(".lkf-carousel-nav.right-arrow");
    
    if (prevBtn || nextBtn) {
        const container = e.target.closest(".lkf-carousel-container");
        if (!container) return;
        
        let currentIndex = parseInt(container.getAttribute("data-current-index") || "0", 10);
        const slides = container.querySelectorAll(".lkf-carousel-slide");
        if (slides.length <= 3) return; // No need to slide
        
        const maxIndex = slides.length - 3;
        
        const isFetching = container.getAttribute("data-fetching") === "true";
        if (prevBtn) {
            currentIndex = currentIndex - 1;
            if (currentIndex < 0) currentIndex = maxIndex;
        } else if (nextBtn) {
            if (currentIndex === maxIndex && isFetching) {
                return; // Block wrapping if we are actively downloading the next page
            }
            currentIndex = currentIndex + 1;
            if (currentIndex > maxIndex) currentIndex = 0;
        }
        
        // Trigger background fetch if we are approaching the end
        if (currentIndex >= maxIndex - 6 && !isFetching) {
            const nextPageUrl = container.getAttribute("data-next-page");
            if (nextPageUrl) {
                container.setAttribute("data-fetching", "true");
                console.log("LKF: Pre-fetching next page of community images...");
                
                fetch(nextPageUrl)
                    .then(res => res.json())
                    .then(data => {
                        const items = data.items || [];
                        const meta = data.metadata || {};
                        let newHtml = "";
                        
                        items.forEach(item => {
                            const m = item.meta;
                            if (m && m.prompt) {
                                const url = item.url || "";
                                const pos = encodeURIComponent(m.prompt || "");
                                const neg = encodeURIComponent(m.negativePrompt || "");
                                
                                const btnHtml = `<div class="lkf-img-prompt-btn" data-pos="${pos}" data-neg="${neg}" title="Send prompts to UI">📝</div>`;
                                newHtml += `<div class="lkf-carousel-slide"><div class="lkf-img-wrapper"><a href="${url}" target="_blank"><img src="${url}"/></a>${btnHtml}</div></div>`;
                            }
                        });
                        
                        if (newHtml) {
                            const rBtn = container.querySelector(".right-arrow");
                            if (rBtn) rBtn.insertAdjacentHTML('beforebegin', newHtml);
                        }
                        
                        if (meta.nextPage) {
                            container.setAttribute("data-next-page", meta.nextPage);
                        } else {
                            container.removeAttribute("data-next-page");
                        }
                    })
                    .catch(err => console.error("LKF Fetch Error:", err))
                    .finally(() => {
                        container.setAttribute("data-fetching", "false");
                    });
            }
        }
        
        container.setAttribute("data-current-index", currentIndex.toString());
        
        // Update slide visibility
        slides.forEach((slide, idx) => {
            // Because it's an infinite loop without cloning nodes, we just wrap around visually by showing the right slides
            // Actually, wait, if currentIndex + 3 exceeds the total, we need to wrap the visible slides around too!
            // Wait, does it? If currentIndex = maxIndex, currentIndex + 3 is the exact length, so it's perfectly safe.
            // maxIndex is slides.length - 3. So currentIndex + 3 is slides.length. It never goes out of bounds.
            if (idx >= currentIndex && idx < currentIndex + 3) {
                slide.classList.add("lkf-visible");
            } else {
                slide.classList.remove("lkf-visible");
            }
        });
        
        // Keep both arrows visible for infinite carousel
        const lBtn = container.querySelector(".left-arrow");
        const rBtn = container.querySelector(".right-arrow");
        if (lBtn) lBtn.style.display = "block";
        if (rBtn) rBtn.style.display = "block";
        
        return; // Event handled
    }

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
