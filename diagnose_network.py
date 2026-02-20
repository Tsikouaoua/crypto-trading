#!/usr/bin/env python3
"""Diagnose network connectivity issues"""

import socket
import requests
import ssl
from urllib.parse import urlparse

print("=== Network Diagnostics ===\n")

# 1. DNS Resolution
print("1. Testing DNS resolution...")
try:
    ip = socket.gethostbyname("fapi.binance.com")
    print(f"   ✓ fapi.binance.com resolves to: {ip}")
except socket.gaierror as e:
    print(f"   ✗ DNS resolution failed: {e}")

# 2. Socket connection
print("\n2. Testing socket connection...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    result = sock.connect_ex(("fapi.binance.com", 443))
    if result == 0:
        print("   ✓ Socket connection to port 443 successful")
    else:
        print(f"   ✗ Socket connection failed: code {result}")
    sock.close()
except Exception as e:
    print(f"   ✗ Socket error: {e}")

# 3. SSL Handshake
print("\n3. Testing SSL handshake...")
try:
    context = ssl.create_default_context()
    with socket.create_connection(("fapi.binance.com", 443), timeout=5) as sock:
        with context.wrap_socket(sock, server_hostname="fapi.binance.com") as ssock:
            print(f"   ✓ SSL handshake successful")
            print(f"     Protocol: {ssock.version()}")
except Exception as e:
    print(f"   ✗ SSL handshake failed: {e}")

# 4. HTTP Request without SSL verification
print("\n4. Testing HTTP request (SSL verification disabled)...")
try:
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/ping",
        timeout=5,
        verify=False  # Disable SSL verification
    )
    print(f"   ✓ Request successful: {r.status_code}")
except requests.exceptions.Timeout:
    print("   ✗ Request timed out")
except requests.exceptions.ConnectionError as e:
    print(f"   ✗ Connection error: {e}")
except Exception as e:
    print(f"   ✗ Request failed: {e}")

# 5. HTTP Request with SSL verification
print("\n5. Testing HTTP request (SSL verification enabled)...")
try:
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/ping",
        timeout=5,
        verify=True
    )
    print(f"   ✓ Request successful: {r.status_code}")
except requests.exceptions.Timeout:
    print("   ✗ Request timed out")
except requests.exceptions.ConnectionError as e:
    print(f"   ✗ Connection error: {e}")
except Exception as e:
    print(f"   ✗ Request failed: {e}")

print("\n=== Summary ===")
print("If DNS works but socket/SSL fails: Check firewall/proxy")
print("If request works without SSL verification: SSL certificate issue")
print("If requests timeout: Network/ISP blocking or timeout issue")
