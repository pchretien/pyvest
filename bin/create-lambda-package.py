#!/usr/bin/env python3
"""
Script to create a Lambda deployment package for PyVest.
This script handles creating the package directory, installing dependencies,
copying the code, and creating the ZIP file.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

def main():
    # Get the bin directory (where this script is located)
    bin_dir = Path(__file__).parent.absolute()
    # Get the project root directory (parent of bin)
    project_root = bin_dir.parent.absolute()
    lambda_package_dir = project_root / "lambda-package"
    zip_file = bin_dir / "pyvest-lambda.zip"
    
    print("🚀 Creating Lambda deployment package...")
    print(f"   Project root: {project_root}")
    print(f"   Bin directory: {bin_dir}")
    
    # Step 1: Create lambda-package directory
    print("\n1. Creating lambda-package directory...")
    if lambda_package_dir.exists():
        print(f"   Directory exists, cleaning: {lambda_package_dir}")
        shutil.rmtree(lambda_package_dir)
    lambda_package_dir.mkdir(exist_ok=True)
    print(f"   ✓ Created: {lambda_package_dir}")
    
    # Step 2: Install dependencies
    print("\n2. Installing dependencies...")
    requirements_file = project_root / "requirements.txt"
    if not requirements_file.exists():
        print(f"   ✗ Error: {requirements_file} not found!")
        sys.exit(1)
    
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-user",
        "-r", str(requirements_file),
        "-t", str(lambda_package_dir)
    ]
    
    try:
        subprocess.run(cmd, check=True, cwd=project_root)
        print("   ✓ Dependencies installed")
    except subprocess.CalledProcessError as e:
        print(f"   ✗ Error installing dependencies: {e}")
        sys.exit(1)
    
    # Step 3: Copy Python source files from src directory
    print("\n3. Copying Python source files from src/...")
    src_dir = project_root / "src"
    source_files = ["pyvest.py", "harvest_processor.py", "s3_event_handler.py"]
    
    if not src_dir.exists():
        print(f"   ✗ Error: {src_dir} directory not found!")
        sys.exit(1)
    
    for source_file in source_files:
        source_path = src_dir / source_file
        if not source_path.exists():
            print(f"   ✗ Error: {source_path} not found!")
            sys.exit(1)
        
        shutil.copy2(source_path, lambda_package_dir / source_file)
        print(f"   ✓ Copied: {source_file}")
    
    # Step 4: Create ZIP file
    print("\n4. Creating ZIP file...")
    if zip_file.exists():
        zip_file.unlink()
        print(f"   Removed old ZIP file")
    
    shutil.make_archive(str(bin_dir / "pyvest-lambda"), 'zip', lambda_package_dir)
    zip_size = zip_file.stat().st_size / (1024 * 1024)  # Size in MB
    print(f"   ✓ Created: {zip_file} ({zip_size:.2f} MB)")
    
    print("\n✅ Lambda package created successfully!")
    print(f"\n   Next steps:")
    print(f"   1. Upload {zip_file.name} to AWS Lambda")
    print(f"   2. Set handler to: pyvest.lambda_handler")
    print(f"   3. Configure environment variables (see README.md)")

if __name__ == "__main__":
    main()

