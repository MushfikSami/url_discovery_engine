import time
import csv
from datetime import datetime
from fanout import generate_wikipedia_query
from search import search_wikipedia
from parser import extract_markdown_from_url

def run_batch_benchmark(queries: list, output_filename: str = "webrag_benchmark_results.csv"):
    print(f"\n🚀 Starting Batch Benchmark for {len(queries)} queries...")
    print(f"📁 Results will be saved to: {output_filename}\n")

    # Define the CSV column headers
    headers = [
        "Timestamp", 
        "Original_Query", 
        "Optimized_Query", 
        "Target_URL",
        "Fanout_Time_sec", 
        "Search_Time_sec", 
        "Parse_Time_sec", 
        "Total_Time_sec",
        "Markdown_Length", 
        "Status"
    ]

    # Open the CSV file in write mode
    with open(output_filename, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)

        for index, query in enumerate(queries, 1):
            print(f"[{index}/{len(queries)}] Testing: '{query}'")
            
            # Default values for this iteration
            status = "Success"
            opt_query = ""
            url = ""
            md_len = 0
            fanout_t = search_t = parse_t = 0.0

            # --- 1. LLM Fanout Test ---
            t0 = time.perf_counter()
            opt_query = generate_wikipedia_query(query)
            fanout_t = time.perf_counter() - t0
            
            if not opt_query or opt_query == query: # Assuming fallback to original query means failure
                status = "Failed at Fanout"
                print(f"  ❌ {status}")
                _write_row(writer, query, opt_query, url, fanout_t, search_t, parse_t, md_len, status)
                continue

            # --- 2. SearXNG Search Test ---
            t0 = time.perf_counter()
            url = search_wikipedia(opt_query)
            search_t = time.perf_counter() - t0
            
            if not url:
                status = "Failed at Search (No URL)"
                print(f"  ❌ {status}")
                _write_row(writer, query, opt_query, url, fanout_t, search_t, parse_t, md_len, status)
                continue

            # --- 3. Docling Parsing Test ---
            t0 = time.perf_counter()
            final_markdown = extract_markdown_from_url(url)
            parse_t = time.perf_counter() - t0
            
            if not final_markdown:
                status = "Failed at Parse (Empty Markdown)"
                print(f"  ❌ {status}")
            else:
                md_len = len(final_markdown)
                print(f"  ✅ Success ({md_len} chars extracted)")

            # Write successful or parse-failed row
            _write_row(writer, query, opt_query, url, fanout_t, search_t, parse_t, md_len, status)
            
            # Give the local SearXNG and vLLM a tiny 1-second breather to prevent port exhaustion
            time.sleep(5.0)

    print(f"\n🎉 Benchmark complete! All data saved to {output_filename}")

def _write_row(writer, query, opt_query, url, fanout_t, search_t, parse_t, md_len, status):
    """Helper function to format and write the row to the CSV."""
    total_t = fanout_t + search_t + parse_t
    writer.writerow([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        query,
        opt_query,
        url,
        round(fanout_t, 3),
        round(search_t, 3),
        round(parse_t, 3),
        round(total_t, 3),
        md_len,
        status
    ])

if __name__ == "__main__":
    # You can paste the 20 test queries here!
    test_queries = ['When was Dhaka University established?',
                  'Who is the current President of Bangladesh?',
                  'What is the national flower of Bangladesh?',
                  'Tell me about the Padma Bridge.',
                  'Where is the Sundarbans located?',
                  'What is the official currency of Bangladesh?',
                  'Who wrote the national anthem of Bangladesh?',
                  'Tell me about the history of Coxs Bazar.',
                  'Who is Kazi Nazrul Islam?',
                  'When did the Liberation War of Bangladesh start?',
                  'বাংলাদেশের প্রথম রাষ্ট্রপতি কে ছিলেন?',
                  'সেন্ট মার্টিন দ্বীপ কোথায় অবস্থিত?',
                  'শহীদ মিনার কে নকশা করেছেন?',
                  'সুন্দরবনে কোন বিখ্যাত প্রাণী বাস করে?',
                  'ঢাকা শহরের পুরনো নাম কী ছিল?',
                  'জাতীয় সংসদ ভবনের স্থপতি কে?',''
                  'বাংলাদেশের স্বাধীনতা দিবস কবে?',
                  'কর্ণফুলী নদী কোথায় অবস্থিত?',
                  'বাংলাদেশের সর্বোচ্চ পর্বতশৃঙ্গ কোনটি?',
                  'লালবাগ কেল্লা কে নির্মাণ করেন?',
                  "What is the longest river in Bangladesh?",
    "Who designed the National Martyrs' Monument?",
    "What is the main seaport of Bangladesh?",
    "Tell me about the Bengal famine of 1943.",
    "Who was the founder of the Mughal Empire?",
    "What is the national fruit of Bangladesh?",
    "Who is the author of the novel Pather Panchali?",
    "Where is the archaeological site Mahasthangarh located?",
    "What is the largest mangrove forest in the world?",
    "Tell me about the history of the Bengali language movement.",
    "ভাই, আমাকে একটু বলবেন কি বাংলাদেশের জাতীয় পাখি কোনটি?",
    "পলাশীর যুদ্ধ কত সালে সংঘটিত হয়েছিল?",
    "বাংলাদেশের কোন জেলাকে চায়ের দেশ বলা হয়?",
    "বঙ্গবন্ধু স্যাটেলাইট-১ সম্পর্কে বিস্তারিত কিছু তথ্য দিন।",
    "রোকেয়া সাখাওয়াত হোসেন কেন বিখ্যাত?",
    "ময়নামতি কোথায় অবস্থিত এবং এর ইতিহাস কী?",
    "বাংলাদেশের বর্তমান সংবিধান কবে গৃহীত হয়?",
    "হাতিরঝিল প্রজেক্ট সম্পর্কে জানতে চাই।",
    "বাউল সম্রাট লালন শাহের জীবনকাহিনী সংক্ষেপে বলুন।",
    "রূপপুর পারমাণবিক বিদ্যুৎ কেন্দ্র কোথায় তৈরি হচ্ছে?",
    "Who is the architect of the Kamalapur Railway Station?",
    "Tell me about the Independence Day Award of Bangladesh.",
    "Who won the Nobel Peace Prize from Bangladesh?",
    "What is the total length of the Jamuna Bridge?",
    "Explain the significance of the 21st of February in Bangladesh.",
    "What is the national sport of Bangladesh?",
    "Who was the commander-in-chief of the Mukti Bahini?",
    "Where is Foy's Lake located?",
    "What is the main ingredient in Panta Bhat?",
    "Tell me about the history of Rajshahi University.",
    "Who is known as the Shilpacharya of Bangladesh?",
    "What is the largest island in Bangladesh?",
    "Give me a brief overview of the economy of Bangladesh.",
    "Who was the first female Prime Minister of Bangladesh?",
    "What is the primary role of the Bangladesh Bank?",
    "Give me information about the Somapura Mahavihara.",
    "Who wrote the famous Bengali poem 'Bidrohi'?",
    "What is the total border length between Bangladesh and India?",
    "Tell me about the Chittagong Hill Tracts Peace Accord.",
    "What is the significance of the Suhrawardy Udyan?",
    "আমাদের দেশের জাতীয় মাছ ইলিশের বৈজ্ঞানিক নাম এবং বাসস্থান সম্পর্কে বলুন।",
    "কান্তজীর মন্দির কোন জেলায় অবস্থিত এবং এটি কে বানিয়েছিলেন?",
    "বাংলার বারো ভূঁইয়াদের নেতা কে ছিলেন?",
    "আমাকে একটু সাহায্য করুন, ছয় দফা দাবি কবে এবং কেন উত্থাপন করা হয়?",
    "বাংলাদেশের মুক্তিযুদ্ধের সময় দেশকে কয়টি সেক্টরে ভাগ করা হয়েছিল?",
    "বিখ্যাত ভাওয়াইয়া গায়ক আব্বাসউদ্দীন আহমদ কোথায় জন্মগ্রহণ করেন?",
    "বাংলাদেশের শেয়ার বাজার নিয়ন্ত্রণকারী মূল সংস্থার নাম কী?",
    "সুন্দরবনের সুন্দরী গাছের প্রধান বৈশিষ্ট্য কী কী?",
    "মহাস্থানগড়ের পুরোনো নাম যে পুণ্ড্রবর্ধন ছিল, সেটার ইতিহাস কী?",
    "আচ্ছা, বাংলাদেশের জাতীয় চিড়িয়াখানা কোথায় অবস্থিত?",
    "শিল্পাচার্য জয়নুল আবেদিনের বিখ্যাত চিত্রকর্মগুলো সম্পর্কে বিস্তারিত জানতে চাই।",
    "গ্রামীণ ব্যাংকের প্রতিষ্ঠাতা ড. মুহাম্মদ ইউনূস সম্পর্কে কিছু বলুন।",
    "বাংলাদেশ ও মিয়ানমারের সীমানার মধ্যে দিয়ে কোন নদী প্রবাহিত হয়েছে?",
    "ঢাকার বায়তুল মোকাররম জাতীয় মসজিদের মূল নকশা কে করেছিলেন?",
    "বাংলাদেশের সবচেয়ে বড় হাওর হাকালুকি হাওর সম্পর্কে তথ্য দিন।",
    "ব্রিটিশ বিরোধী আন্দোলনে তিতুমীরের বাঁশের কেল্লার ভূমিকা কী ছিল?",
    "শিল্প ও সাহিত্যে অবদানের জন্য একুশে পদক কেন দেওয়া হয়?",
    "ঢাকার মেট্রোরেল প্রকল্প কবে সর্বসাধারণের জন্য উদ্বোধন করা হয়?",
    "বাংলাদেশের সর্বোচ্চ বেসামরিক সম্মাননা স্বাধীনতা পদক সম্পর্কে জানতে চাই।",
    "ভাই, আপনি কি বলতে পারবেন লালন শাহের আখড়া কোথায় অবস্থিত?",
    "What is the significance of the 6-point movement in Bangladesh?",
    "Tell me about the construction of the Rooppur Nuclear Power Plant.",
    "Who is the current governor of Bangladesh Bank?",
    "What is the history of the Ahsan Manzil museum?",
    "Explain the cultural importance of Pohela Boishakh.",
    "Where is the Kuakata beach located?",
    "Who designed the Jatiya Sangsad Bhaban?",
    "What are the main features of the Meghna River?",
    "Tell me about the Bangladesh Awami League's founding.",
    "Who was the commander of Sector 7 during the Liberation War?",
    "ভাই, সুন্দরবনের রয়েল বেঙ্গল টাইগার সম্পর্কে কিছু মজার তথ্য দিন।",
    "আমি জানতে চাই, বাংলাদেশের সবচেয়ে দক্ষিণের উপজেলা টেকনাফের ইতিহাস কী?",
    "জাতীয় স্মৃতিসৌধের সাতটি স্তম্ভের তাৎপর্য কী?",
    "আপনি কি জানেন, বাংলাদেশের প্রথম এভারেস্ট বিজয়ী মুসা ইব্রাহীম কবে চূড়ায় ওঠেন?",
    "সোমপুর মহাবিহার বা পাহাড়পুর বৌদ্ধ বিহার কে আবিষ্কার করেন?",
    "বাংলাদেশের প্রথম অস্থায়ী সরকার বা মুজিবনগর সরকার কবে গঠিত হয়?",
    "বাংলাদেশের সংবিধানের রাষ্ট্র পরিচালনার মূলনীতিগুলো কী কী?",
    "বিশ্বসাহিত্য কেন্দ্রের প্রতিষ্ঠাতা অধ্যাপক আবদুল্লাহ আবু সায়ীদ সম্পর্কে বলুন।",
    "কর্ণফুলী নদীর তলদেশে নির্মিত বঙ্গবন্ধু টানেলের দৈর্ঘ্য কত?",
    "কাজী নজরুল ইসলামের বিখ্যাত কাব্যগ্রন্থ 'অগ্নিবীণা' কবে প্রকাশিত হয়?"]
    
    run_batch_benchmark(test_queries[91:100], "webrag_benchmark_results_10.csv")

