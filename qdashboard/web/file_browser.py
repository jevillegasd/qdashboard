"""
File browser and web interface utilities.
"""

import os
import re
import mimetypes
from flask import Response, request, make_response
from flask.views import MethodView
from werkzeug.utils import secure_filename
from pathlib2 import Path
import json

from ..utils.formatters import get_type
from ..qpu.monitoring import get_qibo_versions


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
            contents = []
            total = {'size': 0, 'dir': 0, 'file': 0}

            for filename in os.listdir(path):
                if filename in self.ignored:
                    continue
                if hide_dotfile == 'yes' and filename[0] == '.':
                    continue
                filepath = os.path.join(path, filename)
                stat_res = os.stat(filepath)
                info = {}
                info['name'] = filename
                info['mtime'] = stat_res.st_mtime
                ft = get_type(stat_res.st_mode)
                info['type'] = ft
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
