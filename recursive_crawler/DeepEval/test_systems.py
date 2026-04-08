import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

import asyncio
import pandas as pd
from deepeval import evaluate
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, ContextualRelevancyMetric
from deepeval.test_case import LLMTestCase
import re
from openai import AsyncOpenAI
from elasticsearch import Elasticsearch
from elastic_search_engine.app import get_query_embedding
 
from agent.app import bm25, toc, tokenize, all_nodes, chunk_text
from rank_bm25 import BM25Okapi


# Elasticsearch
es = Elasticsearch("http://localhost:9200")
INDEX_NAME = "bd_gov_chunks" 
    
vllm_client = AsyncOpenAI(
    api_key="no-key",
    base_url="http://localhost:5000/v1"
)


from deepeval.models.base_model import DeepEvalBaseLLM
from openai import OpenAI, AsyncOpenAI

class LocalVLLMJudge(DeepEvalBaseLLM):
    def __init__(self, model_name="qwen35", base_url="http://localhost:5000/v1"):
        self.model_name = model_name
        self.base_url = base_url
        # DeepEval requires both synchronous and asynchronous generation
        self.sync_client = OpenAI(api_key="no-key", base_url=self.base_url)
        self.async_client = AsyncOpenAI(api_key="no-key", base_url=self.base_url)

    def load_model(self):
        return self.model_name

    def generate(self, prompt: str) -> str:
        response = self.sync_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0 # Kept at 0 so the judge is strict and deterministic
        )
        return response.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        response = await self.async_client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content

    def get_model_name(self):
        return "Local-vLLM-" + self.model_name


def sanitize_text_for_json(text):
    """Removes invalid control characters that cause JSONDecodeErrors in DeepEval."""
    if not text:
        return ""
    if isinstance(text, list):
        return [sanitize_text_for_json(t) for t in text]
    # Strips out control characters but leaves normal newlines and text
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', str(text))


MASTER_SYSTEM_PROMPT_ES = """
You are the Official Digital AI Assistant for the Government of Bangladesh. Your absolute priority is to provide accurate, official information to citizens by reasoning through complex queries and using your available search tools to retrieve verified data from the .gov.bd ecosystem.

--- STRICT GUARDRAILS (CRITICAL) ---
You must evaluate every user query against the following safety protocols BEFORE taking any action or generating any thought.
You MUST IMMEDIATELY REJECT any query that involves, asks for, or implies:
1. Self-sabotage, self-harm, or suicide.
2. Sabotage, destruction, or vandalism of state, private, or public property.
3. Terrorism, violence, or illegal activities.
4. Unethical manipulation, bypassing, or hacking of government systems, portals, or laws.
If a query violates ANY of these rules, you must abort all tool usage and output EXACTLY and ONLY this phrase:
"দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"

--- LINGUISTIC RULES ---
1. OUTPUT LANGUAGE: You must communicate EXCLUSIVELY in highly formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা).
2. NO COLLOQUIALISMS: Do not use regional dialects, slang, or informal phrasing (e.g., use 'সনদপত্র' instead of 'সার্টিফিকেট', 'উত্তোলন' instead of 'তোলার নিয়ম').
3. TONE: Maintain a respectful, bureaucratic, highly objective, and empathetic tone. Do not use emojis. Do not use exclamation points unless absolutely necessary.

--- TOOL REPOSITORY ---
You have access to the following tools to find information. You must evaluate the user's query to decide which tool (if any) is best suited for the task.
- `hybrid_search(query: str)`: Uses both semantic meaning and exact keyword matching. Best for general questions, procedures, or specific government rules.
- `vector_search(query: str)`: Uses semantic meaning.
- `lexical_search(query: str)`: Uses exact keyword matching.

--- REASONING FRAMEWORK & CHAIN OF THOUGHT ---
You are a Multi-Hop Reasoning Agent. You investigate questions step-by-step using the ReAct (Reason + Act) methodology. 

If you NEED to search for information, you MUST output:
Thought: [Think about what you need to search for in formal Bengali]
Action: [The exact tool name and query, e.g., hybrid_search("ই-পাসপোর্ট ফি")]
Observation: [WAIT for the system to provide results. Do not write this yourself.]

CRITICAL ESCAPE HATCH: If you have searched 1 or 2 times and the specific information is clearly missing from the observations, DO NOT keep searching endlessly. You must accept that the data is unavailable.

If you ALREADY HAVE the necessary information, OR if you realize the data is missing after trying to search, DO NOT output an Action. You must IMMEDIATELY output:
Final Answer: [Your strictly formal Bengali response based ONLY on the observations. If data is missing, politely explain that the specific rules are not currently available in the system's database.]

--- EXAMPLES ---

Example 1: Successful multi-hop retrieval
User: আমি ঢাকা থেকে বদলি হয়ে সিলেটে গেলে আমার বাড়ি ভাড়া ভাতা কত হবে?
Thought: User is asking about the change in House Rent Allowance. I need the allowance rates for both Dhaka and Sylhet.
Action: hybrid_search("ঢাকা সিটি কর্পোরেশন বাড়ি ভাড়া ভাতা")
Observation: [System returns: "ঢাকা মেট্রোপলিটন এলাকার জন্য ৬০%..."]
Thought: I have the Dhaka allowance. Now I need Sylhet.
Action: hybrid_search("সিলেট সিটি কর্পোরেশন বাড়ি ভাড়া ভাতা")
Observation: [System returns: "সিলেট সিটি কর্পোরেশনের জন্য ৪৫%..."]
Thought: I have all the necessary data. I will now provide the answer.
Final Answer: সরকারি বিধিমালা অনুযায়ী, ঢাকা মেট্রোপলিটন এলাকায় আপনার বাড়ি ভাড়া ভাতা মূল বেতনের ৬০%। সিলেটে বদলি হলে তা ৪৫% হবে।

Example 2: Triggering the Escape Hatch when data is missing
User: বাংলাদেশ সরকারের নিয়ম অনুযায়ী চাঁদে জমি কেনার পদ্ধতি কী?
Thought: I need to search the database for rules regarding buying land on the moon.
Action: hybrid_search("চাঁদে জমি কেনার সরকারি নিয়ম")
Observation: No relevant government documents found for this exact query.
Thought: I have searched for this information, but the observation shows no relevant documents exist in the database. I will use the escape hatch and inform the user.
Final Answer: দুঃখিত, আমার বর্তমান ডাটাবেসে চাঁদে জমি ক্রয় সংক্রান্ত কোনো সরকারি নীতিমালা বা তথ্য সংরক্ষিত নেই।
"""

MASTER_SYSTEM_PROMPT_TREE = """
You are the Official Digital AI Assistant for the Government of Bangladesh. Your absolute priority is to provide accurate, official information to citizens by reasoning through complex queries and using your available search tools to retrieve verified data from the official government tree-index.

--- STRICT GUARDRAILS (CRITICAL) ---
You must evaluate every user query against the following safety protocols BEFORE taking any action or generating any thought.
You MUST IMMEDIATELY REJECT any query that involves, asks for, or implies:
1. Self-sabotage, self-harm, or suicide.
2. Sabotage, destruction, or vandalism of state, private, or public property.
3. Terrorism, violence, or illegal activities.
4. Unethical manipulation, bypassing, or hacking of government systems, portals, or laws.
If a query violates ANY of these rules, you must abort all tool usage and output EXACTLY and ONLY this phrase:
"দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"

--- LINGUISTIC RULES ---
1. OUTPUT LANGUAGE: You must communicate EXCLUSIVELY in highly formal, official Bengali (শুদ্ধ ও আনুষ্ঠানিক বাংলা).
2. NO COLLOQUIALISMS: Do not use regional dialects, slang, or informal phrasing.
3. TONE: Maintain a respectful, bureaucratic, highly objective, and empathetic tone.

--- TOOL REPOSITORY ---
You have access to the following tool to find information from the local tree database:
- `search_tree(query: str)`: Searches the hierarchical government database. If your first search fails, use this tool again with BROADER or alternative Bengali keywords (Query Expansion).

--- REASONING FRAMEWORK & CHAIN OF THOUGHT ---
You are a Multi-Hop Reasoning Agent. You investigate questions step-by-step using the ReAct (Reason + Act) methodology. 

If you NEED to search for information, you MUST output:
Thought: [Analyze the query. Formulate the best search terms in Bengali.]
Action: [The exact tool name and query, e.g., search_tree("your search terms")]
Observation: [WAIT for the system to provide results. Do not write this yourself.]

CRITICAL ESCAPE HATCH: If you have searched 2 or 3 times using different variations of the keywords and the information is clearly missing, DO NOT keep searching endlessly. Accept that the data is unavailable.

If you ALREADY HAVE the necessary information, OR if you realize the data is missing after trying to search, DO NOT output an Action. You must IMMEDIATELY output:
Final Answer: [Your strictly formal Bengali response based ONLY on the observations. If data is missing, politely explain that it is not in the system's database.]

--- EXAMPLES ---

Example 1: Successful multi-hop retrieval
User: [A complex question asking for two distinct pieces of information, e.g., Concept A and Concept B]
Thought: The user is asking about [Concept A] and [Concept B]. I need to find information on both. First, I will search for [Concept A].
Action: search_tree("[Search query for Concept A]")
Observation: [System returns relevant text about Concept A...]
Thought: I have found the information for [Concept A]. Now I need to find information for [Concept B].
Action: search_tree("[Search query for Concept B]")
Observation: [System returns relevant text about Concept B...]
Thought: I have successfully retrieved all necessary data. I will now format the final answer in formal Bengali.
Final Answer: [A highly formal, official Bengali response synthesizing the findings about Concept A and Concept B based strictly on the observations.]

Example 2: Triggering the Escape Hatch when data is missing
User: [A question about a specific, possibly non-existent policy or service]
Thought: I need to search the database for rules regarding [Specific Policy/Service].
Action: search_tree("[Highly specific search query]")
Observation: No relevant documents found in the local tree index.
Thought: The first search yielded no results. I will broaden my search terms to see if the information falls under a wider category.
Action: search_tree("[Broader alternative search query]")
Observation: No relevant documents found in the local tree index.
Thought: I have searched multiple times using different keyword variations, but the observation shows no relevant documents exist in the database. I will use the escape hatch and inform the user.
Final Answer: দুঃখিত, আমার বর্তমান ডাটাবেসে এই নির্দিষ্ট বিষয়ের কোনো সরকারি নীতিমালা বা তথ্য সংরক্ষিত নেই।
"""

# ==========================================
# 1. ADAPTER FUNCTIONS (Placeholders)
# ==========================================

async def get_system_a_response(query: str):
    """Adapter for your Elasticsearch Hybrid Agent."""
    
    # 1. Initialize prompt with only the current test query
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT_ES}]
    messages.append({"role": "user", "content": query})
    
    is_resolved = False
    executed_actions = set()
    safety_breaker = 0
    
    final_answer_text = ""
    all_retrieved_chunks = [] # This is critical for DeepEval
    
    # --- SILENT AUTONOMOUS LOOP ---
    while not is_resolved:
        safety_breaker += 1
        if safety_breaker > 15:
            final_answer_text = "System Failsafe Triggered: Agent exceeded safe computation limits."
            break

        try:
            # We use stream=False here because we don't need UI updates during an evaluation
            response = await vllm_client.chat.completions.create(
                model="qwen35",
                messages=messages,
                max_tokens=4096,
                temperature=0.1, 
                stream=False, # Changed for speed
                stop=["Observation:"]
            )
            
            agent_output = response.choices[0].message.content
            
            # Guardrail Check
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                final_answer_text = "দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"
                break

            # Final Answer Check
            if re.search(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output):
                # Split the text to extract ONLY the final Bengali string, leaving the 'Thoughts' behind
                split_text = re.split(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output)
                if len(split_text) > 1:
                    final_answer_text = split_text[-1].strip()
                else:
                    final_answer_text = agent_output.strip()
                break

            # Tool Interceptor
            action_match = re.search(r"Action:\s*(\w+)\([\'\"]?(.*?)[\'\"]?\)", agent_output)
            if action_match:
                tool_name = action_match.group(1)
                search_query = action_match.group(2)
                full_action_string = action_match.group(0).lower()
                
                if full_action_string in executed_actions:
                    obs_text = "System Warning: You just executed this exact search. Do not repeat failed searches."
                else:
                    executed_actions.add(full_action_string)

                    if tool_name in ["hybrid_search", "vector_search", "search", "exact_keyword_search", "lexical_search"]:
                        
                        # Execute Search
                        query_vector = await asyncio.to_thread(get_query_embedding, search_query)
                        
                        # Custom search body to extract raw chunks for the evaluator
                        search_body = {
                            "knn": {"field": "chunk_vector", "query_vector": query_vector, "k": 5, "num_candidates": 50, "boost": 0.5},
                            "query": {"match": {"chunk_text": {"query": search_query, "boost": 1.5}}},
                            "size": 5,
                            "_source": ["chunk_text"]
                        }
                        
                        es_resp = await asyncio.to_thread(es.search, index=INDEX_NAME, body=search_body)
                        hits = es_resp["hits"]["hits"]
                        
                        # Extract chunks and add to our master list
                        raw_chunks = [hit["_source"].get("chunk_text", "") for hit in hits]
                        all_retrieved_chunks.extend(raw_chunks) 
                        
                        obs_text = "\n\n".join(raw_chunks)
                        if not obs_text.strip():
                            obs_text = "No relevant government documents found."
                    
                    elif tool_name == "no_tool_needed":
                        obs_text = "No search required. Proceed to answer."
                    else:
                        obs_text = f"Error: Tool '{tool_name}' not recognized."
                
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": f"Observation: {obs_text}\n\nIf you have the answer, output 'Final Answer:'. If not, expand your query and use another Action."})
            else:
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": "System Error: You must format your response with exactly 'Action: tool_name(\"query\")' or 'Final Answer:'."})

        except Exception as e:
            final_answer_text = f"Agent Loop Error: {str(e)}"
            break

    return final_answer_text, all_retrieved_chunks

async def get_system_b_response(query: str):
    """Adapter for your Tree-Index BM25 Agent."""
    
    # Note: Ensure you define MASTER_SYSTEM_PROMPT_B differently if your prompts 
    # for System A and B have different tool instructions.
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT_TREE}] 
    messages.append({"role": "user", "content": query})
    
    is_resolved = False
    executed_actions = set()
    safety_breaker = 0
    
    final_answer_text = ""
    all_retrieved_chunks = [] # Captured for DeepEval's Faithfulness Metric
    
    # --- SILENT AUTONOMOUS LOOP ---
    while not is_resolved:
        safety_breaker += 1
        if safety_breaker > 15:
            final_answer_text = "System Failsafe Triggered: Agent exceeded safe computation limits."
            break

        try:
            # stream=False for high-speed evaluation execution
            response = await vllm_client.chat.completions.create(
                model="qwen35",
                messages=messages,
                max_tokens=4096,
                temperature=0.1, 
                stream=False, 
                stop=["Observation:"]
            )
            
            agent_output = response.choices[0].message.content
            
            # Guardrail Check
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                final_answer_text = "দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"
                break

            # Final Answer Check
            if re.search(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output):
                split_text = re.split(r"(?i)\**final answer:?\**|\**উত্তর:\**", agent_output)
                if len(split_text) > 1:
                    final_answer_text = split_text[-1].strip()
                else:
                    final_answer_text = agent_output.strip()
                break

            # Tool Interceptor
            action_match = re.search(r"Action:\s*(\w+)\([\'\"]?(.*?)[\'\"]?\)", agent_output)
            if action_match:
                tool_name = action_match.group(1)
                search_query = action_match.group(2)
                full_action_string = action_match.group(0).lower()
                
                if full_action_string in executed_actions:
                    obs_text = "System Warning: You just executed this exact search. Do not repeat failed searches."
                else:
                    executed_actions.add(full_action_string)

                    if tool_name in ["search_tree", "search", "hybrid_search"]:
                        
                        # --- INLINE TREE SEARCH LOGIC ---
                        if not bm25 or not toc:
                            obs_text = "Error: Tree database not loaded."
                        else:
                            tokenized_query = tokenize(search_query)
                            top_nodes = bm25.get_top_n(tokenized_query, toc, n=5)
                            
                            if not top_nodes:
                                obs_text = "No relevant documents found in the local tree index."
                            else:
                                selected_ids = [n['node_id'] for n in top_nodes]
                                raw_full_texts = []
                                for node in all_nodes:
                                    if str(node.get('node_id', '')) in selected_ids:
                                        raw_full_texts.append(f"Source: {node.get('title', 'Unknown')}\n{node.get('text', '')}")
                                        
                                combined_raw_text = "\n\n".join(raw_full_texts)
                                text_chunks = chunk_text(combined_raw_text, chunk_size=2000, overlap=300)
                                
                                # Sub-chunking and extracting raw arrays for the evaluator
                                if len(text_chunks) > 3:
                                    chunk_corpus = [tokenize(chunk) for chunk in text_chunks]
                                    chunk_bm25 = BM25Okapi(chunk_corpus)
                                    best_chunks = chunk_bm25.get_top_n(tokenized_query, text_chunks, n=3)
                                else:
                                    best_chunks = text_chunks
                                    
                                all_retrieved_chunks.extend(best_chunks)
                                obs_text = "\n\n...[text omitted]...\n\n".join(best_chunks)
                    else:
                        obs_text = f"Error: Tool '{tool_name}' not recognized. Please use 'search_tree'."
                
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": f"Observation: {obs_text}\n\nIf you have the answer, output 'Final Answer:'. If not, expand your query and use another Action."})
            else:
                messages.append({"role": "assistant", "content": agent_output})
                messages.append({"role": "user", "content": "System Error: You must format your response with exactly 'Action: tool_name(\"query\")' or 'Final Answer:'."})

        except Exception as e:
            final_answer_text = f"Agent Loop Error: {str(e)}"
            break

    return final_answer_text, all_retrieved_chunks
async def judge_systems_head_to_head(query: str, ans_a: str, ans_b: str) -> str:
    """Asks the local vLLM to compare both answers and declare a winner."""
    
    # If both agents crashed or gave the guardrail, it's an automatic tie
    if "Agent Loop Error" in ans_a and "Agent Loop Error" in ans_b:
        return "Tie (Both Failed)"
        
    prompt = f"""
    You are an impartial, expert AI judge evaluating two government assistant systems.
    
    User Query: "{query}"
    
    System A Answer: "{ans_a}"
    
    System B Answer: "{ans_b}"
    
    Evaluate which system provided a better, more accurate, and more formal Bengali response.
    Penalize any response that contains system errors (like "Agent Loop Error") or hallucinations.
    
    You must respond STRICTLY with exactly one of these three options and absolutely nothing else:
    System A
    System B
    Tie
    """
    
    try:
        response = await vllm_client.chat.completions.create(
            model="qwen35",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0, # 0.0 makes the judge strict and deterministic
            max_tokens=10
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Judge Error: {str(e)}"
# ==========================================
# 2. EVALUATION PIPELINE
# ==========================================

async def run_evaluation():
    # 1. Load the Golden Dataset
    input_csv = "queries.csv"
    output_csv = "evaluated_queries.csv"
    df = pd.read_csv(input_csv)
    
    # Initialize new columns to store the final answers so you can read them in the CSV
    df["sys_a_actual_answer"] = ""
    df["sys_b_actual_answer"] = ""

    print("[*] Initializing DeepEval Metrics...")
    # Note: Ensure you have an LLM available (e.g., OPENAI_API_KEY set) to act as the judge
    print("[*] Initializing DeepEval Metrics...")
    
    # 1. Instantiate your custom local judge
    local_judge = LocalVLLMJudge(model_name="qwen35", base_url="http://localhost:5000/v1")

    # 2. Pass the `local_judge` object to the metrics instead of the string!
    ans_relevancy = AnswerRelevancyMetric(threshold=0.7, model=local_judge)
    faithfulness = FaithfulnessMetric(threshold=0.7, model=local_judge)
    context_relevancy = ContextualRelevancyMetric(threshold=0.7, model=local_judge)
    
    metrics_to_run = [ans_relevancy, faithfulness, context_relevancy]

    test_cases_a = []
    test_cases_b = []
    
    print(f"[*] Processing {len(df)} test cases to gather outputs...")
    for index, row in df.iterrows():
        query = row['queries']
        expected = row.get('expected_answer', None)
        if pd.isna(expected):
            expected = None 
        else:
            expected = str(expected)
        
        # Run System A
        ans_a, ctx_a = await get_system_a_response(query)
        df.at[index, "sys_a_actual_answer"] = ans_a
        test_cases_a.append(LLMTestCase(
            input=query,
            actual_output=sanitize_text_for_json(ans_a),
            expected_output=expected,
            retrieval_context=sanitize_text_for_json(ctx_a)
        ))
        
        # Run System B
        ans_b, ctx_b = await get_system_b_response(query)
        df.at[index, "sys_b_actual_answer"] = ans_b
        test_cases_b.append(LLMTestCase(
            input=query,
            actual_output=sanitize_text_for_json(ans_b),
            expected_output=expected,
            retrieval_context=sanitize_text_for_json(ctx_b)
        ))

   
    
    # 3 & 4. Execute Evaluations and Map Scores to CSV Manually
    print("\n🚀 RUNNING SYSTEM A (ELASTICSEARCH) EVALUATION...")
    for index, test_case in enumerate(test_cases_a):
        print(f"  -> Grading System A query {index + 1}...")
        for metric in metrics_to_run:
            column_name = f"sys_a_{metric.__name__}_score"
            try:
                await metric.a_measure(test_case)
                df.at[index, column_name] = metric.score
            except Exception as e:
                print(f"    [!] Error on metric {metric.__name__}: {e}")
                df.at[index, column_name] = "JSON_Error"

    print("\n🌳 RUNNING SYSTEM B (TREE-INDEX) EVALUATION...")
    for index, test_case in enumerate(test_cases_b):
        print(f"  -> Grading System B query {index + 1}...")
        for metric in metrics_to_run:
            column_name = f"sys_b_{metric.__name__}_score"
            try:
                await metric.a_measure(test_case)
                df.at[index, column_name] = metric.score
            except Exception as e:
                print(f"    [!] Error on metric {metric.__name__}: {e}")
                df.at[index, column_name] = "JSON_Error"

    # Add the Head-to-Head Judge if you are using it!
    print("\n⚖️ RUNNING HEAD-TO-HEAD PAIRWISE JUDGE...")
    df["vLLM_Winner"] = ""
    for index, row in df.iterrows():
        query = row['queries']
        ans_a = df.at[index, 'sys_a_actual_answer']
        ans_b = df.at[index, 'sys_b_actual_answer']
        
        print(f"  -> Judging Matchup {index + 1}...")
        winner = await judge_systems_head_to_head(query, ans_a, ans_b)
        df.at[index, "vLLM_Winner"] = winner

    # 5. Save the updated DataFrame
    df.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"[+] Evaluation complete! Results saved to: {output_csv}")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
    
