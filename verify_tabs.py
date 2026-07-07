import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:7860")
        
        # Wait for Gradio to load
        await page.wait_for_selector("button:has-text('Average User Journey Heatmaps')", state='visible')
        
        async def click_tab(name):
            print(f"Clicking {name}...")
            await page.evaluate(f"""
                const btns = Array.from(document.querySelectorAll('button')).filter(el => el.textContent.includes('{name}'));
                btns.forEach(btn => btn.click());
            """)
            await asyncio.sleep(2)

        # Screenshot Heatmaps tab
        await click_tab('Average User Journey Heatmaps')
        await page.screenshot(path="/home/jules/verification/heatmaps_tab.png")
        
        # Screenshot Agents.txt tab
        await click_tab('Agents.txt')
        await page.screenshot(path="/home/jules/verification/agents_tab.png")
        
        # Screenshot Full New UI tab
        await click_tab('Full New UI')
        await page.screenshot(path="/home/jules/verification/full_ui_tab.png")
        
        await browser.close()

asyncio.run(run())
