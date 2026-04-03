"""
Simple HTTP file server for ESP32-C3 MicroPython.

Serves files from /data directory over WiFi.
Browse to http://<ip_address> to see file listing and download files.

Usage:
    import file_server
    file_server.start('YourWiFiSSID', 'YourPassword')
    
    # To start with access point mode instead (no router needed):
    file_server.start_ap('DropLogger', 'hailstone')
    # Then connect your phone/laptop to the 'DropLogger' WiFi network
    # and browse to http://192.168.4.1
"""

import network
import socket
import os
import time
from machine import Pin

DATA_DIR = '/data'
CHUNK_SIZE = 4096  # Read/send files in 4KB chunks to avoid memory issues


def get_file_size(path):
    return os.stat(path)[6]


def format_size(size):
    """Human readable file size"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def build_file_list_html():
    """Generate HTML page listing all files in DATA_DIR"""
    global device_name
    
    try:
        files = sorted(os.listdir(DATA_DIR))
    except OSError:
        files = []

    rows = ""
    total_size = 0
    for fname in files:
        fpath = f"{DATA_DIR}/{fname}"
        size = get_file_size(fpath)
        total_size += size
        rows += (f'<tr><td><a href="/download/{fname}">{fname}</a></td>'
                 f'<td>{format_size(size)}</td>'
                 f'<td><a href="/delete/{fname}" class="del" '
                 f'onclick="return confirm(\'Delete {fname}?\')">delete</a></td></tr>\n')

    delete_all = ""
    if files:
        delete_all = ('<p><a href="/delete_all" class="del-all" '
                      'onclick="return confirm(\'Delete ALL files?\')">Delete All Files</a></p>')

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{device_name} Files</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1a1a2e; color: #e0e0e0; }}
        h1 {{ color: #64ffda; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 700px; }}
        th, td {{ text-align: left; padding: 8px 16px; border-bottom: 1px solid #333; }}
        th {{ color: #64ffda; }}
        a {{ color: #82b1ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .del {{ color: #ff5252; font-size: 0.85em; }}
        .del:hover {{ color: #ff8a80; }}
        .del-all {{ color: #ff5252; font-size: 0.9em; }}
        .del-all:hover {{ color: #ff8a80; }}
        .info {{ color: #888; margin-top: 16px; }}
    </style>
</head>
<body>
    <h1>{device_name} Files</h1>
    <table>
        <tr><th>File</th><th>Size</th><th></th></tr>
        {rows}
    </table>
    <p class="info">{len(files)} files, {format_size(total_size)} total</p>
    {delete_all}
</body>
</html>"""
    return html


def get_content_type(filename):
    if filename.endswith('.csv'):
        return 'text/csv'
    elif filename.endswith('.bin'):
        return 'application/octet-stream'
    elif filename.endswith('.txt'):
        return 'text/plain'
    else:
        return 'application/octet-stream'


def handle_client(client):
    """Handle a single HTTP request"""
    try:
        request = client.recv(1024).decode('utf-8')
        if not request:
            client.close()
            return

        # Parse request line
        first_line = request.split('\r\n')[0]
        parts = first_line.split(' ')
        if len(parts) < 2:
            client.close()
            return
        path = parts[1]

        if path == '/' or path == '':
            # Serve file listing
            html = build_file_list_html()
            response = (f"HTTP/1.0 200 OK\r\n"
                        f"Content-Type: text/html\r\n"
                        f"Content-Length: {len(html)}\r\n"
                        f"Connection: close\r\n\r\n")
            client.send(response.encode())
            client.send(html.encode())

        elif path.startswith('/download/'):
            # Serve file download
            filename = path[len('/download/'):]
            filepath = f"{DATA_DIR}/{filename}"

            try:
                size = get_file_size(filepath)
                content_type = get_content_type(filename)
                header = (f"HTTP/1.0 200 OK\r\n"
                          f"Content-Type: {content_type}\r\n"
                          f"Content-Length: {size}\r\n"
                          f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
                          f"Connection: close\r\n\r\n")
                client.send(header.encode())

                # Stream file in chunks to avoid memory issues with large files
                with open(filepath, 'rb') as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        client.send(chunk)

            except OSError:
                msg = f"File not found: {filename}"
                response = (f"HTTP/1.0 404 Not Found\r\n"
                            f"Content-Type: text/plain\r\n"
                            f"Content-Length: {len(msg)}\r\n"
                            f"Connection: close\r\n\r\n{msg}")
                client.send(response.encode())
        elif path.startswith('/delete/'):
            # Delete a single file and redirect to listing
            filename = path[len('/delete/'):]
            filepath = f"{DATA_DIR}/{filename}"
            try:
                os.remove(filepath)
                print(f"Deleted: {filename}")
            except OSError:
                print(f"Delete failed: {filename}")
            # Redirect back to file listing
            response = ("HTTP/1.0 303 See Other\r\n"
                        "Location: /\r\n"
                        "Connection: close\r\n\r\n")
            client.send(response.encode())

        elif path == '/delete_all':
            # Delete all files in data directory
            try:
                for fname in os.listdir(DATA_DIR):
                    os.remove(f"{DATA_DIR}/{fname}")
                    print(f"Deleted: {fname}")
            except OSError as e:
                print(f"Delete all error: {e}")
            response = ("HTTP/1.0 303 See Other\r\n"
                        "Location: /\r\n"
                        "Connection: close\r\n\r\n")
            client.send(response.encode())

        else:
            msg = "Not Found"
            response = (f"HTTP/1.0 404 Not Found\r\n"
                        f"Content-Type: text/plain\r\n"
                        f"Content-Length: {len(msg)}\r\n"
                        f"Connection: close\r\n\r\n{msg}")
            client.send(response.encode())

    except Exception as e:
        print(f"Error handling request: {e}")
    finally:
        client.close()


def connect_wifi(ssid, password, timeout=15):
    """Connect to WiFi network, returns IP address"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if wlan.isconnected():
        wlan.disconnect()
        time.sleep(1)
    
    print(f"Connecting to {ssid}...")
    wlan.connect(ssid, password)
    
    start = time.time()
    while not wlan.isconnected():
        if time.time() - start > timeout:
            raise RuntimeError(f"Could not connect to {ssid} within {timeout}s")
        time.sleep(0.5)
    
    ip = wlan.ifconfig()[0]
    print(f"Connected! IP: {ip}")
    return ip


def create_ap(ssid, password):
    """Create WiFi access point, returns IP address"""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ssid, password=password, authmode=network.AUTH_WPA2_PSK)
    
    # Wait for AP to be active
    while not ap.active():
        time.sleep(0.5)
    
    ip = ap.ifconfig()[0]
    print(f"Access point '{ssid}' active. IP: {ip}")
    return ip


def serve(ip, port=80):
    """Start HTTP server"""
    led = Pin(6, Pin.OUT)
    
    addr = socket.getaddrinfo(ip, port)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    
    print(f"File server running at http://{ip}:{port}")
    print("Press Ctrl+C to stop\n")
    
    # Blink LED to indicate server is ready
    for _ in range(10):
        led.value(1); time.sleep(0.1)
        led.value(0); time.sleep(0.1)
    led.value(0)  # LED off = server running
    
    try:
        while True:
            client, addr = s.accept()
            handle_client(client)
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        s.close()
        led.value(0)


def start(ssid, password, port=80):
    """Connect to WiFi and start file server"""
    ip = connect_wifi(ssid, password)
    serve(ip, port)


def start_ap(ssid='DropLogger', password='hailstone', port=80):
    """Create access point and start file server"""
    global device_name
    device_name = ssid
    ip = create_ap(ssid, password)
    serve(ip, port)