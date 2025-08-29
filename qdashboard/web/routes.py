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
            last_path = config.get('home_path', '/home')
            
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
    def repeat_experiment():
        """Repeat an experiment by submitting it to SLURM."""
        try:
            config = current_app.config['QDASHBOARD_CONFIG']
            report_path = request.form.get('report_path')
            
            if not report_path:
                return jsonify({'success': False, 'message': 'Report path is required'}), 400
            
            # Construct full path
            full_report_path = os.path.join(config['root'], report_path.lstrip('/'))
            
            if not os.path.exists(full_report_path):
                return jsonify({'success': False, 'message': f'Report path does not exist: {report_path}'}), 404
            
            # Check for required files
            runcard_path = None
            parameters_json_path = None
            
            # Look for runcard.yml in the report directory
            for filename in os.listdir(full_report_path):
                if filename.startswith('runcard') and filename.endswith('.yml'):
                    runcard_path = os.path.join(full_report_path, filename)
                    break
            
            if not runcard_path:
                return jsonify({'success': False, 'message': 'No runcard.yml file found in report directory'}), 400
            
            # Generate a unique temporary directory name with 8-digit hex timestamp
            import time
            timestamp_hex = format(int(time.time()), '08x')
            temp_dir_name = f"qq_{timestamp_hex}"
            
            # Create temporary directory in user's home directory instead of /tmp
            user_home = os.path.expanduser("~")
            temp_base = os.path.join(user_home, '.qdashboard', 'temp')
            os.makedirs(temp_base, exist_ok=True)
            temp_dir = os.path.join(temp_base, temp_dir_name)
            
            # Create temporary directory
            os.makedirs(temp_dir, exist_ok=True)
            
            # Copy runcard.yml to temporary directory
            import shutil
            temp_runcard_path = os.path.join(temp_dir, 'runcard.yml')
            shutil.copy2(runcard_path, temp_runcard_path)
            
            # Read the runcard to extract platform information
            import yaml
            try:
                with open(temp_runcard_path, 'r') as f:
                    runcard_data = yaml.safe_load(f)
                platform = runcard_data.get('platform')
                partition = runcard_data.get('partition')
                environment = runcard_data.get('environment')
                if not platform:
                    return jsonify({'success': False, 'message': 'No platform specified in runcard'}), 400
                if not environment:
                    # Use the app running environment 
                    environment = config['environment']
                    if not environment:
                        return jsonify({'success': False, 'message': f'No environment specified in runcard or {environment}'}), 400
                
                # If no partition specified, try to infer it from the platform
                if not partition:
                    platforms_base = get_platforms_path(config['root'])
                    partition = get_partition(platform)
                    logger.warning(f"{platforms_base}:{partition}")
                    if not partition:
                        return jsonify({'success': False, 'message': f'No partition specified in runcard and could not infer partition for platform {platform}'}), 400
            except Exception as e:
                return jsonify({'success': False, 'message': f'Error reading runcard: {e}{str(e.__traceback__)}'}), 400
            
            # Check if parameters.json exists in the report and copy it as backup
            report_parameters_path = os.path.join(full_report_path, 'parameters.json')
            
            # Determine platform path and parameters.json location
            platforms_base = get_platforms_path(config['root'])
            platform_dir = os.path.join(platforms_base, platform)
            platform_parameters_path = os.path.join(platform_dir, 'parameters.json')
            
            if os.path.exists(report_parameters_path) and os.path.exists(platform_parameters_path):
                # Backup current platform parameters.json
                backup_parameters_path = os.path.join(temp_dir, 'parameters_backup.json')
                shutil.copy2(platform_parameters_path, backup_parameters_path)
                
                # # Replace platform parameters.json with report's version
                # # We could to this in the future to ensure the experiment is the
                # # exact same as the open report.
                # shutil.copy2(report_parameters_path, platform_parameters_path)
                # logger.info(f"Backed up platform parameters and replaced with report parameters for {platform}")
            
            # Generate output directory name (parent directory + timestamp)
            parent_dir = os.path.dirname(full_report_path)
            report_dir_name = f"qq_{timestamp_hex}"
            new_report_path = os.path.join(parent_dir, report_dir_name)
            os.makedirs(new_report_path, exist_ok=True)
            # Prepare SLURM job submission script based on run.sh
            job_script = f"""#!/bin/bash
#SBATCH --job-name=qq_{platform}
#SBATCH --partition={partition}
#SBATCH --output=logs/slurm_output.log
#SBATCH --time=01:00:00

# Set environment variables
export QIBOLAB_PLATFORMS={platforms_base}
export QIBO_PLATFORM={platform}

# Activate environment (using {environment} environment)
# source ~/.env/{environment}/bin/activate

# Run the experiment
qq run {temp_runcard_path} -o {new_report_path} -f --no-update

exit 0
"""
            
            # Write job script to temporary file
            job_script_path = os.path.join(temp_dir, 'job_script.sh')
            with open(job_script_path, 'w') as f:
                f.write(job_script)
            
            # Make script executable
            os.chmod(job_script_path, 0o755)
            
            # Submit job to SLURM
            result = subprocess.run(['sbatch', job_script_path], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Extract job ID from sbatch output
                job_id = None
                for line in result.stdout.split('\n'):
                    if 'Submitted batch job' in line:
                        job_id = line.split()[-1]
                        break
                
                # Save job information to temporary directory
                job_info = {
                    'job_id': job_id,
                    'output_dir': new_report_path,
                    'temp_dir': temp_dir,
                    'platform': platform,
                    'submitted_at': time.time(),
                    'original_report': full_report_path
                }
                
                job_info_path = os.path.join(temp_dir, 'job_info.json')
                with open(job_info_path, 'w') as f:
                    json.dump(job_info, f, indent=2)
                    
                logger.info(f"Experiment repeat job submitted: {job_id}, output: {new_report_path}")
                # Save to file logs/last_report_path
                slurm_log = slurm_log_path()
                config = current_app.config['QDASHBOARD_CONFIG']
                last_report_path = config.get('last_report_path', '.qdashboard/logs/last_report_path')
                with open(os.path.join(config['root'], last_report_path), 'w') as f:
                    f.write(new_report_path)
                return jsonify({
                    'success': True,
                    'message': 'Experiment submitted successfully',
                    'job_id': job_id,
                    'output_dir': new_report_path,
                    'temp_dir': temp_dir,
                    'job_info': job_info
                })
            else:
                logger.error(f"Failed to submit SLURM job: {result.stderr}")
                return jsonify({'success': False, 'message': f'Failed to submit job: {result.stderr}'}), 500
                
        except Exception as e:
            logger.error(f"Error repeating experiment: {str(e)}")
            return jsonify({'success': False, 'message': f'Error repeating experiment: {str(e)}'}), 500

    logger.debug("Routes module initialized")
    return app
