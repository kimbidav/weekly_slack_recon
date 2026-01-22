#!/usr/bin/env python3
"""
HTTP server to serve the dashboard with API endpoints for data generation
"""
import http.server
import socketserver
import webbrowser
import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from weekly_slack_recon.config import load_config
from weekly_slack_recon.slack_client import SlackAPI
from weekly_slack_recon.logic import build_candidate_submissions
from weekly_slack_recon.reporting import write_markdown, write_json

PORT = 8001
DIRECTORY = Path(__file__).parent
load_dotenv()

# Global state for generation progress
generation_status = {
    "running": False,
    "progress": "",
    "error": None,
    "completed": False
}


class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/status':
            self.handle_api_status()
        elif parsed_path.path == '/api/generate':
            self.handle_api_generate()
        else:
            # Serve static files
            super().do_GET()
    
    def do_POST(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/generate':
            self.handle_api_generate_post()
        else:
            self.send_error(404)
    
    def handle_api_status(self):
        """Return current generation status"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps(generation_status)
        self.wfile.write(response.encode())
    
    def handle_api_generate(self):
        """Start generation in background (GET request)"""
        if generation_status["running"]:
            self.send_response(409)  # Conflict - already running
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Generation already in progress"}).encode())
            return
        
        # Start generation in background thread
        thread = threading.Thread(target=run_generation, daemon=True)
        thread.start()
        
        self.send_response(202)  # Accepted
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "started"}).encode())
    
    def handle_api_generate_post(self):
        """Start generation with POST body (for future use with settings)"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            settings = json.loads(body) if body else {}
        except:
            settings = {}
        
        if generation_status["running"]:
            self.send_response(409)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Generation already in progress"}).encode())
            return
        
        # Start generation with settings
        thread = threading.Thread(target=run_generation, args=(settings,), daemon=True)
        thread.start()
        
        self.send_response(202)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "started"}).encode())


def update_progress(message: str):
    """Update generation progress"""
    generation_status["progress"] = message
    print(f"[PROGRESS] {message}")


def run_generation(settings: dict = None):
    """Run the reconciliation tool and generate JSON"""
    global generation_status
    
    generation_status["running"] = True
    generation_status["progress"] = "Starting..."
    generation_status["error"] = None
    generation_status["completed"] = False
    
    try:
        update_progress("Loading configuration...")
        cfg = load_config()
        
        update_progress("Connecting to Slack...")
        slack = SlackAPI(token=cfg.slack_bot_token)
        
        update_progress("Resolving DK Slack user by email...")
        dk_user_id = slack.get_user_id_by_email(cfg.dk_email)
        
        update_progress("Discovering relevant channels...")
        channels = slack.list_candidate_channels_for_user(dk_user_id)
        
        if not channels:
            generation_status["error"] = "No matching channels found"
            generation_status["running"] = False
            return
        
        update_progress(f"Found {len(channels)} channels. Scanning messages (this may take a few minutes due to rate limits)...")
        
        now = datetime.now(tz=timezone.utc)
        try:
            submissions, stats = build_candidate_submissions(cfg, slack, dk_user_id, channels, now=now)
        except Exception as e:
            # Even if there's an error, try to save partial data if possible
            error_msg = f"Error during scanning: {str(e)}"
            print(f"[ERROR] {error_msg}")
            # Check if we can still get partial results
            generation_status["error"] = error_msg + ". Check terminal for details. Partial data may have been saved."
            generation_status["running"] = False
            return
        
        update_progress(f"Found {len(submissions)} candidate submissions. Generating report...")
        
        # Write markdown and JSON
        if cfg.output_markdown_path:
            write_markdown(submissions, cfg.output_markdown_path, generated_at=now)
            json_path = cfg.output_markdown_path.replace('.md', '.json')
            write_json(submissions, json_path, generated_at=now)
        
        update_progress("Complete!")
        generation_status["completed"] = True
        generation_status["running"] = False
        
    except Exception as e:
        error_msg = str(e)
        generation_status["error"] = error_msg
        generation_status["running"] = False
        update_progress(f"Error: {error_msg}")
        print(f"[ERROR] {error_msg}")


def main():
    os.chdir(DIRECTORY)
    
    # Try to find an available port
    port = PORT
    max_attempts = 10
    httpd = None
    
    for attempt in range(max_attempts):
        try:
            httpd = socketserver.TCPServer(("", port), DashboardRequestHandler)
            break
        except OSError:
            if attempt < max_attempts - 1:
                port += 1
            else:
                print(f"Error: Could not find an available port (tried {PORT}-{port})")
                print("Another instance may already be running. Please close it first.")
                return
    
    url = f"http://localhost:{port}/dashboard.html"
    print(f"Dashboard server starting on port {port}...")
    print(f"Opening dashboard at: {url}")
    print(f"Press Ctrl+C to stop the server")
    print()
    
    # Open browser
    webbrowser.open(url)
    
    # Start server
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
    finally:
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    main()
