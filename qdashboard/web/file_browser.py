"""
File browser and web interface utilities.
"""

import os
import pathlib
import re
import json
import mimetypes
from pathlib2 import Path
from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import FileResponse, Response
from starlette.responses import HTMLResponse

from ..utils.formatters import get_type
from ..qpu.monitoring import get_qibo_versions
from ..web.reports import report_viewer


def is_qibocal_report(directory_path):
    """
    Check if a directory is a qibocal report by looking for required files.

    A qibocal report directory must contain both:
    - meta.json
    - runcard.yml
    """
    if not os.path.isdir(directory_path):
        return False
    try:
        return (os.path.isfile(os.path.join(directory_path, "meta.json")) and
                os.path.isfile(os.path.join(directory_path, "runcard.yml")))
    except (PermissionError, OSError):
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

    headers = {
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Type': mimetypes.guess_type(path)[0] or 'application/octet-stream',
    }
    return Response(content=bytes_data, status_code=206, headers=headers)


def get_range(request: Request):
    """Parse HTTP Range header."""
    range_header = request.headers.get('Range', '')
    m = re.match(r'bytes=(?P<start>\d+)-(?P<end>\d+)?', range_header)
    if m:
        start = int(m.group('start'))
        end = int(m.group('end')) if m.group('end') else None
        return start, end
    return 0, None


def make_file_router(root_path: str, key: str = "") -> APIRouter:
    """Return an APIRouter with all file-browser endpoints configured."""

    router = APIRouter()
    ignored = ['.bzr', '$RECYCLE.BIN', '.DAV', '.DS_Store', '.git', '.hg',
               '.htaccess', '.htpasswd', '.Spotlight-V100', '.svn', '__MACOSX',
               'ehthumbs.db', 'robots.txt', 'Thumbs.db', 'thumbs.tps']

    _resolved_root = os.path.realpath(root_path)

    def _safe_join(p: str):
        """Return the real absolute path for *p* inside root_path, or None if it escapes."""
        candidate = os.path.realpath(os.path.join(root_path, p))
        if candidate != _resolved_root and not candidate.startswith(_resolved_root + os.sep):
            return None
        return candidate

    async def _handle_get(request: Request, p: str):
        from ..core.app import templates

        hide_dotfile = request.query_params.get(
            'hide-dotfile', request.cookies.get('hide-dotfile', 'no'))

        path = _safe_join(p)
        if path is None:
            return Response(content='Forbidden', status_code=403)

        if os.path.isdir(path):
            # Qibocal report directory — render as report
            if is_qibocal_report(path):
                try:
                    version_data = get_qibo_versions(request=request)
                    response = report_viewer(path, root_path, request, version_data['versions'],
                                            access_mode="file_browser")
                    if not version_data.get('from_cache', False):
                        response.set_cookie('qibo_versions', version_data['cookie_data'],
                                            max_age=24 * 60 * 60, httponly=True, secure=False)
                    return response
                except Exception:
                    pass  # fall through to directory listing

            contents = []
            total = {'size': 0, 'dir': 0, 'file': 0}
            for filename in os.listdir(path):
                if filename in ignored:
                    continue
                if hide_dotfile == 'yes' and filename[0] == '.':
                    continue
                filepath = os.path.join(path, filename)
                try:
                    stat_res = os.stat(filepath)
                except (PermissionError, OSError):
                    continue
                info = {
                    'name': filename,
                    'mtime': stat_res.st_mtime,
                    'type': get_type(stat_res.st_mode),
                    'size': stat_res.st_size,
                    'is_qibocal_report': False,
                }
                ft = info['type']
                if ft == 'dir' and is_qibocal_report(filepath):
                    info['is_qibocal_report'] = True
                total[ft] += 1
                total['size'] += stat_res.st_size
                contents.append(info)

            qibo_versions = get_qibo_versions(request=request)
            html = templates.get_template('file_browser.html').render(
                request=request,
                path=p,
                contents=contents,
                total=total,
                hide_dotfile=hide_dotfile,
                qibo_versions=qibo_versions['versions'],
            )
            response = HTMLResponse(content=html, status_code=200)
            response.set_cookie('hide-dotfile', hide_dotfile,
                                max_age=16070400, httponly=True, secure=False)
            if not qibo_versions.get('from_cache', False):
                response.set_cookie('qibo_versions', qibo_versions['cookie_data'],
                                    max_age=24 * 60 * 60, httponly=True, secure=False)
            return response

        elif os.path.isfile(path):
            # index.html inside a qibocal report → render as report
            if os.path.basename(path).lower() == 'index.html':
                parent_dir = os.path.dirname(path)
                if is_qibocal_report(parent_dir):
                    try:
                        version_data = get_qibo_versions(request=request)
                        response = report_viewer(parent_dir, root_path, request, version_data['versions'],
                                                 access_mode="file_browser")
                        if not version_data.get('from_cache', False):
                            response.set_cookie('qibo_versions', version_data['cookie_data'],
                                                max_age=24 * 60 * 60, httponly=True, secure=False)
                        return response
                    except Exception:
                        pass

            # Range request
            if 'range' in request.headers or 'Range' in request.headers:
                start, end = get_range(request)
                return partial_response(path, start, end)

            _, ext = os.path.splitext(path)
            if ext.lower() in ['.html', '.yml', '.json']:
                return FileResponse(path)
            return FileResponse(path, filename=os.path.basename(path))
        else:
            return Response(content='Not found', status_code=404)

    @router.get('/files/', name='files_root')
    async def files_root(request: Request):
        return await _handle_get(request, '')

    @router.get('/files/{p:path}', name='path_view')
    async def path_view(request: Request, p: str):
        return await _handle_get(request, p)

    @router.put('/files/{p:path}', name='path_put')
    async def path_put(request: Request, p: str):
        if request.cookies.get('auth_cookie') != key:
            info = {'status': 'error', 'msg': 'Authentication failed'}
            return Response(content=json.dumps(info), status_code=401,
                            media_type='application/json')
        path = _safe_join(p)
        if path is None:
            return Response(content=json.dumps({'status': 'error', 'msg': 'Forbidden'}),
                            status_code=403, media_type='application/json')
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        try:
            body = await request.body()
            with open(path, 'wb') as f:
                f.write(body)
            info = {'status': 'success', 'msg': 'File Saved'}
        except Exception as e:
            info = {'status': 'error', 'msg': str(e)}
        return Response(content=json.dumps(info), status_code=201,
                        media_type='application/json')

    @router.post('/files/{p:path}', name='path_post')
    async def path_post(request: Request, p: str, files: list[UploadFile] = File(..., alias='files[]')):
        if request.cookies.get('auth_cookie') != key:
            info = {'status': 'error', 'msg': 'Authentication failed'}
            return Response(content=json.dumps(info), status_code=401,
                            media_type='application/json')
        path = _safe_join(p)
        if path is None:
            return Response(content=json.dumps({'status': 'error', 'msg': 'Forbidden'}),
                            status_code=403, media_type='application/json')
        Path(path).mkdir(parents=True, exist_ok=True)
        for file in files:
            if file and file.filename:
                filename = pathlib.Path(file.filename).name  # secure_filename(file.filename)
                contents = await file.read()
                with open(os.path.join(path, filename), 'wb') as f:
                    f.write(contents)
        info = {'status': 'success', 'msg': 'Files Saved'}
        return Response(content=json.dumps(info), status_code=200,
                        media_type='application/json')

    @router.delete('/files/{p:path}', name='path_delete')
    async def path_delete(request: Request, p: str):
        if request.cookies.get('auth_cookie') != key:
            info = {'status': 'error', 'msg': 'Authentication failed'}
            return Response(content=json.dumps(info), status_code=401,
                            media_type='application/json')
        path = _safe_join(p)
        if path is None:
            return Response(content=json.dumps({'status': 'error', 'msg': 'Forbidden'}),
                            status_code=403, media_type='application/json')
        dir_path = os.path.dirname(path)
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                os.rmdir(path)
            info = {'status': 'success', 'msg': 'File Deleted'}
        except Exception as e:
            info = {'status': 'error', 'msg': str(e)}
        return Response(content=json.dumps(info), status_code=204,
                        media_type='application/json')

    return router

