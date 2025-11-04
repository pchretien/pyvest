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
    # Get the project root directory
    project_root = Path(__file__).parent.absolute()
    lambda_package_dir = project_root / "lambda-package"
    zip_file = project_root / "pyvest-lambda.zip"
    
    print("🚀 Creating Lambda deployment package...")
    print(f"   Project root: {project_root}")
    
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
    
    # Step 3: Copy pyvest.py
    print("\n3. Copying pyvest.py...")
    pyvest_file = project_root / "pyvest.py"
    if not pyvest_file.exists():
        print(f"   ✗ Error: {pyvest_file} not found!")
        sys.exit(1)
    
    shutil.copy2(pyvest_file, lambda_package_dir / "pyvest.py")
    print(f"   ✓ Copied: {pyvest_file} -> {lambda_package_dir / 'pyvest.py'}")
    
    # Step 4: Create ZIP file
    print("\n4. Creating ZIP file...")
    if zip_file.exists():
        zip_file.unlink()
        print(f"   Removed old ZIP file")
    
    shutil.make_archive(str(project_root / "pyvest-lambda"), 'zip', lambda_package_dir)
    zip_size = zip_file.stat().st_size / (1024 * 1024)  # Size in MB
    print(f"   ✓ Created: {zip_file} ({zip_size:.2f} MB)")
    
    print("\n✅ Lambda package created successfully!")
    print(f"\n   Next steps:")
    print(f"   1. Upload {zip_file.name} to AWS Lambda")
    print(f"   2. Set handler to: pyvest.lambda_handler")
    print(f"   3. Configure environment variables (see README.md)")

if __name__ == "__main__":
    main()

