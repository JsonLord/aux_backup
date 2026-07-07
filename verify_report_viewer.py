import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:7860")
        
        # Wait for Gradio to load
        await page.wait_for_selector("button:has-text('Report Viewer')", state='visible')
        
        # Click Report Viewer
        await page.evaluate("""
            Array.from(document.querySelectorAll('button')).find(el => el.textContent === 'Report Viewer').click()
        """)
        await asyncio.sleep(2)
        
        # The Report Viewer might be empty if no reports exist.
        # I'll check if there's any content or at least the dropdown.
        await page.screenshot(path="/home/jules/verification/report_viewer_tab.png")
        
        await browser.close()

asyncio.run(run())
