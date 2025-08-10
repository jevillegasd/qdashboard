#!/bin/bash
# Job script to ping electronics IPs for qw11q
for ip in ['192.168.0.101:80', '192.168.0.34', '192.168.0.33']; do
    ping -c 1 $ip > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Connection error to $ip"
        exit 1
    fi
done
echo "All electronics IPs are reachable"
