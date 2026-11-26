import os
from pathlib import Path
from dotenv import load_dotenv

def load_config() -> dict:
    # Get the project root directory (where .env is located)
    # Go up from compliance/config.py to the root
    root_dir = Path(__file__).parent.parent
    env_path = root_dir / '.env'
    
    # Force load with explicit path
    load_dotenv(dotenv_path=env_path, override=True)
    
    db_url = os.getenv("SQLALCHEMY_DATABASE_URI") or "sqlite:///compliance.sqlite3"
    
    return {
        "SECRET_KEY": os.getenv("SECRET_KEY", "dev"),
        "SQLALCHEMY_DATABASE_URI": db_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "AWS_REGION": os.getenv("AWS_REGION", "us-east-1"),
        "AWS_S3_BUCKET": os.getenv("AWS_S3_BUCKET"),
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
