"""
Main application routes and endpoints.
"""

import os
import subprocess
import json
import time
import shutil
import yaml
from flask import render_template, request, jsonify, send_file, make_response, current_app

from ..qpu.monitoring import get_qpu_health, get_available_qpus, get_qibo_versions, get_qpu_details, get_qpu_list, qpu_parameters
from ..qpu.platforms import get_platforms_path, list_repository_branches, switch_repository_branch, get_current_branch_info, commit_changes, push_changes, stash_changes, list_stashes, apply_latest_stash, discard_changes, get_partition
from ..qpu.slurm import get_slurm_status, get_slurm_output, parse_slurm_log_for_errors, slurm_log_path
from ..qpu.topology import qpu_connectivity, infer_topology_from_connectivity, generate_topology_visualization
from ..experiments.protocols import get_qibocal_protocols, get_protocol_attributes
from ..experiments import submit_experiment, repeat_experiment, get_experiment_status, list_user_experiments
from ..web.reports import report_viewer, get_latest_report_path
from ..utils.formatters import yaml_response, json_response
from qdashboard.utils.logger import get_logger
from packaging.version import parse as parse_version

logger = get_logger(__name__)


def register_routes(app, config):
    """Register all application routes."""
    
    # Store config in app for access in routes
    app.config['QDASHBOARD_CONFIG'] = config
    
    @app.route("/")
    def dashboard():
        """Main dashboard route with QPU health and SLURM status."""
        qpu_health = get_qpu_health()
        available_qpus = get_available_qpus()
        version_data = get_qibo_versions(request=request)
        slurm_queue_status = get_slurm_status()
        last_slurm_log = get_slurm_output()
        
        logger.info("Dashboard loaded with QPU health and SLURM status")
        
        response = make_response(render_template('dashboard.html',
                               qpu_health=qpu_health,
                               available_qpus=available_qpus,
                               qibo_versions=version_data['versions'],
                               slurm_queue_status=slurm_queue_status,
                               last_slurm_log=last_slurm_log))
        
        # Prevent caching of SLURM data
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        # Set cookie if we have fresh data
        if not version_data.get('from_cache', False):
            response.set_cookie('qibo_versions', 
                              version_data['cookie_data'],
                              max_age=24*60*60,  # 24 hours
                              httponly=True,
                              secure=False)
        
        return response

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
        logger.info(f"Job submitted to SLURM queue for QPU: {qpu}")
        return render_template('job_submission.html', output_content=out_string)

    @app.route("/latest")
    def latest():
        """View the latest report."""
        config = current_app.config['QDASHBOARD_CONFIG']
        last_path = get_latest_report_path()
        version_data = get_qibo_versions(request=request)
        
        if not last_path:
            # Get SLURM information for the not found page
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            has_error, error_message = parse_slurm_log_for_errors()
            
            # Set last_path for file browser link
            last_path = config.get('home_path', os.path.expanduser('~'))
            
            logger.warning(f"Last report not found, using default path: {last_path}")
            response = make_response(render_template('latest_not_found.html',
                                   has_error=has_error,
                                   error_message=error_message,
                                   last_path=last_path,
                                   slurm_queue_status=slurm_queue_status,
                                   last_slurm_log=last_slurm_log,
                                   qibo_versions=version_data['versions']))
            
            # Set cookie if we have fresh data
            if not version_data.get('from_cache', False):
                response.set_cookie('qibo_versions', 
                                  version_data['cookie_data'],
                                  max_age=24*60*60,
                                  httponly=True,
                                  secure=False)
            
            return response
        
        try:
            res = report_viewer(last_path, config['root'], version_data['versions'], access_mode="latest")
            logger.info(f"Latest report viewed: {last_path}")
        except FileNotFoundError:
            # Get SLURM information for the not found page
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            has_error, error_message = parse_slurm_log_for_errors()
            
            #remove home from last path for file browser link
            last_path = "/"+last_path.replace(config['home_path'], "").lstrip("/")
            logger.warning(f"Report not found: {last_path}")
            response = make_response(render_template('latest_not_found.html',
                                   has_error=has_error,
                                   error_message=error_message,
                                   last_path=last_path,
                                   slurm_queue_status=slurm_queue_status,
                                   last_slurm_log=last_slurm_log,
                                   qibo_versions=version_data['versions']))
            
            # Set cookie if we have fresh data
            if not version_data.get('from_cache', False):
                response.set_cookie('qibo_versions', 
                                  version_data['cookie_data'],
                                  max_age=24*60*60,
                                  httponly=True,
                                  secure=False)
            
            return response
        except Exception as e:
            logger.error(f"Error loading report: {str(e)}")
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
                    logger.info(f"Serving asset: {asset_path}")
                    return send_file(asset_path)
            logger.warning(f"Asset not found: {filename}")
            return make_response('Asset not found', 404)
        except Exception as e:
            logger.error(f'Error serving asset: {str(e)}')
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
                    logger.info(f"Job {job_id} cancelled successfully")
                    return jsonify({'status': 'success', 'message': f'Job {job_id} cancelled'})
                else:
                    logger.error(f"Failed to cancel job {job_id}: {result.stderr}")
                    return jsonify({'status': 'error', 'message': f'Failed to cancel job: {result.stderr}'})
            else:
                logger.warning("No job ID provided for cancellation")
                return jsonify({'status': 'error', 'message': 'No job ID provided'})
        except subprocess.TimeoutExpired:
            logger.error("Cancel command timed out")
            return jsonify({'status': 'error', 'message': 'Cancel command timed out'})
        except Exception as e:
            logger.error(f"Error cancelling job: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route("/api/slurm_status", methods=['GET'])
    def api_slurm_status():
        """API endpoint to get fresh SLURM status data."""
        try:
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            
            logger.info("Fresh SLURM status data retrieved via API")
            
            response = jsonify({
                'status': 'success',
                'queue_status': [
                    {
                        'job_id': job.job_id,
                        'name': job.name,
                        'user': job.user,
                        'state': job.state,
                        'time': job.time,
                        'time_limit': job.time_limit,
                        'nodes': job.nodes,
                        'nodelist': job.nodelist,
                        'is_current_user': job.is_current_user
                    } for job in slurm_queue_status
                ],
                'last_log': last_slurm_log
            })
            
            # Prevent caching
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            return response
            
        except Exception as e:
            logger.error(f"Error fetching SLURM status: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route("/qpus")
    def qpus():
        """QPU status and monitoring page."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qpu_details = get_qpu_details()
        version_data = get_qibo_versions(request=request)
        
        # Get branch information for the dropdown
        platforms_path = get_platforms_path(config['root'])
        git_branches_info = list_repository_branches(platforms_path) if platforms_path else None
        git_current_branch_info = get_current_branch_info(platforms_path) if platforms_path else None
        
        logger.info("QPU status page loaded")
        
        response = make_response(render_template('qpus.html', 
                               qpus=qpu_details,
                               git_branch=  git_current_branch_info['branch'] if git_current_branch_info else None,
                               git_commit=  git_current_branch_info['commit'] if git_current_branch_info else None,
                               platforms_path= platforms_path,
                               branches_info=git_branches_info,
                               current_branch_info=git_current_branch_info,
                               qibo_versions=version_data['versions']))
        
        # Set cookie if we have fresh data
        if not version_data.get('from_cache', False):
            response.set_cookie('qibo_versions', 
                              version_data['cookie_data'],
                              max_age=24*60*60,
                              httponly=True,
                              secure=False)
        
        return response

    @app.route("/api/platforms/branches")
    def api_platforms_branches():
        """API endpoint to get available branches."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            branches_info = list_repository_branches(platforms_path)
            if not branches_info:
                logger.error("Failed to retrieve branch information")
                return jsonify({'error': 'Failed to retrieve branch information'}), 500
            
            logger.info("Branch information retrieved successfully")
            return jsonify(branches_info)
        except Exception as e:
            logger.error(f"Error retrieving branches: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/switch", methods=['POST'])
    def api_platforms_switch():
        """API endpoint to switch platform branch."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            data = request.get_json()
            if not data or 'branch' not in data:
                logger.warning("Branch name is required for switching")
                return jsonify({'error': 'Branch name is required'}), 400
            
            branch_name = data['branch']
            create_if_not_exists = data.get('create', False)
            handle_changes = data.get('handle_changes', 'fail')  # 'fail', 'stash', or 'commit'
            
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            # Perform the switch
            switch_result = switch_repository_branch(platforms_path, branch_name, create_if_not_exists, handle_changes)
            if not switch_result['success']:
                logger.error(f"Failed to switch to branch: {branch_name} - {switch_result.get('error', 'Unknown error')}")
                return jsonify({
                    'error': switch_result.get('error', f'Failed to switch to branch: {branch_name}'),
                    'has_changes': switch_result.get('has_changes', False)
                }), 400
            
            # Get updated information
            current_branch_info = get_current_branch_info(platforms_path)
            qpu_details = get_qpu_details()  # Get updated QPU list
            
            response_data = {
                'success': True,
                'branch': branch_name,
                'branch_info': current_branch_info,
                'qpus': qpu_details,  
                'platforms_path': platforms_path
            }
            
            # Add stash information if changes were stashed
            if switch_result.get('changes_handled') == 'stashed':
                response_data['stash_created'] = switch_result.get('stash_created')
                response_data['changes_handled'] = 'stashed'
            
            # Add stash restoration information
            if switch_result.get('stash_restored'):
                response_data['stash_applied'] = switch_result.get('stash_applied')
                response_data['stash_restored'] = True
            
            logger.info(f"Switched to branch: {branch_name}")
            return jsonify(response_data)
            
        except Exception as e:
            logger.error(f"Error switching branch: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/current")
    def api_platforms_current():
        """API endpoint to get current branch information."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            current_branch_info = get_current_branch_info(platforms_path)
            if not current_branch_info:
                logger.error("Failed to get current branch information")
                return jsonify({'error': 'Failed to get current branch information'}), 500
            
            logger.info("Current branch information retrieved")
            return jsonify(current_branch_info)
        except Exception as e:
            logger.error(f"Error retrieving current branch information: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/commit", methods=['POST'])
    def api_platforms_commit():
        """API endpoint to commit changes to the platforms repository."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            data = request.get_json() or {}
            commit_message = data.get('message', 'Update platform configurations (qibolab version detection)')
            
            # Perform the commit
            result = commit_changes(platforms_path, commit_message)
            
            if not result['success']:
                logger.warning(f"Commit failed: {result.get('error', 'Unknown error')}")
                return jsonify({'error': result.get('error', 'Commit failed')}), 400
            
            logger.info(f"Successfully committed changes with hash: {result['commit_hash']}")
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error committing changes: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/stash", methods=['POST'])
    def api_platforms_stash():
        """API endpoint to stash changes in the platforms repository."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            data = request.get_json() or {}
            stash_message = data.get('message', 'WIP: Stashed via QDashboard')
            
            # Perform the stash
            result = stash_changes(platforms_path, stash_message)
            
            if not result['success']:
                logger.warning(f"Stash failed: {result.get('error', 'Unknown error')}")
                return jsonify({'error': result.get('error', 'Stash failed')}), 400
            
            logger.info(f"Successfully stashed changes: {result['stash_name']}")
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error stashing changes: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/discard", methods=['POST'])
    def api_platforms_discard():
        """API endpoint to discard all uncommitted changes in the platforms repository."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            # Perform the discard
            result = discard_changes(platforms_path)
            
            if not result['success']:
                logger.warning(f"Discard failed: {result.get('error', 'Unknown error')}")
                return jsonify({'error': result.get('error', 'Discard failed')}), 400
            
            logger.info(f"Successfully discarded changes: {result.get('discarded_files', [])}")
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error discarding changes: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/stashes")
    def api_platforms_list_stashes():
        """API endpoint to list all stashes in the platforms repository."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            result = list_stashes(platforms_path)
            
            if not result['success']:
                logger.warning(f"Failed to list stashes: {result.get('error', 'Unknown error')}")
                return jsonify({'error': result.get('error', 'Failed to list stashes')}), 400
            
            logger.info("Successfully retrieved stash list")
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error listing stashes: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/platforms/push", methods=['POST'])
    def api_platforms_push():
        """API endpoint to push changes to the remote repository."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning("Platforms directory not available")
                return jsonify({'error': 'Platforms directory not available'}), 404
            
            # Perform the push
            result = push_changes(platforms_path)
            
            if not result['success']:
                logger.warning(f"Push failed: {result.get('error', 'Unknown error')}")
                return jsonify({'error': result.get('error', 'Push failed')}), 400
            
            logger.info(f"Successfully pushed changes to {result['remote']}/{result['branch']}")
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error pushing changes: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route("/api/protocols")
    def api_protocols():
        """API endpoint to get all available protocols."""
        protocols = get_qibocal_protocols()

        jsonifiable_protocols = {}
        for category in protocols:
            jsonifiable_protocols[category] = {item['name']: {'id': item['id'],
                                    'class_name': item['class_name'],
                                    'module_name': item['module_name'],
                                    'module_path': item['module_path']}
                      for item in protocols[category]}
        
        logger.info(f"Protocols retrieved successfully: {jsonifiable_protocols}")
        return jsonify(jsonifiable_protocols), 200

    @app.route("/api/protocols/<protocol_id>")
    def api_protocol_details(protocol_id):
        """API endpoint to get details of a specific protocol."""
        try:
            attributes = get_protocol_attributes(protocol_id)
            return jsonify(attributes), 200
        except Exception as e:
            logger.warning(f"Protocol not found: {protocol_id}")
            logger.debug(f"Error details: {e}:{e.__context__}")
            return jsonify({'error': 'Protocol not found'}), 404

    @app.route("/experiments")
    def experiments():
        """Experiment builder page."""
        protocols = get_qibocal_protocols()
        qpus = get_qpu_list()
        version_data = get_qibo_versions(request=request)
        
        qibolab_version = version_data['versions'].get('qibolab', '0.0.0')
        is_new_qibolab = parse_version(qibolab_version) > parse_version('0.2.0')

        # Get protocol attributes for each protocol
        protocols_with_attributes = {}
        for category, protocol_list in protocols.items():
            protocols_with_attributes[category] = []
            for protocol in protocol_list:
                protocol_attrs = get_protocol_attributes(protocol)
                protocol_with_attrs = protocol.copy()
                protocol_with_attrs['attributes'] = protocol_attrs
                protocols_with_attributes[category].append(protocol_with_attrs)

        logger.info("Experiment builder page loaded")
        
        response = make_response(render_template('experiments.html', 
                               protocols=protocols_with_attributes, 
                               qpus=qpus, 
                               qibo_versions=version_data['versions'],
                               is_new_qibolab=is_new_qibolab))
        
        # Set cookie if we have fresh data
        if not version_data.get('from_cache', False):
            response.set_cookie('qibo_versions', 
                              version_data['cookie_data'],
                              max_age=24*60*60,
                              httponly=True,
                              secure=False)
        
        return response

    @app.route("/api/qpu_parameters/<platform>")
    def qpu_parameters_api(platform):
        """API endpoint to get parameters for a specific QPU."""
        platform_params = qpu_parameters(platform)
        logger.info(f"QPU parameters retrieved for platform: {platform}")
        return jsonify(platform_params)

    @app.route("/api/qpu_topology/<platform>")
    def qpu_topology_visualization_api(platform):
        """API endpoint to generate topology visualization for a specific QPU."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qrc_path = get_platforms_path(config['root'])
        
        if not qrc_path:
            logger.warning("QPU platforms directory not available")
            return jsonify({'error': 'QPU platforms directory not available'}), 404
            
        qpu_path = os.path.join(qrc_path, platform)
        
        if not os.path.exists(qpu_path):
            logger.warning(f"QPU not found: {platform}")
            return jsonify({'error': 'QPU not found'}), 404
        
        # Get connectivity data and topology type
        connectivity_data = qpu_connectivity(platform)  
        if not connectivity_data:
            logger.warning("No connectivity data found for this QPU")
            return jsonify({'error': 'No connectivity data found for this QPU'}), 404
        
        topology_type = infer_topology_from_connectivity(connectivity_data)
        if topology_type == 'N/A' or topology_type == 'unknown':
            logger.warning("Could not determine topology type")
            return jsonify({'error': 'Could not determine topology type'}), 404
        
        # Generate visualization
        try:
            img_base64 = generate_topology_visualization(connectivity_data, topology_type)
        except Exception as e:
            logger.error(f"Error generating topology visualization: {str(e)}")
            return jsonify({'error': 'Failed to generate topology visualization'}), 500

        
        logger.info(f"Topology visualization generated for {platform}")
        return jsonify({
            'topology_type': topology_type,
            'num_qubits': len(set([q for conn in connectivity_data for q in conn[:2]])),
            'num_connections': len(connectivity_data),
            'image': img_base64
        })

    @app.route("/api/qpu_qubits/<platform>")
    def qpu_qubits_api(platform):
        """API endpoint to get the list of available qubits for a specific QPU."""
        config = current_app.config['QDASHBOARD_CONFIG']
        qrc_path = get_platforms_path(config['root'])
        
        if not qrc_path:
            logger.warning("QPU platforms directory not available")
            return jsonify({'error': 'QPU platforms directory not available'}), 404
            
        qpu_path = os.path.join(qrc_path, platform)
        
        if not os.path.exists(qpu_path):
            logger.warning(f"QPU not found: {platform}")
            return jsonify({'error': 'QPU not found'}), 404
        
        # Get connectivity data to extract qubits
        connectivity_data = qpu_connectivity(platform)  
        if not connectivity_data:
            logger.warning("No connectivity data found for this QPU")
            return jsonify({'error': 'No connectivity data found for this QPU'}), 404
        
        # Extract unique qubits from connectivity data
        raw_qubits = list(set([q for conn in connectivity_data for q in conn[:2]]))
        
        # Sort qubits properly handling both strings and numbers
        def qubit_sort_key(qubit):
            """Sort qubits: numbers first (by value), then strings (alphabetically)"""
            if isinstance(qubit, (int, float)):
                return (0, qubit)  # Numbers get priority 0
            else:
                # Try to parse as number for mixed cases
                try:
                    return (0, int(qubit))
                except (ValueError, TypeError):
                    return (1, str(qubit))  # Strings get priority 1
        
        qubits = sorted(raw_qubits, key=qubit_sort_key)
        
        logger.info(f"Available qubits retrieved for {platform}: {qubits}")
        return jsonify({
            'qubits': qubits,
            'num_qubits': len(qubits)
        })

    @app.route("/api/qpu_calibration/<platform>")
    def qpu_calibration_api(platform):
        """API endpoint to get calibration data for a specific QPU."""
        # For now, we'll just read a dummy file.
        # In the future, this should read the calibration.json from the platform directory.
        config = current_app.config['QDASHBOARD_CONFIG']
        platforms_path = get_platforms_path(config['root'])
        calibration_path = os.path.join(platforms_path, platform, 'calibration.json')

        if os.path.exists(calibration_path):
            with open(calibration_path, 'r') as f:
                calibration_data = json.load(f)
            logger.info(f"QPU calibration data retrieved for platform: {platform}")
            return jsonify(calibration_data)
        else:
            logger.warning(f"Calibration data not found for platform: {platform}")
            return jsonify({'error': 'Calibration data not found'}), 404

    # Qibocal CLI routes
    @app.route("/qibocal/<action>", methods=['POST'])
    def qibocal_cli_action(action):
        """Execute qibocal CLI commands."""
        config = current_app.config['QDASHBOARD_CONFIG']
        
        # Get the report path from form data
        report_path = request.form.get('report_path')
        if not report_path:
            return jsonify({'success': False, 'message': 'No report path provided'}), 400
        
        # Convert relative path to absolute path
        full_report_path = os.path.join(config['root'], report_path)
        
        # Validate that the path exists and is a qibocal report
        if not os.path.exists(full_report_path):
            return jsonify({'success': False, 'message': f'Report path does not exist: {report_path}'}), 404
        
        # Check if this is actually a qibocal report (has meta.json and runcard.yml)
        if not (os.path.exists(os.path.join(full_report_path, 'meta.json')) and 
                os.path.exists(os.path.join(full_report_path, 'runcard.yml'))):
            return jsonify({'success': False, 'message': f'Path is not a valid qibocal report (missing meta.json or runcard.yml): {report_path}'}), 400
        
        # Validate action
        valid_actions = ['fit', 'report', 'update']
        if action not in valid_actions:
            return jsonify({'success': False, 'message': f'Invalid action: {action}'}), 400
        
        try:
            # Check if qibocal is available
            from ..web.reports import check_qibocal_availability
            if not check_qibocal_availability():
                return jsonify({'success': False, 'message': 'Qibocal CLI (qq) is not available. Please install qibocal.'}), 503
            
            # Construct the command
            cmd = ['qq', action, full_report_path]
            if action == 'fit':
                cmd.append('-f')
            logger.info(f"Executing qibocal command: {' '.join(cmd)}")
            
            # Execute the command
            result = subprocess.run(cmd, 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=300,  # 5 minute timeout
                                  cwd=full_report_path)
            
            if result.returncode == 0:
                success_messages = {
                    'fit': 'Fit operation completed successfully.',
                    'report': 'Report regeneration completed successfully.',
                    'update': 'Platform update completed successfully.'
                }
                logger.info(f"Qibocal {action} completed successfully for {report_path}")
                return jsonify({
                    'success': True, 
                    'message': success_messages[action],
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
            else:
                error_msg = f"Qibocal {action} failed with exit code {result.returncode}"
                if result.stderr:
                    error_msg += f": {result.stderr}"
                logger.error(f"Qibocal {action} failed for {report_path}: {error_msg}")
                return jsonify({
                    'success': False, 
                    'message': error_msg,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }), 500
                
        except subprocess.TimeoutExpired:
            logger.error(f"Qibocal {action} timed out for {report_path}")
            return jsonify({'success': False, 'message': f'Qibocal {action} operation timed out (5 minutes)'}), 408
            
        except Exception as e:
            logger.error(f"Error executing qibocal {action} for {report_path}: {str(e)}")
            return jsonify({'success': False, 'message': f'Error executing qibocal {action}: {str(e)}'}), 500

    @app.route("/repeat_experiment", methods=['POST'])
    def repeat_experiment_route():
        """Repeat an experiment by submitting it to SLURM."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            report_path = request.form.get('report_path')
            
            if not report_path:
                return jsonify({'success': False, 'message': 'Report path is required'}), 400
            
            # Use the modular repeat_experiment function
            result = repeat_experiment(report_path, config)
            
            if result['success']:
                logger.info(f"Experiment repeat submitted: {result['experiment_id']}")
                return jsonify(result)
            else:
                logger.error(f"Failed to repeat experiment: {result['message']}")
                return jsonify(result), 400
                
        except Exception as e:
            logger.error(f"Error in repeat_experiment route: {str(e)}")
            return jsonify({'success': False, 'message': f'Error repeating experiment: {str(e)}'}), 500

    @app.route("/submit_experiment", methods=['POST'])
    def submit_experiment_route():
        """Submit a new experiment to SLURM."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            
            # Check if runcard file was uploaded
            if 'runcard' not in request.files:
                return jsonify({'success': False, 'message': 'No runcard file provided'}), 400
            
            runcard_file = request.files['runcard']
            if runcard_file.filename == '':
                return jsonify({'success': False, 'message': 'No runcard file selected'}), 400
            
            # Get optional environment parameter
            environment = request.form.get('environment')
            
            # Save uploaded file temporarily
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as tmp_file:
                runcard_content = runcard_file.read().decode('utf-8')
                tmp_file.write(runcard_content)
                tmp_runcard_path = tmp_file.name
            
            try:
                # Use the modular submit_experiment function
                result = submit_experiment(tmp_runcard_path, config, environment)
                
                if result['success']:
                    logger.info(f"New experiment submitted: {result['experiment_id']}")
                    return jsonify(result)
                else:
                    logger.error(f"Failed to submit experiment: {result['message']}")
                    return jsonify(result), 400
            finally:
                # Clean up temporary file
                os.unlink(tmp_runcard_path)
                
        except Exception as e:
            logger.error(f"Error in submit_experiment route: {str(e)}")
            return jsonify({'success': False, 'message': f'Error submitting experiment: {str(e)}'}), 500

    @app.route("/api/submit_experiment_data", methods=['POST'])
    def submit_experiment_data_route():
        """Submit a new experiment to SLURM using runcard data."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            
            # Get JSON data from request
            if not request.is_json:
                return jsonify({'success': False, 'message': 'Request must be JSON'}), 400
            
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'message': 'No data provided'}), 400
            
            # Extract runcard data and optional environment
            runcard_data = data.get('runcard_data')
            environment = data.get('environment')
            
            if not runcard_data:
                return jsonify({'success': False, 'message': 'No runcard_data provided'}), 400
            
            # Validate required fields
            if 'platform' not in runcard_data:
                return jsonify({'success': False, 'message': 'Missing required field: platform'}), 400
            
            # Use the enhanced submit_experiment function with runcard_data
            result = submit_experiment(runcard_data=runcard_data, config=config, environment=environment)
            
            if result['success']:
                logger.info(f"New experiment submitted with data: {result['experiment_id']}")
                return jsonify(result)
            else:
                logger.error(f"Failed to submit experiment with data: {result['message']}")
                return jsonify(result), 400
                
        except Exception as e:
            logger.error(f"Error in submit_experiment_data route: {str(e)}")
            return jsonify({'success': False, 'message': f'Error submitting experiment: {str(e)}'}), 500

    @app.route("/api/experiments", methods=['GET'])
    def api_list_experiments():
        """API endpoint to list user experiments."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            experiments = list_user_experiments(config)
            return jsonify({
                'success': True,
                'experiments': experiments,
                'count': len(experiments)
            })
        except Exception as e:
            logger.error(f"Error listing experiments: {str(e)}")
            return jsonify({'success': False, 'message': f'Error listing experiments: {str(e)}'}), 500

    @app.route("/api/experiments/<experiment_id>", methods=['GET'])
    def api_experiment_status(experiment_id):
        """API endpoint to get experiment status."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            status = get_experiment_status(experiment_id, config)
            if status:
                return jsonify({
                    'success': True,
                    'experiment': status
                })
            else:
                return jsonify({'success': False, 'message': 'Experiment not found'}), 404
        except Exception as e:
            logger.error(f"Error getting experiment status: {str(e)}")
            return jsonify({'success': False, 'message': f'Error getting experiment status: {str(e)}'}), 500

    logger.debug("Routes module initialized")
    return app
