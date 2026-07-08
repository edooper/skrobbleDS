#!/usr/bin/env python3
"""
Test script to verify UPnP multicast reception
Run this inside the container to test if multicast works
"""
import socket
import struct
import sys

MCAST_GRP = '239.255.255.250'
MCAST_PORT = 1900

print(f"Testing UPnP multicast reception on {MCAST_GRP}:{MCAST_PORT}")
print("This will listen for 30 seconds...")
print()

try:
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind to SSDP port
    sock.bind(('', MCAST_PORT))

    # Join multicast group
    mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    # Set timeout
    sock.settimeout(30.0)

    print("✓ Socket created and bound to multicast group")
    print("✓ Listening for SSDP packets...")
    print()

    packet_count = 0
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            packet_count += 1
            print(f"[{packet_count}] Received {len(data)} bytes from {addr[0]}:{addr[1]}")

            # Decode and show first line
            try:
                lines = data.decode('utf-8', errors='ignore').split('\r\n')
                print(f"    First line: {lines[0]}")
            except:
                print(f"    (Binary data)")
            print()

        except socket.timeout:
            break

    print(f"\nReceived {packet_count} multicast packets")

    if packet_count == 0:
        print("✗ FAILED: No multicast packets received")
        print("\nPossible issues:")
        print("  - Container not using host networking")
        print("  - Firewall blocking multicast")
        print("  - No UPnP devices on network")
        sys.exit(1)
    else:
        print("✓ SUCCESS: Multicast is working!")
        sys.exit(0)

except PermissionError:
    print("✗ ERROR: Permission denied - may need to run as root")
    sys.exit(1)
except OSError as e:
    print(f"✗ ERROR: {e}")
    print("\nThis usually means:")
    print("  - Port 1900 already in use (SkrobbleDS running?)")
    print("  - Or network interface issues")
    sys.exit(1)
except Exception as e:
    print(f"✗ ERROR: {e}")
    sys.exit(1)
finally:
    sock.close()
