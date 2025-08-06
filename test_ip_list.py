# test monitoring / get_instruments_ip

from qdashboard.qpu.monitoring import get_instruments_ip

def test_get_instruments_ip():
    # Test with a valid QPU name
    qpu_name = 'QPU118'
    ip = get_instruments_ip(qpu_name)
    print(f"IP address for {qpu_name}: {ip}")
    assert isinstance(ip, list) and len(ip) > 0, "Expected a non-empty string for the IP address"

if __name__ == "__main__":
    test_get_instruments_ip()
    print("Test passed!")