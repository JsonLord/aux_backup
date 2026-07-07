import asyncio
from playwright.async_api import async_playwright

async def verify_thinking_status():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("http://localhost:7860", timeout=60000)
            print("Page loaded.")
            
            # Fill mandatory fields
            await page.get_by_label("Theme").fill("Test Theme")
            await page.get_by_label("Target URL").fill("https://example.com")
            
            # Click Generate
            await page.get_by_role("button", name="Generate Personas & Tasks").click()
            print("Clicked Generate button.")
            
            # Check for Thinking... status
            # It might be in the status textbox
            status_box = page.get_by_label("Status")
            
            # Use a loop to check for the text since it's transient
            found = False
            for _ in range(20):
                val = await status_box.input_value()
                if "Thinking..." in val:
                    print(f"Found status: {val}")
                    found = True
                    break
                await asyncio.sleep(0.5)
            
            if not found:
                print("Thinking... status not found or appeared too quickly.")

            await page.screenshot(path="thinking_verification.png")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(verify_thinking_status())
