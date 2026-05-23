"""
File and data formatting utilities for QDashboard.
"""

import os
import stat
import mimetypes
import json
import yaml
from datetime import datetime

try:
    from humanize import naturaltime
except ImportError:
    # Fallback if humanize is not available
    def naturaltime(dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S')


def size_fmt(size):
    """Format file size in human readable format."""
    for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def time_desc(timestamp):
    """Format timestamp to human readable time description."""
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def time_humanize(timestamp):
    """Humanize timestamp (e.g., '2 hours ago')."""
    dt = datetime.fromtimestamp(timestamp)
    return naturaltime(dt)


def data_fmt(filename):
    """Get data type for file based on extension."""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    datatypes = {
        'audio': ['m4a', 'mp3', 'oga', 'ogg', 'webma', 'wav'],
        'archive': ['7z', 'zip', 'rar', 'gz', 'tar', 'npz'],
        'image': ['gif', 'ico', 'jpe', 'jpeg', 'jpg', 'png', 'svg', 'webp'],
        'pdf': ['pdf'],
        'quicktime': ['3g2', '3gp', '3gp2', '3gpp', 'mov', 'qt'],
        'source': ['atom', 'bat', 'bash', 'c', 'cmd', 'coffee', 'css', 'html', 'js', 'json', 'java', 'less', 'markdown', 'md', 'php', 'pl', 'py', 'rb', 'rss', 'sass', 'scpt', 'swift', 'scss', 'sh', 'xml', 'yml', 'plist'],
        'text': ['txt'],
        'video': ['mp4', 'm4v', 'ogv', 'webm'],
        'website': ['htm', 'html', 'mhtm', 'mhtml', 'xhtm', 'xhtml']
    }
    
    for data_type, extensions in datatypes.items():
        if ext in extensions:
            return data_type
    return 'file'


def icon_fmt(filename):
    """Get FontAwesome icon class for file based on extension."""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    icontypes = {
        'fa-music': ['m4a', 'mp3', 'oga', 'ogg', 'webma', 'wav'],
        'fa-archive': ['7z', 'zip', 'rar', 'gz', 'tar'],
        'fa-picture-o': ['gif', 'ico', 'jpe', 'jpeg', 'jpg', 'png', 'svg', 'webp'],
        'fa-file-text': ['pdf'],
        'fa-film': ['3g2', '3gp', '3gp2', '3gpp', 'mov', 'qt', 'mp4', 'm4v', 'ogv', 'webm'],
        'fa-code': ['atom', 'plist', 'bat', 'bash', 'c', 'cmd', 'coffee', 'css', 'html', 'js', 'json', 'java', 'less', 'markdown', 'md', 'php', 'pl', 'py', 'rb', 'rss', 'sass', 'scpt', 'swift', 'scss', 'sh', 'xml', 'yml'],
        'fa-file-text-o': ['txt'],
        'fa-globe': ['htm', 'html', 'mhtm', 'mhtml', 'xhtm', 'xhtml']
    }
    
    for icon_class, extensions in icontypes.items():
        if ext in extensions:
            return icon_class
    return 'fa-file-o'


def get_type(mode):
    """Get file type from stat mode."""
    if stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        return 'dir'
    else:
        return 'file'


def yaml_response(data):
    from starlette.responses import Response
    return Response(content=yaml.dump(data), status_code=200, media_type='application/x-yaml')


def json_response(data):
    """Format JSON as HTTP response."""
    from starlette.responses import Response
    return Response(content=json.dumps(data), status_code=200, media_type='application/json')
