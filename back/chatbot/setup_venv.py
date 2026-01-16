#!/usr/bin/env python
"""Script to setup virtual environment and install dependencies"""
import os
import subprocess
import sys

def main():
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_path = os.path.join(script_dir, 'venv')
    requirements_path = os.path.join(script_dir, 'requirements.txt')
    
    print(f"Script directory: {script_dir}")
    print(f"Venv path: {venv_path}")
    
    # Create virtual environment
    if not os.path.exists(venv_path):
        print("Creating virtual environment...")
        subprocess.run([sys.executable, '-m', 'venv', venv_path], check=True)
        print("Virtual environment created!")
    else:
        print("Virtual environment already exists")
    
    # Determine pip path
    if os.name == 'nt':  # Windows
        pip_path = os.path.join(venv_path, 'Scripts', 'pip.exe')
        python_path = os.path.join(venv_path, 'Scripts', 'python.exe')
    else:
        pip_path = os.path.join(venv_path, 'bin', 'pip')
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    # Install requirements
    if os.path.exists(requirements_path):
        print(f"Installing requirements from {requirements_path}...")
        subprocess.run([pip_path, 'install', '-r', requirements_path], check=True)
        print("Requirements installed!")
    else:
        print(f"Warning: {requirements_path} not found")
    
    print("\nSetup complete!")
    print(f"To activate the virtual environment, run:")
    print(f"  Windows: {venv_path}\\Scripts\\activate")
    print(f"  Linux/Mac: source {venv_path}/bin/activate")

if __name__ == '__main__':
    main()

