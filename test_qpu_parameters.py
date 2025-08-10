#!/usr/bin/env python3
"""
Test script for debugging get_qpu_parameters function.
"""

import sys
import os
import json
from qdashboard.experiments.protocols import get_qpu_parameters

def test_qpu_parameters(platform_name):
    """Test the get_qpu_parameters function with detailed output."""
    print(f"Testing get_qpu_parameters with platform: {platform_name}")
    print("-" * 50)
    
    # Check environment variables
    print("Environment check:")
    qibolab_platforms = os.environ.get('QIBOLAB_PLATFORMS', 'Not set')
    print(f"  QIBOLAB_PLATFORMS: {qibolab_platforms}")
    
    # Test the function
    try:
        result = get_qpu_parameters(platform_name)
        print("\nResult:")
        print(json.dumps(result, indent=2, default=str))
        
        # Additional analysis
        if 'single_qubit_gates' in result:
            print(f"\nSingle-qubit gates found: {len(result['single_qubit_gates'])}")
            for gate, qubits in result['single_qubit_gates'].items():
                print(f"  {gate}: {qubits}")
        
        if 'two_qubit_gates' in result:
            print(f"\nTwo-qubit gates found: {len(result['two_qubit_gates'])}")
            for gate, pairs in result['two_qubit_gates'].items():
                print(f"  {gate}: {pairs}")
                
    except Exception as e:
        print(f"Error testing function: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    platform = sys.argv[1] if len(sys.argv) > 1 else "qpu118"
    test_qpu_parameters(platform)
