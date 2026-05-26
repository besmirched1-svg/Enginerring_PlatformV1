import os
import sys
import json
import subprocess
from pathlib import Path

STATE_FILE = ".controller_state.json"

def get_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"current_phase": "PHASE 1", "approval_pending": False}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def extract_json(text):
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try block extraction
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None

def ingest(file_path):
    if not os.path.exists(file_path):
        print(f"Error: Input file {file_path} not found.")
        sys.exit(1)
        
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()
        
    data = extract_json(raw_content)
    if not data or "file" not in data or "content" not in data:
        print("Error: Could not extract valid Phase 4 JSON payload.")
        sys.exit(1)
        
    target_file = data["file"]
    content = data["content"]
    
    # Path safety check
    if os.path.isabs(target_file) or ".." in target_file:
        print("Security Error: Absolute paths or traversal not allowed.")
        sys.exit(5)
        
    # Create directory if missing
    Path(target_file).parent.mkdir(parents=True, exist_ok=True)
    
    # Backup existing
    if os.path.exists(target_file):
        backup_path = f"{target_file}.bak"
        with open(backup_path, 'w', encoding='utf-8') as b:
            with open(target_file, 'r', encoding='utf-8') as original:
                b.write(original.read())
        print(f"Backup created at: {backup_path}")
        
    # Write payload
    with open(target_file, 'w', encoding='utf-8', newline='\n') as out:
        out.write(content)
    print(f"Successfully wrote payload to: {target_file}")
    
    # Validation check
    if target_file.endswith('.py'):
        res = subprocess.run([sys.executable, "-m", "py_compile", target_file], capture_output=True)
        if res.returncode != 0:
            print(f"Validation Failed! Python syntax error in {target_file}")
            if os.path.exists(f"{target_file}.bak"):
                os.replace(f"{target_file}.bak", target_file)
                print("Rolled back to working backup.")
            sys.exit(1)
        print("Validation Passed: Python syntax is clean.")
        
    state = get_state()
    state["current_phase"] = "PHASE 5"
    save_state(state)

def approve():
    state = get_state()
    print(f"Advancing from state: {state['current_phase']}")
    state["current_phase"] = "PHASE 6"
    save_state(state)
    print("State advanced. System ready for next entry.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_controller.py [ingest <file> | approve]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "ingest" and len(sys.argv) == 3:
        ingest(sys.argv[2])
    elif cmd == "approve":
        approve()
    else:
        print("Unknown command layout.")
