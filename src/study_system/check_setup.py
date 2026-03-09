#!/usr/bin/env python3
"""
Setup checker for Study System
Verifies all prerequisites are installed and running
"""

import sys
import subprocess
import importlib

def check_python_packages():
    """Check if required Python packages are installed"""
    print("📦 Checking Python packages...")
    required = [
        'streamlit',
        'chromadb',
        'PIL',
        'numpy',
        'cv2',
        'ollama'
    ]
    
    optional = {
        'Vision': 'Apple Vision Framework (macOS)',
        'easyocr': 'EasyOCR (fallback)'
    }
    
    missing = []
    for package in required:
        try:
            if package == 'PIL':
                importlib.import_module('PIL')
            elif package == 'cv2':
                importlib.import_module('cv2')
            else:
                importlib.import_module(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - NOT INSTALLED")
            missing.append(package)
    
    # Check optional OCR engines
    print("\n📷 OCR Engines:")
    ocr_found = False
    for package, description in optional.items():
        try:
            importlib.import_module(package)
            print(f"  ✅ {description}")
            ocr_found = True
        except ImportError:
            print(f"  ⚠️  {description} - not available")
    
    if not ocr_found:
        print("  ❌ No OCR engine found!")
        missing.append('Vision or easyocr')
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        if 'Vision or easyocr' in missing:
            print("Install EasyOCR with: pip install easyocr")
            print("Or install Vision with: pip install pyobjc-framework-Vision pyobjc-framework-Quartz")
        else:
            print(f"Install with: pip install {' '.join([p for p in missing if p != 'Vision or easyocr'])}")
        return False
    return True

def check_ollama_installed():
    """Check if Ollama is installed"""
    print("\n🤖 Checking Ollama installation...")
    try:
        result = subprocess.run(['ollama', '--version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            print(f"  ✅ Ollama installed: {result.stdout.strip()}")
            return True
        else:
            print("  ❌ Ollama not found")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("  ❌ Ollama not found")
        print("  Install from: https://ollama.ai")
        return False

def check_ollama_running():
    """Check if Ollama service is running"""
    print("\n🔄 Checking if Ollama is running...")
    try:
        result = subprocess.run(['ollama', 'ps'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            print("  ✅ Ollama service is running")
            if result.stdout.strip():
                print(f"  Running models:\n{result.stdout}")
            return True
        else:
            print("  ❌ Ollama service not running")
            print("  Start with: ollama serve")
            return False
    except subprocess.TimeoutExpired:
        print("  ❌ Ollama not responding")
        print("  Start with: ollama serve")
        return False

def check_model_installed():
    """Check if required model is installed"""
    print("\n🧠 Checking for granite3.2:8b model...")
    try:
        result = subprocess.run(['ollama', 'list'], 
                              capture_output=True, 
                              text=True, 
                              timeout=10)
        if 'granite3.2' in result.stdout:
            print("  ✅ granite3.2:8b model installed")
            return True
        else:
            print("  ❌ granite3.2:8b model not found")
            print("  Install with: ollama pull granite3.2:8b")
            return False
    except subprocess.TimeoutExpired:
        print("  ⚠️  Could not check models (timeout)")
        return False

def main():
    print("=" * 60)
    print("Study System - Setup Checker")
    print("=" * 60)
    
    checks = [
        check_python_packages(),
        check_ollama_installed(),
        check_ollama_running(),
        check_model_installed()
    ]
    
    print("\n" + "=" * 60)
    if all(checks):
        print("✅ All checks passed! You're ready to go!")
        print("\nStart the study assistant with:")
        print("  streamlit run study_chat_ui.py")
    else:
        print("⚠️  Some checks failed. Please fix the issues above.")
        sys.exit(1)
    print("=" * 60)

if __name__ == "__main__":
    main()
