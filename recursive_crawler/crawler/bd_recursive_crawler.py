import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import sys
import os
import json

class RecursiveBDCrawler:
    def __init__(self, max_concurrent_requests=30):
        self.state_file = "crawler_state.json"
        self.output_file = "recursive_gov_bd_domains.txt"
        
        self.seed_urls = [
            "https://bangladesh.gov.bd",
            "https://bangladesh.gov.bd/views/ministry-and-directorate-list",
            "https://bangladesh.gov.bd/views/union-list"
        ]
        
        self.found_domains = set()
        self.visited_urls = set()
        self.queue = asyncio.Queue()
        
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.headers = {'User-Agent': 'BD-Gov-Ecosystem-Mapper/3.0 (Research)'}

    def load_state(self):
        """Loads previous progress if it exists."""
        if os.path.exists(self.state_file):
            print("[*] Found previous state file. Resuming progress...")
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                
            self.visited_urls = set(data.get("visited_urls", []))
            
            # Repopulate the queue
            saved_queue = data.get("queue", [])
            for url in saved_queue:
                self.queue.put_nowait(url)
                
            # Reload found domains
            if os.path.exists(self.output_file):
                with open(self.output_file, 'r') as f:
                    self.found_domains = set([line.strip() for line in f if line.strip()])
                    
            print(f"[*] Resuming with {len(self.found_domains)} domains found and {self.queue.qsize()} URLs in queue.")
            return True
        return False

    def save_state(self):
        """Saves current progress so it can be resumed later."""
        print("\n[*] Saving current state... Please wait.")
        
        # Extract everything currently in the queue
        current_queue = []
        while not self.queue.empty():
            current_queue.append(self.queue.get_nowait())
            
        state_data = {
            "visited_urls": list(self.visited_urls),
            "queue": current_queue
        }
        
        with open(self.state_file, 'w') as f:
            json.dump(state_data, f)
            
        print(f"[+] State saved successfully! You can safely exit now.")

    def get_gov_bd_domain(self, url):
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().split(':')[0]
            if domain.startswith('www.'):
                domain = domain[4:]
            if domain.endswith('.gov.bd'):
                return domain
        except Exception:
            pass
        return None

    async def fetch_and_parse(self, session, url):
        async with self.semaphore:
            try:
                async with session.get(url, headers=self.headers, timeout=15, ssl=False) as response:
                    if response.status == 200:
                        html = await response.text()
                        return html, url
            except Exception:
                return None, url
        return None, url

    async def worker(self, session, worker_id):
        while True:
            try:
                current_url = await self.queue.get()
                
                if current_url in self.visited_urls:
                    self.queue.task_done()
                    continue
                    
                self.visited_urls.add(current_url)
                html, url = await self.fetch_and_parse(session, current_url)
                
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    for link in soup.find_all('a', href=True):
                        raw_href = link['href'].strip()
                        full_url = urljoin(url, raw_href).split('#')[0]
                        domain = self.get_gov_bd_domain(full_url)
                        
                        if domain and domain not in self.found_domains:
                            self.found_domains.add(domain)
                            print(f"[Worker-{worker_id}] [+] New: {domain} (Total: {len(self.found_domains)})")
                            
                            with open(self.output_file, "a") as f:
                                f.write(f"{domain}\n")
                        
                        if domain and full_url not in self.visited_urls:
                            await self.queue.put(full_url)
                
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.queue.task_done()

    async def run(self):
        print("[*] Initializing Resumable Recursive Crawler...")
        
        # Try to load previous state; if not, use seed URLs
        if not self.load_state():
            open(self.output_file, "w").close() # Clear output file on fresh start
            for url in self.seed_urls:
                self.queue.put_nowait(url)
                
        async with aiohttp.ClientSession() as session:
            workers = []
            for i in range(30):
                task = asyncio.create_task(self.worker(session, i))
                workers.append(task)
                
            try:
                await self.queue.join()
            except asyncio.CancelledError:
                pass
            finally:
                for w in workers:
                    w.cancel()

if __name__ == "__main__":
    crawler = RecursiveBDCrawler(max_concurrent_requests=30)
    
    # We use the main event loop so we can cleanly catch Ctrl+C
    loop = asyncio.get_event_loop()
    main_task = loop.create_task(crawler.run())
    
    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        print("\n[!] Crawler manually stopped via Ctrl+C.")
        main_task.cancel()
        # Wait a moment for tasks to cancel cleanly
        loop.run_until_complete(asyncio.sleep(0.5)) 
        # Save the current progress
        crawler.save_state()
        sys.exit(0)