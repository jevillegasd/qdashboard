#!/usr/bin/env python3
"""
QDashboard - Quantum Computing Dashboard

A professional quantum computing dashboard with file browsing, experiment monitoring, 
QPU status tracking, and report visualization capabilities.

File server functionality based on flask-file-server by Wildog:
https://github.com/Wildog/flask-file-server

Extended with quantum computing specific features:
- QPU status monitoring and SLURM integration
- Real-time package version tracking (qibo, qibolab, qibocal)
- Enhanced report rendering with Plotly support
- Dark theme optimized for quantum computing workflows
"""

from flask import Flask, make_response, request, session, render_template, send_file, Response, jsonify
from flask.views import MethodView
from werkzeug.utils import secure_filename
from datetime import datetime
import humanize
import os
import re
import stat
import json
import mimetypes
import sys, subprocess
from pathlib2 import Path

PORT_NUMBER=5005
home_path = os.environ.get('HOME')
user = os.environ.get('USER')
host, port, root = "127.0.0.1", PORT_NUMBER, os.path.normpath(home_path)
app = Flask(__name__, static_url_path='/assets', static_folder='assets')
app.config['APPLICATION_NAME'] = 'QDashboard'
key = ""

ignored = ['.bzr', '$RECYCLE.BIN', '.DAV', '.DS_Store', '.git', '.hg', '.htaccess', '.htpasswd', '.Spotlight-V100', '.svn', '__MACOSX', 'ehthumbs.db', 'robots.txt', 'Thumbs.db', 'thumbs.tps']
datatypes = {'audio': 'm4a,mp3,oga,ogg,webma,wav', 'archive': '7z,zip,rar,gz,tar,npz', 'image': 'gif,ico,jpe,jpeg,jpg,png,svg,webp', 'pdf': 'pdf', 'quicktime': '3g2,3gp,3gp2,3gpp,mov,qt', 'source': 'atom,bat,bash,c,cmd,coffee,css,hml,js,json,java,less,markdown,md,php,pl,py,rb,rss,sass,scpt,swift,scss,sh,xml,yml,plist', 'text': 'txt', 'video': 'mp4,m4v,ogv,webm', 'website': 'htm,html,mhtm,mhtml,xhtm,xhtml'}
icontypes = {'fa-music': 'm4a,mp3,oga,ogg,webma,wav', 'fa-archive': '7z,zip,rar,gz,tar', 'fa-picture-o': 'gif,ico,jpe,jpeg,jpg,png,svg,webp', 'fa-file-text': 'pdf', 'fa-film': '3g2,3gp,3gp2,3gpp,mov,qt', 'fa-code': 'atom,plist,bat,bash,c,cmd,coffee,css,hml,js,json,java,less,markdown,md,php,pl,py,rb,rss,sass,scpt,swift,scss,sh,xml,yml', 'fa-file-text-o': 'txt', 'fa-film': 'mp4,m4v,ogv,webm', 'fa-globe': 'htm,html,mhtm,mhtml,xhtm,xhtml'}

@app.template_filter('size_fmt')
def size_fmt(size):
    return humanize.naturalsize(size)

@app.template_filter('time_fmt')
def time_desc(timestamp):
    mdate = datetime.fromtimestamp(timestamp)
    str = mdate.strftime('%Y-%m-%d %H:%M:%S')
    return str

@app.template_filter('data_fmt')
def data_fmt(filename):
    t = 'unknown'
    for type, exts in datatypes.items():
        if filename.split('.')[-1] in exts:
            t = type
    return t

@app.template_filter('icon_fmt')
def icon_fmt(filename):
    i = 'fa-file-o'
    for icon, exts in icontypes.items():
        if filename.split('.')[-1] in exts:
            i = icon
    return i

@app.template_filter('humanize')
def time_humanize(timestamp):
    mdate = datetime.utcfromtimestamp(timestamp)
    return humanize.naturaltime(mdate)




def get_type(mode):
    if stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        type = 'dir'
    else:
        type = 'file'
    return type

def partial_response(path, start, end=None):
    file_size = os.path.getsize(path)

    if end is None:
        end = file_size - start - 1
    end = min(end, file_size - 1)
    length = end - start + 1

    with open(path, 'rb') as fd:
        fd.seek(start)
        bytes = fd.read(length)
    assert len(bytes) == length

    response = Response(
        bytes,
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
    range = request.headers.get('Range')
    m = re.match('bytes=(?P<start>\d+)-(?P<end>\d+)?', range)
    if m:
        start = m.group('start')
        end = m.group('end')
        start = int(start)
        if end is not None:
            end = int(end)
        return start, end
    else:
        return 0, None


@app.route("/")
def dashboard():
    """
    Main dashboard route - QDashboard extension
    
    Displays quantum computing specific metrics including:
    - QPU health and availability 
    - Package versions (qibo, qibolab, qibocal)
    - SLURM queue status and logs
    
    This extends the original flask-file-server with quantum computing dashboard
    """
    qpu_health = get_qpu_health()
    available_qpus = get_available_qpus()
    qibo_versions = get_qibo_versions()
    slurm_queue_status = get_slurm_status()
    last_slurm_log = get_slurm_output()
    return render_template('dashboard.html',
                           qpu_health=qpu_health,
                           available_qpus=available_qpus,
                           qibo_versions=qibo_versions,
                           slurm_queue_status=slurm_queue_status,
                           last_slurm_log=last_slurm_log)

def get_qpu_health():
    # Placeholder
    return "N/A"

def get_available_qpus():
    qrc_path = os.environ.get('QIBOLAB_PLATFORMS', os.path.join(root, 'qibolab_platforms_qrc'))
    
    # Check if platforms directory exists
    if not os.path.exists(qrc_path):
        return "N/A"
    
    try:
        with open(os.path.join(qrc_path, 'queues.json'), 'r') as f:
            queues = json.load(f)
    except (IOError, json.JSONDecodeError):
        queues = {}
    
    total_qpus = 0
    online_qpus = 0
    
    try:
        for qpu_name in os.listdir(qrc_path):
            qpu_path = os.path.join(qrc_path, qpu_name)
            if os.path.isdir(qpu_path) and not qpu_name.startswith('.'):
                total_qpus += 1
                
                # Check if QPU is online
                queue_name = queues.get(qpu_name, 'N/A')
                if queue_name != 'N/A':
                    try:
                        sinfo_output = subprocess.check_output(['sinfo', '-p', queue_name]).decode()
                        if queue_name in sinfo_output:
                            online_qpus += 1
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass # Keep as offline if sinfo fails or queue not found
    except OSError:
        return "N/A"
    
    return f"{online_qpus} / {total_qpus}"

def get_qibo_versions():
    """Get versions of qibo, qibolab, and qibocal packages"""
    versions = {}
    packages = ['qibo', 'qibolab', 'qibocal']
    
    for package in packages:
        try:
            import importlib.metadata
            version = importlib.metadata.version(package)
            versions[package] = version
        except ImportError:
            # Fallback for older Python versions
            try:
                import pkg_resources
                version = pkg_resources.get_distribution(package).version
                versions[package] = version
            except (pkg_resources.DistributionNotFound, ImportError):
                versions[package] = "Not installed"
        except Exception:
            versions[package] = "Unknown"
    
    return versions

"""Submit a job to the SLURM queue"""
@app.route("/qqsubmit")
def qqsubmit():
     qpu = request.args.get('qpu')
     import subprocess
     os_process = subprocess.Popen(["bash",root+"/work/qqsubmit.sh",home_path,qpu],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
     stdout, stderr = os_process.communicate()
     
     out_string = stdout.decode('utf-8').replace('\n','<br>')
     return render_template('job_submission.html', output_content=out_string)

@app.route("/latest")
def latest():    
    with open(home_path+"/.latest", 'r') as file:  # r to open file in READ mode
        report_path = file.read().rstrip()

    try:
        res = report_viewer(report_path)
    except FileNotFoundError as e:
        last_path = report_path.rstrip().replace(root,'')
        res = make_response(render_template('latest_not_found.html',
                                            last_path=last_path,
                                            slurm_queue_status=get_slurm_status(),
                                            last_slurm_log=get_slurm_output()), 201)
    except Exception as e:
        raise(e)
    
    return res

@app.route("/report_assets/<path:filename>")
def report_assets(filename):
    """Serve assets from the latest report directory"""
    try:
        with open(home_path+"/.latest", 'r') as file:
            report_path = file.read().rstrip()
        asset_path = os.path.join(report_path, filename)
        if os.path.exists(asset_path):
            return send_file(asset_path)
        else:
            return make_response('Asset not found', 404)
    except Exception as e:
        return make_response('Asset not found', 404)

@app.route("/cancel_job", methods=['POST'])
def cancel_job():
    """Cancel a SLURM job"""
    try:
        job_id = request.json.get('job_id')
        if not job_id:
            return jsonify({'status': 'error', 'message': 'Job ID is required'}), 400
        
        # Execute scancel command
        result = subprocess.run(['scancel', str(job_id)], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return jsonify({'status': 'success', 'message': f'Job {job_id} cancelled successfully'})
        else:
            return jsonify({'status': 'error', 'message': f'Failed to cancel job {job_id}: {result.stderr.strip()}'}), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'status': 'error', 'message': 'Cancel operation timed out'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error cancelling job: {str(e)}'}), 500

def get_slurm_status():
    """Get SLURM queue status as structured data for table display"""
    try:
        # Get current user
        current_user = os.environ.get('USER', 'unknown')
        
        # Get squeue output with specific format
        result = subprocess.check_output(['squeue', '--format=%i %.18j %.8u %.8T %.10M %.9l %.6D %R', '--noheader'], 
                                       stderr=subprocess.DEVNULL).decode()
        
        jobs = []
        for line in result.strip().split('\n'):
            if line.strip() and 'sim' not in line.lower():  # Skip simulation jobs and empty lines
                parts = line.split()
                if len(parts) >= 8:
                    job = {
                        'job_id': parts[0],
                        'name': parts[1],
                        'user': parts[2], 
                        'state': parts[3],
                        'time': parts[4],
                        'time_limit': parts[5],
                        'nodes': parts[6],
                        'nodelist': ' '.join(parts[7:]),  # Join remaining parts for nodelist
                        'is_current_user': parts[2] == current_user[:len(parts[2])] # Check if job belongs to current user
                    }
                    jobs.append(job)
        
        return jobs
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Return empty list if squeue command fails
        return []

def check_queue_running_jobs(queue_name):
    """Check if there are running jobs in a specific SLURM queue"""
    try:
        # Use squeue to check for running jobs in the specific partition
        squeue_output = subprocess.check_output(['squeue', '-p', queue_name, '-t', 'RUNNING'], 
                                               stderr=subprocess.DEVNULL).decode()
        # If there's output beyond the header line, there are running jobs
        lines = squeue_output.strip().split('\n')
        return len(lines) > 1  # More than just the header line means there are running jobs
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False  # If command fails, assume no running jobs

def get_slurm_output(slurm_output_path = home_path+"/work/logs/slurm_output.txt"):
    with open(slurm_output_path, 'r') as file:  # r to open file in READ mode
        log_content = file.read()
    return log_content.replace('\n','<br>')

def report_viewer(report_path):
    with open(report_path+"index.html", 'r') as file:  # r to open file in READ mode
            report_viewer_content = file.read()
    
    # Extract the head section to get CSS and JS dependencies
    head_content = ""
    if '<head>' in report_viewer_content and '</head>' in report_viewer_content:
        head_content = report_viewer_content.split('<head>')[1].split('</head>')[0]
    
    # Extract main content
    report_viewer_body = report_viewer_content
    if '<body>' in report_viewer_content and '</body>' in report_viewer_content:
        report_viewer_body = report_viewer_content.split('<body>')[1].split('</body>')[0]
        
        # Remove header if present
        if '<header' in report_viewer_body and '</header>' in report_viewer_body:
            report_viewer_body = report_viewer_body.split('</header>')[1]
    
    # Fix relative asset paths - convert them to use our report_assets route
    import re
    
    # Remove the original report's sidebar menu if it exists (should be redundant now but safe to keep)
    report_viewer_body = re.sub(r'<nav id="sidebarMenu".*?</nav>', '', report_viewer_body, flags=re.DOTALL)

    # Fix CSS links
    head_content = re.sub(r'''href=(['"])(?!/|http|https|data:)([^'"]+\.css[^'"]*)['"]''', r'href="/report_assets/\2"', head_content)
    
    # Fix JS script sources
    head_content = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''', r'src="/report_assets/\2"', head_content)
    report_viewer_body = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''', r'src="/report_assets/\2"', report_viewer_body)
    
    # Fix image sources
    report_viewer_body = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.(?:png|jpg|jpeg|gif|svg)[^'"]*)['"]''', r'src="/report_assets/\2"', report_viewer_body)
    
    # Fix any other asset references (like data files for plots)
    report_viewer_body = re.sub(r'''(['"])(?!/|http|https|data:)([^'"]+\.(?:json|csv|data|yml|yaml)[^'"]*)['"]''', r'"/report_assets/\2"', report_viewer_body)

    # Prepare the report path for the file browser link (remove root prefix and ensure it starts with /)
    report_path_for_link = report_path.replace(root, "").lstrip("/")

    # Insert body into html template
    report_viewer_template = render_template('latest_report.html')
    report_viewer_template = report_viewer_template.replace("report_viewer_BODY", report_viewer_body)
    report_viewer_template = report_viewer_template.replace("report_viewer_MENU", "")
    report_viewer_template = report_viewer_template.replace("report_viewer_PATH", report_path_for_link)
    report_viewer_template = report_viewer_template.replace("report_viewer_HEAD", head_content)

    res = make_response(report_viewer_template, 200)
    return res
   

class PathView(MethodView):
    """
    File browser functionality based on flask-file-server by Wildog
    https://github.com/Wildog/flask-file-server
    
    Enhanced with quantum computing dashboard integration
    """
    def get(self, p=''):
        hide_dotfile = request.args.get('hide-dotfile', request.cookies.get('hide-dotfile', 'no'))

        path = os.path.join(root, p)

        if os.path.isdir(path):
            contents = []
            total = {'size': 0, 'dir': 0, 'file': 0}

            for filename in os.listdir(path):
                if filename in ignored:
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
          
            page = render_template('file_browser.html', path=p, contents=contents, total=total, hide_dotfile=hide_dotfile)
            res = make_response(page, 200)
            res.set_cookie('hide-dotfile', hide_dotfile, max_age=16070400)

        elif os.path.isfile(path):
            if 'Range' in request.headers:
                start, end = get_range(request)
                res = partial_response(path, start, end)
            else:
                filename, file_extension = os.path.splitext(path)
                if file_extension in ['.html', '.yml','.json']:
                    with open(path, 'r') as file:  # r to open file in READ mode
                        report_viewer_content = file.read()
                    res = make_response(report_viewer_content, 200)
                else:
                    res = send_file(path)
                    #res.headers.add('Content-Disposition', 'attachment')
        else:
            res = make_response('Not found', 404)
        return res
    
    def put(self, p=''):
        if request.cookies.get('auth_cookie') == key:
            path = os.path.join(root, p)
            dir_path = os.path.dirname(path)
            Path(dir_path).mkdir(parents=True, exist_ok=True)

            info = {}
            if os.path.isdir(dir_path):
                try:
                    filename = secure_filename(os.path.basename(path))
                    with open(os.path.join(dir_path, filename), 'wb') as f:
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
        if request.cookies.get('auth_cookie') == key:
            path = os.path.join(root, p)
            Path(path).mkdir(parents=True, exist_ok=True)
    
            info = {}
            if os.path.isdir(path):
                files = request.files.getlist('files[]')
                for file in files:
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
        if request.cookies.get('auth_cookie') == key:
            path = os.path.join(root, p)
            dir_path = os.path.dirname(path)
            Path(dir_path).mkdir(parents=True, exist_ok=True)

            info = {}
            if os.path.isdir(dir_path):
                try:
                    filename = secure_filename(os.path.basename(path))
                    os.remove(os.path.join(dir_path, filename))
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

"""Read YAML File"""
import yaml
def read_yaml_file(file_path):
    with open(file_path, 'r') as file:
        data = yaml.load(file, Loader=yaml.FullLoader)
    return data

"""Write YAML File"""
def write_yaml_file(file_path, data):
    with open(file_path, 'w') as file:
        yaml.dump(data, file)

"""Read JSON File"""
def read_json_file(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data

"""Write JSON File"""
def write_json_file(file_path, data):
    with open(file_path, 'w') as file:
        json.dump(data, file)

"""Format YAML as hhtp response"""
def yaml_response(data):
    response = make_response(yaml.dump(data), 200)
    response.headers.add('Content-type', 'application/x-yaml')
    return response

"""Format JSON as hhtp response"""
def json_response(data):    
    response = make_response(json.dumps(data), 200)
    response.headers.add('Content-type', 'application/json')
    return response


"""Format HTML as hhtp response"""
path_view = PathView.as_view('path_view')
app.add_url_rule('/files', view_func=path_view)
app.add_url_rule('/files/<path:p>', view_func=path_view)



@app.route("/qpus")
def qpus():
    qrc_path = os.environ.get('QIBOLAB_PLATFORMS', os.path.join(root, 'qibolab_platforms_qrc'))
    qpus_list = []
    
    # Get git branch information
    git_branch = 'N/A'
    git_commit = 'N/A'
    
    if os.path.exists(qrc_path):
        try:
            # Check if the directory is a git repository
            git_dir = os.path.join(qrc_path, '.git')
            if os.path.exists(git_dir) or os.path.exists(os.path.join(os.path.dirname(qrc_path), '.git')):
                # Get current branch
                branch_output = subprocess.check_output(['git', 'branch', '--show-current'], 
                                                      cwd=qrc_path, stderr=subprocess.DEVNULL).decode().strip()
                if branch_output:
                    git_branch = branch_output
                
                # Get short commit hash
                commit_output = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], 
                                                      cwd=qrc_path, stderr=subprocess.DEVNULL).decode().strip()
                if commit_output:
                    git_commit = commit_output
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass # Keep defaults if git commands fail
    
    try:
        with open(os.path.join(qrc_path, 'queues.json'), 'r') as f:
            queues = json.load(f)
    except (IOError, json.JSONDecodeError):
        queues = {}

    if os.path.exists(qrc_path):
        for qpu_name in os.listdir(qrc_path):
            qpu_path = os.path.join(qrc_path, qpu_name)
            if os.path.isdir(qpu_path) and not qpu_name.startswith('.'):
                # Defaults
                num_qubits = 'N/A'
                topology = 'N/A'
                calibration_time = 'N/A'
                status = 'offline'
                
                # Get queue info and check status
                queue_name = queues.get(qpu_name, 'N/A')
                if queue_name != 'N/A':
                    try:
                        sinfo_output = subprocess.check_output(['sinfo', '-p', queue_name]).decode()
                        if queue_name in sinfo_output:
                            # Check if there are running jobs in this queue
                            if check_queue_running_jobs(queue_name):
                                status = 'running'
                            else:
                                status = 'online'
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass # Keep status as offline if sinfo fails or queue not found

                # Get qubit count from platform.py
                platform_py_path = os.path.join(qpu_path, 'platform.py')
                if os.path.exists(platform_py_path):
                    with open(platform_py_path, 'r') as f:
                        for line in f:
                            if 'NUM_QUBITS' in line:
                                try:
                                    num_qubits = int(line.split('=')[1].strip())
                                    break
                                except (ValueError, IndexError):
                                    pass
                
                qpus_list.append({
                    'name': qpu_name,
                    'qubits': num_qubits,
                    'status': status,
                    'queue': queue_name,
                    'topology': topology,
                    'calibration_time': calibration_time
                })

    return render_template('qpus.html', qpus=qpus_list, git_branch=git_branch, git_commit=git_commit, platforms_path=qrc_path)

@app.route("/experiments")
def experiments():
    """
    Experiment builder page.
    
    - Fetches available qibocal protocols dynamically from qibocal.protocols module.
    - Fetches available QPUs from the platforms directory.
    - Renders the experiment builder interface.
    """
    protocols = get_qibocal_protocols()
    qpus = get_available_qpu_list()
    
    return render_template('experiments.html', protocols=protocols, qpus=qpus)

def get_qibocal_protocols():
    """
    Dynamically discover all available qibocal protocols by inspecting the qibocal.protocols module.
    Returns a dictionary categorized by protocol type.
    """
    try:
        import qibocal.protocols as protocols_module
        import inspect
        
        # Get all classes from the protocols module
        protocol_classes = []
        
        # Inspect all attributes in the protocols module
        for name, obj in inspect.getmembers(protocols_module):
            if inspect.isclass(obj) and hasattr(obj, '__module__'):
                # Check if the class is actually from qibocal.protocols
                if obj.__module__.startswith('qibocal.protocols'):
                    protocol_classes.append({
                        'id': name.lower(),
                        'name': name.replace('_', ' ').title(),
                        'class_name': name,
                        'module': obj.__module__
                    })
        
        # Try to categorize protocols based on their module path or name patterns
        categorized = {
            "Characterization": [],
            "Calibration": [],
            "Verification": [],
            "Tuning": [],
            "Other": []
        }
        
        for protocol in protocol_classes:
            module_parts = protocol['module'].split('.')
            name_lower = protocol['name'].lower()
            
            # Categorize based on module path or protocol name patterns
            if any(keyword in module_parts or keyword in name_lower 
                   for keyword in ['spectroscopy', 'resonator', 'readout', 'characterization']):
                categorized["Characterization"].append(protocol)
            elif any(keyword in module_parts or keyword in name_lower 
                     for keyword in ['calibration', 'tune', 'tuning', 'optimization']):
                categorized["Calibration"].append(protocol)
            elif any(keyword in module_parts or keyword in name_lower 
                     for keyword in ['verification', 'benchmark', 'fidelity', 'allxy', 'randomized']):
                categorized["Verification"].append(protocol)
            elif any(keyword in module_parts or keyword in name_lower 
                     for keyword in ['rabi', 'ramsey', 'echo', 'coherence']):
                categorized["Tuning"].append(protocol)
            else:
                categorized["Other"].append(protocol)
        
        # Remove empty categories
        categorized = {k: v for k, v in categorized.items() if v}
        
        return categorized
        
    except ImportError as e:
        print(f"Warning: Could not import qibocal.protocols: {e}")
        # Fallback to placeholder data if qibocal is not available
        return {
            "Characterization": [
                {"id": "resonator_spectroscopy", "name": "Resonator Spectroscopy"},
                {"id": "rabi_oscillations", "name": "Rabi Oscillations"}
            ],
            "Verification": [
                {"id": "allxy", "name": "AllXY"}
            ]
        }
    except Exception as e:
        print(f"Error discovering qibocal protocols: {e}")
        return {"Error": [{"id": "error", "name": f"Error loading protocols: {str(e)}"}]}

def get_available_qpu_list():
    """
    Get list of available QPU platforms from the qibolab platforms directory.
    """
    qrc_path = os.environ.get('QIBOLAB_PLATFORMS', os.path.join(root, 'qibolab_platforms_qrc'))
    qpus = []
    
    if os.path.exists(qrc_path):
        try:
            for qpu_name in os.listdir(qrc_path):
                qpu_path = os.path.join(qrc_path, qpu_name)
                if os.path.isdir(qpu_path) and not qpu_name.startswith('.'):
                    qpus.append(qpu_name)
        except OSError:
            pass
    
    # Fallback to default QPUs if directory doesn't exist or is empty
    if not qpus:
        qpus = ["qpu130", "qpu132"]
    
    return sorted(qpus)

@app.route("/api/qpu_parameters/<platform>")
def qpu_parameters(platform):
    """
    API endpoint to get parameters for a specific QPU.
    In the future, this will read from the platform's runcard.
    """
    # Placeholder data
    params = {
        "qpu130": {
            "qubits": {
                "0": {"readout_frequency": 6.021, "drive_amplitude": 0.5},
                "1": {"readout_frequency": 6.130, "drive_amplitude": 0.45},
                "2": {"readout_frequency": 6.245, "drive_amplitude": 0.52}
            }
        },
        "qpu132": {
            "qubits": {
                "0": {"readout_frequency": 7.011, "drive_amplitude": 0.6},
                "1": {"readout_frequency": 7.123, "drive_amplitude": 0.55}
            }
        }
    }
    
    platform_params = params.get(platform, {"qubits": {}})
    return jsonify(platform_params)

if __name__ == '__main__':
    # Check inputs to the python call
    if len(sys.argv) > 1:
        port = sys.argv[1]
    
    bind = os.getenv('QD_BIND', host)
    port = os.getenv('QD_PORT', port)
    root = os.path.normpath(os.getenv('QD_PATH', root))
    key = os.getenv('QD_KEY')

    
    print('Quantum Dashboard Server running on http://{}:{}'.format(bind, port))
    print('Serving path: {}'.format(root))
    print('Authentication key: {}'.format(key))
    print('Press Ctrl+C to stop')
    app.run(bind, port, threaded=True, debug=False)
    sys.stdout.flush()
    # app.serve_forever()

    print('Quantum Dashboard Server stopped')
    sys.stdout.flush()
    sys.exit(0)
