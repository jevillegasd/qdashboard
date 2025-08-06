"""
Main application routes and endpoints.
"""

import os
import subprocess
import json
from flask import render_template, request, jsonify, send_file, make_response, current_app

from ..qpu.monitoring import get_qpu_health, get_available_qpus, get_qibo_versions, get_qpu_details, get_qpu_list
from ..qpu.platforms import get_platforms_path, list_repository_branches, switch_repository_branch, get_current_branch_info
from ..qpu.slurm import get_slurm_status, get_slurm_output, parse_slurm_log_for_errors
from ..qpu.topology import get_connectivity_data_from_qpu_config, get_topology_from_qpu_config, generate_topology_visualization
from ..experiments.protocols import get_qibocal_protocols, get_qpu_parameters
from ..web.reports import report_viewer, get_latest_report_path
from ..utils.formatters import yaml_response, json_response


def register_routes(app, config):
    """Register all application routes."""
    
    # Store config in app for access in routes
    app.config['QDASHBOARD_CONFIG'] = config
    
    @app.route("/")
    def dashboard():
        """Main dashboard route with QPU health and SLURM status."""
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

    @app.route("/qqsubmit")
    def qqsubmit():
        """Submit a job to the SLURM queue."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qpu = request.args.get('qpu')
        os_process = subprocess.Popen(
            ["bash", os.path.join(config['root'], "work/qqsubmit.sh"), config['home_path'], qpu],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = os_process.communicate()
        
        out_string = stdout.decode('utf-8').replace('\n', '<br>')
        return render_template('job_submission.html', output_content=out_string)

    @app.route("/latest")
    def latest():
        """View the latest report."""
        config = current_app.config['QDASHBOARD_CONFIG']
        last_path = get_latest_report_path(config['home_path'])
        qibo_versions = get_qibo_versions()
        if not last_path:
            # Get SLURM information for the not found page
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            has_error, error_message = parse_slurm_log_for_errors()
            
            # Set last_path for file browser link
            last_path = config.get('home_path', '/home')
            
            return render_template('latest_not_found.html',
                                   has_error=has_error,
                                   error_message=error_message,
                                   last_path=last_path,
                                   slurm_queue_status=slurm_queue_status,
                                   last_slurm_log=last_slurm_log,
                                   qibo_versions=qibo_versions)
        
        try:
            res = report_viewer(last_path, config['root'])
        except FileNotFoundError:
            # Get SLURM information for the not found page
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            has_error, error_message = parse_slurm_log_for_errors()
            
            #remove home from last path for file browser link
            last_path = "/"+last_path.replace(config['home_path'], "").lstrip("/")
            return render_template('latest_not_found.html',
                                   has_error=has_error,
                                   error_message=error_message,
                                   last_path=last_path,
                                   slurm_queue_status=slurm_queue_status,
                                   last_slurm_log=last_slurm_log,
                                   qibo_versions=qibo_versions)
        except Exception as e:
            return make_response(f'Error loading report: {str(e)}', 500)
        
        return res

    @app.route("/report_assets/<path:filename>")
    def report_assets(filename):
        """Serve assets from the latest report directory."""
        config = current_app.config['QDASHBOARD_CONFIG']
        try:
            latest_path = get_latest_report_path(config['home_path'])
            if latest_path:
                asset_path = os.path.join(latest_path, filename)
                if os.path.exists(asset_path):
                    return send_file(asset_path)
            return make_response('Asset not found', 404)
        except Exception as e:
            return make_response(f'Error serving asset: {str(e)}', 500)

    @app.route("/cancel_job", methods=['POST'])
    def cancel_job():
        """Cancel a SLURM job."""
        try:
            job_id = request.json.get('job_id')
            if job_id:
                result = subprocess.run(['scancel', str(job_id)], 
                                      capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return jsonify({'status': 'success', 'message': f'Job {job_id} cancelled'})
                else:
                    return jsonify({'status': 'error', 'message': f'Failed to cancel job: {result.stderr}'})
            else:
                return jsonify({'status': 'error', 'message': 'No job ID provided'})
        except subprocess.TimeoutExpired:
            return jsonify({'status': 'error', 'message': 'Cancel command timed out'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route("/qpus")
    def qpus():
        """QPU status and monitoring page."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qpu_details = get_qpu_details()
        qibo_versions = get_qibo_versions()
        
        # Get branch information for the dropdown
        platforms_path = get_platforms_path(config['root'])
        branches_info = list_repository_branches(platforms_path) if platforms_path else None
        current_branch_info = get_current_branch_info(platforms_path) if platforms_path else None
        
        return render_template('qpus.html', 
                               qpus=qpu_details['qpus'],
                               git_branch=qpu_details['git_branch'],
                               git_commit=qpu_details['git_commit'],
                               platforms_path=qpu_details['platforms_path'],
                               branches_info=branches_info,
                               current_branch_info=current_branch_info,
                               qibo_versions=qibo_versions)

    @app.route("/api/platforms/branches")
    def api_platforms_branches():
        """API endpoint to get available branches."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            branches_info = list_repository_branches(platforms_path)
            if not branches_info:
                return jsonify({'error': 'Failed to retrieve branch information'}), 500
            
            return jsonify(branches_info)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/switch", methods=['POST'])
    def api_platforms_switch():
        """API endpoint to switch platform branch."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            data = request.get_json()
            if not data or 'branch' not in data:
                return jsonify({'error': 'Branch name is required'}), 400
            
            branch_name = data['branch']
            create_if_not_exists = data.get('create', False)
            
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            # Perform the switch
            success = switch_repository_branch(platforms_path, branch_name, create_if_not_exists)
            if not success:
                return jsonify({'error': f'Failed to switch to branch: {branch_name}'}), 500
            
            # Get updated information
            current_branch_info = get_current_branch_info(platforms_path)
            qpu_details = get_qpu_details()  # Get updated QPU list
            
            return jsonify({
                'success': True,
                'branch': branch_name,
                'branch_info': current_branch_info,
                'qpus': qpu_details['qpus'],  # Return updated QPU list
                'platforms_path': qpu_details['platforms_path']
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/current")
    def api_platforms_current():
        """API endpoint to get current branch information."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            current_branch_info = get_current_branch_info(platforms_path)
            if not current_branch_info:
                return jsonify({'error': 'Failed to get current branch information'}), 500
            
            return jsonify(current_branch_info)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route("/experiments")
    def experiments():
        """Experiment builder page."""
        protocols = get_qibocal_protocols()
        qpus = get_qpu_list()
        qibo_versions = get_qibo_versions()
        
        return render_template('experiments.html', 
                               protocols=protocols, 
                               qpus=qpus, 
                               qibo_versions=qibo_versions)

    @app.route("/api/qpu_parameters/<platform>")
    def qpu_parameters_api(platform):
        """API endpoint to get parameters for a specific QPU."""
        platform_params = get_qpu_parameters(platform)
        return jsonify(platform_params)

    @app.route("/api/qpu_topology/<platform>")
    def qpu_topology_visualization_api(platform):
        """API endpoint to generate topology visualization for a specific QPU."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qrc_path = get_platforms_path(config['root'])
        
        if not qrc_path:
            return jsonify({'error': 'QPU platforms directory not available'}), 404
            
        qpu_path = os.path.join(qrc_path, platform)
        
        if not os.path.exists(qpu_path):
            return jsonify({'error': 'QPU not found'}), 404
        
        # Get connectivity data and topology type
        connectivity_data = get_connectivity_data_from_qpu_config(qpu_path)
        topology_type = get_topology_from_qpu_config(qpu_path)
        
        if not connectivity_data:
            return jsonify({'error': 'No connectivity data found for this QPU'}), 404
        
        if topology_type == 'N/A' or topology_type == 'unknown':
            return jsonify({'error': 'Could not determine topology type'}), 404
        
        # Generate visualization
        img_base64 = generate_topology_visualization(connectivity_data, topology_type)
        
        if img_base64 is None:
            return jsonify({'error': 'Failed to generate topology visualization'}), 500
        
        return jsonify({
            'topology_type': topology_type,
            'num_qubits': len(set([q for conn in connectivity_data for q in conn[:2]])),
            'num_connections': len(connectivity_data),
            'image': img_base64
        })

    return app
