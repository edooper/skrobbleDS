"""NetUtil.py - shared network interface helpers for the Upnp package"""
import socket


def get_local_ip(preferred=None, peer_ip=None):
    """Best-effort determination of the local interface IP address.

    preferred: a configured address; returned as-is unless empty/None/'0.0.0.0'
    peer_ip:   a host on the target network; the route towards it decides
               which interface to report

    Connecting a UDP socket sends no packets - it only resolves the route.
    """
    if preferred and preferred != '0.0.0.0':
        return preferred

    targets = []
    if peer_ip:
        targets.append(peer_ip)
    targets.append('8.8.8.8')

    for target in targets:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 80))
                return s.getsockname()[0]
        except OSError:
            continue

    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        return '127.0.0.1'
