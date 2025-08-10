"""
Main application routes and endpoints.
"""

import os
import subprocess
import json
from flask import render_template, request, jsonify, send_file, make_response, current_app

from ..qpu.monitoring import get_qpu_health, get_available_qpus, get_qibo_versions, get_qpu_details, get_qpu_list, qpu_parameters
from ..qpu.platforms import get_platforms_path, list_repository_branches, switch_repository_branch, get_current_branch_info, commit_changes, push_changes, stash_changes, list_stashes, apply_latest_stash, discard_changes
from ..qpu.slurm import get_slurm_status, get_slurm_output, parse_slurm_log_for_errors
from ..qpu.topology import qpu_connectivity, infer_topology_from_connectivity, generate_topology_visualization
from ..experiments.protocols import get_qibocal_protocols
from ..web.reports import report_viewer, get_latest_report_path
from ..utils.formatters import yaml_response, json_response
from qdashboard.utils.logger import get_logger

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
        last_path = get_latest_report_path(config['home_path'])
        version_data = get_qibo_versions(request=request)
        
        if not last_path:
            # Get SLURM information for the not found page
            slurm_queue_status = get_slurm_status()
            last_slurm_log = get_slurm_output()
            has_error, error_message = parse_slurm_log_for_errors()
            
            # Set last_path for file browser link
            last_path = config.get('home_path', '/home')
            
            logger.warning(f"Latest report not found, using default path: {last_path}")
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
            res = report_viewer(last_path, config['root'], version_data['versions'])
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

    @app.route("/experiments")
    def experiments():
        """Experiment builder page."""
        protocols = get_qibocal_protocols()
        qpus = get_qpu_list()
        version_data = get_qibo_versions(request=request)
        
        logger.info("Experiment builder page loaded")
        
        response = make_response(render_template('experiments.html', 
                               protocols=protocols, 
                               qpus=qpus, 
                               qibo_versions=version_data['versions']))
        
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

    logger.debug("Routes module initialized")
    return app
