# js injection for stealth mode

# canvas fingerprint noise

CANVAS_SPOOF_JS = """
(() => {
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const originalToBlob = HTMLCanvasElement.prototype.toBlob;
    const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    
    // Random seed per session (consistent within one session)
    const NOISE_SEED = Math.floor(Math.random() * 256);
    
    // Add subtle noise to canvas pixel data
    function addNoise(data) {
        for (let i = 0; i < data.length; i += 4) {
            // Shift R channel by tiny amount (imperceptible visually)
            data[i] = (data[i] + NOISE_SEED) % 256;
        }
        return data;
    }
    
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = originalGetImageData.call(ctx, 0, 0, this.width, this.height);
                addNoise(imageData.data);
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}  // CORS canvas — ignore
        }
        return originalToDataURL.apply(this, args);
    };
    
    HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = originalGetImageData.call(ctx, 0, 0, this.width, this.height);
                addNoise(imageData.data);
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}
        }
        return originalToBlob.call(this, callback, ...args);
    };
    
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {
        const imageData = originalGetImageData.apply(this, args);
        addNoise(imageData.data);
        return imageData;
    };
})();
"""


# webgl gpu spoofing

WEBGL_SPOOF_JS = """
(() => {
    // realistic gpu configs
    const GPU_CONFIGS = [
        { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (AMD)', renderer: 'ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (Intel)', renderer: 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (Intel)', renderer: 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)' },
        { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, Apple M1, OpenGL 4.1)' },
        { vendor: 'Google Inc. (Apple)', renderer: 'ANGLE (Apple, Apple M2, OpenGL 4.1)' },
    ];
    
    const GPU = GPU_CONFIGS[Math.floor(Math.random() * GPU_CONFIGS.length)];
    
    const getParameterProxy = new Proxy(WebGLRenderingContext.prototype.getParameter, {
        apply(target, thisArg, args) {
            const param = args[0];
            // UNMASKED_VENDOR_WEBGL
            if (param === 0x9245) return GPU.vendor;
            // UNMASKED_RENDERER_WEBGL
            if (param === 0x9246) return GPU.renderer;
            return Reflect.apply(target, thisArg, args);
        }
    });
    
    WebGLRenderingContext.prototype.getParameter = getParameterProxy;
    
    // handle WebGL2 too
    if (typeof WebGL2RenderingContext !== 'undefined') {
        const getParameter2Proxy = new Proxy(WebGL2RenderingContext.prototype.getParameter, {
            apply(target, thisArg, args) {
                const param = args[0];
                if (param === 0x9245) return GPU.vendor;
                if (param === 0x9246) return GPU.renderer;
                return Reflect.apply(target, thisArg, args);
            }
        });
        WebGL2RenderingContext.prototype.getParameter = getParameter2Proxy;
    }
})();
"""



AUDIO_SPOOF_JS = """
(() => {
    const originalGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
    const originalGetByteFrequencyData = AnalyserNode.prototype.getByteFrequencyData;
    const AUDIO_NOISE = Math.random() * 0.0001;
    
    AnalyserNode.prototype.getFloatFrequencyData = function(array) {
        originalGetFloatFrequencyData.call(this, array);
        for (let i = 0; i < array.length; i++) {
            array[i] = array[i] + AUDIO_NOISE * (Math.random() - 0.5);
        }
    };
    
    AnalyserNode.prototype.getByteFrequencyData = function(array) {
        originalGetByteFrequencyData.call(this, array);
        for (let i = 0; i < array.length; i++) {
            array[i] = Math.max(0, Math.min(255,
                array[i] + Math.floor(Math.random() * 3 - 1)
            ));
        }
    };
    
    // spoof oscillator timing too
    const originalCreateOscillator = AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator = function() {
        const osc = originalCreateOscillator.call(this);
        osc._spoofed = true;
        return osc;
    };
})();
"""

# font metric noise

FONT_SPOOF_JS = """
(() => {
    const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
    const FONT_NOISE = 1 + (Math.random() * 0.002 - 0.001);
    
    CanvasRenderingContext2D.prototype.measureText = function(text) {
        const metrics = originalMeasureText.call(this, text);
        
        return new Proxy(metrics, {
            get(target, prop) {
                if (prop === 'width') {
                    return target.width * FONT_NOISE;
                }
                if (prop === 'actualBoundingBoxLeft' || 
                    prop === 'actualBoundingBoxRight') {
                    const val = target[prop];
                    return typeof val === 'number' ? val * FONT_NOISE : val;
                }
                const val = target[prop];
                return typeof val === 'function' ? val.bind(target) : val;
            }
        });
    };
})();
"""

# navigator overrides (on top of playwright-stealth)

NAVIGATOR_SPOOF_JS = """
(() => {
    // randomize cpu cores
    const CORES = [4, 8, 12, 16][Math.floor(Math.random() * 4)];
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => CORES,
        configurable: true,
    });
    
    // device memory
    const MEMORY = [4, 8, 16][Math.floor(Math.random() * 3)];
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => MEMORY,
        configurable: true,
    });
    
    // no touch for desktop
    Object.defineProperty(navigator, 'maxTouchPoints', {
        get: () => 0,
        configurable: true,
    });
    
    // network info
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'effectiveType', {
            get: () => '4g',
            configurable: true,
        });
        Object.defineProperty(navigator.connection, 'downlink', {
            get: () => 10 + Math.random() * 40,
            configurable: true,
        });
    }
    
    // fake battery api
    if (navigator.getBattery) {
        navigator.getBattery = async () => ({
            charging: true,
            chargingTime: 0,
            dischargingTime: Infinity,
            level: 0.85 + Math.random() * 0.15,
            addEventListener: () => {},
        });
    }
    
    // permissions api
    const originalQuery = Permissions.prototype.query;
    Permissions.prototype.query = function(desc) {
        if (desc.name === 'notifications') {
            return Promise.resolve({ state: 'prompt', addEventListener: () => {} });
        }
        return originalQuery.call(this, desc);
    };
})();
"""

# auto-dismiss cookie banners

COOKIE_DISMISS_JS = """
(() => {
    function dismissCookies() {
        const selectors = [
            '[id*="cookie"] button[class*="accept"]',
            '[id*="cookie"] button[class*="agree"]',
            '[class*="cookie"] button[class*="accept"]',
            '[class*="cookie"] button[class*="agree"]',
            '[id*="consent"] button[class*="accept"]',
            '[class*="consent"] button[class*="accept"]',
            'button[id*="accept-cookies"]',
            'button[id*="cookie-accept"]',
            '#onetrust-accept-btn-handler',
            '.cc-accept',
            '.cc-btn.cc-dismiss',
            '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
            '[data-testid="cookie-policy-dialog-accept-button"]',
            'button[aria-label*="accept" i]',
            'button[aria-label*="agree" i]',
            'button[aria-label*="Allow" i]',
            // '.cmpboxbtn.cmpboxbtnyes',   // old one, not sure if still needed
        ];
        
        for (const sel of selectors) {
            try {
                const btn = document.querySelector(sel);
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return true;
                }
            } catch(e) {}
        }
        
        // fallback - look for buttons with accept/agree text
        const buttons = document.querySelectorAll('button, a.button, [role="button"]');
        for (const btn of buttons) {
            const text = btn.textContent.toLowerCase().trim();
            if ((text.includes('accept') || text.includes('agree') || text.includes('got it') || text.includes('i understand'))
                && text.length < 30 && btn.offsetParent !== null) {
                btn.click();
                return true;
            }
        }
        
        return false;
    }
    
    // try a few times since some load late
    setTimeout(dismissCookies, 1000);
    setTimeout(dismissCookies, 3000);
    setTimeout(dismissCookies, 5000);
})();
"""
# FIXME: doesnt handle german sites with "Akzeptieren" button

# cloudflare turnstile

CF_CHALLENGE_JS = """
(() => {
    function solveTurnstile() {
        const frames = document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]');
        for (const frame of frames) {
            try {
                const doc = frame.contentDocument;
                if (doc) {
                    const checkbox = doc.querySelector('input[type="checkbox"], [role="checkbox"]');
                    if (checkbox) checkbox.click();
                }
            } catch(e) {
                // cross-origin, cant access
            }
        }
        
        const checkboxes = document.querySelectorAll(
            '.cf-turnstile input, [data-action="managed-challenge"] input'
        );
        for (const cb of checkboxes) {
            try { cb.click(); } catch(e) {}
        }
    }
    
    setTimeout(solveTurnstile, 2000);
    setTimeout(solveTurnstile, 5000);
})();
"""


ALL_SPOOFING_SCRIPTS = "\n".join([
    CANVAS_SPOOF_JS,
    WEBGL_SPOOF_JS,
    AUDIO_SPOOF_JS,
    FONT_SPOOF_JS,
    NAVIGATOR_SPOOF_JS,
])

ALL_HELPER_SCRIPTS = "\n".join([
    COOKIE_DISMISS_JS,
    CF_CHALLENGE_JS,
])

FULL_STEALTH_INJECTION = "\n".join([
    ALL_SPOOFING_SCRIPTS,
    ALL_HELPER_SCRIPTS,
])


async def inject_stealth_scripts(page):
    await page.add_init_script(ALL_SPOOFING_SCRIPTS)


async def inject_helper_scripts(page):
    await page.evaluate(ALL_HELPER_SCRIPTS)
