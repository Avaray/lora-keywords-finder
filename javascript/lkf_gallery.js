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
        const isExhausted = container.getAttribute("data-exhausted") === "true";
        const isCommunity = container.getAttribute("data-mode") === "community";

        if (prevBtn) {
            // Left: freely go back through history, wrap from 0 to end
            currentIndex = currentIndex - 1;
            if (currentIndex < 0) currentIndex = maxIndex;

        } else if (nextBtn) {
            if (currentIndex >= maxIndex) {
                if (isCommunity && !isExhausted) {
                    // More pages are being fetched — stay put, don't show duplicates
                    return;
                } else {
                    // Truly exhausted (or official mode) — loop from beginning
                    currentIndex = 0;
                }
            } else {
                currentIndex = currentIndex + 1;
            }
        }
        
        // Trigger background fetch when approaching end (community mode only)
        if (isCommunity && currentIndex >= maxIndex - 6 && !isFetching && !isExhausted) {
            let nextPageUrl = container.getAttribute("data-next-page");
            if (nextPageUrl) {
                // Ensure withMeta=true is always present so CivitAI returns prompt data
                if (!nextPageUrl.includes("withMeta=true")) {
                    nextPageUrl += (nextPageUrl.includes("?") ? "&" : "?") + "withMeta=true";
                }
                container.setAttribute("data-fetching", "true");
                console.log("LKF: Pre-fetching next page of community images...");
                
                fetch(nextPageUrl)
                    .then(res => res.json())
                    .then(data => {
                        const items = data.items || [];
                        const meta = data.metadata || {};
                        let newHtml = "";
                        let added = 0;
                        
                        const requiredVersionId = String(container.getAttribute("data-version-id") || "");
                        
                        items.forEach(item => {
                            const m = item.meta;
                            if (!m || !m.prompt) return;
                            
                            // Verify this image actually used the exact model version selected by the user
                            const resources = m.civitaiResources || [];
                            if (requiredVersionId && resources.length > 0) {
                                const usedVersions = resources.map(r => String(r.modelVersionId || ""));
                                if (!usedVersions.includes(requiredVersionId)) return;
                            }
                            
                            const url = item.url || "";
                            const pos = encodeURIComponent(m.prompt || "");
                            const neg = encodeURIComponent(m.negativePrompt || "");
                            const btnHtml = `<div class="lkf-img-prompt-btn" data-pos="${pos}" data-neg="${neg}" title="Send prompts to UI">📝</div>`;
                            newHtml += `<div class="lkf-carousel-slide"><div class="lkf-img-wrapper"><a href="${url}" target="_blank"><img src="${url}"/></a>${btnHtml}</div></div>`;
                            added++;
                        });
                        
                        if (newHtml) {
                            const rBtn = container.querySelector(".right-arrow");
                            if (rBtn) rBtn.insertAdjacentHTML('beforebegin', newHtml);
                            console.log(`LKF: Added ${added} new community images.`);
                        }
                        
                        if (meta.nextPage) {
                            container.setAttribute("data-next-page", meta.nextPage);
                        } else {
                            // No more pages from API — mark exhausted, will loop on next end-hit
                            container.removeAttribute("data-next-page");
                            container.setAttribute("data-exhausted", "true");
                            console.log("LKF: All community images fetched. Will loop from beginning on next wrap.");
                        }
                    })
                    .catch(err => console.error("LKF Fetch Error:", err))
                    .finally(() => {
                        container.setAttribute("data-fetching", "false");
                    });
            } else if (!isExhausted) {
                // No nextPage stored yet and not marked exhausted — mark now
                container.setAttribute("data-exhausted", "true");
            }
        }
        
        container.setAttribute("data-current-index", currentIndex.toString());
        
        // Update slide visibility: show 3 slides at a time starting at currentIndex
        slides.forEach((slide, idx) => {
            if (idx >= currentIndex && idx < currentIndex + 3) {
                slide.classList.add("lkf-visible");
            } else {
                slide.classList.remove("lkf-visible");
            }
        });
        
        // Keep both arrows always visible
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
    
    const gradioApp = typeof window.gradioApp === 'function' ? window.gradioApp() : document;
    
    const allPos = gradioApp.querySelectorAll('#txt2img_prompt textarea, #img2img_prompt textarea');
    const allNeg = gradioApp.querySelectorAll('#txt2img_neg_prompt textarea, #img2img_neg_prompt textarea');
    
    if (allPos.length === 0 && allNeg.length === 0) {
        console.error("LKF ERROR: Could not find any prompt textareas in the UI!");
        alert("LKF Error: Could not locate prompt textareas in this WebUI version.");
        return;
    }

    let confirmOverwrite = true;
    
    // Check if user enabled "Skip paste prompt dialog" in Advanced Options
    const skipDialogEl = document.querySelector('.lkf-cfg-skip-dialog');
    const skipDialog = skipDialogEl?.textContent?.trim() === "1";
    
    if (!skipDialog) {
        let hasExistingText = false;
        [...allPos, ...allNeg].forEach(el => {
            if (el && el.offsetParent !== null && el.value.trim() !== "") {
                hasExistingText = true;
            }
        });
        if (hasExistingText) {
            confirmOverwrite = confirm("Do you want to overwrite your current prompts with the ones from this image?");
        }
    } // end if (!skipDialog)
    
    if (confirmOverwrite) {
        let updatedCount = 0;
        allPos.forEach(posTextarea => {
            if (posTextarea.offsetParent !== null) {
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
