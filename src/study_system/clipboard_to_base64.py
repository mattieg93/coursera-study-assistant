#!/usr/bin/env python3
"""
Helper script to convert clipboard image to base64 for pasting into Streamlit.

Usage:
1. Take a screenshot (Cmd+Shift+Ctrl+4 on Mac - copies to clipboard)
2. Run: python clipboard_to_base64.py
3. Paste the output into the Streamlit "Paste from Clipboard" tab
"""

import sys

try:
    from PIL import ImageGrab
    import base64
    import io
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
    from PIL import ImageGrab
    import base64
    import io

def get_clipboard_image_as_base64():
    """Get image from clipboard and convert to base64."""
    try:
        # Get image from clipboard
        img = ImageGrab.grabclipboard()
        
        if img is None or not hasattr(img, 'save'):
            print("❌ No image found in clipboard!")
            print("\n💡 Tips:")
            print("   - Take a screenshot: Cmd+Shift+Ctrl+4 (copies to clipboard)")
            print("   - Or copy an image file: Cmd+C on an image")
            return None
        
        # Type assertion for type checker
        from PIL import Image
        assert isinstance(img, Image.Image), "Clipboard content is not an image"
        
        # Convert to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_bytes = buffer.getvalue()
        
        # Encode to base64
        b64_string = base64.b64encode(img_bytes).decode('utf-8')
        
        print("✅ Image converted successfully!")
        print("\n📋 Copy the text below and paste it into Streamlit:\n")
        print("-" * 80)
        print(b64_string)
        print("-" * 80)
        print(f"\n✓ Image size: {len(img_bytes)} bytes")
        print(f"✓ Dimensions: {img.size[0]}x{img.size[1]} pixels")
        
        return b64_string
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None

if __name__ == "__main__":
    get_clipboard_image_as_base64()
