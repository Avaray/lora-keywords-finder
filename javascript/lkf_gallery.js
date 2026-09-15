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
                            const pos = m.prompt ? encodeURIComponent(m.prompt) : "";
                            const neg = m.negativePrompt ? encodeURIComponent(m.negativePrompt) : "";
                            let btnHtml = '<div class="lkf-img-prompt-container">';
                            if (pos) btnHtml += `<div class="lkf-img-prompt-btn lkf-pos-btn" data-pos="${pos}" title="Send positive prompt to UI">😇</div>`;
                            if (neg) btnHtml += `<div class="lkf-img-prompt-btn lkf-neg-btn" data-neg="${neg}" title="Send negative prompt to UI">😈</div>`;
                            btnHtml += '</div>';
                            newHtml += `<div class="lkf-carousel-slide"><div class="lkf-img-wrapper"><a href="${url}" target="_blank"><img src="${url}" loading="lazy"/></a>${btnHtml}</div></div>`;
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
        
        // Optimized: only toggle slides adjacent to the transition,
        // avoiding a full forEach over all slides (which grows unbounded in community mode).
        const prevIndex = parseInt(container.getAttribute("data-prev-index") || "0", 10);
        container.setAttribute("data-prev-index", currentIndex.toString());

        // Hide the 3 slides that were visible before
        for (let i = prevIndex; i < prevIndex + 3; i++) {
            if (slides[i]) slides[i].classList.remove("lkf-visible");
        }
        // Show the 3 slides at the new position
        for (let i = currentIndex; i < currentIndex + 3; i++) {
            if (slides[i]) slides[i].classList.add("lkf-visible");
        }
        
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

    const isPosBtn = btn.classList.contains("lkf-pos-btn");
    const isNegBtn = btn.classList.contains("lkf-neg-btn");

    const pos = isPosBtn ? decodeURIComponent(btn.getAttribute("data-pos") || "") : null;
    const neg = isNegBtn ? decodeURIComponent(btn.getAttribute("data-neg") || "") : null;
    
    if (!pos && !neg) {
        console.warn("LKF: Prompt is empty for this button.");
        return;
    }
    
    const gradioApp = typeof window.gradioApp === 'function' ? window.gradioApp() : document;
    
    const allPos = gradioApp.querySelectorAll('#txt2img_prompt textarea, #img2img_prompt textarea');
    const allNeg = gradioApp.querySelectorAll('#txt2img_neg_prompt textarea, #img2img_neg_prompt textarea');
    
    const targets = isPosBtn ? allPos : allNeg;

    if (targets.length === 0) {
        console.error("LKF ERROR: Could not find corresponding prompt textareas in the UI!");
        alert("LKF Error: Could not locate prompt textareas in this WebUI version.");
        return;
    }

    let confirmOverwrite = true;
    
    // Check if user enabled "Skip paste prompt dialog" in Advanced Options
    const skipDialogEl = document.querySelector('.lkf-cfg-skip-dialog');
    const skipDialog = skipDialogEl?.textContent?.trim() === "1";
    
    if (!skipDialog) {
        let hasExistingText = false;
        targets.forEach(el => {
            if (el && el.offsetParent !== null && el.value.trim() !== "") {
                hasExistingText = true;
            }
        });
        if (hasExistingText) {
            confirmOverwrite = confirm(`Do you want to overwrite your current ${isPosBtn ? 'positive' : 'negative'} prompt with the one from this image?`);
        }
    } // end if (!skipDialog)
    
    if (confirmOverwrite) {
        let updatedCount = 0;
        
        targets.forEach(textarea => {
            if (textarea.offsetParent !== null) {
                textarea.value = isPosBtn ? pos : neg;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                textarea.dispatchEvent(new Event('change', { bubbles: true }));
                updatedCount++;
            }
        });
        
        console.log(`LKF: Successfully updated ${updatedCount} textareas!`);
    } else {
        console.log("LKF: User cancelled prompt overwrite.");
    }
});
