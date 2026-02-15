#!/usr/bin/env python3
"""
HTTP server to serve the dashboard with API endpoints for data generation
"""
import http.server
import socketserver
import traceback
import webbrowser
import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
from weekly_slack_recon.config import load_config
from weekly_slack_recon.slack_client import SlackAPI
from weekly_slack_recon.logic import build_candidate_submissions, CandidateSubmission
from weekly_slack_recon.reporting import write_markdown, write_json
from weekly_slack_recon.enrichment import enrich_submissions

# Cached SlackAPI instance for follow-up sends
_slack_instance: SlackAPI = None

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

# Global state for enrichment progress
enrichment_status = {
    "running": False,
    "phase": "",        # "gathering", "analyzing", "complete"
    "current": 0,
    "total": 0,
    "detail": "",
    "error": None,
    "completed": False,
    "results": None,    # List of enrichment result dicts when done
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
        elif parsed_path.path == '/api/enrich/status':
            self.handle_api_enrich_status()
        elif parsed_path.path == '/api/enrich/results':
            self.handle_api_enrich_results()
        else:
            # Serve static files
            super().do_GET()
    
    def do_POST(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/generate':
            self.handle_api_generate_post()
        elif parsed_path.path == '/api/send-followup':
            self.handle_api_send_followup()
        elif parsed_path.path == '/api/enrich':
            self.handle_api_enrich()
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
        except (json.JSONDecodeError, ValueError):
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


    def handle_api_send_followup(self):
        """Send a follow-up message to a Slack channel."""
        global _slack_instance

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            payload = json.loads(body)
        except Exception:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return

        channel_id = payload.get("channel_id")
        message = payload.get("message")

        if not channel_id or not message:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "channel_id and message are required"}).encode())
            return

        try:
            if _slack_instance is None:
                cfg = load_config()
                _slack_instance = SlackAPI(token=cfg.slack_bot_token)

            ts = _slack_instance.post_channel_message(channel_id, message)

            if ts:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "ts": ts}).encode())
            else:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Failed to send message"}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


    def handle_api_enrich_status(self):
        """Return current enrichment status."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        # Don't send full results in status poll (too large); client fetches them separately
        status_copy = {k: v for k, v in enrichment_status.items() if k != "results"}
        status_copy["has_results"] = enrichment_status["results"] is not None
        response = json.dumps(status_copy)
        self.wfile.write(response.encode())

    def handle_api_enrich(self):
        """Start enrichment in background. POST body can specify candidate filters."""
        global enrichment_status

        if enrichment_status["running"]:
            self.send_response(409)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Enrichment already in progress"}).encode())
            return

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        # Start enrichment in background thread
        thread = threading.Thread(target=run_enrichment, args=(payload,), daemon=True)
        thread.start()

        self.send_response(202)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "started"}).encode())

    def handle_api_enrich_results(self):
        """Return enrichment results (called after enrichment completes)."""
        if enrichment_status["results"] is None:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "No enrichment results available"}).encode())
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"results": enrichment_status["results"]}).encode())


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


def run_enrichment(payload: dict = None):
    """Run LLM enrichment on current submissions data."""
    global enrichment_status

    enrichment_status = {
        "running": True,
        "phase": "starting",
        "current": 0,
        "total": 0,
        "detail": "Loading data...",
        "error": None,
        "completed": False,
        "results": None,
    }

    try:
        # Load existing JSON data
        json_path = DIRECTORY / "weekly_slack_reconciliation.json"
        if not json_path.exists():
            enrichment_status["error"] = "No submission data found. Run 'Generate Data' first."
            enrichment_status["running"] = False
            return

        with open(json_path, "r") as f:
            data = json.load(f)

        submissions_data = data.get("submissions", [])
        if not submissions_data:
            enrichment_status["error"] = "No submissions in data file."
            enrichment_status["running"] = False
            return

        # Filter candidates if payload specifies which ones
        filter_statuses = (payload or {}).get("statuses")  # e.g. ["IN PROCESS — unclear"]
        filter_channels = (payload or {}).get("channels")  # e.g. ["candidatelabs-argus"]

        # Convert JSON dicts back to CandidateSubmission objects
        # Skip CLOSED candidates — only enrich active ones to save tokens
        filtered_submissions = []
        for s in submissions_data:
            if s["status"] == "CLOSED":
                continue
            if filter_statuses and s["status"] not in filter_statuses:
                continue
            if filter_channels and s["channel_name"] not in filter_channels:
                continue
            submitted_at = datetime.fromisoformat(s["submitted_at"])
            filtered_submissions.append(CandidateSubmission(
                candidate_name=s["candidate_name"],
                linkedin_url=s["linkedin_url"],
                channel_name=s["channel_name"],
                channel_id=s["channel_id"],
                submitted_at=submitted_at,
                status=s["status"],
                status_reason=s.get("status_reason"),
                days_since_submission=s["days_since_submission"],
                needs_followup=s["needs_followup"],
                slack_url=s.get("slack_url"),
            ))

        if not filtered_submissions:
            enrichment_status["error"] = "No submissions match the filter criteria."
            enrichment_status["running"] = False
            return

        enrichment_status["total"] = len(filtered_submissions)
        enrichment_status["detail"] = f"Enriching {len(filtered_submissions)} candidates..."

        cfg = load_config()
        slack = SlackAPI(token=cfg.slack_bot_token)

        def progress_callback(phase, current, total, detail):
            enrichment_status["phase"] = phase
            enrichment_status["current"] = current
            enrichment_status["total"] = total
            enrichment_status["detail"] = detail
            print(f"[ENRICH] {phase}: {current}/{total} - {detail}")

        results = enrich_submissions(cfg, slack, filtered_submissions, progress_callback=progress_callback)

        # Store results
        enrichment_status["results"] = [r.to_dict() for r in results]

        # Also merge results into the JSON file so the dashboard can show them
        _merge_enrichment_into_json(json_path, results)

        enrichment_status["phase"] = "complete"
        enrichment_status["completed"] = True
        enrichment_status["running"] = False
        enrichment_status["detail"] = f"Done! Enriched {len(results)} candidates."

    except Exception as e:
        error_msg = str(e)
        enrichment_status["error"] = error_msg
        enrichment_status["running"] = False
        enrichment_status["detail"] = f"Error: {error_msg}"
        print(f"[ENRICH ERROR] {error_msg}")
        traceback.print_exc()


def _merge_enrichment_into_json(json_path: Path, results: list):
    """Merge enrichment results back into the submissions JSON file."""
    with open(json_path, "r") as f:
        data = json.load(f)

    # Build lookup: (candidate_name, channel_name) -> result
    result_lookup = {}
    for r in results:
        key = (r.candidate_name, r.channel_name)
        result_lookup[key] = r

    for sub in data.get("submissions", []):
        key = (sub["candidate_name"], sub["channel_name"])
        result = result_lookup.get(key)
        if result:
            sub["ai_summary"] = result.ai_summary
            sub["ai_enriched_at"] = result.enriched_at

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[ENRICH] Merged {len(result_lookup)} enrichment results into {json_path}")


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
