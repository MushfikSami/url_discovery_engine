import psycopg2
import datetime
import os
from db_setup import DB_CONFIG

def generate_health_report():
    print("📊 Generating Spider Fleet Health Report...\n")
    
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # 1. Domain Progress
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status = 'completed'),
                COUNT(*) FILTER (WHERE status = 'processing'),
                COUNT(*) FILTER (WHERE status = 'pending')
            FROM seed_websites;
        """)
        domains_completed, domains_processing, domains_pending = cursor.fetchone()
        total_domains = (domains_completed or 0) + (domains_processing or 0) + (domains_pending or 0)

        # 2. Webpage Queue Progress
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status = 'completed'),
                COUNT(*) FILTER (WHERE status = 'failed'),
                COUNT(*) FILTER (WHERE status = 'pending'),
                COUNT(*) FILTER (WHERE status = 'processing')
            FROM spider_queue;
        """)
        pages_completed, pages_failed, pages_pending, pages_processing = cursor.fetchone()
        pages_completed = pages_completed or 0
        total_discovered = pages_completed + (pages_failed or 0) + (pages_pending or 0) + (pages_processing or 0)

        # 3. Successful Data Extraction
        cursor.execute("SELECT COUNT(*) FROM crawled_data;")
        successfully_extracted = cursor.fetchone()[0]

        # 4. Speed Calculation
        # Get the time the very first URL was added to the queue
        cursor.execute("SELECT MIN(added_at) FROM spider_queue;")
        start_time = cursor.fetchone()[0]
        
        pages_per_minute = 0
        if start_time and pages_completed > 0:
            time_elapsed = datetime.datetime.now() - start_time
            minutes_elapsed = time_elapsed.total_seconds() / 60.0
            if minutes_elapsed > 0:
                pages_per_minute = pages_completed / minutes_elapsed

        # Format the Report
        report = []
        report.append("="*50)
        report.append(f"🕷️ SPIDER FLEET DAILY REPORT - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("="*50)
        
        report.append("\n🌍 ROOT DOMAINS (seed_websites):")
        report.append(f"  - Completed:  {domains_completed}")
        report.append(f"  - Processing: {domains_processing} (Active workers)")
        report.append(f"  - Pending:    {domains_pending}")
        report.append(f"  - Total:      {total_domains}")

        report.append("\n📄 INTERNAL WEBPAGES (spider_queue):")
        report.append(f"  - Completed:  {pages_completed}")
        report.append(f"  - Failed:     {pages_failed} (Dead links / Timeouts)")
        report.append(f"  - Pending:    {pages_pending}")
        report.append(f"  - Total Found:{total_discovered}")

        report.append("\n💾 EXTRACTED DATA (crawled_data):")
        report.append(f"  - Clean Markdown Saved: {successfully_extracted} pages")

        report.append("\n⚡ FLEET PERFORMANCE:")
        report.append(f"  - Average Speed: {pages_per_minute:.2f} pages / minute")
        if pages_per_minute > 0:
            estimated_minutes_left = pages_pending / pages_per_minute
            report.append(f"  - Est. time to clear current queue: {estimated_minutes_left / 60:.2f} hours")
        report.append("="*50)

        # Print to terminal
        final_output = "\n".join(report)
        print(final_output)

        # Save to file
        os.makedirs("reports", exist_ok=True)
        filename = f"reports/fleet_report_{datetime.datetime.now().strftime('%Y_%m_%d')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(final_output)
        print(f"\n[+] Report saved to {filename}")

    except Exception as e:
        print(f"[!] Error generating report: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    generate_health_report()