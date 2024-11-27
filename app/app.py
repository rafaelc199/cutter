from flask import Flask, request, jsonify, render_template, send_from_directory
import yt_dlp
import os
import sys
import uuid
import time
import re

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024  # 16GB max-size
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Desabilitar cache

# Create base directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
CLIP_DIR = os.path.join(BASE_DIR, "clips")

# Create necessary directories
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CLIP_DIR, exist_ok=True)

# Após criar os diretórios
os.chmod(DOWNLOAD_DIR, 0o755)
os.chmod(CLIP_DIR, 0o755)

# Route to serve the front-end
@app.route("/")
def home():
    return render_template("index.html")  # Flask will look for this in templates/

# Adicionar rota para servir os vídeos baixados
@app.route('/downloads/<path:filename>')
def download_file(filename):
    try:
        # Usar send_from_directory com o caminho absoluto
        return send_from_directory(
            DOWNLOAD_DIR, 
            filename,
            as_attachment=False,  # Para reproduzir no navegador
            mimetype='video/mp4'  # Definir explicitamente o tipo MIME
        )
    except Exception as e:
        app.logger.error(f"Error serving video file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

@app.route('/clips/<path:filename>')
def serve_clip(filename):
    try:
        # Usar send_from_directory com o caminho absoluto e configurações corretas
        response = send_from_directory(
            CLIP_DIR,
            filename,
            as_attachment=False,
            mimetype='video/mp4',
            conditional=True  # Habilita suporte a streaming
        )
        
        # Adicionar headers necessários para streaming de vídeo
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Cache-Control'] = 'no-cache'
        return response
        
    except Exception as e:
        app.logger.error(f"Error serving clip file: {str(e)}")
        return jsonify({"error": "File not found"}), 404

def extract_video_id(url):
    """Extract video ID from YouTube URL"""
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
    """Downloads YouTube video using yt-dlp with improved configuration"""
    try:
        # Generate unique filename
        filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]',  # Modificada a ordem dos formatos
            'outtmpl': output_path,
            'quiet': True,  # Reduzir logs
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
        
        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise Exception("Could not extract video information")
                
                # Verificar se o arquivo foi criado
                if not os.path.exists(output_path):
                    raise Exception("Video file was not created")
                
                return {
                    "file_path": f"/downloads/{filename}",  # URL relativa para o frontend
                    "absolute_path": output_path,  # Caminho absoluto para uso interno
                    "title": info.get('title', 'Unknown Title'),
                    "duration": info.get('duration', 0),
                    "channel": info.get('uploader', 'Unknown Channel')
                }
            except Exception as download_error:
                print(f"Download error: {str(download_error)}")
                raise Exception(f"Download process failed: {str(download_error)}")
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error in download_video_ytdlp: {error_msg}")
        raise Exception(f"Download failed: {error_msg}")

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
            "file_path": result["file_path"],  # URL relativa para o frontend
            "absolute_path": result["absolute_path"],  # Caminho absoluto para uso interno
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

@app.route("/clip", methods=["POST"])
def clip_video():
    try:
        from moviepy.editor import VideoFileClip
        
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
            
        data = request.get_json()
        video_path = data.get("file_path")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if not all([video_path, start_time is not None, end_time is not None]):
            return jsonify({"error": "Missing required parameters"}), 400

        # Converter o caminho relativo para absoluto
        if video_path.startswith('/downloads/'):
            video_path = os.path.join(DOWNLOAD_DIR, os.path.basename(video_path))

        try:
            start_time = float(start_time)
            end_time = float(end_time)
        except ValueError:
            return jsonify({"error": "Invalid time format"}), 400
        
        if start_time < 0 or end_time <= start_time:
            return jsonify({"error": "Invalid time values"}), 400

        if not os.path.exists(video_path):
            return jsonify({"error": "Video file not found"}), 404

        clip_filename = f"clip_{uuid.uuid4()}.mp4"
        clip_output_path = os.path.join(CLIP_DIR, clip_filename)

        with VideoFileClip(video_path) as video:
            if end_time > video.duration:
                return jsonify({"error": "End time exceeds video duration"}), 400
                
            clip = video.subclip(start_time, end_time)
            clip.write_videofile(
                clip_output_path,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=os.path.join(CLIP_DIR, "temp-audio.m4a"),
                remove_temp=True,
                threads=4,  # Usar múltiplas threads para melhor performance
                preset='ultrafast'  # Codificação mais rápida
            )
            
        # Garantir que o arquivo tem as permissões corretas
        os.chmod(clip_output_path, 0o644)

        # Verificar se o arquivo foi criado e é acessível
        if not os.path.exists(clip_output_path):
            raise Exception("Failed to create clip file")

        return jsonify({
            "message": "Video clipped successfully",
            "clip_path": f"/clips/{clip_filename}"  # URL relativa para o frontend
        })

    except ModuleNotFoundError:
        return jsonify({"error": "Required video processing module not found. Please install moviepy."}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to create clip: {str(e)}"}), 500

@app.route("/cleanup", methods=["POST"])
def cleanup_files():
    """Remove files older than 24 hours"""
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
