"""
File browser and web interface utilities.
"""

import os
import re
import mimetypes
from flask import Response, request, make_response, redirect, url_for
from flask.views import MethodView
from werkzeug.utils import secure_filename
from pathlib2 import Path
import json

from ..utils.formatters import get_type
from ..qpu.monitoring import get_qibo_versions
from ..web.reports import report_viewer


def is_qibocal_report(directory_path):
    """
    Check if a directory is a qibocal report by looking for required files.
    
    A qibocal report directory must contain both:
    - meta.json
    - runcard.yml
    
    Args:
        directory_path (str): Path to the directory to check
        
    Returns:
        bool: True if directory contains qibocal report files, False otherwise
    """
    if not os.path.isdir(directory_path):
        return False
    
    try:
        meta_json_path = os.path.join(directory_path, "meta.json")
        runcard_yml_path = os.path.join(directory_path, "runcard.yml")
        
        return os.path.isfile(meta_json_path) and os.path.isfile(runcard_yml_path)
    except (PermissionError, OSError):
        # If we can't access the directory, assume it's not a qibocal report
        return False


def partial_response(path, start, end=None):
    """Generate partial HTTP response for file streaming."""
    file_size = os.path.getsize(path)

    if end is None:
        end = file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1

    with open(path, 'rb') as fd:
        fd.seek(start)
        bytes_data = fd.read(length)
    assert len(bytes_data) == length

    response = Response(
        bytes_data,
        206,
        mimetype=mimetypes.guess_type(path)[0],
        direct_passthrough=True,
    )
    response.headers.add(
        'Content-Range', 'bytes {0}-{1}/{2}'.format(
            start, end, file_size,
        ),
    )
    response.headers.add(
        'Accept-Ranges', 'bytes'
    )
    return response


def get_range(request):
    """Parse HTTP Range header."""
    range_header = request.headers.get('Range')
    m = re.match('bytes=(?P<start>\d+)-(?P<end>\d+)?', range_header)
    if m:
        start = m.group('start')
        end = m.group('end')
        start = int(start)
        if end is not None:
            end = int(end)
        return start, end
    else:
        return 0, None


class PathView(MethodView):
    """
    File browser functionality based on flask-file-server by Wildog
    https://github.com/Wildog/flask-file-server
    
    Enhanced with quantum computing dashboard integration
    """
    
    def __init__(self, root_path, key=""):
        self.root = root_path
        self.key = key
        self.ignored = ['.bzr', '$RECYCLE.BIN', '.DAV', '.DS_Store', '.git', '.hg', 
                       '.htaccess', '.htpasswd', '.Spotlight-V100', '.svn', '__MACOSX', 
                       'ehthumbs.db', 'robots.txt', 'Thumbs.db', 'thumbs.tps']
    
    def get(self, p=''):
        from flask import render_template, send_file
        
        hide_dotfile = request.args.get('hide-dotfile', request.cookies.get('hide-dotfile', 'no'))

        path = os.path.join(self.root, p)

        if os.path.isdir(path):
            # Check if this directory is a qibocal report
            if is_qibocal_report(path):
                # Use report viewer instead of directory listing
                try:
                    version_data = get_qibo_versions(request=request)
                    response = report_viewer(path, self.root, version_data['versions'], access_mode="file_browser")
                    
                    # Set cookie if we have fresh data
                    if not version_data.get('from_cache', False):
                        response.set_cookie('qibo_versions', 
                                          version_data['cookie_data'],
                                          max_age=24*60*60,  # 24 hours
                                          httponly=True,
                                          secure=False)
                    
                    return response
                except Exception as e:
                    # If report viewer fails, fall back to regular directory listing
                    # but add a warning message
                    pass
            
            # Regular directory listing
            contents = []
            total = {'size': 0, 'dir': 0, 'file': 0}

            for filename in os.listdir(path):
                if filename in self.ignored:
                    continue
                if hide_dotfile == 'yes' and filename[0] == '.':
                    continue
                filepath = os.path.join(path, filename)
                
                try:
                    stat_res = os.stat(filepath)
                except (PermissionError, OSError):
                    # Skip files/directories we can't access
                    continue
                    
                info = {}
                info['name'] = filename
                info['mtime'] = stat_res.st_mtime
                ft = get_type(stat_res.st_mode)
                info['type'] = ft
                
                # Check if this directory is a qibocal report
                if ft == 'dir' and is_qibocal_report(filepath):
                    info['is_qibocal_report'] = True
                else:
                    info['is_qibocal_report'] = False
                
                total[ft] += 1
                sz = stat_res.st_size
                info['size'] = sz
                total['size'] += sz
                contents.append(info)
          
            qibo_versions = get_qibo_versions(request=request)
            response = make_response(render_template('file_browser.html', 
                                   path=p, 
                                   contents=contents, 
                                   total=total, 
                                   hide_dotfile=hide_dotfile, 
                                   qibo_versions=qibo_versions['versions']), 
                                200)

            response.set_cookie('hide-dotfile', hide_dotfile, max_age=16070400, httponly=True, secure=False)
            
            # Set cookie if we have fresh data
            if not qibo_versions.get('from_cache', False):
                response.set_cookie('qibo_versions',
                                    qibo_versions['cookie_data'], 
                                    max_age=24*60*60,
                                    httponly=True,
                                    secure=False)

        elif os.path.isfile(path):
            # Check if this is an index.html file in a qibocal report directory
            if os.path.basename(path).lower() == 'index.html':
                parent_dir = os.path.dirname(path)
                if is_qibocal_report(parent_dir):
                    # Redirect to the report viewer for the parent directory
                    try:
                        version_data = get_qibo_versions(request=request)
                        response = report_viewer(parent_dir, self.root, version_data['versions'], access_mode="file_browser")
                        
                        # Set cookie if we have fresh data
                        if not version_data.get('from_cache', False):
                            response.set_cookie('qibo_versions', 
                                              version_data['cookie_data'],
                                              max_age=24*60*60,  # 24 hours
                                              httponly=True,
                                              secure=False)
                        
                        return response
                    except Exception as e:
                        # If report viewer fails, fall back to regular file serving
                        pass
            
            # Regular file serving
            if 'Range' in request.headers:
                start, end = get_range(request)
                response = partial_response(path, start, end)
            else:
                filename, file_extension = os.path.splitext(path)
                if file_extension in ['.html', '.yml', '.json']:
                    response = send_file(path)
                else:
                    response = send_file(path, as_attachment=True, download_name=os.path.basename(path))
        else:
            response = make_response('Not found', 404)
        return response
    
    def put(self, p=''):
        if request.cookies.get('auth_cookie') == self.key:
            path = os.path.join(self.root, p)
            dir_path = os.path.dirname(path)
            Path(dir_path).mkdir(parents=True, exist_ok=True)

            info = {}
            if os.path.isdir(dir_path):
                try:
                    with open(path, 'wb') as f:
                        f.write(request.stream.read())
                except Exception as e:
                    info['status'] = 'error'
                    info['msg'] = str(e)
                else:
                    info['status'] = 'success'
                    info['msg'] = 'File Saved'
            else:
                info['status'] = 'error'
                info['msg'] = 'Invalid Operation'
            res = make_response(json.JSONEncoder().encode(info), 201)
            res.headers.add('Content-type', 'application/json')
        else:
            info = {} 
            info['status'] = 'error'
            info['msg'] = 'Authentication failed'
            res = make_response(json.JSONEncoder().encode(info), 401)
            res.headers.add('Content-type', 'application/json')
        return res

    def post(self, p=''):
        if request.cookies.get('auth_cookie') == self.key:
            path = os.path.join(self.root, p)
            Path(path).mkdir(parents=True, exist_ok=True)
    
            info = {}
            if os.path.isdir(path):
                files = request.files.getlist('files[]')
                for file in files:
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        file.save(os.path.join(path, filename))
                info['status'] = 'success'
                info['msg'] = 'Files Saved'
            else:
                info['status'] = 'error'
                info['msg'] = 'Invalid Operation'
        else:
            info = {} 
            info['status'] = 'error'
            info['msg'] = 'Authentication failed'
            res = make_response(json.JSONEncoder().encode(info), 200)
            res.headers.add('Content-type', 'application/json')
        return res    
    
    def delete(self, p=''):
        if request.cookies.get('auth_cookie') == self.key:
            path = os.path.join(self.root, p)
            dir_path = os.path.dirname(path)
            Path(dir_path).mkdir(parents=True, exist_ok=True)

            info = {}
            if os.path.isdir(dir_path):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    else:
                        os.rmdir(dir_path)
                except Exception as e:
                    info['status'] = 'error'
                    info['msg'] = str(e)
                else:
                    info['status'] = 'success'
                    info['msg'] = 'File Deleted'
            else:
                info['status'] = 'error'
                info['msg'] = 'Invalid Operation'
            res = make_response(json.JSONEncoder().encode(info), 204)
            res.headers.add('Content-type', 'application/json')
        else:
            info = {}
            info['status'] = 'error'
            info['msg'] = 'Authentication failed'
            res = make_response(json.JSONEncoder().encode(info), 401)
            res.headers.add('Content-type', 'application/json')
        return res
