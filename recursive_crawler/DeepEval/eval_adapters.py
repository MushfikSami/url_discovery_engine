# eval_adapters.py

import sys
import os
import asyncio
import re

# Ensure the parent directory is in the path to import your app files
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from elasticsearch import Elasticsearch
from rank_bm25 import BM25Okapi

# Import your custom agent tools
from elastic_search_engine.es_engine import get_query_embedding,retrieve_context
from agent.app import bm25, toc, tokenize, all_nodes, chunk_text

# Import our modularized config and helpers
from eval_config import INDEX_NAME, MASTER_SYSTEM_PROMPT_ES, MASTER_SYSTEM_PROMPT_TREE
from eval_helpers import vllm_client

# Initialize Elasticsearch
es = Elasticsearch("http://localhost:9200")


async def get_system_a_response(query: str):
    """Adapter for your Elasticsearch Hybrid Agent."""
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT_ES}]
    messages.append({"role": "user", "content": query})
    
    is_resolved = False
    executed_actions = set()
    safety_breaker = 0
    final_answer_text = ""
    all_retrieved_chunks = [] 
    
    while not is_resolved:
        safety_breaker += 1
        if safety_breaker > 15:
            final_answer_text = "System Failsafe Triggered: Agent exceeded safe computation limits."
            break

        try:
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
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                final_answer_text = "দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"
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

                    if tool_name in ["hybrid_search", "vector_search", "search", "exact_keyword_search", "lexical_search"]:
                        
                        # ১. ভেক্টর তৈরি
                        query_vector = await asyncio.to_thread(get_query_embedding, search_query)
                        
                        # ২. নতুন মডিউলার ফাংশন দিয়ে ডাটাবেস থেকে সার্চ 
                        obs_text, new_sources = await asyncio.to_thread(retrieve_context, search_query, query_vector)
                        
                        # ৩. DeepEval এর জন্য চাংকগুলো সেভ করা
                        if obs_text.strip():
                            all_retrieved_chunks.append(obs_text)
                        else:
                            obs_text = "No relevant government documents found for this exact query. Try a different search term."
                            
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
    messages = [{"role": "system", "content": MASTER_SYSTEM_PROMPT_TREE}] 
    messages.append({"role": "user", "content": query})
    
    is_resolved = False
    executed_actions = set()
    safety_breaker = 0
    final_answer_text = ""
    all_retrieved_chunks = [] 
    
    while not is_resolved:
        safety_breaker += 1
        if safety_breaker > 15:
            final_answer_text = "System Failsafe Triggered: Agent exceeded safe computation limits."
            break

        try:
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
            if "দুঃখিত, সরকারি নীতিমালার আওতায়" in agent_output:
                final_answer_text = "দুঃখিত, সরকারি নীতিমালার আওতায় এ ধরনের ক্ষতিকর, বেআইনি বা অনৈতিক তথ্য প্রদান করা সম্পূর্ণ নিষিদ্ধ।"
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