from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, Response
from pytubefix import YouTube, Playlist, Search
import os
import json
import threading
import time
from datetime import datetime
import re
import tempfile
import shutil
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'whibo_secret_key_2025'

# Configuration
TEMP_DOWNLOAD_FOLDER = 'temp_downloads'
MAX_CONCURRENT_DOWNLOADS = 5
CLEANUP_AFTER_MINUTES = 10

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
        """Old files ko automatically cleanup kariye"""
        while True:
            try:
                current_time = time.time()
                files_to_remove = []
                
                for download_id, file_info in download_files.items():
                    if current_time - file_info['created_at'] > (CLEANUP_AFTER_MINUTES * 60):
                        files_to_remove.append(download_id)
                        
                        # Delete physical file
                        if os.path.exists(file_info['filepath']):
                            os.remove(file_info['filepath'])
                            print(f"🗑️ Cleaned up: {file_info['filename']}")
                
                # Remove from memory
                for download_id in files_to_remove:
                    download_files.pop(download_id, None)
                    download_status.pop(download_id, None)
                    
            except Exception as e:
                print(f"Cleanup error: {e}")
            
            time.sleep(300)  # Check every 5 minutes
    
    def validate_youtube_url(self, url):
        """YouTube URL validate kariye"""
        youtube_regex = re.compile(
            r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
            r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        )
        return youtube_regex.match(url) is not None
    
    def get_video_info(self, url):
        """Video information get kariye"""
        try:
            yt = YouTube(url)
            
            # Video streams
            video_streams = []
            progressive_streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
            for stream in progressive_streams:
                if stream.resolution:
                    video_streams.append({
                        'resolution': stream.resolution,
                        'filesize': stream.filesize // (1024 * 1024) if stream.filesize else 0,
                        'fps': getattr(stream, 'fps', 30),
                        'type': 'progressive',
                        'quality_label': f"{stream.resolution} (Combined)"
                    })
            
            # Adaptive streams
            adaptive_video_streams = yt.streams.filter(adaptive=True, type='video', file_extension='mp4').order_by('resolution').desc()
            for stream in adaptive_video_streams:
                if stream.resolution:
                    video_streams.append({
                        'resolution': stream.resolution,
                        'filesize': stream.filesize // (1024 * 1024) if stream.filesize else 0,
                        'fps': getattr(stream, 'fps', 30),
                        'type': 'adaptive',
                        'quality_label': f"{stream.resolution} {stream.fps}fps (Video Only)"
                    })
            
            # Remove duplicates
            seen = set()
            unique_streams = []
            for stream in video_streams:
                key = f"{stream['resolution']}_{stream['type']}"
                if key not in seen:
                    seen.add(key)
                    unique_streams.append(stream)
            
            # Audio streams
            audio_streams = []
            audio_only_streams = yt.streams.filter(only_audio=True).order_by('abr').desc()
            for stream in audio_only_streams:
                if stream.abr:
                    audio_streams.append({
                        'abr': stream.abr,
                        'filesize': stream.filesize // (1024 * 1024) if stream.filesize else 0,
                        'audio_codec': getattr(stream, 'audio_codec', 'unknown')
                    })
            
            video_info = {
                'title': yt.title,
                'author': yt.author,
                'length': f"{yt.length // 60}:{yt.length % 60:02d}",
                'views': f"{yt.views:,}",
                'description': yt.description[:500] + "..." if len(yt.description) > 500 else yt.description,
                'thumbnail_url': yt.thumbnail_url,
                'publish_date': yt.publish_date.strftime('%Y-%m-%d') if yt.publish_date else 'Unknown',
                'video_streams': unique_streams[:10],
                'audio_streams': audio_streams[:8]
            }
            
            return video_info, None
        except Exception as e:
            return None, str(e)
    
    def download_video_async(self, url, quality, download_type, download_id, client_ip):
        """Client-specific temporary download"""
        global active_downloads
        active_downloads += 1
        
        try:
            download_status[download_id] = {
                'status': 'downloading',
                'progress': 0,
                'filename': '',
                'error': None,
                'file_size': 0,
                'client_ip': client_ip
            }
            
            yt = YouTube(url, on_progress_callback=lambda stream, chunk, bytes_remaining: 
                        self.progress_callback(download_id, stream, chunk, bytes_remaining))
            
            # Stream selection
            if download_type == 'audio':
                stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
                filename_suffix = '.mp3'
            elif download_type == 'adaptive':
                stream = yt.streams.filter(adaptive=True, type='video', res=quality, file_extension='mp4').first()
                if not stream:
                    stream = yt.streams.filter(adaptive=True, type='video', file_extension='mp4').order_by('resolution').desc().first()
                filename_suffix = '.mp4'
            else:
                if quality == 'best_quality':
                    stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
                else:
                    stream = yt.streams.filter(res=quality, progressive=True).first()
                    if not stream:
                        stream = yt.streams.get_highest_resolution()
                filename_suffix = '.mp4'
            
            if not stream:
                raise Exception("No suitable stream found")
            
            # Create unique filename with timestamp
            safe_title = secure_filename(yt.title)[:50]
            timestamp = str(int(time.time()))
            temp_filename = f"{safe_title}_{timestamp}_{download_id[:8]}"
            
            # Download to temp folder
            download_path = stream.download(
                output_path=TEMP_DOWNLOAD_FOLDER,
                filename=temp_filename + filename_suffix
            )
            
            # Rename audio file to .mp3
            if download_type == 'audio':
                base, ext = os.path.splitext(download_path)
                new_path = base + '.mp3'
                os.rename(download_path, new_path)
                download_path = new_path
            
            # Store file information temporarily
            download_files[download_id] = {
                'filepath': download_path,
                'filename': os.path.basename(download_path),
                'created_at': time.time(),
                'client_ip': client_ip,
                'original_title': yt.title
            }
            
            download_status[download_id]['status'] = 'completed'
            download_status[download_id]['filename'] = os.path.basename(download_path)
            download_status[download_id]['filepath'] = download_path
            
            # Add to history
            self.download_history.append({
                'title': yt.title,
                'filename': os.path.basename(download_path),
                'download_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'type': download_type,
                'quality': quality,
                'client_ip': client_ip
            })
            
            print(f"✅ Download completed for client {client_ip}: {yt.title}")
            
        except Exception as e:
            download_status[download_id]['status'] = 'error'
            download_status[download_id]['error'] = str(e)
            print(f"❌ Download failed for client {client_ip}: {str(e)}")
        
        finally:
            active_downloads -= 1
    
    def progress_callback(self, download_id, stream, chunk, bytes_remaining):
        """Download progress callback"""
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = (bytes_downloaded / total_size) * 100
        
        download_status[download_id]['progress'] = int(percentage)
        download_status[download_id]['downloaded_mb'] = bytes_downloaded // (1024 * 1024)
        download_status[download_id]['total_mb'] = total_size // (1024 * 1024)
    
    def search_videos(self, query, max_results=15):
        """YouTube search functionality"""
        try:
            search = Search(query)
            results = []
            
            for video in search.results[:max_results]:
                results.append({
                    'title': video.title,
                    'author': video.author,
                    'length': f"{video.length // 60}:{video.length % 60:02d}",
                    'views': f"{video.views:,}",
                    'thumbnail_url': video.thumbnail_url,
                    'url': video.watch_url,
                    'description': video.description[:100] + "..." if video.description else ""
                })
            
            return results, None
        except Exception as e:
            return None, str(e)

# Initialize WhiBO downloader
whibo_downloader = WhiBO_ClientDownloader()

# ===== ALL FLASK ROUTES =====

@app.route('/')
def index():
    """WhiBO Home page"""
    client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def get_info():
    """Video information page"""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Please enter a YouTube URL', 'error')
        return redirect(url_for('index'))
    
    if not whibo_downloader.validate_youtube_url(url):
        flash('Please enter a valid YouTube URL', 'error')
        return redirect(url_for('index'))
    
    video_info, error = whibo_downloader.get_video_info(url)
    
    if error:
        flash(f'Error getting video info: {error}', 'error')
        return redirect(url_for('index'))
    
    return render_template('info.html', video_info=video_info, url=url)

@app.route('/download', methods=['POST'])
def start_download():
    """Start client-side download"""
    global active_downloads
    
    client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
    
    if active_downloads >= MAX_CONCURRENT_DOWNLOADS:
        return jsonify({
            'success': False, 
            'message': f'Server busy. Maximum {MAX_CONCURRENT_DOWNLOADS} downloads allowed'
        })
    
    url = request.form.get('url', '').strip()
    quality = request.form.get('quality', 'best_quality')
    download_type = request.form.get('type', 'video')
    
    if not url or not whibo_downloader.validate_youtube_url(url):
        return jsonify({'success': False, 'message': 'Invalid YouTube URL'})
    
    # Generate unique download ID
    download_id = f"{int(time.time() * 1000)}_{client_ip.replace('.', '')}"
    
    # Start download in background thread
    thread = threading.Thread(
        target=whibo_downloader.download_video_async,
        args=(url, quality, download_type, download_id, client_ip)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'download_id': download_id})

@app.route('/progress/<download_id>')
def get_progress(download_id):
    """Get download progress"""
    if download_id in download_status:
        return jsonify(download_status[download_id])
    else:
        return jsonify({'status': 'not_found'})

@app.route('/download_file/<download_id>')
def download_file(download_id):
    """Client downloads the file directly"""
    client_ip = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)
    
    if download_id not in download_files:
        flash('File not found or expired', 'error')
        return redirect(url_for('index'))
    
    file_info = download_files[download_id]
    filepath = file_info['filepath']
    
    if not os.path.exists(filepath):
        flash('File has been cleaned up or moved', 'error')
        return redirect(url_for('index'))
    
    print(f"📥 Client {client_ip} downloading: {file_info['filename']}")
    
    def remove_file():
        """Remove file after download"""
        time.sleep(5)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"🗑️ Auto-cleaned: {file_info['filename']}")
            download_files.pop(download_id, None)
            download_status.pop(download_id, None)
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    cleanup_thread = threading.Thread(target=remove_file, daemon=True)
    cleanup_thread.start()
    
    return send_file(
        filepath, 
        as_attachment=True,
        download_name=file_info['filename']
    )

@app.route('/search')
def search():
    """WhiBO Search page"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return render_template('search.html', results=[], query='')
    
    results, error = whibo_downloader.search_videos(query)
    
    if error:
        flash(f'Search error: {error}', 'error')
        return render_template('search.html', results=[], query=query)
    
    return render_template('search.html', results=results, query=query)

@app.route('/history')
def history():
    """WhiBO Download history"""
    return render_template('history.html', history=whibo_downloader.download_history)

@app.route('/about')
def about():
    """WhiBO About page"""
    return render_template('about.html')

@app.route('/stats')
def server_stats():
    """Server statistics"""
    stats = {
        'active_downloads': active_downloads,
        'temp_files_count': len(download_files),
        'temp_folder_size': get_folder_size(TEMP_DOWNLOAD_FOLDER),
        'recent_downloads': list(download_files.values())[-10:]
    }
    return render_template('stats.html', stats=stats)

def get_folder_size(folder_path):
    """Get folder size in MB"""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)
        return round(total_size / (1024 * 1024), 2)
    except:
        return 0

@app.route('/cleanup_server', methods=['POST'])
def manual_cleanup():
    """Manual server cleanup"""
    try:
        cleaned_count = 0
        
        for download_id, file_info in list(download_files.items()):
            filepath = file_info['filepath']
            if os.path.exists(filepath):
                os.remove(filepath)
                cleaned_count += 1
            download_files.pop(download_id, None)
            download_status.pop(download_id, None)
        
        return jsonify({
            'success': True, 
            'message': f'Cleaned up {cleaned_count} files',
            'cleaned_count': cleaned_count
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'active_downloads': active_downloads,
        'temp_files': len(download_files),
        'app_name': 'WhiBO'
    })

# ===== ERROR HANDLERS =====

@app.errorhandler(404)
def page_not_found(error):
    return render_template('error.html', 
                         error_code=404, 
                         error_message="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', 
                         error_code=500, 
                         error_message="Internal server error"), 500

if __name__ == '__main__':
    print("\n🚀 WhiBO - Client-Side YouTube Downloader Starting...")
    print("📍 Local access: http://localhost:5000")
    print("🌐 Network access: http://YOUR_IP:5000")
    print(f"🗂️  Temp folder: {TEMP_DOWNLOAD_FOLDER}")
    print(f"🧹 Auto cleanup: {CLEANUP_AFTER_MINUTES} minutes")
    print(f"👥 Max concurrent: {MAX_CONCURRENT_DOWNLOADS} downloads")
    print("-" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
