from flask import Flask, request, jsonify, render_template, send_from_directory
import yt_dlp
import os
import uuid
import time
import re

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024  # 16GB max-size
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Create base directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
CLIP_DIR = os.path.join(BASE_DIR, "clips")

# Create necessary directories
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CLIP_DIR, exist_ok=True)
os.chmod(DOWNLOAD_DIR, 0o755)
os.chmod(CLIP_DIR, 0o755)

@app.route("/")
def home():
    return render_template("index.html")

@app.route('/downloads/<path:filename>')
def download_file(filename):
    try:
        return send_from_directory(
            DOWNLOAD_DIR, 
            filename,
            as_attachment=False,
            mimetype='video/mp4'
        )
    except Exception as e:
        app.logger.error(f"Error serving video file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

@app.route('/clips/<path:filename>')
def serve_clip(filename):
    try:
        response = send_from_directory(
            CLIP_DIR,
            filename,
            as_attachment=False,
            mimetype='video/mp4',
            conditional=True
        )
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Cache-Control'] = 'no-cache'
        return response
    except Exception as e:
        app.logger.error(f"Error serving clip file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

def extract_video_id(url):
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be\/([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_video_ytdlp(url):
    try:
        filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)
        
        ydl_opts = {
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'no_check_certificates': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
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
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise Exception("Could not extract video information")
            
            if not os.path.exists(output_path):
                raise Exception("Video file was not created")
            
            return {
                "file_path": f"/downloads/{filename}",
                "absolute_path": output_path,
                "title": info.get('title', 'Unknown Title'),
                "duration": info.get('duration', 0),
                "channel": info.get('uploader', 'Unknown Channel')
            }
            
    except Exception as e:
        print(f"Error in download_video_ytdlp: {str(e)}")
        raise Exception(f"Download failed: {str(e)}")

@app.route("/download", methods=["POST"])
def download_video():
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        video_url = data.get("url")

        if not video_url:
            return jsonify({"error": "No video URL provided"}), 400

        video_id = extract_video_id(video_url)
        if not video_id:
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

    except Exception as e:
        error_msg = str(e)
        if "age-restricted" in error_msg.lower():
            return jsonify({"error": "This video is age-restricted"}), 403
        elif "private" in error_msg.lower():
            return jsonify({"error": "This video is private"}), 403
        elif "unavailable" in error_msg.lower():
            return jsonify({"error": "This video is unavailable"}), 404
        else:
            return jsonify({"error": f"Download failed: {error_msg}"}), 500

@app.route("/clip-multiple", methods=["POST"])
def clip_multiple():
    try:
        from moviepy.editor import VideoFileClip
        
        data = request.json
        file_path = data["file_path"]
        cuts = data["cuts"]
        
        if file_path.startswith('/downloads/'):
            file_path = os.path.join(DOWNLOAD_DIR, os.path.basename(file_path))
        
        if not os.path.exists(file_path):
            return jsonify({"error": "Video file not found"}), 404
        
        clips = []
        for cut in cuts:
            start_time = float(cut["start_time"])
            end_time = float(cut["end_time"])
            
            temp_filename = f"temp_{uuid.uuid4()}.mp4"
            clip_path = os.path.join(CLIP_DIR, temp_filename)
            
            video = VideoFileClip(file_path)
            
            if end_time > video.duration:
                video.close()
                return jsonify({"error": f"End time {end_time} exceeds video duration {video.duration}"}), 400
            if start_time < 0 or end_time <= start_time:
                video.close()
                return jsonify({"error": "Invalid time values"}), 400
            
            clip = video.subclip(start_time, end_time)
            clip.write_videofile(
                clip_path,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=os.path.join(CLIP_DIR, f"temp-audio-{uuid.uuid4()}.m4a"),
                remove_temp=True,
                threads=4,
                preset='ultrafast'
            )
            clip.close()
            video.close()
            
            os.chmod(clip_path, 0o644)
            
            clips.append({
                "start_time": start_time,
                "end_time": end_time,
                "clip_path": f"/clips/{temp_filename}"
            })
        
        return jsonify({"clips": clips})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rename-clip", methods=["POST"])
def rename_clip():
    try:
        data = request.json
        old_name = data["old_name"]
        new_name = data["new_name"]
        
        new_name = "".join(c for c in new_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        if not new_name:
            new_name = "clip"
        
        old_path = os.path.join(CLIP_DIR, old_name)
        base_new_path = os.path.join(CLIP_DIR, f"{new_name}.mp4")
        
        if not os.path.exists(old_path):
            return jsonify({"error": "File not found"}), 404
        
        counter = 1
        new_path = base_new_path
        while os.path.exists(new_path):
            new_path = os.path.join(CLIP_DIR, f"{new_name}_{counter}.mp4")
            counter += 1
        
        os.rename(old_path, new_path)
        new_filename = os.path.basename(new_path)
        
        return jsonify({
            "success": True,
            "new_path": f"/clips/{new_filename}"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/cleanup", methods=["POST"])
def cleanup_files():
    try:
        current_time = time.time()
        deleted_files = []
        
        for directory in [DOWNLOAD_DIR, CLIP_DIR]:
            for filename in os.listdir(directory):
                filepath = os.path.join(directory, filename)
                if os.path.getmtime(filepath) < current_time - 86400:  # 24 hours
                    try:
                        os.remove(filepath)
                        deleted_files.append(filename)
                    except OSError as e:
                        app.logger.error(f"Failed to delete {filename}: {e}")
                        
        return jsonify({
            "message": "Cleanup completed successfully",
            "deleted_files": deleted_files
        })
    except Exception as e:
        return jsonify({"error": f"Cleanup failed: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host='127.0.0.1', port=5000)
