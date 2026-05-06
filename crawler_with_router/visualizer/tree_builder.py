from urllib.parse import urlparse
import json

def build_site_tree(domain, url_list):
    """
    Takes a base domain and a list of flat URLs, and returns a nested 
    JSON structure formatted perfectly for ECharts or D3.js.
    """
    # 1. We use a dictionary to build the nested paths efficiently
    tree_dict = {}

    for url in url_list:
        parsed = urlparse(url)
        # Extract just the path, remove leading/trailing slashes
        path = parsed.path.strip('/')
        
        # If the URL is just the homepage (no path), skip the parsing loop
        if not path:
            continue
            
        parts = path.split('/')
        
        # Traverse the dictionary and create nested folders if they don't exist
        current_level = tree_dict
        for part in parts:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]

    # 2. Recursive function to convert the python dictionary into ECharts format
    def format_for_visualizer(name, node_dict):
        children = []
        for key, value in node_dict.items():
            children.append(format_for_visualizer(key, value))
        
        result = {"name": name}
        if children:
            result["children"] = children
        else:
            # If it has no children, it's a leaf node (an actual webpage)
            result["value"] = 1 
            
        return result

    # 3. Wrap the whole thing under the Root Domain
    final_tree = format_for_visualizer(domain, tree_dict)
    return final_tree

# ==========================================
# 🧪 TEST THE SCRIPT
# ==========================================
if __name__ == "__main__":
    # Simulate a fetch from your `domain_hierarchy` Postgres table
    sample_domain = "teachers.gov.bd"
    sample_urls_from_db = [
        "https://teachers.gov.bd/contents/pictures",
        "https://teachers.gov.bd/contents/documents",
        "https://teachers.gov.bd/index.php/blog/details/838726",
        "https://teachers.gov.bd/index.php/blog/details/838710",
        "https://teachers.gov.bd/profile/settings",
        "https://teachers.gov.bd/profile/security"
    ]

    # Run the transformation
    tree_json = build_site_tree(sample_domain, sample_urls_from_db)
    
    # Print the result to the console
    print(json.dumps(tree_json, indent=2))