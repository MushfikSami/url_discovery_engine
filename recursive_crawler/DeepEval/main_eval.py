# main_eval.py

import os
import asyncio
import pandas as pd

# DeepEval Imports
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, ContextualRelevancyMetric
from deepeval.test_case import LLMTestCase

# Custom Imports from your modularized files
from eval_helpers import LocalVLLMJudge, sanitize_text_for_json, judge_systems_head_to_head
from eval_adapters import get_system_a_response, get_system_b_response


async def run_evaluation():
    # 1. Load the Golden Dataset
    input_csv = "queries.csv"
    output_csv = "evaluated_queries.csv"
    df = pd.read_csv(input_csv)
    
    # Initialize new columns
    df["sys_a_actual_answer"] = ""
    df["sys_b_actual_answer"] = ""

    print("[*] Initializing DeepEval Metrics...")
    
    # Instantiate custom local judge
    local_judge = LocalVLLMJudge(model_name="qwen35", base_url="http://localhost:5000/v1")

    # Initialize Metrics
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
        
        # --- Run System A ---
        ans_a, ctx_a = await get_system_a_response(query)
        df.at[index, "sys_a_actual_answer"] = ans_a
        test_cases_a.append(LLMTestCase(
            input=query,
            actual_output=sanitize_text_for_json(ans_a),
            expected_output=expected,
            retrieval_context=sanitize_text_for_json(ctx_a)
        ))
        
        # --- Run System B ---
        ans_b, ctx_b = await get_system_b_response(query)
        df.at[index, "sys_b_actual_answer"] = ans_b
        test_cases_b.append(LLMTestCase(
            input=query,
            actual_output=sanitize_text_for_json(ans_b),
            expected_output=expected,
            retrieval_context=sanitize_text_for_json(ctx_b)
        ))

    # --- Execute DeepEval Grading ---
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

    # --- Execute Head-to-Head Pairwise Judge ---
    print("\n⚖️ RUNNING HEAD-TO-HEAD PAIRWISE JUDGE...")
    df["vLLM_Winner"] = ""
    for index, row in df.iterrows():
        query = row['queries']
        ans_a = df.at[index, 'sys_a_actual_answer']
        ans_b = df.at[index, 'sys_b_actual_answer']
        
        print(f"  -> Judging Matchup {index + 1}...")
        winner = await judge_systems_head_to_head(query, ans_a, ans_b)
        df.at[index, "vLLM_Winner"] = winner

    # --- Save Results ---
    df.to_csv(output_csv, index=False, encoding="utf-8")
    print(f"[+] Evaluation complete! Results saved to: {output_csv}")

if __name__ == "__main__":
    # Disable telemetry to prevent connection errors
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
    asyncio.run(run_evaluation())