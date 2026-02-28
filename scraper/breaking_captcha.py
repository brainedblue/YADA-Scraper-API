# captcha solver - uses gemini vision

import asyncio
import base64
import json
import os
import re
from typing import Optional

from playwright.async_api import Page


class SolveResult:
    def __init__(self, solved, captcha_type="", solution=None, confidence=0.0, error="", attempts=0):
        self.solved = solved
        self.captcha_type = captcha_type
        self.solution = solution
        self.confidence = confidence
        self.error = error
        self.attempts = attempts


class GeminiClient:

    # updated jan 2025 to use gemini 2.0 flash
    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")

    @property
    def available(self):
        return bool(self.api_key)

    async def analyze_image(self, image_bytes, prompt):
        if not self.available:
            raise RuntimeError("GEMINI_API_KEY not set. Get one at https://aistudio.google.com/apikey")

        from curl_cffi.requests import AsyncSession

        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": b64_image,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 256,
            },
        }

        async with AsyncSession() as session:
            response = await session.post(
                f"{self.API_URL}?key={self.api_key}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            result = response.json()

            if "error" in result:
                raise RuntimeError(f"Gemini API error: {result['error'].get('message', 'Unknown')}")

            try:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                raise RuntimeError(f"Unexpected Gemini response: {json.dumps(result)[:500]}")




async def _try_image_captcha(page, gemini):
    # XXX: success rate is like 40%, needs work
    attempts = 0
    max_tries = 3

    for attempt in range(max_tries):
        attempts += 1
        try:
            # find the captcha iframe
            captcha_frame = None
            for frame in page.frames:
                url = frame.url.lower()
                if "recaptcha" in url or "hcaptcha" in url or "challenge" in url:
                    captcha_frame = frame
                    break

            if not captcha_frame:
                captcha_frame = page

            # take a screenshot
            screenshot = await page.screenshot(type="png")

            # ask gemini whats up
            prompt = (
                "You are looking at a CAPTCHA challenge on a webpage. "
                "Analyze the CAPTCHA and provide the solution.\n\n"
                "If it's an image grid selection (like 'Select all images with traffic lights'):\n"
                "- Tell me which grid cells to click, numbered 1-9 or 1-16 (left to right, top to bottom)\n"
                "- Format: CLICK: 1,3,5,7\n\n"
                "If it's a text CAPTCHA:\n"
                "- Tell me what text to type\n"
                "- Format: TYPE: <text>\n\n"
                "If it's a checkbox:\n"
                "- Format: CHECKBOX\n\n"
                "If there's no CAPTCHA visible:\n"
                "- Format: NONE\n\n"
                "Be precise. Only output the format above, nothing else."
            )

            response = await gemini.analyze_image(screenshot, prompt)
            response = response.strip()

            if response.startswith("CLICK:"):
                cells_str = response.replace("CLICK:", "").strip()
                cells = [int(c.strip()) for c in cells_str.split(",") if c.strip().isdigit()]

                grid_images = await captcha_frame.query_selector_all(
                    "td.rc-imageselect-tile, .task-image, .challenge-item"
                )

                if grid_images:
                    for cell_num in cells:
                        idx = cell_num - 1
                        if 0 <= idx < len(grid_images):
                            await grid_images[idx].click()
                            await asyncio.sleep(0.3)

                    # click verify button
                    verify_btn = await captcha_frame.query_selector(
                        "#recaptcha-verify-button, .verify-button, [type='submit'], .button-submit"
                    )
                    if verify_btn:
                        await verify_btn.click()
                        await asyncio.sleep(2)

                    return SolveResult(
                        solved=True, captcha_type="image_selection",
                        solution=f"Clicked cells: {cells}",
                        confidence=0.7, attempts=attempts,
                    )

            elif response.startswith("TYPE:"):
                text = response.replace("TYPE:", "").strip()
                input_field = await captcha_frame.query_selector(
                    "input[type='text'], #captcha-input, .captcha-input"
                )
                if input_field:
                    await input_field.fill(text)
                    submit_btn = await captcha_frame.query_selector(
                        "[type='submit'], .submit, button"
                    )
                    if submit_btn:
                        await submit_btn.click()
                        await asyncio.sleep(2)

                    return SolveResult(
                        solved=True, captcha_type="text_captcha",
                        solution=f"Typed: {text}",
                        confidence=0.8, attempts=attempts,
                    )

            elif response.startswith("CHECKBOX"):
                checkbox = await captcha_frame.query_selector(
                    ".recaptcha-checkbox, #recaptcha-anchor, [role='checkbox']"
                )
                if checkbox:
                    await checkbox.click()
                    await asyncio.sleep(2)

                    return SolveResult(
                        solved=True, captcha_type="checkbox",
                        solution="Clicked checkbox",
                        confidence=0.9, attempts=attempts,
                    )

            elif response.startswith("NONE"):
                return SolveResult(
                    solved=True, captcha_type="none",
                    solution="No CAPTCHA detected",
                    confidence=1.0, attempts=attempts,
                )

        except Exception as e:
            if attempt == max_tries - 1:
                return SolveResult(
                    solved=False, captcha_type="image_selection",
                    error=f"Failed after {attempts} attempts: {type(e).__name__}: {e}",
                    attempts=attempts,
                )
            await asyncio.sleep(1)

    return SolveResult(
        solved=False, captcha_type="unknown",
        error="Max attempts reached", attempts=attempts,
    )


async def _click_recaptcha_box(page):
    try:
        recaptcha_frame = None
        for frame in page.frames:
            if "recaptcha/api2/anchor" in frame.url:
                recaptcha_frame = frame
                break

        if not recaptcha_frame:
            return SolveResult(solved=False, error="reCAPTCHA iframe not found")

        checkbox = await recaptcha_frame.query_selector("#recaptcha-anchor")
        if checkbox:
            await checkbox.click()
            await asyncio.sleep(3)

            is_checked = await recaptcha_frame.query_selector(
                ".recaptcha-checkbox-checked, [aria-checked='true']"
            )

            if is_checked:
                return SolveResult(
                    solved=True, captcha_type="recaptcha_checkbox",
                    solution="Checkbox click passed",
                    confidence=1.0, attempts=1,
                )

            # didnt pass, probably got an image challenge
            return SolveResult(
                solved=False, captcha_type="recaptcha_checkbox",
                error="Checkbox click triggered image challenge — needs image solver",
                attempts=1,
            )

        return SolveResult(solved=False, error="Checkbox element not found")

    except Exception as e:
        return SolveResult(
            solved=False, captcha_type="recaptcha_checkbox",
            error=f"Error: {type(e).__name__}: {e}",
        )


class CaptchaSolver:

    def __init__(self, api_key=None):
        self.gemini = GeminiClient(api_key=api_key)

    @property
    def available(self):
        return self.gemini.available

    async def solve(self, page, captcha_type="auto"):
        if not self.available:
            return SolveResult(
                solved=False,
                error="GEMINI_API_KEY not configured. Get one at https://aistudio.google.com/apikey",
            )

        if captcha_type == "auto":
            captcha_type = await self._detect_type(page)

        if captcha_type in ("recaptcha_v2", "hcaptcha"):
            # try checkbox first, might get lucky
            box_result = await _click_recaptcha_box(page)
            if box_result.solved:
                return box_result
            return await _try_image_captcha(page, self.gemini)

        elif captcha_type == "text_captcha":
            return await _try_image_captcha(page, self.gemini)

        elif captcha_type in ("cloudflare_turnstile", "cloudflare_challenge"):
            await asyncio.sleep(5)
            return SolveResult(
                solved=False, captcha_type=captcha_type,
                error="Turnstile requires browser-level solving, not image analysis",
            )

        else:
            return await _try_image_captcha(page, self.gemini)

    async def _detect_type(self, page):
        html = await page.content()
        html_lower = html.lower()

        if "recaptcha" in html_lower or "g-recaptcha" in html_lower:
            return "recaptcha_v2"
        elif "hcaptcha" in html_lower or "h-captcha" in html_lower:
            return "hcaptcha"
        elif "turnstile" in html_lower or "cf-turnstile" in html_lower:
            return "cloudflare_turnstile"
        elif "captcha" in html_lower:
            return "text_captcha"

        return "unknown"
