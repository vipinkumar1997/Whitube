# app.py (Final, Secure Version with Environment Variables)

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
from werkzeug.utils import secure_filename
import os
import threading
import time
from datetime import datetime
import re
import subprocess
import json
import secrets
import tempfile

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'whibo_secret_key_2025')

# Configuration
TEMP_DOWNLOAD_FOLDER = os.environ.get('TEMP_DOWNLOAD_FOLDER', 'temp_downloads')
MAX_CONCURRENT_DOWNLOADS = int(os.environ.get('MAX_CONCURRENT_DOWNLOADS', 5))
CLEANUP_AFTER_MINUTES = int(os.environ.get('CLEANUP_AFTER_MINUTES', 10))

# Create temp directory
if not os.path.exists(TEMP_DOWNLOAD_FOLDER):
    os.makedirs(TEMP_DOWNLOAD_FOLDER)

# Global variables
download_status = {}
active_downloads = 0
download_files = {}

class WhiBO_ClientDownloader:
    def __init__(self):
        self.download_history = []
        self.cleanup_thread = threading.Thread(target=self.cleanup_old_files, daemon=True)
        self.cleanup_thread.start()

    def cleanup_old_files(self):
        while True:
            try:
                current_time = time.time()
                files_to_remove = []
                for download_id, file_info in list(download_files.items()):
                    if current_time - file_info['created_at'] > (CLEANUP_AFTER_MINUTES * 60):
                        files_to_remove.append(download_id)
                        if os.path.exists(file_info['filepath']):
                            os.remove(file_info['filepath'])
                            print(f"🗑️ Cleaned up: {file_info['filename']}")
                
                for download_id in files_to_remove:
                    download_files.pop(download_id, None)
                    download_status.pop(download_id, None)
            except Exception as e:
                print(f"Cleanup error: {e}")
            time.sleep(300)

    def validate_youtube_url(self, url):
        return re.match(r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+$', url)

    def _run_yt_dlp_command(self, command):
        """Helper function to run yt-dlp with cookie handling"""
        cookie_content = os.environ.get('YOUTUBE_COOKIES')
        temp_cookie_file = None

        try:
            if cookie_content:
                # Create a temporary file to store cookies
                with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as temp:
                    temp.write(cookie_content)
                    temp_cookie_file = temp.name
                command.extend(['--cookies', temp_cookie_file])

            # Run the actual command
            return subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        
        finally:
            # Securely delete the temporary cookie file after use
            if temp_cookie_file and os.path.exists(temp_cookie_file):
                os.remove(temp_cookie_file)

    def get_video_info(self, url):
        try:
            command = ['yt-dlp', '--dump-json', '--no-playlist', url]
            result = self._run_yt_dlp_command(command)
            video_data = json.loads(result.stdout)
            
            # Format data (same as before)
            video_streams = []
            audio_streams = []
            seen_resolutions = set()
            for f in video_data.get('formats', []):
                filesize_mb = round(f.get('filesize', 0) / (1024 * 1024), 2) if f.get('filesize') else 0
                if f.get('vcodec') != 'none' and f.get('resolution') not in seen_resolutions:
                    video_streams.append({'resolution': f.get('resolution'), 'filesize': filesize_mb, 'quality_label': f"{f.get('height', 'N/A')}p"})
                    seen_resolutions.add(f.get('resolution'))
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                     audio_streams.append({'abr': f.get('abr'), 'filesize': filesize_mb})
            
            video_info = {
                'title': video_data.get('title'), 'author': video_data.get('uploader'),
                'length': f"{int(video_data.get('duration', 0) // 60)}:{int(video_data.get('duration', 0) % 60):02d}",
                'views': f"{video_data.get('view_count', 0):,}", 'description': video_data.get('description', '')[:500],
                'thumbnail_url': video_data.get('thumbnail'),
                'publish_date': datetime.strptime(video_data.get('upload_date'), '%Y%m%d').strftime('%Y-%m-%d') if video_data.get('upload_date') else 'Unknown',
                'video_streams': sorted(video_streams, key=lambda x: int(x['quality_label'].split('p')[0]), reverse=True),
                'audio_streams': sorted(audio_streams, key=lambda x: x.get('abr', 0), reverse=True)
            }
            return video_info, None
        except subprocess.CalledProcessError as e:
            return None, f"yt-dlp error: {e.stderr}"
        except Exception as e:
            return None, str(e)

    def download_video_async(self, url, quality, download_type, download_id, client_ip):
        global active_downloads
        active_downloads += 1
        try:
            download_status[download_id] = {'status': 'downloading', 'progress': 0, 'error': None}
            safe_title = secure_filename(f"video_{download_id}")[:50]
            output_template = os.path.join(TEMP_DOWNLOAD_FOLDER, f"{safe_title}.%(ext)s")

            command = ['yt-dlp', '--no-playlist']
            if download_type == 'audio':
                command.extend(['-f', 'bestaudio', '--extract-audio', '--audio-format', 'mp3'])
            else:
                command.extend(['-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', '--merge-output-format', 'mp4'])
            command.extend(['-o', output_template, url])
            
            self._run_yt_dlp_command(command) # Use the helper function

            downloaded_file = next((f for f in os.listdir(TEMP_DOWNLOAD_FOLDER) if safe_title in f), None)
            if not downloaded_file: raise Exception("Downloaded file not found.")

            filepath = os.path.join(TEMP_DOWNLOAD_FOLDER, downloaded_file)
            download_files[download_id] = {'filepath': filepath, 'filename': downloaded_file, 'created_at': time.time(), 'client_ip': client_ip}
            download_status[download_id]['status'] = 'completed'
            download_status[download_id]['filename'] = downloaded_file
            download_status[download_id]['progress'] = 100
        except Exception as e:
            download_status[download_id]['status'] = 'error'
            download_status[download_id]['error'] = str(e)
        finally:
            active_downloads -= 1

# Initialize downloader
whibo_downloader = WhiBO_ClientDownloader()

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def get_info():
    url = request.form.get('url', '').strip()
    if not url or not whibo_downloader.validate_youtube_url(url):
        flash('Please enter a valid YouTube URL', 'error')
        return redirect(url_for('index'))
    video_info, error = whibo_downloader.get_video_info(url)
    if error:
        flash(f'Error getting video info: {error}', 'error')
        return redirect(url_for('index'))
    return render_template('info.html', video_info=video_info, url=url)

@app.route('/download', methods=['POST'])
def start_download():
    if active_downloads >= MAX_CONCURRENT_DOWNLOADS:
        return jsonify({'success': False, 'message': 'Server busy.'})
    url = request.form.get('url', '').strip()
    quality = request.form.get('quality', 'best_quality')
    download_type = request.form.get('type', 'video')
    if not url: return jsonify({'success': False, 'message': 'Invalid URL'})
    
    download_id = secrets.token_hex(16)
    client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
    thread = threading.Thread(target=whibo_downloader.download_video_async, args=(url, quality, download_type, download_id, client_ip), daemon=True)
    thread.start()
    return jsonify({'success': True, 'download_id': download_id})

@app.route('/progress/<download_id>')
def get_progress(download_id):
    return jsonify(download_status.get(download_id, {'status': 'not_found'}))

@app.route('/download_file/<download_id>')
def download_file(download_id):
    file_info = download_files.get(download_id)
    if not file_info or not os.path.exists(file_info['filepath']):
        flash('File not found, expired, or cleaned up.', 'error')
        return redirect(url_for('index'))
    return send_file(file_info['filepath'], as_attachment=True, download_name=file_info['filename'])

# Other routes (search, history, about) can remain as they are.
@app.route('/search')
def search():
    flash('Search functionality is not implemented in this version.', 'info')
    return render_template('search.html', results=[], query=request.args.get('q', ''))

# Boilerplate for other pages and error handlers
@app.route('/history')
def history(): return render_template('history.html', history=[])
@app.route('/about')
def about(): return render_template('about.html')
@app.errorhandler(404)
def page_not_found(e): return render_template('error.html', error_code=404, error_message="Page Not Found"), 404
@app.errorhandler(500)
def internal_error(e): return render_template('error.html', error_code=500, error_message="Internal Server Error"), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
