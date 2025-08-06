"""
QPU topology analysis and visualization utilities.
"""

import os
import json
import yaml
import base64
import io
import traceback

try:
    import rustworkx as rx
    HAS_RUSTWORKX = True
except ImportError:
    HAS_RUSTWORKX = False
    print("Warning: rustworkx not available. Topology detection will be limited.")

try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    import numpy as np
    from rustworkx.visualization import mpl_draw
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Warning: matplotlib not available. Topology visualization will be limited.")


def get_connectivity_data_from_qpu_config(qpu_path):
    """
    Extract connectivity data from QPU configuration files.
    
    Args:
        qpu_path: Path to the QPU directory
        
    Returns:
        list: List of connectivity pairs, or None if not found
    """
    # Look for common configuration file names
    config_files = ['parameters.json', 'topology.json']
    
    for config_file in config_files:
        config_path = os.path.join(qpu_path, config_file)
        if os.path.exists(config_path):
            try:
                # Try to read the configuration file (json or yaml)
                if config_file.endswith('.json'):
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                elif config_file.endswith('.yaml') or config_file.endswith('.yml'):
                    with open(config_path, 'r') as f:
                        config_data = yaml.load(f, Loader=yaml.FullLoader)
                else:
                    continue  # Skip unsupported file types
                
                # Look for connectivity data
                connectivity = None
                connectivity_keys = [
                    'topology', 'connectivity', 'connections', 'coupling_map', 'couplings',
                    'native_gates', 'edges', 
                ]
                
                # Search through the config structure
                for key in connectivity_keys:
                    if key in config_data:
                        connectivity = config_data[key]
                        break
                
                # Also check nested structures
                if not connectivity:
                    for section in ['platform', 'device', 'chip', 'qubits']:
                        if section in config_data:
                            section_data = config_data[section]
                            for key in connectivity_keys:
                                if key in section_data:
                                    connectivity = section_data[key]
                                    break
                            if connectivity:
                                break
                
                # If we found connectivity data, format it
                if connectivity:
                    if isinstance(connectivity, list):
                        return connectivity
                    elif isinstance(connectivity, dict):
                        pairs = []
                        for source, targets in connectivity.items():
                            if isinstance(targets, list):
                                for target in targets:
                                    pairs.append([int(source), int(target)])
                            else:
                                pairs.append([int(source), int(targets)])
                        return pairs
                
            except Exception as e:
                print(f"Error reading config file {config_path}: {e}")
                continue
    
    return None


def infer_topology_from_connectivity(connectivity_data):
    """
    Infer topology type from connectivity data using rustworkx graph analysis.
    
    Args:
        connectivity_data: List of qubit pairs representing connections, e.g. [[0,1], [1,2], [2,3]]
        
    Returns:
        str: Topology type ('chain', 'lattice', 'bow_tie', 'honeycomb', 'star', 'ring', 'custom')
    """
    if not connectivity_data or not HAS_RUSTWORKX:
        return 'unknown'
    
    try:
        # Create a graph using rustworkx
        graph = rx.PyGraph()
        
        # Find all unique qubits from connectivity data
        qubits = set()
        for connection in connectivity_data:
            if len(connection) >= 2:
                qubits.add(connection[0])
                qubits.add(connection[1])
        
        if len(qubits) == 0:
            return 'isolated'
        
        # Add nodes to graph
        qubit_to_node = {}
        for qubit in sorted(qubits):
            node_idx = graph.add_node(qubit)
            qubit_to_node[qubit] = node_idx
        
        # Add edges
        for connection in connectivity_data:
            if len(connection) >= 2:
                qubit1, qubit2 = connection[0], connection[1]
                if qubit1 in qubit_to_node and qubit2 in qubit_to_node:
                    graph.add_edge(qubit_to_node[qubit1], qubit_to_node[qubit2], None)
        
        num_nodes = len(qubits)
        num_edges = len(connectivity_data)
        
        # Single qubit case
        if num_nodes == 1:
            return 'single'
        
        # Calculate graph metrics
        degrees = [graph.degree(node) for node in graph.node_indices()]
        max_degree = max(degrees) if degrees else 0
        min_degree = min(degrees) if degrees else 0
        avg_degree = sum(degrees) / len(degrees) if degrees else 0
        
        # Check if graph is connected
        is_connected = rx.is_connected(graph)
        
        # Topology classification logic
        
        # Chain topology: linear arrangement, max degree 2, exactly n-1 edges
        if (max_degree <= 2 and num_edges == num_nodes - 1 and is_connected and
            degrees.count(1) == 2 and degrees.count(2) == num_nodes - 2):
            return 'chain'
        
        # Ring topology: circular arrangement, all degree 2, exactly n edges
        if (max_degree == 2 and min_degree == 2 and num_edges == num_nodes and is_connected):
            return 'ring'
        
        # Star topology: one central node connected to all others
        if (max_degree == num_nodes - 1 and degrees.count(1) == num_nodes - 1 and 
            degrees.count(num_nodes - 1) == 1):
            return 'star'
        
        # Lattice topology: regular 2D grid-like structure
        # Typical characteristics: nodes have degree 2-4, rectangular arrangement
        if (2 <= avg_degree <= 4 and max_degree <= 4 and is_connected):
            # Check for regular lattice patterns
            corner_nodes = degrees.count(2)  # Corner nodes in 2D lattice
            edge_nodes = degrees.count(3)    # Edge nodes in 2D lattice  
            inner_nodes = degrees.count(4)   # Inner nodes in 2D lattice
            
            total_special = corner_nodes + edge_nodes + inner_nodes
            if total_special == num_nodes and corner_nodes >= 4:
                return 'lattice'
        
        # Bow tie topology: two connected components joined at a bridge
        if num_nodes >= 5:
            # Look for articulation points (bridge nodes)
            articulation_points = rx.articulation_points(graph)
            if len(articulation_points) == 1:
                # Remove the articulation point and check connected components
                temp_graph = graph.copy()
                temp_graph.remove_node(articulation_points[0])
                components = rx.connected_components(temp_graph)
                if len(components) == 2:
                    comp_sizes = [len(comp) for comp in components]
                    # Bow tie typically has roughly equal-sized components
                    if abs(comp_sizes[0] - comp_sizes[1]) <= 1:
                        return 'bow_tie'
        
        # Honeycomb topology: hexagonal lattice structure
        # Characteristics: degree 3 for most nodes, specific pattern
        if (min_degree >= 2 and max_degree <= 3 and is_connected):
            degree_3_nodes = degrees.count(3)
            if degree_3_nodes >= num_nodes * 0.8:  # Most nodes have degree 3
                # Check for hexagonal cycles (harder to detect, simplified check)
                return 'honeycomb'
        
        # If none of the above patterns match
        return 'custom'
        
    except Exception as e:
        print(f"Error analyzing topology: {e}")
        return 'unknown'


def get_topology_from_qpu_config(qpu_path):
    """
    Extract topology information from QPU configuration files.
    
    Args:
        qpu_path: Path to the QPU directory
        
    Returns:
        str: Inferred topology type
    """
    # Look for common configuration file names
    config_files = ['parameters.json', 'topology.json']
    
    for config_file in config_files:
        config_path = os.path.join(qpu_path, config_file)
        if os.path.exists(config_path):
            try:
                # Try to read the configuration file (json or yaml)
                if config_file.endswith('.json'):
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                elif config_file.endswith('.yaml') or config_file.endswith('.yml'):
                    with open(config_path, 'r') as f:
                        config_data = yaml.load(f, Loader=yaml.FullLoader)
                else:
                    continue  # Skip unsupported file types
            except Exception as e:
                print(f"Error reading config file {config_path}: {e}")
                continue

            try:
                # Look for connectivity data in various possible locations
                connectivity = None
                
                # Common key names for connectivity data
                connectivity_keys = [
                    'topology', 'connectivity', 'connections', 'coupling_map', 'couplings',
                    'native_gates', 'edges', 
                ]
                
                # Search through the config structure
                for key in connectivity_keys:
                    if key in config_data:
                        connectivity = config_data[key]
                        break
                
                # Also check nested structures
                if not connectivity:
                    for section in ['platform', 'device', 'chip', 'qubits']:
                        if section in config_data:
                            section_data = config_data[section]
                            for key in connectivity_keys:
                                if key in section_data:
                                    connectivity = section_data[key]
                                    break
                            if connectivity:
                                break
                
                # If we found connectivity data, analyze it
                if connectivity:
                    # Handle different formats of connectivity data
                    if isinstance(connectivity, list):
                        # Direct list of connections
                        return infer_topology_from_connectivity(connectivity)
                    elif isinstance(connectivity, dict):
                        # Dictionary format - extract pairs
                        pairs = []
                        for source, targets in connectivity.items():
                            if isinstance(targets, list):
                                for target in targets:
                                    pairs.append([int(source), int(target)])
                            else:
                                pairs.append([int(source), int(targets)])
                        return infer_topology_from_connectivity(pairs)
                
            except (yaml.YAMLError, IOError, ValueError) as e:
                print(f"Error reading config file {config_path}: {e}")
                continue
    
    return 'N/A'


def generate_topology_visualization(connectivity_data, topology_type):
    """
    Generate a topology visualization using rustworkx mpl_draw function.
    
    Args:
        connectivity_data: List of qubit pairs representing connections
        topology_type: String indicating the topology type
        
    Returns:
        str: Base64 encoded PNG image of the topology, or None if generation fails
    """
    if not connectivity_data or not HAS_RUSTWORKX or not HAS_MATPLOTLIB:
        return None
    
    try:
        # Create a graph using rustworkx
        graph = rx.PyGraph()
        
        # Find all unique qubits from connectivity data
        qubits = set()
        for connection in connectivity_data:
            if len(connection) >= 2:
                qubits.add(connection[0])
                qubits.add(connection[1])
        
        if len(qubits) == 0:
            return None
        
        # Add nodes to graph
        qubit_to_node = {}
        node_labels = {}
        for qubit in sorted(qubits):
            node_idx = graph.add_node(f"Q{qubit}")
            qubit_to_node[qubit] = node_idx
            node_labels[node_idx] = f"Q{qubit}"
        
        # Add edges
        edge_list = []
        for connection in connectivity_data:
            if len(connection) >= 2:
                qubit1, qubit2 = connection[0], connection[1]
                if qubit1 in qubit_to_node and qubit2 in qubit_to_node:
                    graph.add_edge(qubit_to_node[qubit1], qubit_to_node[qubit2], None)
                    edge_list.append((qubit1, qubit2))
        
        # Generate layout based on topology type
        if topology_type == 'chain':
            # Linear layout for chains
            pos = {}
            sorted_nodes = sorted(qubits)
            for i, qubit in enumerate(sorted_nodes):
                node_idx = qubit_to_node[qubit]
                pos[node_idx] = (i * 2, 0)
        elif topology_type == 'ring':
            # Circular layout for rings
            pos = rx.circular_layout(graph)
        elif topology_type == 'lattice':
            # Grid layout for lattices
            pos = rx.spring_layout(graph, k=2.0, num_iter=100)
        elif topology_type == 'star':
            # Star layout - center node in middle, others around
            degrees = [graph.degree(node) for node in graph.node_indices()]
            center_node = degrees.index(max(degrees))
            pos = {}
            pos[center_node] = (0, 0)
            other_nodes = [i for i in range(len(qubits)) if i != center_node]
            for i, node in enumerate(other_nodes):
                angle = 2 * np.pi * i / len(other_nodes)
                pos[node] = (2 * np.cos(angle), 2 * np.sin(angle))
        else:
            # Default spring layout for other topologies
            pos = rx.spring_layout(graph, k=2.0, num_iter=100)

        # Create figure and use mpl_draw
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_title(f'Quantum Device Topology: {topology_type.title()}', fontsize=16, fontweight='bold')
        
        # Use rustworkx mpl_draw for graph visualization
        try:
            # Use mpl_draw with minimal parameters first
            mpl_draw(
                graph,
                pos=pos,
                ax=ax
            )
            
            # Add labels manually if mpl_draw doesn't support them
            for node_idx, (x, y) in pos.items():
                if node_idx in node_labels:
                    ax.text(x, y, node_labels[node_idx], ha='center', va='center', 
                           fontsize=12, fontweight='bold', 
                           bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))
        except Exception as draw_error:
            print(f"DEBUG: Error with mpl_draw: {draw_error}")
            # Fallback to manual plotting if mpl_draw fails
            
            # Plot edges manually
            for qubit1, qubit2 in edge_list:
                node1_idx = qubit_to_node[qubit1]
                node2_idx = qubit_to_node[qubit2]
                if node1_idx in pos and node2_idx in pos:
                    x1, y1 = pos[node1_idx]
                    x2, y2 = pos[node2_idx]
                    ax.plot([x1, x2], [y1, y2], 'b-', linewidth=2, alpha=0.7)
            
            # Plot nodes manually
            x_coords = []
            y_coords = []
            labels = []
            for qubit in sorted(qubits):
                node_idx = qubit_to_node[qubit]
                if node_idx in pos:
                    x_coords.append(pos[node_idx][0])
                    y_coords.append(pos[node_idx][1])
                    labels.append(f"Q{qubit}")
            
            ax.scatter(x_coords, y_coords, c='lightblue', s=800, alpha=0.8, 
                      edgecolors='navy', linewidths=2)
            
            # Add labels manually
            for i, label in enumerate(labels):
                ax.annotate(label, (x_coords[i], y_coords[i]), 
                           ha='center', va='center', fontweight='bold', fontsize=12)
        
        # Styling
        ax.axis('equal')
        ax.axis('off')
        plt.tight_layout()
        
        # Add some information text
        info_text = f"Topology: {topology_type.title()}\nQubits: {len(qubits)}\nConnections: {len(edge_list)}"
        plt.figtext(0.02, 0.02, info_text, fontsize=10, 
                   bbox=dict(boxstyle="round,pad=0.3", facecolor="lightgray", alpha=0.8))
        
        # Convert plot to base64 string
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
        plt.close()
        
        return img_base64
        
    except Exception as e:
        print(f"DEBUG: Error generating topology visualization: {e}")
        traceback.print_exc()
        return None
