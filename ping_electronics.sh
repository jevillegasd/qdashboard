#!/bin/bash
# Job script to ping electronics IPs for qpu164
for ip in ['192.168.0.20', '192.168.0.32']; do
    ping -c 1 $ip > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Connection error to $ip"
        exit 1
    fi
done
echo "All electronics IPs are reachable"
