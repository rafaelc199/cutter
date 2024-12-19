# Standard library imports
import io
import logging
import os
import subprocess
import zipfile
from typing import Optional, Any, cast, Dict
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import shutil

# Third-party imports
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from dotenv import load_dotenv
import yt_dlp

# Local imports
from models import db, User
from forms import LoginForm, RegistrationForm

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables from .flaskenv
load_dotenv('.flaskenv')

app = Flask(__name__)
app.static_folder = 'static'

# Flask configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-123')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_EXTENSIONS'] = ['.mp4', '.avi', '.mov']
app.config['FILE_CLEANUP_AGE'] = timedelta(hours=24)

# Initialize extensions
db.init_app(app)

# Create database tables
with app.app_context():
    db.create_all()

# Configure login manager
login_manager = LoginManager()
login_manager.init_app(app)
setattr(login_manager, 'login_view', 'login')  # type: ignore

@login_manager.user_loader
def load_user(user_id: str) -> Optional[UserMixin]:
    """Load user by ID."""
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user: Optional[User] = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Logged in successfully.')
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    """Handle user logout."""
    logout_user()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Handle user registration."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/')
def index():
    """Home page."""
    return render_template('index.html')

def cleanup_old_files():
    """Remove files older than FILE_CLEANUP_AGE"""
    try:
        cutoff = datetime.now() - app.config['FILE_CLEANUP_AGE']
        
        # Cleanup downloads
        downloads_dir = os.path.join(app.root_path, 'downloads')
        processed_dir = os.path.join(app.root_path, 'static', 'processed')
        
        for directory in [downloads_dir, processed_dir]:
            if os.path.exists(directory):
                for user_dir in os.listdir(directory):
                    user_path = os.path.join(directory, user_dir)
                    if os.path.isdir(user_path):
                        for filename in os.listdir(user_path):
                            filepath = os.path.join(user_path, filename)
                            file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                            if file_time < cutoff:
                                if os.path.isfile(filepath):
                                    os.remove(filepath)
                                elif os.path.isdir(filepath):
                                    shutil.rmtree(filepath)
        
    except Exception as e:
        logger.error(f"Error cleaning up files: {e}")

def cleanup_user_files(user_id: int, video_path: Optional[str] = None):
    """Clean up user's processed files.
    
    Args:
        user_id: The user's ID
        video_path: Optional specific video path to clean up related files
    """
    try:
        processed_dir = os.path.join(app.root_path, 'static', 'processed', str(user_id))
        if not os.path.exists(processed_dir):
            return
            
        video_basename = os.path.basename(video_path) if video_path else None
        
        for filename in os.listdir(processed_dir):
            file_path = os.path.join(processed_dir, filename)
            # Se video_basename for fornecido, remover apenas arquivos relacionados a este vídeo
            if video_basename:
                # Remover timestamp do nome do arquivo para comparação
                cleaned_filename = '_'.join(filename.split('_')[2:]) if filename.count('_') >= 2 else filename
                if video_basename not in cleaned_filename:
                    continue
                    
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not remove file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error in cleanup_user_files: {e}")

@app.route('/process_video', methods=['POST'])
@login_required
def process_video():
    """Process uploaded YouTube video."""
    if not request.content_length:
        flash('No content received')
        return redirect(url_for('index'))
        
    if request.content_length > app.config['MAX_CONTENT_LENGTH']:
        flash('File too large')
        return redirect(url_for('index'))
    
    youtube_url = request.form.get('youtube_url', '').strip()
    if not youtube_url:
        flash('Please provide a YouTube URL')
        return redirect(url_for('index'))
    
    try:
        # Setup directories
        base_dir = os.path.abspath(os.path.dirname(__file__))
        user_download_dir = os.path.join(base_dir, 'downloads', str(current_user.id))
        os.makedirs(user_download_dir, exist_ok=True)
        
        logger.debug("Processing video from URL: %s", youtube_url)
        logger.debug("Download directory: %s", user_download_dir)
        
        # Configure yt-dlp with error checking
        try:
            ydl_opts = {
                'format': 'best',
                'outtmpl': os.path.join(user_download_dir, '%(title)s.%(ext)s'),
                'verbose': True,
                'merge_output_format': 'mp4'
            }
            
            # Download video
            ydl = yt_dlp.YoutubeDL(ydl_opts)
            logger.debug("Starting video download...")
            info = ydl.extract_info(youtube_url, download=True)
            if not info:
                raise ValueError("Failed to extract video information")
                
            video_title = str(info.get('title', ''))
            if not video_title:
                raise ValueError("Failed to get video title")
            
            # Ensure path uses correct separator and has extension
            video_path = f"{current_user.id}/{video_title}.mp4"
            video_path = video_path.replace('\\', '/')
            
            full_path = os.path.join(base_dir, 'downloads', str(current_user.id), f'{video_title}.mp4')
            logger.debug("Video downloaded to: %s", full_path)
            
            # Verify file exists and has content
            if not os.path.exists(full_path):
                raise FileNotFoundError(f"Downloaded file not found: {full_path}")
                
            file_size = os.path.getsize(full_path)
            if file_size == 0:
                raise ValueError(f"Downloaded file is empty: {full_path}")
                
            logger.debug("File exists and size is: %s bytes", file_size)
            
            flash(f'Video "{video_title}" downloaded successfully!')
            return redirect(url_for('edit_video', video_path=video_path))
                
        except yt_dlp.DownloadError as e:
            raise ValueError(f"Failed to download video: {str(e)}")
            
    except ValueError as e:
        logger.error("Value error in video processing: %s", str(e))
        flash(f'Error processing video: {str(e)}')
        return redirect(url_for('index'))
    except FileNotFoundError as e:
        logger.error("File error in video processing: %s", str(e))
        flash(f'Error with video file: {str(e)}')
        return redirect(url_for('index'))
    except Exception as e:
        logger.error("Unexpected error in video processing: %s", str(e), exc_info=True)
        flash('An unexpected error occurred while processing the video')
        return redirect(url_for('index'))

@app.route('/edit/<path:video_path>')
@login_required
def edit_video(video_path):
    """Video editing page."""
    # Limpar apenas os arquivos relacionados ao vídeo atual
    cleanup_user_files(current_user.id, video_path)
    return render_template('edit_video.html', video_path=video_path)

@app.route('/api/edit-video', methods=['POST'])
@login_required
def edit_video_api():
    """Handle video editing API requests.
    
    Returns:
        JSON response with success status and video URL or error message.
    
    Raises:
        400: If request data is invalid
        500: If video processing fails
    """
    try:
        # Validate request data
        data = cast(Dict[str, Any], request.get_json())
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        # Extract and validate parameters
        try:
            video_path = str(data['videoPath']).strip()
            if not video_path:
                raise ValueError("Video path cannot be empty")
                
            start_time = float(data['startTime'])
            if start_time < 0:
                raise ValueError("Start time cannot be negative")
                
            end_time = float(data['endTime'])
            if end_time <= start_time:
                raise ValueError("End time must be greater than start time")
                
            resolution = str(data['resolution'])
            if resolution != 'original' and not resolution.endswith('p'):
                raise ValueError("Invalid resolution format")
                
        except (KeyError, ValueError, TypeError) as e:
            return jsonify({
                'success': False,
                'error': f'Invalid data: {str(e)}'
            }), 400
        
        # Create output directory
        base_dir = os.path.abspath(os.path.dirname(__file__))
        output_dir = os.path.join('static', 'processed', str(current_user.id))
        os.makedirs(output_dir, exist_ok=True)
        
        # Gerar nome único para o arquivo de saída
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f'edited_{timestamp}_{os.path.basename(video_path)}'
        output_path = os.path.join(output_dir, output_filename)
        
        # Remover versões anteriores do mesmo vídeo
        for old_file in os.listdir(output_dir):
            if old_file.startswith('edited_') and old_file.endswith(os.path.basename(video_path)):
                old_path = os.path.join(output_dir, old_file)
                try:
                    os.remove(old_path)
                except Exception as e:
                    logger.warning(f"Could not remove old file {old_path}: {e}")
        
        # Validate input video exists
        input_path = os.path.join(base_dir, 'downloads', video_path)
        if not os.path.exists(input_path):
            return jsonify({
                'success': False,
                'error': 'Input video file not found'
            }), 404
        
        try:
            # Build FFmpeg command
            command = ['ffmpeg', '-i', input_path, '-ss', str(start_time), '-to', str(end_time)]
            
            # Add resolution parameters if not original
            if resolution != 'original':
                try:
                    height = int(resolution.replace('p', ''))
                    command.extend(['-vf', f'scale=-2:{height}'])
                except ValueError:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid resolution value'
                    }), 400
            
            # Add output path and overwrite flag
            command.extend(['-y', output_path])
            
            # Execute FFmpeg command
            logger.debug("Running FFmpeg command: %s", ' '.join(command))
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Verify output file was created
            if not os.path.exists(output_path):
                raise FileNotFoundError("FFmpeg failed to create output file")
                
            if os.path.getsize(output_path) == 0:
                raise ValueError("FFmpeg created an empty output file")
            
            # Return success response
            video_url = url_for('static', filename=f'processed/{current_user.id}/{output_filename}')
            return jsonify({
                'success': True,
                'videoUrl': video_url
            })
            
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg error: %s", e.stderr)
            return jsonify({
                'success': False,
                'error': f'FFmpeg error: {e.stderr}'
            }), 500
            
        except (FileNotFoundError, ValueError) as e:
            logger.error("File processing error: %s", str(e))
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
            
    except Exception as e:
        logger.error("Unexpected error in edit_video_api: %s", str(e), exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500

@app.route('/api/generate-clips', methods=['POST'])
@login_required
def generate_clips():
    try:
        data = cast(Dict[str, Any], request.get_json())
        logger.debug("Received data: %s", data)
        
        if not data:
            raise ValueError("No JSON data received")
            
        # Obter o video_path do request
        video_path = str(data.get('videoPath', '')).strip()
        if not video_path:
            raise ValueError("Video path is required")
            
        clips = cast(list[Dict[str, Any]], data.get('clips', []))
        logger.debug("Clips data: %s", clips)
        
        if not clips:
            raise ValueError("No clips data provided")
        
        base_dir = os.path.abspath(os.path.dirname(__file__))
        generated_clips: list[str] = []
        
        # Usar o video_path específico em vez de procurar por qualquer arquivo MP4
        input_video_path = os.path.join(base_dir, 'downloads', video_path)
        if not os.path.exists(input_video_path):
            raise FileNotFoundError(f"Input video not found: {input_video_path}")
            
        logger.debug("Input video path: %s", input_video_path)
        
        for clip in clips:
            logger.debug("Processing clip: %s", clip)
            
            # Validate clip data
            required_keys = ['name', 'startTime', 'endTime']
            if not all(key in clip for key in required_keys):
                raise ValueError(f"Missing required clip data. Required: {required_keys}. Received: {clip}")
            
            # Convert MM:SS to seconds for FFmpeg
            try:
                start_time_str = str(clip.get('startTime', ''))
                end_time_str = str(clip.get('endTime', ''))
                
                if not start_time_str or not end_time_str:
                    raise ValueError("Start time and end time cannot be empty")
                
                start_minutes, start_seconds = map(int, start_time_str.split(':'))
                end_minutes, end_seconds = map(int, end_time_str.split(':'))
                
                start_time = start_minutes * 60 + start_seconds
                end_time = end_minutes * 60 + end_seconds
                
                if start_time < 0:
                    raise ValueError("Start time cannot be negative")
                if end_time <= start_time:
                    raise ValueError("End time must be greater than start time")
                
                logger.debug("Converted times - Start: %ss, End: %ss", start_time, end_time)
            except ValueError as e:
                logger.error("Error converting time format: %s", e)
                raise ValueError(f"Invalid time format. Expected MM:SS, got start={clip.get('startTime')}, end={clip.get('endTime')}")
            
            # Create output directory if it doesn't exist
            output_dir = os.path.join(base_dir, 'static', 'processed', str(current_user.id))
            os.makedirs(output_dir, exist_ok=True)
            logger.debug("Output directory: %s", output_dir)
            
            # Gerar nome único para o clip
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_name = "".join(c for c in clip.get('name', '') if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_name:
                safe_name = "clip"
                
            # Incluir o nome do vídeo original no nome do clip
            video_basename = os.path.splitext(os.path.basename(video_path))[0]
            output_filename = f"{safe_name}_{timestamp}_{video_basename}_{start_time}-{end_time}.mp4"
            
            # Build FFmpeg command for trimming
            command = [
                'ffmpeg',
                '-i', input_video_path,
                '-ss', str(start_time),
                '-t', str(end_time - start_time),  # Duration instead of end time
                '-c', 'copy',  # Use copy codec for faster processing
                '-y',  # Overwrite output file
                os.path.join(output_dir, output_filename)
            ]
            
            logger.debug("FFmpeg command: %s", ' '.join(command))
            
            try:
                # Execute FFmpeg command
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True
                )
                logger.debug("FFmpeg stdout: %s", result.stdout)
                logger.debug("FFmpeg stderr: %s", result.stderr)
                
                if not os.path.exists(os.path.join(output_dir, output_filename)):
                    raise FileNotFoundError(f"Output file was not created: {os.path.join(output_dir, output_filename)}")
                
                file_size = os.path.getsize(os.path.join(output_dir, output_filename))
                if file_size == 0:
                    raise ValueError(f"Generated clip is empty: {os.path.join(output_dir, output_filename)}")
                    
                logger.debug("Clip generated successfully: %s (size: %s bytes)", os.path.join(output_dir, output_filename), file_size)
                # Generate URL for the clip
                clip_url = url_for('serve_clip', user_id=current_user.id, filename=output_filename)
                generated_clips.append(clip_url)
                    
            except subprocess.CalledProcessError as e:
                error_msg = f"FFmpeg error: {e.stderr}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
        
        if not generated_clips:
            raise ValueError("No clips were generated")
            
        return jsonify({
            'success': True,
            'message': f'Generated {len(generated_clips)} clips successfully',
            'clips': generated_clips
        })
        
    except ValueError as e:
        logger.error("Value error in clip generation: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
    except FileNotFoundError as e:
        logger.error("File error in clip generation: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 404
    except RuntimeError as e:
        logger.error("Runtime error in clip generation: %s", str(e))
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    except Exception as e:
        logger.error("Unexpected error in clip generation: %s", str(e), exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred while generating clips'
        }), 500

@app.route('/api/download-clips', methods=['GET'])
@login_required
def download_clips():
    """Download all generated clips.
    
    Returns:
        A file response with the zip file containing all clips or an error response.
        
    Raises:
        FileNotFoundError: If clips directory or files are not found
        IOError: If there are issues creating the zip file
    """
    try:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        clips_dir = os.path.join(base_dir, 'static', 'processed', str(current_user.id))
        
        # Verify clips directory exists
        if not os.path.exists(clips_dir):
            logger.error("Clips directory not found: %s", clips_dir)
            return jsonify({
                'success': False,
                'error': 'No clips directory found'
            }), 404
        
        # Get list of clip files
        clip_files = [f for f in os.listdir(clips_dir) if f.endswith('.mp4')]
        if not clip_files:
            logger.error("No clips found in directory: %s", clips_dir)
            return jsonify({
                'success': False,
                'error': 'No clips found to download'
            }), 404
        
        # Create a BytesIO object to store the zip file
        memory_file = io.BytesIO()
        
        # Create a zip file
        try:
            with zipfile.ZipFile(memory_file, 'w') as zf:
                for filename in clip_files:
                    file_path = os.path.join(clips_dir, filename)
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        if file_size == 0:
                            logger.warning("Empty clip file found: %s", file_path)
                            continue
                            
                        logger.debug("Adding file to zip: %s (size: %s bytes)", filename, file_size)
                        zf.write(file_path, filename)
                    else:
                        logger.warning("Clip file not found: %s", file_path)
                        
            # Check if any files were added to the zip
            if memory_file.tell() == 0:
                logger.error("No valid clips were added to the zip file")
                return jsonify({
                    'success': False,
                    'error': 'No valid clips to download'
                }), 404
                
            # Seek to the beginning of the BytesIO object
            memory_file.seek(0)
            
            logger.debug("Zip file created successfully with %d clips", len(clip_files))
            return send_file(
                memory_file,
                mimetype='application/zip',
                as_attachment=True,
                download_name='video_clips.zip'
            )
            
        except (IOError, zipfile.BadZipFile) as e:
            logger.error("Error creating zip file: %s", str(e))
            return jsonify({
                'success': False,
                'error': 'Error creating zip file'
            }), 500
            
    except Exception as e:
        logger.error("Unexpected error in download_clips: %s", str(e), exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred while downloading clips'
        }), 500

@app.route('/downloads/<path:filename>')
@login_required
def serve_video(filename: str):
    """Serve downloaded video files.
    
    Args:
        filename: The name of the video file to serve.
        
    Returns:
        The video file response or an error message.
    """
    try:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        file_path = os.path.join(base_dir, 'downloads', filename)
        
        logger.debug("Request to serve video: %s", filename)
        logger.debug("Base directory: %s", base_dir)
        logger.debug("Full video path: %s", file_path)
        
        if not os.path.exists(file_path):
            logger.error("File not found: %s", file_path)
            return "File not found", 404
            
        logger.debug("File exists: %s", file_path)
        logger.debug("File size: %s bytes", os.path.getsize(file_path))
        
        return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path))
    except Exception as e:
        error_msg = str(e)
        logger.error("Error serving video: %s", error_msg)
        return error_msg, 500

@app.route('/clip/<int:user_id>/<path:filename>')
@login_required
def serve_clip(user_id: int, filename: str):
    """Serve a processed clip.
    
    Args:
        user_id: The ID of the user requesting the clip.
        filename: The name of the clip file to serve.
        
    Returns:
        The clip file response or an error message.
    """
    if user_id != current_user.id:
        return "Unauthorized", 403
        
    try:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        clips_dir = os.path.join(base_dir, 'static', 'processed', str(user_id))
        
        if not os.path.exists(clips_dir):
            raise FileNotFoundError(f"Clips directory not found: {clips_dir}")
            
        file_path = os.path.join(clips_dir, filename)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Clip file not found: {file_path}")
            
        return send_from_directory(clips_dir, filename)
    except Exception as e:
        error_msg = str(e)
        logger.error("Error serving clip: %s", error_msg)
        return error_msg, 500

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1') 