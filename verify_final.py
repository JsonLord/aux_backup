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
        btns = await page.query_selector_all("button")
        for btn in btns:
            text = await btn.text_content()
            if text == "Report Viewer":
                await btn.click(force=True)
                break
        
        await asyncio.sleep(2)
        await page.screenshot(path="/home/jules/verification/report_viewer_final.png")
        await browser.close()

asyncio.run(run())
