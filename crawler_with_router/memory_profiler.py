import asyncio
import os
import gc
import tracemalloc
import time
import psutil
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

def get_total_fleet_memory():
    """Calculates memory usage of the current Python process and all its child processes (Chromium)."""
    current_process = psutil.Process(os.getpid())
    # Base Python process memory
    total_mem = current_process.memory_info().rss
    
    # Add all child processes (Chromium browser contexts, page threads, etc.)
    try:
        for child in current_process.children(recursive=True):
            total_mem += child.memory_info().rss
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
        
    return total_mem / 1024 / 1024  # Return in MB

async def profile_skeleton_browser(target_url):
    print(f"🚀 Initializing Async SKELETON Headless Browser Profile for: {target_url}")
    
    # Clean up memory states before tracking
    gc.collect()
    tracemalloc.start()
    
    baseline_system_mem = get_total_fleet_memory()
    print(f"📊 Baseline System RAM Usage: {baseline_system_mem:.2f} MB")
    print("-" * 50)

    start_time = time.time()
    peak_system_mem = baseline_system_mem
    
    # Background asynchronous task to sample process spikes every 50ms
    async def monitor_memory():
        nonlocal peak_system_mem
        while True:
            current_mem = get_total_fleet_memory()
            if current_mem > peak_system_mem:
                peak_system_mem = current_mem
            await asyncio.sleep(0.05)

    monitor_task = asyncio.create_task(monitor_memory())

    # =======================================================
    # CONFIGURATION: THE SKELETON BROWSER STRATEGY
    # =======================================================
    # 1. Turn off heavy backend UI features and isolation over-allocation
    browser_cfg = BrowserConfig(
        headless=True,
        light_mode=True,  
        text_mode=True,
        
        # THE STRICT CHROMIUM CHOKEHOLD (No inner quotes)
        extra_args=[
            "--js-flags=--max-old-space-size=256",   # Corrected syntax: NO single quotes
            "--disable-dev-shm-usage",               # Avoids /dev/shm memory limitations
            "--disable-gpu",                         # Disables hardware acceleration entirely
            "--disable-software-rasterizer",         # Blocks fallback software rendering engine
            "--single-process",                      # Forces tabs to share process space if supported
            "--mute-audio",                          # Kills browser audio subsystem allocations
            "--no-sandbox"                           # Reduces process sandboxing resource isolation overhead
        ]
    )
    
    # 2. Block all heavy media payloads at the network request engine
    # 2. Block all heavy media payloads using standard v0.8+ parameters
    run_cfg = CrawlerRunConfig(
        remove_overlay_elements=True,   # Drops annoying UI layers
        # Explicitly ban heavy tags here instead of using the invalid flags
        excluded_tags=["nav", "footer", "header", "aside", "svg", "canvas", "img", "picture", "video", "iframe"],
        page_timeout=15000,            # 15 seconds max constraint to kill Cloudflare traps
        cache_mode=CacheMode.BYPASS             
    )

    markdown_output = ""
    try:
        # Pass the configurations directly to the crawler session setup
        async with AsyncWebCrawler(config=browser_cfg, verbose=False) as crawler:
            result = await crawler.arun(
                url=target_url,
                config=run_cfg
            )
            if result.success:
                markdown_output = result.markdown
            else:
                print(f"⚠️ Crawl failed or hit defensive wall. Status: {result.status_code}")
                
    except Exception as e:
        print(f"❌ Execution Error during profiling: {e}")
    finally:
        # Stop background monitoring loops safely
        monitor_task.cancel()
        current_python_mem, peak_python_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        end_time = time.time()

    # 3. Output Diagnostics
    print("\n🔍 --- PROFILE DIAGNOSTICS ---")
    print(f"⏱️  Total Processing Time : {end_time - start_time:.4f} seconds")
    print(f"🐍 Peak INTERNAL Python RAM: {peak_python_mem / 1024 / 1024:.2f} MB")
    print(f"🖥️  Peak TOTAL System RAM  : {peak_system_mem:.2f} MB")
    print(f"🌐 Chromium Overhead Cost : {max(0.0, peak_system_mem - baseline_system_mem):.2f} MB")
    print(f"📊 Extracted Markdown Size: {len(markdown_output)} characters")
    print("-" * 50)
    
    if markdown_output:
        print("\nPreview of extracted output:")
        print(markdown_output[:250] + "...\n")

if __name__ == "__main__":
    TEST_URL = "https://bcc.gov.bd"
    asyncio.run(profile_skeleton_browser(TEST_URL))