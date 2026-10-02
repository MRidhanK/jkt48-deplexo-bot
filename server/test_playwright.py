import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        await page.goto(
            "https://jkt48.com",
            wait_until="networkidle",
            timeout=120000
        )

        print("TITLE =", await page.title())

        html = await page.content()

        print(html[:1000])

        await browser.close()

asyncio.run(main())