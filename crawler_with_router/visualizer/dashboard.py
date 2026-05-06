import gradio as gr
import requests
import json
import base64

# --- Configuration ---
API_BASE_URL = "http://localhost:8001/api"

def fetch_domain_list():
    """Fetches the master list once on boot and stores it in server RAM."""
    try:
        print("📥 Caching master domain list into server memory...")
        response = requests.get(f"{API_BASE_URL}/domains")
        if response.status_code == 200:
            return response.json().get("domains", [])
    except Exception as e:
        print(f"⚠️ Warning: Could not fetch domains. Error: {e}")
    return ["teachers.gov.bd", "moa.gov.bd", "sreda.gov.bd"] # Fallbacks

# Load all 40k domains into a Python list (Fast & uses negligible RAM)
MASTER_DOMAIN_LIST = fetch_domain_list()
# Grab 10 default domains to show when the app first loads
DEFAULT_DOMAINS = MASTER_DOMAIN_LIST[:10] if len(MASTER_DOMAIN_LIST) >= 10 else MASTER_DOMAIN_LIST

def filter_domains(search_query):
    """
    Searches the 40k memory list instantly and returns only the top 15 matches.
    This prevents the user's browser from crashing!
    """
    if not search_query:
        return gr.update(choices=DEFAULT_DOMAINS, value=DEFAULT_DOMAINS[0] if DEFAULT_DOMAINS else None)
    
    search_query = search_query.lower()
    matches = [d for d in MASTER_DOMAIN_LIST if search_query in d.lower()]
    
    # Cap the results at 15 so the browser never freezes
    top_matches = matches[:15]
    
    if top_matches:
        return gr.update(choices=top_matches, value=top_matches[0])
    else:
        return gr.update(choices=["No matches found..."], value="No matches found...")

def generate_tree_html(domain_query):
    """Fetches data from FastAPI and generates an injected HTML ECharts visual."""
    if not domain_query or domain_query == "No matches found...":
        return "<div style='color: #ef4444; padding: 20px;'>Please select a valid domain.</div>"

    domain_to_search = domain_query.strip()

    try:
        response = requests.get(f"{API_BASE_URL}/tree/{domain_to_search}")
        
        if response.status_code == 200:
            tree_data = response.json()
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"></script>
                <style>
                    body {{ margin: 0; padding: 0; background-color: #0f172a; height: 100vh; overflow: hidden; }}
                    #main {{ width: 100%; height: 100%; }}
                </style>
            </head>
            <body>
                <div id="main"></div>
                <script>
                    var chartDom = document.getElementById('main');
                    var myChart = echarts.init(chartDom, 'dark');
                    var treeData = {json.dumps(tree_data)};
                    
                    var option = {{
                        backgroundColor: '#0f172a',
                        tooltip: {{ trigger: 'item', triggerOn: 'mousemove' }},
                        series: [
                            {{
                                type: 'tree',
                                data: [treeData],
                                top: '5%', left: '10%', bottom: '5%', right: '20%',
                                symbolSize: 10,
                                label: {{ position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 14, color: '#e2e8f0' }},
                                leaves: {{ label: {{ position: 'right', verticalAlign: 'middle', align: 'left', color: '#94a3b8' }} }},
                                emphasis: {{ focus: 'descendant' }},
                                expandAndCollapse: true,
                                initialTreeDepth: 2,
                                animationDuration: 550,
                                animationDurationUpdate: 750
                            }}
                        ]
                    }};
                    myChart.setOption(option);
                    window.addEventListener('resize', function() {{ myChart.resize(); }});
                </script>
            </body>
            </html>
            """
            b64_html = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
            return f'<iframe src="data:text/html;base64,{b64_html}" width="100%" height="750px" style="border:none; border-radius: 8px;"></iframe>'
            
        elif response.status_code == 404:
             return f"<div style='color: #ef4444; padding: 20px;'>Domain '{domain_to_search}' not found in the database.</div>"
        else:
             return f"<div style='color: #ef4444; padding: 20px;'>API Error: {response.status_code} - {response.text}</div>"
            
    except requests.exceptions.ConnectionError:
        return "<div style='color: #ef4444; padding: 20px;'>🚨 Could not connect to the API. Is your FastAPI server running?</div>"

# --- Gradio UI Layout ---
with gr.Blocks() as demo:
    gr.Markdown("# 🕸️ Gov Spider: Domain Taxonomy Explorer")
    gr.Markdown(f"Database contains **{len(MASTER_DOMAIN_LIST):,}** verified domains. Use the search bar to find a specific website.")
    
    with gr.Row():
        with gr.Column(scale=2):
            search_box = gr.Textbox(label="🔍 Type to Search Domains (e.g., 'solar', 'education')", placeholder="Search...")
        with gr.Column(scale=2):
            domain_dropdown = gr.Dropdown(
                choices=DEFAULT_DOMAINS, 
                value=DEFAULT_DOMAINS[0] if DEFAULT_DOMAINS else None,
                label="Select Matching Domain", 
                interactive=True,
                allow_custom_value=True
            )
        with gr.Column(scale=1):
            # Added a little margin to align the button with the text boxes
            gr.HTML("<div style='height: 28px;'></div>") 
            generate_button = gr.Button("Generate Tree", variant="primary")
            
    output_html = gr.HTML(label="Visualization Engine")
    
    # --- Event Wiring ---
    # 1. As the user types in the search box, update the dropdown instantly!
    search_box.change(fn=filter_domains, inputs=search_box, outputs=domain_dropdown)
    
    # 2. When the user clicks the button OR changes the dropdown, generate the tree!
    domain_dropdown.change(fn=generate_tree_html, inputs=domain_dropdown, outputs=output_html)
    generate_button.click(fn=generate_tree_html, inputs=domain_dropdown, outputs=output_html)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=8502, share=True)