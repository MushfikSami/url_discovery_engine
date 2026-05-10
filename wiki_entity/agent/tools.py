import json
from knowledge_tool import QLeverWikipediaTool

# Initialize our actual local QLever database tool
# (This will load the CSV into RAM when the server starts)
kg_tool = QLeverWikipediaTool(csv_path="./data/bangladesh_bn_wiki_true_massive.csv", qlever_url="http://localhost:7005")

def search_local_wikipedia_graph(entity_name: str) -> str:
    """The actual python function executed by the LLM."""
    print(f"🔧 [TOOL TRIGGERED] Searching QLever Graph for: {entity_name}")
    # Execute the real database call
    result = kg_tool.search_entity(entity_name)
    return f"[System Observation]: {result}"

# --- Tool Dispatcher ---
def execute_tool(tool_name: str, arguments: str) -> str:
    args_dict = json.loads(arguments)
    
    if tool_name == "search_local_wikipedia_graph":
        entity = args_dict.get("entity_name", "")
        return search_local_wikipedia_graph(entity)
    else:
        return f"[System Observation]: Error - Tool {tool_name} not found."

# --- vLLM Tool Schema ---
BD_GOV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_local_wikipedia_graph",
            "description": "Searches the local Bangladesh Knowledge Graph. Input MUST be the Bengali name of the entity (e.g., 'ঢাকা', 'শেখ মুজিবুর রহমান'). Returns a list of Wikidata P-Nodes and Q-Nodes representing facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "The exact Bengali Wikipedia title of the entity to search for."
                    }
                },
                "required": ["entity_name"]
            }
        }
    }
]