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

import sys
import os

# Add the qdashboard package to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qdashboard.core.app import create_app, get_config
from qdashboard.web.routes import register_routes
from qdashboard.web.file_browser import PathView


def main():
    """Main entry point for the QDashboard application."""
    
    # Get configuration
    config = get_config()
    
    # Create Flask app
    app = create_app()
    
    # Register main routes
    register_routes(app, config)
    
    # Register file browser - create a proper class-based view
    class ConfiguredPathView(PathView):
        def __init__(self):
            super().__init__(root_path=config['root'], key=config['key'])
    
    path_view = ConfiguredPathView.as_view('path_view')
    app.add_url_rule('/files', view_func=path_view)
    app.add_url_rule('/files/<path:p>', view_func=path_view)
    
    # Check for command line named arguments --port
    if '--port' in sys.argv:
        port_index = sys.argv.index('--port') + 1
        if port_index < len(sys.argv):
            try:
                config['port'] = int(sys.argv[port_index])
            except ValueError:
                print(f"Invalid port number: {sys.argv[port_index]}")
                sys.exit(1)
        else:
            print("No port number provided after --port argument.")
            sys.exit(1)
    
    # Set default port if not specified
    if 'port' not in config or not config['port']:
        if len(sys.argv) == 1:
            try:
                config['port'] = int(sys.argv[1])
            except ValueError:
                print(f"Invalid port number: {sys.argv[1]}")
                sys.exit(1)
        else:
            # Check for an available port in the default range
            import random
            from socket import socket, AF_INET, SOCK_STREAM
            
            def find_free_port():
                with socket(AF_INET, SOCK_STREAM) as s:
                    s.bind(('', 0))
                    return s.getsockname()[1]

            config['port'] = find_free_port()
            print(f"No port specified, using random available port: {config['port']}")

    # Check for command line port argument
    
    
    # Print startup information
    print('Quantum Dashboard Server running on http://{}:{}'.format(config['host'], config['port']))
    print('Serving path: {}'.format(config['root']))
    print('Authentication key: {}'.format(config['key']))
    print('Press Ctrl+C to stop')
    
    # Start the Flask application
    try:
        app.run(config['host'], config['port'], threaded=True, debug=False)
    except KeyboardInterrupt:
        print('\nQuantum Dashboard Server stopped')
    except Exception as e:
        print(f'Error starting server: {e}')
        sys.exit(1)
    
    sys.stdout.flush()
    sys.exit(0)


if __name__ == '__main__':
    main()
