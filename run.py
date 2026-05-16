"""
NEXUS Trading System - Production Entry Point
Compiled with PyInstaller for standalone distribution.
"""
import os
import sys
import multiprocessing
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent
    return base_path / relative_path


def main():
    multiprocessing.freeze_support()

    base_path = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

    # Set up environment
    os.environ["NEXUS_ROOT"] = str(base_path)
    os.environ["PYTHONPATH"] = str(base_path)

    # Ensure data and logs directories exist
    (base_path / "data").mkdir(exist_ok=True)
    (base_path / "logs").mkdir(exist_ok=True)

    # Load .env if present
    env_file = base_path / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)

    # Add project root to sys.path
    if str(base_path) not in sys.path:
        sys.path.insert(0, str(base_path))

    # Import and run uvicorn
    import uvicorn
    from backend.main import app

    print("=" * 60)
    print("  NEXUS Trading System v1.0.0")
    print("  Professional Cryptocurrency Trading Workstation")
    print("=" * 60)
    print()
    print("  Application: http://127.0.0.1:8000")
    print("  API Docs:    http://127.0.0.1:8000/docs")
    print("  Health:      http://127.0.0.1:8000/health")
    print()
    print("  Press Ctrl+C to stop")
    print()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
