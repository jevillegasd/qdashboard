#!/usr/bin/env python3
"""
QDashboard Platforms Manager - CLI tool to manage qibolab platforms repository
"""

import sys
import argparse
from qdashboard.qpu.platforms import (
    ensure_platforms_directory, 
    update_platforms_repository,
    get_platforms_path,
    list_repository_branches,
    switch_repository_branch,
    get_current_branch_info,
    QIBOLAB_PLATFORMS_REPO
)

from qdashboard.utils.logger import get_logger
logger = get_logger(__name__)

def cmd_setup(args):
    """Set up the platforms directory."""
    try:
        path = ensure_platforms_directory(args.root)
        print(f"✅ Platforms directory ready at: {path}")
        
        # List available platforms
        import os
        if os.path.exists(path):
            platforms = [d for d in os.listdir(path) 
                        if os.path.isdir(os.path.join(path, d)) and not d.startswith('.') and not d.startswith('_')]
            if platforms:
                print(f"📋 Available platforms: {', '.join(sorted(platforms))}")
            else:
                print("📋 No platforms found in directory")
                
    except Exception as e:
        print(f"❌ Error setting up platforms: {e}")
        sys.exit(1)


def cmd_update(args):
    """Update the platforms repository."""
    try:
        path = get_platforms_path(args.root)
        if not path:
            print("❌ Platforms directory not found. Run 'setup' first.")
            sys.exit(1)
            
        success = update_platforms_repository(path)
        if success:
            print(f"✅ Platforms repository updated successfully")
        else:
            print(f"❌ Failed to update platforms repository")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error updating platforms: {e}")
        sys.exit(1)


def cmd_status(args):
    """Show status of platforms directory."""
    import os
    
    # Check environment variable
    env_path = os.environ.get('QIBOLAB_PLATFORMS')
    if env_path:
        print(f"🔧 QIBOLAB_PLATFORMS: {env_path}")
        if os.path.exists(env_path):
            print("   ✅ Directory exists")
        else:
            print("   ❌ Directory does not exist")
    else:
        print("🔧 QIBOLAB_PLATFORMS: Not set")
    
    # Check default path
    try:
        path = get_platforms_path(args.root)
        if path:
            print(f"📁 Platforms directory: {path}")
            
            # Check if it's a git repository
            git_path = os.path.join(path, '.git')
            if os.path.exists(git_path):
                print("   ✅ Git repository detected")
                
                # Get current branch info
                branch_info = get_current_branch_info(path)
                if branch_info:
                    print(f"   🌿 Current branch: {branch_info['branch']}")
                    print(f"   📝 Latest commit: {branch_info['commit']} - {branch_info['commit_message']}")
                    
                    if branch_info['behind'] > 0:
                        print(f"   ⬇️  Behind upstream: {branch_info['behind']} commits")
                    if branch_info['ahead'] > 0:
                        print(f"   ⬆️  Ahead of upstream: {branch_info['ahead']} commits")
                    
                    status_emoji = "✅" if branch_info['clean'] else "⚠️"
                    status_text = "clean" if branch_info['clean'] else "has uncommitted changes"
                    print(f"   {status_emoji} Working directory: {status_text}")
                
                # Try to get git remote info
                try:
                    import subprocess
                    result = subprocess.run(['git', '-C', path, 'remote', 'get-url', 'origin'], 
                                          capture_output=True, text=True, check=True)
                    remote_url = result.stdout.strip()
                    print(f"   🔗 Remote: {remote_url}")
                except:
                    pass
            else:
                print("   ❌ Not a git repository")
                
            # List platforms
            platforms = [d for d in os.listdir(path) 
                        if os.path.isdir(os.path.join(path, d)) and not d.startswith('.') and not d.startswith('_')]
            if platforms:
                print(f"   📋 Platforms ({len(platforms)}): {', '.join(sorted(platforms))}")
            else:
                print("   📋 No platforms found")
        else:
            print("📁 Platforms directory: Not available")
            
    except Exception as e:
        print(f"❌ Error checking status: {e}")


def cmd_branches(args):
    """List available branches in the platforms repository."""
    try:
        path = get_platforms_path(args.root)
        if not path:
            print("❌ Platforms directory not found. Run 'setup' first.")
            sys.exit(1)
            
        branches_info = list_repository_branches(path)
        if not branches_info:
            print("❌ Failed to retrieve branch information")
            sys.exit(1)
        
        print(f"🌿 Branch information for platforms repository:")
        print(f"   📍 Current branch: {branches_info['current']}")
        print()
        
        print("🏠 Local branches:")
        for branch in branches_info['local']:
            marker = " ← current" if branch == branches_info['current'] else ""
            print(f"   • {branch}{marker}")
        
        print()
        print("🌐 Remote branches:")
        for branch in branches_info['remote']:
            print(f"   • {branch}")
            
    except Exception as e:
        print(f"❌ Error listing branches: {e}")
        sys.exit(1)


def cmd_switch(args):
    """Switch to a specific branch."""
    try:
        path = get_platforms_path(args.root)
        if not path:
            print("❌ Platforms directory not found. Run 'setup' first.")
            sys.exit(1)
        
        # Get current branch info before switching
        current_info = get_current_branch_info(path)
        if current_info:
            print(f"🌿 Currently on branch: {current_info['branch']}")
        
        # Perform the switch
        success = switch_repository_branch(path, args.branch, create_if_not_exists=args.create)
        
        if success:
            print(f"✅ Successfully switched to branch: {args.branch}")
            
            # Show new branch info
            new_info = get_current_branch_info(path)
            if new_info:
                print(f"📝 Latest commit: {new_info['commit']} - {new_info['commit_message']}")
            
            # List platforms after switch
            import os
            platforms = [d for d in os.listdir(path) 
                        if os.path.isdir(os.path.join(path, d)) and not d.startswith('.') and not d.startswith('_')]
            if platforms:
                print(f"📋 Available platforms: {', '.join(sorted(platforms))}")
        else:
            print(f"❌ Failed to switch to branch: {args.branch}")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error switching branch: {e}")
        sys.exit(1)


def main():
    """Main entry point for the platforms manager."""
    parser = argparse.ArgumentParser(
        prog='qdashboard-platforms',
        description='QDashboard Platforms Manager',
        epilog=f'Repository: {QIBOLAB_PLATFORMS_REPO}'
    )
    
    parser.add_argument(
        '--root',
        type=str,
        default=None,
        help='Root directory (default: user home directory)'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Setup command
    setup_parser = subparsers.add_parser('setup', help='Set up platforms directory')
    setup_parser.set_defaults(func=cmd_setup)
    
    # Update command  
    update_parser = subparsers.add_parser('update', help='Update platforms repository')
    update_parser.set_defaults(func=cmd_update)
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show platforms status')
    status_parser.set_defaults(func=cmd_status)
    
    # Branches command
    branches_parser = subparsers.add_parser('branches', help='List available branches')
    branches_parser.set_defaults(func=cmd_branches)
    
    # Switch command
    switch_parser = subparsers.add_parser('switch', help='Switch to a specific branch')
    switch_parser.add_argument('branch', help='Branch name to switch to')
    switch_parser.add_argument('--create', '-c', action='store_true', 
                              help='Create branch if it does not exist')
    switch_parser.set_defaults(func=cmd_switch)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == '__main__':
    main()
