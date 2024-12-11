from flask import Flask, request, jsonify, render_template, send_from_directory
from typing import Dict, Any, List, Optional, Union
import yt_dlp
import os
import uuid
import time
import re
import logging
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('cutter')

# Application Constants
class Config:
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024 * 1024  # 16GB max-size
    SEND_FILE_MAX_AGE_DEFAULT = 0
    BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
    DOWNLOAD_DIR = BASE_DIR / "downloads"
    CLIP_DIR = BASE_DIR / "clips"
    ALLOWED_EXTENSIONS = {'mp4'}
    DEFAULT_PERMISSIONS = 0o755

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Create necessary directories with proper permissions
os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
os.makedirs(Config.CLIP_DIR, exist_ok=True)
os.chmod(Config.DOWNLOAD_DIR, Config.DEFAULT_PERMISSIONS)
os.chmod(Config.CLIP_DIR, Config.DEFAULT_PERMISSIONS)

class VideoProcessingError(Exception):
    """Custom exception for video processing errors."""
    pass

def extract_video_id(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from URL.
    
    Args:
        url: YouTube URL
        
    Returns:
        Optional[str]: Video ID if found, None otherwise
    """
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        if match := re.search(pattern, url):
            return match.group(1)
    return None

def download_video_ytdlp(url: str) -> Dict[str, Any]:
    """
    Download video using yt-dlp with optimized settings.
    
    Args:
        url: YouTube URL
        
    Returns:
        Dict containing video information and file paths
        
    Raises:
        VideoProcessingError: If download fails
    """
    try:
        filename = f"{uuid.uuid4()}.mp4"
        output_path = Config.DOWNLOAD_DIR / filename
        
        ydl_opts = {
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]',
            'outtmpl': str(output_path),
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'no_check_certificates': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'retry_sleep': 5,
            'merge_output_format': 'mp4',
            'prefer_ffmpeg': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        info = ydl.extract_info(url, download=True)
        
        if not info:
            raise VideoProcessingError("Could not extract video information")
        
        if not output_path.exists():
            raise VideoProcessingError("Video file was not created")
        
        return {
            "file_path": f"/downloads/{filename}",
            "absolute_path": str(output_path),
            "title": info.get('title', 'Unknown Title'),
            "duration": info.get('duration', 0),
            "channel": info.get('uploader', 'Unknown Channel')
        }
            
    except Exception as e:
        logger.error(f"Error in download_video_ytdlp: {str(e)}")
        raise VideoProcessingError(f"Download failed: {str(e)}")

def convert_time_to_seconds(time_str: str) -> float:
    """
    Convert time string (MM:SS or seconds) to seconds float.
    
    Args:
        time_str: Time in MM:SS format or seconds
        
    Returns:
        float: Time in seconds
        
    Raises:
        ValueError: If time format is invalid
    """
    try:
        return float(time_str)
    except ValueError:
        if ':' in time_str:
            try:
                minutes, seconds = time_str.split(':')
                return float(minutes) * 60 + float(seconds)
            except ValueError:
                raise ValueError(f"Invalid time format: {time_str}. Expected MM:SS or seconds")
        raise ValueError(f"Invalid time format: {time_str}")

def sanitize_filename(name: str, index: int) -> str:
    """
    Sanitize and generate a unique filename.
    
    Args:
        name: Original filename
        index: Clip index
        
    Returns:
        str: Sanitized and unique filename
    """
    if name and (sanitized := "".join(c for c in name.strip() if c.isalnum() or c in (' ', '-', '_')).strip()):
        base_name = sanitized
    else:
        base_name = f"clip_{index + 1}"
    
    clip_name = base_name
    counter = 1
    while (Config.CLIP_DIR / f"{clip_name}.mp4").exists():
        clip_name = f"{base_name}_{counter}"
        counter += 1
    
    return f"{clip_name}.mp4"

@app.route("/")
def home():
    """Render the main page."""
    return render_template("index.html")

@app.route('/downloads/<path:filename>')
def download_file(filename: str):
    """
    Serve downloaded video files.
    
    Args:
        filename: Name of the file to serve
        
    Returns:
        Video file response or error
    """
    try:
        return send_from_directory(
            Config.DOWNLOAD_DIR, 
            filename,
            as_attachment=False,
            mimetype='video/mp4'
        )
    except Exception as e:
        logger.error(f"Error serving video file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

@app.route('/clips/<path:filename>')
def serve_clip(filename: str):
    """
    Serve processed video clips.
    
    Args:
        filename: Name of the clip to serve
        
    Returns:
        Video clip response or error
    """
    try:
        response = send_from_directory(
            Config.CLIP_DIR,
            filename,
            as_attachment=False,
            mimetype='video/mp4',
            conditional=True
        )
        response.headers.update({
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'no-cache'
        })
        return response
    except Exception as e:
        logger.error(f"Error serving clip file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

@app.route("/download", methods=["POST"])
def download_video():
    """
    Handle video download requests.
    
    Returns:
        JSON response with download results or error
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data or not (video_url := data.get("url")):
            return jsonify({"error": "No video URL provided"}), 400

        if not (video_id := extract_video_id(video_url)):
            return jsonify({"error": "Invalid YouTube URL"}), 400

        clean_url = f"https://www.youtube.com/watch?v={video_id}"
        result = download_video_ytdlp(clean_url)
        
        return jsonify({
            "message": "Video downloaded successfully",
            "file_path": result["file_path"],
            "absolute_path": result["absolute_path"],
            "title": result["title"],
            "duration": result["duration"],
            "channel": result["channel"]
        })

    except VideoProcessingError as e:
        error_msg = str(e).lower()
        if "age-restricted" in error_msg:
            return jsonify({"error": "This video is age-restricted"}), 403
        elif "private" in error_msg:
            return jsonify({"error": "This video is private"}), 403
        elif "unavailable" in error_msg:
            return jsonify({"error": "This video is unavailable"}), 404
        else:
            return jsonify({"error": f"Download failed: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in download_video: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route("/clip-multiple", methods=["POST"])
def clip_multiple():
    """
    Process multiple clips from a video.
    
    Returns:
        JSON response with clip information or error
    """
    try:
        from moviepy.editor import VideoFileClip
        
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data or not (file_path := data.get("file_path")) or not (cuts := data.get("cuts")):
            return jsonify({"error": "Missing required parameters"}), 400
        
        if file_path.startswith('/downloads/'):
            file_path = Config.DOWNLOAD_DIR / Path(file_path).name
        
        if not Path(file_path).exists():
            return jsonify({"error": "Video file not found"}), 404
            
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            return jsonify({"error": "FFmpeg not found. Please install FFmpeg"}), 500
        
        clips = []
        video = None
        
        try:
            video = VideoFileClip(str(file_path))
            
            if not video.duration:
                return jsonify({"error": "Invalid video file or duration"}), 400
            
            for i, cut in enumerate(cuts):
                try:
                    start_time = convert_time_to_seconds(cut["start_time"])
                    end_time = convert_time_to_seconds(cut["end_time"])
                    original_name = cut.get("name", "").strip()
                    
                    if end_time > video.duration:
                        return jsonify({"error": f"End time {end_time} exceeds video duration {video.duration}"}), 400
                    if start_time < 0 or end_time <= start_time:
                        return jsonify({"error": "Invalid time values"}), 400
                    
                    filename = sanitize_filename(original_name, i)
                    clip_path = Config.CLIP_DIR / filename
                    
                    temp_audio = str(Config.CLIP_DIR / f"temp_audio_{uuid.uuid4()}.m4a")
                    
                    subclip = video.subclip(start_time, end_time)
                    subclip.write_videofile(
                        str(clip_path),
                        codec='libx264',
                        audio_codec='aac',
                        temp_audiofile=temp_audio,
                        remove_temp=True,
                        logger=None
                    )
                    
                    if os.path.exists(temp_audio):
                        os.remove(temp_audio)
                    
                    clips.append({
                        "clip_path": f"/clips/{filename}",
                        "name": Path(filename).stem,
                        "start_time": start_time,
                        "end_time": end_time,
                        "duration": end_time - start_time
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing clip {i}: {str(e)}")
                    raise VideoProcessingError(f"Error processing clip {i}: {str(e)}")
                    
            return jsonify({
                "message": "Clips created successfully",
                "clips": clips
            })
            
        except Exception as e:
            logger.error(f"Error in clip_multiple: {str(e)}")
            for clip_info in clips:
                clip_path = Config.CLIP_DIR / Path(clip_info["clip_path"]).name
                if clip_path.exists():
                    clip_path.unlink()
            raise VideoProcessingError(f"Error processing clips: {str(e)}")
            
        finally:
            if video:
                video.close()
                
    except VideoProcessingError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.error(f"Unexpected error in clip_multiple: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route("/rename-clip", methods=["POST"])
def rename_clip():
    """
    Rename a processed clip.
    
    Returns:
        JSON response with new clip path or error
    """
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        if not data or not (old_name := data.get("old_name")):
            return jsonify({"error": "Missing required parameters"}), 400
            
        new_name = data.get("new_name", "clip").strip()
        if not new_name:
            new_name = "clip"
        
        old_path = Config.CLIP_DIR / old_name
        new_path = Config.CLIP_DIR / f"{new_name}.mp4"
        
        if not old_path.exists():
            return jsonify({"error": "Original clip not found"}), 404
            
        counter = 1
        while new_path.exists():
            new_path = Config.CLIP_DIR / f"{new_name}_{counter}.mp4"
            counter += 1
        
        old_path.rename(new_path)
        
        return jsonify({
            "message": "Clip renamed successfully",
            "new_path": f"/clips/{new_path.name}"
        })
        
    except Exception as e:
        logger.error(f"Error in rename_clip: {str(e)}")
        return jsonify({"error": f"Failed to rename clip: {str(e)}"}), 500

@app.route("/cleanup", methods=["POST"])
def cleanup_files():
    """
    Clean up temporary files.
    
    Returns:
        JSON response with cleanup results
    """
    try:
        deleted_files = []
        
        for directory in [Config.DOWNLOAD_DIR, Config.CLIP_DIR]:
            for filepath in directory.glob("*"):
                if filepath.is_file():
                    try:
                        filepath.unlink()
                        deleted_files.append(str(filepath))
                    except Exception as e:
                        logger.error(f"Error deleting {filepath}: {str(e)}")
        
        return jsonify({
            "message": "Cleanup completed",
            "deleted_files": deleted_files
        })
        
    except Exception as e:
        logger.error(f"Error in cleanup_files: {str(e)}")
        return jsonify({"error": f"Cleanup failed: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000) 