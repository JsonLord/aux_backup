import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:7860")
        
        # Wait for Gradio to load
        await page.wait_for_selector("button:has-text('Persona Thought Logs')", state='visible')
        
        async def click_tab(name):
            print(f"Clicking {name}...")
            await page.evaluate(f"""
                const btn = Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('{name}'));
                if (btn) btn.click();
            """)
            await asyncio.sleep(2)

        # Screenshot Thought Logs tab
        await click_tab('Persona Thought Logs')
        await page.screenshot(path="/home/jules/verification/thought_logs_tab.png")
        
        # Check Example Persona preview
        await click_tab('Analysis Orchestrator')
        await page.click("input[value='Example Persona']")
        await asyncio.sleep(1)
        await page.screenshot(path="/home/jules/verification/example_persona_selection.png")
        
        await browser.close()

asyncio.run(run())
