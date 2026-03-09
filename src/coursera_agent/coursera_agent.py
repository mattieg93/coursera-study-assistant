import asyncio
import json
import re
import time
import subprocess
import os
from pathlib import Path
from playwright.async_api import async_playwright
import ollama
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# === CONFIG (UPDATE THESE) ===
DOC_ID = "1mvwZchayzE7jhnoIa5ZkeHJuBtXc5-_CzkmkrRq_6EM"  # From Google Doc URL
CREDENTIALS_FILE = "credentials.json"  # Service account JSON
MODEL_NAME = "granite3.2:8b"
OLLAMA_MODELS_PATH = "/Users/mattieg/Repos/ai_models"  # Custom models directory
AUTO_SELECT_TAB = True  # False = prompt user to select tab, True = auto-select last tab
PROCESS_ALL_VIDEOS = True  # False = current video only, True = iterate through remaining videos
PROCESS_READINGS = True   # False = skip Ungraded Plugin reading items, True = include them

# Configure Ollama to use custom models directory
os.environ["OLLAMA_MODELS"] = OLLAMA_MODELS_PATH

print("Coursera Agent - Production Ready")

def get_chrome_path():
    """Find Chrome/Chromium on macOS"""
    paths = [
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None

def launch_chrome_with_debugging():
    """Launch Chrome with remote debugging using a dedicated automation profile"""
    chrome_path = get_chrome_path()
    if not chrome_path:
        raise Exception("Chrome/Chromium not found. Install Chrome or Chromium.")
    
    # Use a dedicated profile for automation (won't conflict with your main browser)
    automation_profile = str(Path.home() / ".coursera-automation-profile")
    
    # Check if already running
    try:
        result = subprocess.run(["pgrep", "-f", "remote-debugging-port=9222"], 
                              capture_output=True, text=True)
        if result.stdout.strip():
            print("   ✓ Chrome already running with debugging")
            return None
    except:
        pass
    
    # Launch Chrome with debugging
    cmd = [
        chrome_path,
        f"--user-data-dir={automation_profile}",
        "--remote-debugging-port=9222",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    
    print(f"   Launching Chrome with automation profile...")
    print(f"   Note: First time? You'll need to log into Coursera once")
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)  # Wait longer for Chrome to start
    return process

async def wait_for_chrome_connection(p, max_retries=10):
    """Wait for Chrome to be ready for CDP connection"""
    for i in range(max_retries):
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            return browser
        except Exception as e:
            if i < max_retries - 1:
                print(f"   Waiting for Chrome... ({i+1}/{max_retries})")
                time.sleep(2)
            else:
                raise Exception(f"Failed to connect to Chrome after {max_retries} attempts") from e

def extract_module_name(lecture_title):
    """Extract module name from lecture title for tab matching"""
    # Remove common suffixes like "| Coursera", "- Lecture", etc.
    clean_title = lecture_title.split('|')[0].strip()
    
    # Common patterns to extract module names
    # "Advanced CNNs in Keras" -> "Advanced CNNs" or "Keras"
    # "Introduction to TensorFlow 2.x" -> "TensorFlow 2.x"
    # "Deep Learning Fundamentals" -> "Deep Learning"
    
    # Strategy: Keep the most significant technical terms
    # Remove filler words but keep technical terms
    filler_words = {'in', 'to', 'the', 'a', 'an', 'of', 'for', 'with', 'on', 'at', 'from', 'by'}
    
    words = clean_title.split()
    # Keep all words except single-word fillers at start/end
    if len(words) > 2 and words[-1].lower() in filler_words:
        words = words[:-1]
    if len(words) > 2 and words[0].lower() in filler_words:
        words = words[1:]
    
    return ' '.join(words)

def auto_select_last_tab(tabs):
    """Automatically select the last tab (highest index)"""    
    if not tabs:
        return None
    
    # Get the last tab
    last_tab = tabs[-1]
    tab_props = last_tab.get('tabProperties', {})
    tab_title = tab_props.get('title', 'Untitled')
    tab_id = tab_props.get('tabId')
    
    if not tab_id:
        return None
    
    # Get end index for last tab
    tab_content = last_tab.get('documentTab', {}).get('body', {}).get('content', [])
    if tab_content:
        end_index = tab_content[-1].get('endIndex', 1) - 1
    else:
        end_index = 1
    
    print(f"   Auto-selected last tab: '{tab_title}' (tab {len(tabs)}/{len(tabs)})")
    return (tab_id, tab_title, end_index)

def prompt_tab_selection(doc, lecture_title):
    """Interactively prompt user to select the correct tab"""
    if 'tabs' not in doc or not doc['tabs']:
        print("   ⚠️  No tabs found in document")
        return None
    
    tabs = doc['tabs']
    print(f"\n   📚 Lecture: {lecture_title}")
    print(f"   📑 Available tabs ({len(tabs)}):")
    
    tab_options = []
    for i, tab in enumerate(tabs, 1):
        tab_props = tab.get('tabProperties', {})
        tab_title = tab_props.get('title', 'Untitled')
        tab_id = tab_props.get('tabId')
        
        if tab_id:
            tab_options.append((tab_id, tab_title, tab))
            print(f"      [{i}] {tab_title}")
    
    if not tab_options:
        return None
    
    # Prompt for selection
    while True:
        try:
            choice = input(f"\n   Select tab (1-{len(tab_options)}) or press Enter for [1]: ").strip()
            
            if choice == "":
                choice = "1"
            
            idx = int(choice) - 1
            
            if 0 <= idx < len(tab_options):
                tab_id, tab_title, tab = tab_options[idx]
                
                # Get end index for selected tab
                tab_content = tab.get('documentTab', {}).get('body', {}).get('content', [])
                if tab_content:
                    end_index = tab_content[-1].get('endIndex', 1) - 1
                else:
                    end_index = 1
                
                print(f"   Selected: '{tab_title}'")
                return (tab_id, tab_title, end_index)
            else:
                print(f"   Invalid selection. Choose 1-{len(tab_options)}")
        except ValueError:
            print(f"   Invalid input. Enter a number 1-{len(tab_options)}")
        except KeyboardInterrupt:
            print("\n  Cancelled by user")
            return None

async def get_transcript(page):
    """Your DOM: rc-Transcript + phrases"""
    print("📺 1/4 Transcript...")
    try:
        # Open transcript using specific test-id
        btn = page.locator('[data-testid="lecture-transcript-tab"]')
        if await btn.count():
            await btn.click()
            await page.wait_for_timeout(3000)

        # Broad search (your screenshots)
        containers = page.locator('[class*="-Transcript"], .transcript, [role="transcript"]')
        phrases = containers.locator("span, div") if await containers.count() else page.locator("span, div")

        count = await phrases.count()
        texts = []
        for i in range(min(500, count)):
            text = await phrases.nth(i).inner_text()
            clean = re.sub(r"^\d+:\d+\s*", "", text).strip()
            if len(clean) > 8:
                texts.append(clean)

        transcript = " ".join(texts[:500])
        print(f"   ✓ {len(transcript)} chars")
        return transcript
    except Exception as e:
        print(f" {e}")
        return ""

async def granite_notes(transcript, title):
    """Generate formatted notes - clean text only, formatting applied later"""
    print(f"2/4 Granite3.2...")
    start = time.time()

    prompt = f"""You are creating professional study notes for an IBM AI Engineering certification course.

Lecture Title: {title}
Transcript: {transcript}

Create notes with this EXACT structure:

FIRST LINE - Output the title EXACTLY as provided above (including "| Coursera" if present):
{title}

Then continue with the sections below. Use plain text - NO bold markers, asterisks, or other formatting symbols:

📊 TECHNICAL SUMMARY:
[Write 2-3 clear sentences explaining the core technical concept]

Key Features of [Main Topic]:
1. [First major feature]:
   • [Detail about feature]
   • [Another detail]
2. [Second major feature]:
   • [Detail]
   • [Detail]
3. [Third major feature]:
   • [Detail]

Key Concepts:
1. [Concept name]: [Brief explanation]
2. [Concept name]: [Brief explanation]
3. [Concept name]: [Brief explanation]
4. [Concept name]: [Brief explanation]

💼 BUSINESS APPLICATION:
[2-3 sentences on real-world business value with concrete examples from 2 different industries]

CRITICAL RULES: 
- MUST start with the exact title shown above as the first line
- NO bold markers (**), asterisks (*), or formatting symbols in the content
- Use • for bullets
- Keep it concise, technical, and business-focused
- Use colons after concept names and feature titles
- END with the Business Application section - do NOT add any meta-commentary, instructions, or explanations after that
- Output ONLY the notes content, nothing else"""

    response = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
    notes = response["message"]["content"]
    
    # Verify the title appears in the first line
    first_line = notes.split('\n')[0].strip()
    if title not in first_line:
        print(f"   ⚠️ WARNING: LLM didn't include full title in first line")
        print(f"   Expected: {title}")
        print(f"   Got: {first_line}")
        print(f"   Prepending title manually...")
        notes = f"{title}\n\n{notes}"
    
    print(f"   ✓ {time.time() - start:.1f}s")
    return notes

def save_doc(doc_id, title, notes):
    """Append notes to module-specific tab (matched by title) with formatting"""
    print("💾 3/4 Doc...")
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/documents"])
        service = build("docs", "v1", credentials=creds)
        
        print(f"   Doc ID: {doc_id}")
        print(f"   Lecture: {title}")
        
        # Get document structure with tabs content
        doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
        
        end_index = None
        tab_id = None
        tab_title = None
        
        # Check if document has tabs
        if 'tabs' in doc and len(doc['tabs']) > 0:
            tabs = doc['tabs']
            
            if AUTO_SELECT_TAB:
                # Automatic last tab selection
                print(f"   Auto-selecting last tab...")
                print(f"   Available tabs: {', '.join([t.get('tabProperties', {}).get('title', 'Untitled') for t in tabs])}")
                
                match_result = auto_select_last_tab(tabs)
                
                if match_result:
                    tab_id, tab_title, end_index = match_result
                else:
                    # Fallback: prompt user to select
                    print(f"    Could not auto-select last tab")
                    print(f"   Falling back to manual selection...")
                    match_result = prompt_tab_selection(doc, title)
                    
                    if match_result:
                        tab_id, tab_title, end_index = match_result
                    else:
                        # User cancelled - use first tab as last resort
                        first_tab = tabs[0]
                        tab_id = first_tab.get('tabProperties', {}).get('tabId')
                        tab_title = first_tab.get('tabProperties', {}).get('title', 'Untitled')
                        print(f"   Using first tab: '{tab_title}'")
                        
                        tab_content = first_tab.get('documentTab', {}).get('body', {}).get('content', [])
                        if tab_content:
                            end_index = tab_content[-1].get('endIndex', 1) - 1
            else:
                # Interactive selection
                match_result = prompt_tab_selection(doc, title)
                
                if match_result:
                    tab_id, tab_title, end_index = match_result
                else:
                    # User cancelled or error - use first tab as fallback
                    first_tab = tabs[0]
                    tab_id = first_tab.get('tabProperties', {}).get('tabId')
                    tab_title = first_tab.get('tabProperties', {}).get('title', 'Untitled')
                    print(f"   Using first tab: '{tab_title}'")
                    
                    tab_content = first_tab.get('documentTab', {}).get('body', {}).get('content', [])
                    if tab_content:
                        end_index = tab_content[-1].get('endIndex', 1) - 1
        else:
            print(f"   No tabs found in document")
        
        # Fallback to main document body if still no end_index
        if end_index is None:
            print(f"   Using main document body")
            end_index = doc['body']['content'][-1]['endIndex'] - 1
        
        print(f"   Appending at index: {end_index}")
        
        # Clean content - no separators
        content = f"\n\n{notes}\n\n"
        
        print(f"   Writing {len(content)} chars at index {end_index}")
        
        # Build the requests list
        requests = []
        
        # 1. Insert the text
        insert_request = {"insertText": {"location": {"index": end_index}, "text": content}}
        if tab_id:
            insert_request["insertText"]["location"]["tabId"] = tab_id
        requests.append(insert_request)
        
        # 2. Apply formatting based on content patterns (post-processing)
        start_pos = end_index + 2  # Account for \n\n
        lines = notes.split('\n')
        current_offset = start_pos
        is_first_line = True
        
        for line in lines:
            line_len = len(line) + 1  # +1 for newline
            stripped = line.strip()
            
            if not stripped:
                current_offset += line_len
                continue
            
            # Calculate line positions
            line_start = current_offset
            line_end = current_offset + len(line.rstrip())
            
            # Pattern 1: First line (title) - Bold + larger font
            if is_first_line:
                format_request = {
                    "updateTextStyle": {
                        "range": {"startIndex": line_start, "endIndex": line_end},
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 14, "unit": "PT"}
                        },
                        "fields": "bold,fontSize"
                    }
                }
                if tab_id:
                    format_request["updateTextStyle"]["range"]["tabId"] = tab_id
                requests.append(format_request)
                is_first_line = False
            
            # Pattern 2: Emoji section headers (📊, 💼) - Bold
            elif '📊' in line or '💼' in line:
                format_request = {
                    "updateTextStyle": {
                        "range": {"startIndex": line_start, "endIndex": line_end},
                        "textStyle": {"bold": True},
                        "fields": "bold"
                    }
                }
                if tab_id:
                    format_request["updateTextStyle"]["range"]["tabId"] = tab_id
                requests.append(format_request)
            
            # Pattern 3: Section headers ending with colon (Key Features:, Key Concepts:)
            elif stripped.endswith(':') and len(stripped) > 5:
                # Check if it's a section header (not part of a numbered list)
                if not re.match(r'^\d+\.', stripped):
                    format_request = {
                        "updateTextStyle": {
                            "range": {"startIndex": line_start, "endIndex": line_end},
                            "textStyle": {"bold": True},
                            "fields": "bold"
                        }
                    }
                    if tab_id:
                        format_request["updateTextStyle"]["range"]["tabId"] = tab_id
                    requests.append(format_request)
            
            # Pattern 4: Numbered list items - bold the number and text up to first colon
            match = re.match(r'^(\d+\.)([^:]+):', stripped)
            if match:
                # Find where the colon is in the original line
                colon_pos = line.find(':', line.find(match.group(1)))
                if colon_pos > 0:
                    bold_end = line_start + colon_pos + 1  # Include the colon
                    format_request = {
                        "updateTextStyle": {
                            "range": {"startIndex": line_start, "endIndex": bold_end},
                            "textStyle": {"bold": True},
                            "fields": "bold"
                        }
                    }
                    if tab_id:
                        format_request["updateTextStyle"]["range"]["tabId"] = tab_id
                    requests.append(format_request)
            
            current_offset += line_len
        
        # Execute all requests
        result = service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        
        tab_url = f"?tab={tab_id}" if tab_id else ""
        tab_info = f" to tab '{tab_title}'" if tab_title else ""
        print(f"   Write successful{tab_info}! Check: https://docs.google.com/document/d/{doc_id}/edit{tab_url}")
    except Exception as e:
        print(f"   ERROR saving to doc: {e}")
        print(f"   Check that the service account has edit access to the doc")
        raise

async def get_video_items(page):
    """Get all video items from the current module"""
    print("📹 Finding video items...")
    try:
        # Get all list items that are videos
        items = page.locator('li:has(.outline-single-item-content-wrapper)')
        count = await items.count()
        
        video_items = []
        for i in range(count):
            item = items.nth(i)
            text = await item.inner_text()
            
            # Check if it's a video (contains "Video. Duration:" or "Video ·")
            if "Video" in text and ("Duration:" in text or "min" in text):
                video_items.append({
                    'index': i,
                    'element': item,
                    'title': text.split('Video')[0].strip()
                })
        
        print(f"   ✓ Found {len(video_items)} videos out of {count} items")
        return video_items
    except Exception as e:
        print(f"   Error finding videos: {e}")
        return []

async def get_course_items(page):
    """Get all processable items (videos + Ungraded Plugin readings) from the current module"""
    print("📋 Finding course items...")
    try:
        items = page.locator('li:has(.outline-single-item-content-wrapper)')
        count = await items.count()

        course_items = []
        for i in range(count):
            item = items.nth(i)
            text = await item.inner_text()

            if "Video" in text and ("Duration:" in text or "min" in text):
                course_items.append({
                    'index': i,
                    'element': item,
                    'title': text.split('Video')[0].strip(),
                    'type': 'video'
                })
            elif "Ungraded Plugin" in text and "Reading:" in text:
                # Extract "Reading: [TITLE]" → "[TITLE]"
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                reading_line = next((l for l in lines if l.startswith('Reading:')), None)
                title = reading_line[len('Reading:'):].strip() if reading_line else text.split('Ungraded Plugin')[0].strip()
                course_items.append({
                    'index': i,
                    'element': item,
                    'title': title,
                    'type': 'reading'
                })

        videos = sum(1 for it in course_items if it['type'] == 'video')
        readings = sum(1 for it in course_items if it['type'] == 'reading')
        print(f"   ✓ Found {videos} videos, {readings} readings ({len(course_items)} total)")
        return course_items
    except Exception as e:
        print(f"   Error finding course items: {e}")
        return []

async def get_reading_content(page):
    """Extract h1 title and body text from an Ungraded Plugin reading iframe.
    Skips 'Estimated time needed' sections entirely."""
    print("📖 1/4 Reading content...")
    try:
        # Wait briefly for iframe to settle after navigation
        await page.wait_for_timeout(2000)

        # Find the reading iframe (hosted on skills.network / cf-courses-data)
        reading_frame = None
        for frame in page.frames:
            url = frame.url
            if 'skills.network' in url or 'cf-courses-data' in url:
                reading_frame = frame
                break

        if not reading_frame:
            print("   ⚠️ No reading iframe found")
            return None, None

        await reading_frame.wait_for_load_state("domcontentloaded", timeout=20000)
        await reading_frame.wait_for_timeout(1000)

        # Extract h1 title
        h1_title = await reading_frame.evaluate("""() => {
            const h1 = document.querySelector(
                '.editormd-preview-container h1, .markdown-body h1'
            );
            return h1 ? h1.innerText.trim() : '';
        }""")

        # Extract body content, skipping 'Estimated time needed' sections
        content = await reading_frame.evaluate("""() => {
            const container = document.querySelector(
                '.editormd-preview-container, .markdown-body[previewcontainer="true"], .markdown-body'
            );
            if (!container) return '';

            const parts = [];
            let skip = false;
            const HEADINGS = new Set(['H1','H2','H3','H4','H5','H6']);

            for (const el of container.children) {
                const text = el.innerText ? el.innerText.trim() : '';
                if (!text) continue;

                const isHeading = HEADINGS.has(el.tagName);

                // Start skipping when we hit an 'Estimated time needed' heading or paragraph
                if (text.toLowerCase().includes('estimated time')) {
                    skip = true;
                    continue;
                }

                // Resume on the next heading after a skipped section
                if (skip && isHeading) {
                    skip = false;
                }

                if (!skip) {
                    parts.push(text);
                }
            }

            return parts.join('\\n\\n');
        }""")

        if not content:
            print("   ⚠️ Preview container returned empty content")
            return h1_title, None

        print(f"   ✓ h1: '{h1_title}', content: {len(content)} chars")
        return h1_title, content
    except Exception as e:
        print(f"   Error extracting reading content: {e}")
        return None, None

async def granite_reading_notes(content, h1_title):
    """Generate structured study notes from reading content using Ollama"""
    print("🤖 2/4 Granite3.2 (reading)...")
    start = time.time()

    prompt = f"""You are creating professional study notes for an IBM AI Engineering certification course.

Reading Title: {h1_title}
Reading Content:
{content}

Create notes with this EXACT structure:

FIRST LINE - Output the title EXACTLY as provided above:
{h1_title}

Then continue with the sections below. Use plain text - NO bold markers, asterisks, or other formatting symbols:

📊 TECHNICAL SUMMARY:
[Write 2-3 clear sentences explaining the core technical concept covered in this reading]

Key Features of [Main Topic]:
1. [First major feature]:
   • [Detail about feature]
   • [Another detail]
2. [Second major feature]:
   • [Detail]
   • [Detail]
3. [Third major feature]:
   • [Detail]

Key Concepts:
1. [Concept name]: [Brief explanation]
2. [Concept name]: [Brief explanation]
3. [Concept name]: [Brief explanation]
4. [Concept name]: [Brief explanation]

💼 BUSINESS APPLICATION:
[2-3 sentences on real-world business value with concrete examples from 2 different industries]

CRITICAL RULES:
- MUST start with the exact title shown above as the first line
- NO bold markers (**), asterisks (*), or formatting symbols in the content
- Use • for bullets
- Keep it concise, technical, and business-focused
- Use colons after concept names and feature titles
- END with the Business Application section - do NOT add any meta-commentary or explanations after that
- Output ONLY the notes content, nothing else"""

    response = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
    notes = response["message"]["content"]

    # Ensure title is on the first line
    first_line = notes.split('\n')[0].strip()
    if h1_title not in first_line:
        print(f"   ⚠️ WARNING: LLM didn't include title in first line — prepending")
        notes = f"{h1_title}\n\n{notes}"

    print(f"   ✓ {time.time() - start:.1f}s")
    return notes

async def find_current_video_index(page, video_items):
    """Find the index of the currently playing/selected video"""
    print("🎯 Finding current video...")
    try:
        # Strategy 1: Check for data-current-item="true"
        for i, video in enumerate(video_items):
            item = video['element']
            current_attr = await item.get_attribute('data-current-item')
            if current_attr == 'true':
                print(f"   ✓ Current video is #{i+1}: {video['title']}")
                return i
        
        # Strategy 2: Match page title to video title
        page_title = await page.title()
        for i, video in enumerate(video_items):
            if video['title'].lower() in page_title.lower():
                print(f"   ✓ Current video is #{i+1}: {video['title']} (matched by title)")
                return i
        
        print(f"   ⚠️  Could not determine current video, assuming first")
        return 0
    except Exception as e:
        print(f"   Error finding current video: {e}")
        return 0

async def click_video_item(page, video_item):
    """Click a video item and wait for it to load"""
    title = video_item['title']
    print(f"   🖱️  Clicking: {title}")
    try:
        # Click the list item directly
        item = video_item['element']
        await item.click()
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)  # Additional wait for video player
        
        print(f"   ✓ Loaded: {title}")
        return True
    except Exception as e:
        print(f"   Failed to click video: {e}")
        return False

def load_progress(progress_file):
    """Load set of completed video titles from progress file"""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                data = json.load(f)
                return set(data.get('completed', []))
        except Exception:
            pass
    return set()

def save_progress(progress_file, completed_videos):
    """Persist set of completed video titles to progress file"""
    with open(progress_file, 'w') as f:
        json.dump({'completed': list(completed_videos)}, f, indent=2)

async def main():
    # Runtime URL input
    COURSE_URL = input("📎 Paste Coursera lecture URL: ").strip()
    if not COURSE_URL:
        print("❌ No URL provided. Exiting.")
        return

    # Progress tracking
    progress_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'progress.json')
    completed_videos = load_progress(progress_file)
    if completed_videos:
        print(f"   ↩️  Resuming — {len(completed_videos)} videos already completed")

    # Show mode
    mode = "📹 BATCH MODE: Processing all remaining videos" if PROCESS_ALL_VIDEOS else "📄 SINGLE MODE: Processing current video only"
    if PROCESS_ALL_VIDEOS and PROCESS_READINGS:
        mode = "📹📖 BATCH MODE: Processing videos + readings"
    print(f"\n{mode}")
    print(f"💡 Toggle with PROCESS_ALL_VIDEOS = {not PROCESS_ALL_VIDEOS}\n")
    
    # Ollama health check
    print("🔍 Ollama...")
    ollama.list()

    # Launch Chrome with debugging if needed
    print("🌐 Chrome setup...")
    chrome_process = launch_chrome_with_debugging()

    async with async_playwright() as p:
        print("🔗 Connecting to Chrome...")
        try:
            # Connect to Chrome with remote debugging (with retry logic)
            browser = await wait_for_chrome_connection(p)
        except Exception as e:
            print(f"Failed to connect to Chrome")
            print(f"   Error: {e}")
            raise e
        
        context = browser.contexts[0] # type: ignore
        page = await context.new_page()

        print(f"📱 {COURSE_URL}")
        await page.goto(COURSE_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)  # Wait for Coursera's redirects to settle
        
        # Verify we're on the correct lecture
        current_url = page.url
        expected_lecture_id = COURSE_URL.split('/lecture/')[-1].split('/')[0] if '/lecture/' in COURSE_URL else None
        current_lecture_id = current_url.split('/lecture/')[-1].split('/')[0] if '/lecture/' in current_url else None
        
        if expected_lecture_id and current_lecture_id != expected_lecture_id:
            print(f"   ⚠️  Coursera redirected to different lecture")
            print(f"   🔄 Re-navigating to correct URL...")
            await page.goto(COURSE_URL, timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            
            # Verify again
            if expected_lecture_id not in page.url:
                print(f"   ⚠️  Still on wrong lecture. You may need to manually navigate.")
                print(f"   Expected: {COURSE_URL}")
                print(f"   Current:  {page.url}")

        input("📄 Transcript OPEN → Enter...")

        if PROCESS_ALL_VIDEOS:
            # Get all processable items (videos + readings if enabled)
            course_items = await get_course_items(page)

            # Filter out readings if disabled
            if not PROCESS_READINGS:
                course_items = [it for it in course_items if it['type'] == 'video']

            if not course_items:
                print("No items found in module")
                return

            # Find current item position
            current_index = await find_current_video_index(page, course_items)

            # Get remaining items (current + forward only)
            remaining_items = course_items[current_index:]
            print(f"\n🎬 Processing {len(remaining_items)} items (starting from #{current_index+1})\n")

            # Process each item
            MAX_RETRIES = 2
            for i, item in enumerate(remaining_items):
                item_num = current_index + i + 1
                item_icon = "📹" if item['type'] == 'video' else "📖"
                item_label = "VIDEO" if item['type'] == 'video' else "READING"
                print(f"\n{'='*60}")
                print(f"{item_icon} {item_label} {item_num}/{len(course_items)}: {item['title']}")
                print(f"{'='*60}\n")

                # Skip if already completed in a previous run
                if item['title'] in completed_videos:
                    print(f"   ⏭️  Already completed, skipping...")
                    continue

                # If not the first item, click to navigate
                if i > 0:
                    success = await click_video_item(page, item)
                    if not success:
                        print(f"   ❌ Skipping item due to navigation error")
                        continue

                # Extract and process with per-item retry
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        if item['type'] == 'video':
                            title = await page.title()
                            transcript = await get_transcript(page)

                            if not transcript:
                                print(f"   ⚠️ No transcript found, skipping...")
                                break

                            notes = await granite_notes(transcript, title)
                            save_doc(DOC_ID, title, notes)

                        else:  # reading
                            h1_title, content = await get_reading_content(page)

                            if not content:
                                print(f"   ⚠️ No reading content found, skipping...")
                                break

                            notes = await granite_reading_notes(content, h1_title)
                            save_doc(DOC_ID, h1_title, notes)

                        completed_videos.add(item['title'])
                        save_progress(progress_file, completed_videos)
                        print(f"\n   ✓ Completed {item_label.lower()} {item_num}/{len(course_items)}")
                        break
                    except Exception as e:
                        if attempt < MAX_RETRIES:
                            print(f"   ⚠️ Attempt {attempt+1}/{MAX_RETRIES+1} failed: {e}. Retrying in 5s...")
                            await page.wait_for_timeout(5000)
                        else:
                            print(f"   ❌ All {MAX_RETRIES+1} attempts failed for '{item['title']}'. Skipping.")

                # Brief pause between items
                if i < len(remaining_items) - 1:
                    print("   Pausing 2 seconds before next item...")
                    await page.wait_for_timeout(2000)

            print(f"\n\n🎊 ALL ITEMS COMPLETE!")
            print(f"   Processed {len(remaining_items)} items")
            if os.path.exists(progress_file):
                os.remove(progress_file)
                print(f"   🗑️  Progress file cleared")
        else:
            # Single video mode (original behavior)
            title = await page.title()
            print(f"📚 {title}")

            transcript = await get_transcript(page)
            notes = await granite_notes(transcript, title)
            save_doc(DOC_ID, title, notes)
            
            print("COMPLETE - Check Doc!")

        await page.close()
        print(" Close Chrome manually when done")

if __name__ == "__main__":
    asyncio.run(main())
