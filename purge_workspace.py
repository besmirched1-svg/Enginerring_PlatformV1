import os
import shutil
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("engine.maintenance")

API_STATUS_URL = "http://localhost:8000/improve/status/hemp_roller"
ARCHIVE_ROOT = "output/revisions/hemp_roller"

def clean_obsolete_assets():
    logger.info("Initializing disk storage optimization sweep...")
    
    # 1. Fetch current elite champion metadata to protect key design assets
    try:
        response = requests.get(API_STATUS_URL, timeout=5)
        if response.status_code != 200:
            logger.error(f"Maintenance aborted. Cloud cluster unavailable: {response.status_code}")
            return
        data = response.json()
    except Exception as e:
        logger.error(f"Critical port block. Unable to resolve current design champion: {str(e)}")
        return
        
    champion_data = data.get("champion", {})
    champion_rev_dir = champion_data.get("revision", "v0")
    
    # Extract the absolute folder directory identifier name
    protected_dir_name = os.path.basename(os.path.normpath(champion_rev_dir))
    logger.info(f"Active Champion identified: [{protected_dir_name}]. Securing files from deletion.")
    
    if not os.path.exists(ARCHIVE_ROOT):
        logger.info("No physical model revision history files found on local storage nodes. Sweep complete.")
        return
        
    purged_count = 0
    # 2. Iterate through archival directories to delete obsolete data logs
    for folder in os.listdir(ARCHIVE_ROOT):
        folder_path = os.path.join(ARCHIVE_ROOT, folder)
        
        if not os.path.isdir(folder_path):
            continue
            
        # Permanent Maintenance Rule: Never delete the active champion profile
        if folder == protected_dir_name or folder == "v0":
            logger.info(f" -> Retaining asset profile: {folder}")
            continue
            
        try:
            logger.warning(f" -> Purging obsolete design revision footprint: {folder}")
            shutil.rmtree(folder_path)
            purged_count += 1
        except Exception as e:
            logger.error(f"Failed to drop target allocation block {folder}: {str(e)}")
            
    logger.info(f"Storage clean up complete! Forcefully recycled {purged_count} obsolete iteration layers.")

if __name__ == '__main__':
    clean_obsolete_assets()
