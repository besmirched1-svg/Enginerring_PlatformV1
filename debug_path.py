import os
import sys
from pathlib import Path

# Simulate what fatigue_model.py does - assuming it's in app/digital_twin/fatigue_model.py
# current_file would be: C:\Users\chodk\openscad-engineering-platform\app\digital_twin\fatigue_model.py
current_file = os.path.abspath(os.path.join("app", "digital_twin", "fatigue_model.py"))
print(f"Simulated current file: {current_file}")

# Go up two levels: fatigue_model.py -> digital_twin -> app -> openscad-engineering-platform
parent_dir = os.path.dirname(current_file)
print(f"Parent dir (digital_twin): {parent_dir}")

grandparent_dir = os.path.dirname(parent_dir)
print(f"Grandparent dir (app): {grandparent_dir}")

great_grandparent_dir = os.path.dirname(grandparent_dir)
print(f"Great grandparent dir (openscad-engineering-platform): {great_grandparent_dir}")

# This is what gets added to sys.path in fatigue_model.py line 14
sys.path.append(great_grandparent_dir)
print(f"Added to sys.path: {great_grandparent_dir}")
print(f"Sys.path now includes: {great_grandparent_dir in sys.path}")

# Check if physics module can be found
print(f"Checking for physics module...")
try:
    import physics
    print("SUCCESS: physics module imported")
    print(f"Physics module location: {physics.__file__}")
except ImportError as e:
    print(f"FAILED: Could not import physics module: {e}")
    
    # Let's see what's in the directory
    physics_path = os.path.join(great_grandparent_dir, "physics")
    print(f"Looking for physics at: {physics_path}")
    print(f"Directory exists: {os.path.isdir(physics_path)}")
    
    if os.path.isdir(physics_path):
        files = os.listdir(physics_path)
        print(f"Files in physics directory: {files}")
        
        fatigue_path = os.path.join(physics_path, "fatigue.py")
        print(f"Looking for fatigue.py at: {fatigue_path}")
        print(f"File exists: {os.path.isfile(fatigue_path)}")