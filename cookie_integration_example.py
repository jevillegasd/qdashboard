"""
Example of how to integrate the cookie-based qibo versions in your Flask routes.
Add this logic to your web routes.
"""

from flask import request, make_response
from qdashboard.qpu.monitoring import get_qibo_versions

# In your route handlers:

@app.route('/')
def dashboard():
    # Get versions with cookie support
    version_data = get_qibo_versions(request=request)
    
    # Create response
    response = make_response(render_template('dashboard.html', 
                                           qibo_versions=version_data['versions']))
    
    # Set cookie if we have fresh data
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', 
                          version_data['cookie_data'],
                          max_age=24*60*60,  # 24 hours
                          httponly=True,
                          secure=False)  # Set to True in production with HTTPS
    
    return response

@app.route('/api/versions/refresh', methods=['POST'])
def refresh_versions():
    """API endpoint to force refresh versions"""
    version_data = get_qibo_versions(force_refresh=True, request=request)
    
    response = make_response({
        'versions': version_data['versions'],
        'refreshed_at': version_data['cached_at']
    })
    
    # Update cookie with fresh data
    response.set_cookie('qibo_versions', 
                      version_data['cookie_data'],
                      max_age=24*60*60,
                      httponly=True,
                      secure=False)
    
    return response

# For QPU status page:
@app.route('/qpus')
def qpus():
    version_data = get_qibo_versions(request=request)
    qpu_details = get_qpu_details()
    
    response = make_response(render_template('qpus.html', 
                                           qibo_versions=version_data['versions'],
                                           **qpu_details))
    
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', 
                          version_data['cookie_data'],
                          max_age=24*60*60,
                          httponly=True,
                          secure=False)
    
    return response
