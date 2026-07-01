"""
File browser and web interface utilities.
"""

import os
import pathlib
import re
import json
import mimetypes
from pathlib2 import Path
from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response, RedirectResponse, JSONResponse

from ..utils.formatters import get_type, size_fmt, time_humanize, icon_fmt


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
        hide_dotfile = request.query_params.get(
            'hide-dotfile', request.cookies.get('hide-dotfile', 'no'))

        path = _safe_join(p)
        if path is None:
            raise HTTPException(403, detail='Forbidden')

        if os.path.isdir(path):
            # Qibocal report directories browse like any other folder now —
            # the Explorer panel adds an "open report" button (opening it as
            # a shell tab via /experiment_report_page/{id}) instead of this
            # route auto-rendering a full standalone report page.
            response = RedirectResponse(url=f"/?panel=explorer&path={p}", status_code=307)
            response.set_cookie('hide-dotfile', hide_dotfile,
                                max_age=16070400, httponly=True, secure=False)
            return response

        elif os.path.isfile(path):
            # Range request
            if 'range' in request.headers or 'Range' in request.headers:
                start, end = get_range(request)
                return partial_response(path, start, end)

            _, ext = os.path.splitext(path)
            if ext.lower() in ['.html', '.yml', '.json']:
                return FileResponse(path)
            return FileResponse(path, filename=os.path.basename(path))
        else:
            raise HTTPException(404, detail=f'File not found: {p}')

    @router.get('/api/files_list', name='api_files_list')
    async def api_files_list(request: Request):
        """JSON directory listing for the Explorer side panel (AJAX navigation)."""
        p = request.query_params.get('path', '')
        hide_dotfile = request.query_params.get(
            'hide-dotfile', request.cookies.get('hide-dotfile', 'no'))

        path = _safe_join(p)
        if path is None or not os.path.isdir(path):
            return JSONResponse({'error': 'Not a directory'}, status_code=404)

        contents = []
        total = {'size': 0, 'dir': 0, 'file': 0}
        for filename in sorted(os.listdir(path)):
            if filename in ignored:
                continue
            if hide_dotfile == 'yes' and filename[0] == '.':
                continue
            filepath = os.path.join(path, filename)
            try:
                stat_res = os.stat(filepath)
            except (PermissionError, OSError):
                continue
            ftype = get_type(stat_res.st_mode)
            info = {
                'name': filename,
                'type': ftype,
                'size': stat_res.st_size,
                'size_fmt': size_fmt(stat_res.st_size),
                'mtime': stat_res.st_mtime,
                'mtime_fmt': time_humanize(stat_res.st_mtime),
                'is_qibocal_report': ftype == 'dir' and is_qibocal_report(filepath),
                'icon_class': icon_fmt(filename) if ftype == 'file' else None,
            }
            total[ftype] += 1
            total['size'] += stat_res.st_size
            contents.append(info)

        # Directories first, then files — both alphabetical (matches the old table sort default).
        contents.sort(key=lambda e: (e['type'] != 'dir', e['name'].lower()))
        return JSONResponse({'path': p, 'contents': contents, 'total': total})

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

