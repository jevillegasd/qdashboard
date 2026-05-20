#!/bin/bash
# Job script to ping electronics IPs for qw5q_platinum
for ip in ['192.168.0.22', '192.168.0.38']; do
    ping -c 1 $ip > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Connection error to $ip"
        exit 1
    fi
done
echo "All electronics IPs are reachable"
