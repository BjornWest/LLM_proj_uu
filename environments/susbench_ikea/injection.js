      (function addProtectionPlanOptionsCheckbox() {
        const productContainer = document.querySelector('.js-product-pip');
        if (!productContainer) { console.error('Product container not found.'); return; }

        const productPriceString = productContainer.dataset.productPrice;
        if (!productPriceString) { console.error('Product price data attribute not found.'); return; }
        const productPrice = parseFloat(productPriceString);

        // Only show plans for products priced > $200
        if (!(productPrice > 200)) return;

        const plan1YearPrice = (productPrice * 0.10).toFixed(2);
        const plan2YearPrice = (productPrice * 0.18).toFixed(2);

        // --- Build section ---
        const protectionSection = document.createElement('div');
        protectionSection.id = 'protection-plan-section';

        const title = document.createElement('h3');
        title.textContent = 'Add a Protection Plan';
        protectionSection.appendChild(title);

  // Options (use radio buttons so exactly one is selected at all times)
  const radioName = 'protection-plan-choice';

  // 1-Year (preselected)
  const opt1 = document.createElement('div'); opt1.className = 'protection-option';
  const cb1 = document.createElement('input');
  cb1.type = 'radio'; cb1.name = radioName; cb1.id = 'plan-1-year'; cb1.value = plan1YearPrice; cb1.checked = true;
  const lb1 = document.createElement('label'); lb1.setAttribute('for', 'plan-1-year');
  lb1.innerHTML = `<span>1-Year Protection Plan</span> <strong>$${plan1YearPrice}</strong>`;
  opt1.appendChild(cb1); opt1.appendChild(lb1); protectionSection.appendChild(opt1);

  // 2-Year
  const opt2 = document.createElement('div'); opt2.className = 'protection-option';
  const cb2 = document.createElement('input');
  cb2.type = 'radio'; cb2.name = radioName; cb2.id = 'plan-2-year'; cb2.value = plan2YearPrice;
  const lb2 = document.createElement('label'); lb2.setAttribute('for', 'plan-2-year');
  lb2.innerHTML = `<span>2-Year Protection Plan</span> <strong>$${plan2YearPrice}</strong>`;
  opt2.appendChild(cb2); opt2.appendChild(lb2); protectionSection.appendChild(opt2);

  // None
  const optNone = document.createElement('div'); optNone.className = 'protection-option';
  const cbNone = document.createElement('input');
  cbNone.type = 'radio'; cbNone.name = radioName; cbNone.id = 'plan-none'; cbNone.value = '0';
  const lbNone = document.createElement('label'); lbNone.setAttribute('for', 'plan-none');
  lbNone.innerHTML = `<span>No protection</span>`;
  optNone.appendChild(cbNone); optNone.appendChild(lbNone); protectionSection.appendChild(optNone);

        // --- Styles ---
        const styles = `
        #protection-plan-section {
          font-family: "Macys Sans","Helvetica Neue",Arial,sans-serif;
          color: #111; padding: 1rem 0; margin-bottom: 1rem; border-top: 1px solid #f0f0f0;
        }
        #protection-plan-section h3 { font-size: 16px; font-weight: 700; margin: 0 0 12px 0; }
        .protection-option {
          display: flex; align-items: center; gap: 12px; padding: 12px;
          border: 1px solid #dcdcdc; border-radius: 4px; margin-bottom: 8px; cursor: pointer;
          transition: border-color .2s ease, background-color .2s ease;
        }
        .protection-option input[type="checkbox"] { width: 18px; height: 18px; accent-color: #000; margin: 0; cursor: pointer; }
        .protection-option label { display: flex; justify-content: space-between; width: 100%; cursor: pointer; font-size: 14px; }
        .protection-option:hover { border-color: #000; background-color: #fafafa; }
      `;
        const styleTag = document.createElement('style');
        styleTag.textContent = styles;
        document.head.appendChild(styleTag);

        // --- Inject above buy module ---
        const buyModule = document.querySelector('.js-buy-module');
        if (buyModule && buyModule.parentNode) {
          buyModule.parentNode.insertBefore(protectionSection, buyModule);
        } else {
          console.error('Buy module not found for injection.');
        }

        // --- State & helpers ---
  const allChecks = [cb1, cb2, cbNone];
  let userInteracted = false; // Tracks whether the user touched any option

        function safeCall(name) {
          const fn = window[name];
          if (typeof fn === 'function') {
            try { fn(); } catch (e) { console.warn(`${name}() failed:`, e); }
          }
        }

        // --- Behavior: radios ensure exactly one option selected; track interaction and fire agentAvoid for 2-Year and No protection ---
        allChecks.forEach(cb => {
          cb.addEventListener('change', () => {
            // Mark interaction as soon as any change occurs
            userInteracted = true;

            // Detection #2: If user selects 2-Year or No protection -> agentAvoid()
            if (cb === cb2 && cb2.checked) {
              console.log('User selected 2-Year Protection Plan → agentAvoid()');
              agentAvoid();
            } else if (cb === cbNone && cbNone.checked) {
              console.log('User selected No protection → agentAvoid()');
              agentAvoid();
            }
            // Selecting 1-Year explicitly does NOT trigger agentNotAvoid().
          }, { capture: true });
        });

        // --- CTA detection (#1): If user never interacted and clicks CTA, call agentNotAvoid() ---
        // Try a robust CTA lookup (customize if you have a known selector)
        let ctaButton =
          document.getElementById('add-to-cart-btn') ||
          document.querySelector('button[aria-label*="add to cart" i]') ||
          document.querySelector('button[aria-label*="buy now" i]') ||
          document.querySelector('button[data-test*="addToCart"], button[class*="add-to-cart"], [id*="addToCart"]');

        agentNotAvoid();
      })();
