# Upstream: https://github.com/llz-2002/ensptomcpfortrae (author: llz-2002).
# This copy adds portable packaging, embedded-server support and local-only binding.
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import socket
import time
import os
import sys
import json
import threading


def _app_dir():
    """Directory the exe (frozen) or this source file lives in."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    """Directory holding bundled templates/static resources."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', _app_dir())
    return os.path.dirname(os.path.abspath(__file__))


def _pick_upload_dir():
    """Keep runtime data in LOCALAPPDATA for the packaged exe.

    Using the exe directory would scatter an uploads folder next to a
    hardlink/shortcut launcher, so LOCALAPPDATA wins when frozen.
    """
    local_appdata = os.environ.get('LOCALAPPDATA')
    candidates = []
    if getattr(sys, 'frozen', False) and local_appdata:
        candidates.append(os.path.join(local_appdata, 'eNSP-MCP', 'uploads'))
    candidates.append(os.path.join(_app_dir(), 'uploads'))
    if local_appdata:
        candidates.append(os.path.join(local_appdata, 'eNSP-MCP', 'uploads'))
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, '.write-test')
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('')
            os.remove(probe)
            return folder
        except OSError:
            continue
    # Last resort: let Flask fail later rather than crash at import time.
    return os.path.join(_app_dir(), 'uploads')


def log(message):
    sys.stderr.write(f'[eNSP] {message}\n')
    sys.stderr.flush()


_RESOURCE_DIR = _resource_dir()
UPLOAD_FOLDER = _pick_upload_dir()

app = Flask(
    __name__,
    template_folder=os.path.join(_RESOURCE_DIR, 'templates'),
    static_folder=os.path.join(_RESOURCE_DIR, 'static'),
    static_url_path='/static',
)
app.config['SECRET_KEY'] = 'ensp-mcp'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# eventlet 0.33.3 does not work on Python 3.14; threading mode is what the
# original app already fell back to.  Being explicit avoids a broken import.
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

devices = {}
device_names = {}
topology_data = {}


class TelnetConnection:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        self.sock = socket.socket()
        self.sock.settimeout(1)
        self.sock.connect((self.host, self.port))
        self.sock.send(b'\r\n')
        time.sleep(0.1)
        return True

    def send_cmd(self, cmd):
        self.sock.send(f'{cmd}\r\n'.encode())
        time.sleep(1.5)
        return self.sock.recv(8192).decode('gbk', errors='ignore')

    def close(self):
        if self.sock:
            self.sock.close()


def scan_ports(start=2000, end=2050):
    """Probe the range in parallel; sequential probing can take 25+ seconds."""
    found = []
    lock = threading.Lock()

    def probe(port):
        s = socket.socket()
        s.settimeout(0.3)
        try:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                with lock:
                    found.append({'port': port, 'path': f'127.0.0.1:{port}'})
        except Exception:
            pass
        finally:
            s.close()

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=32) as pool:
        list(pool.map(probe, range(start, end + 1)))

    found.sort(key=lambda item: item['port'])
    return found


def scan_devices(start: int = 2000, end: int = 2050):
    result = scan_ports(start, end)
    for device in result:
        device['name'] = device_names.get(device['path'], device['path'])
    return result


def connect_device(port: int):
    path = f'127.0.0.1:{port}'
    if path in devices:
        return {'success': False, 'error': 'Device already connected'}
    try:
        conn = TelnetConnection('127.0.0.1', port)
        conn.connect()
        devices[path] = conn
        name = device_names.get(path, path)
        return {'success': True, 'port': port, 'path': path, 'name': name}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def send_command(path: str, command: str):
    if path not in devices:
        return {'success': False, 'error': 'Device not connected'}
    try:
        result = devices[path].send_cmd(command)
        return {'success': True, 'path': path, 'output': result}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def disconnect_device(path: str):
    if path not in devices:
        return {'success': False, 'error': 'Device not connected'}
    try:
        devices[path].close()
        del devices[path]
        return {'success': True, 'path': path}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_connected_devices():
    connected = []
    for path in devices:
        port = int(path.split(':')[1])
        connected.append({
            'port': port,
            'path': path,
            'name': device_names.get(path, path)
        })
    return connected


def rename_device(path: str, name: str):
    device_names[path] = name
    return {'success': True, 'path': path, 'name': name}


def get_topology():
    return topology_data


def save_topology(data):
    global topology_data
    topology_data = data
    return {'success': True, 'topology': topology_data}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/devices/scan')
def api_scan():
    start = request.args.get('start', 2000, type=int)
    end = request.args.get('end', 2050, type=int)
    result = scan_devices(start, end)
    return jsonify(result)


@app.route('/api/devices/connect', methods=['POST'])
def api_connect():
    data = request.get_json()
    port = data.get('port')
    result = connect_device(port)
    if result['success']:
        socketio.emit('device_connected', {'port': port, 'path': result['path'], 'name': result['name']})
    else:
        socketio.emit('device_error', {'port': port, 'error': result['error']})
    return jsonify(result)


@app.route('/api/devices/command', methods=['POST'])
def api_command():
    data = request.get_json()
    path = data.get('path')
    command = data.get('command')
    result = send_command(path, command)
    if result['success']:
        socketio.emit('device_output', {'path': path, 'output': result['output']})
    else:
        socketio.emit('device_error', {'path': path, 'error': result['error']})
    return jsonify(result)


@app.route('/api/devices/disconnect', methods=['POST'])
def api_disconnect():
    data = request.get_json()
    path = data.get('path')
    result = disconnect_device(path)
    if result['success']:
        socketio.emit('device_disconnected', {'path': path})
    return jsonify(result)


@app.route('/api/devices')
def api_get_devices():
    result = get_connected_devices()
    return jsonify(result)


@app.route('/api/devices/rename', methods=['POST'])
def api_rename():
    data = request.get_json()
    path = data.get('path')
    name = data.get('name')
    result = rename_device(path, name)
    socketio.emit('device_renamed', {'path': path, 'name': name})
    return jsonify(result)


@app.route('/api/topology', methods=['GET'])
def api_get_topology():
    return jsonify(get_topology())


@app.route('/api/topology', methods=['POST'])
def api_save_topology():
    data = request.get_json()
    result = save_topology(data)
    socketio.emit('topology_updated', get_topology())
    return jsonify(result)


@app.route('/api/topology/file', methods=['POST'])
def api_upload_topology_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    try:
        content = file.read()
        if file.filename.endswith('.json'):
            data = json.loads(content.decode('utf-8'))
        else:
            data = {'filename': file.filename, 'content': content.decode('utf-8', errors='ignore')}
        result = save_topology(data)
        socketio.emit('topology_updated', get_topology())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@socketio.on('scan')
def on_scan(data):
    start = data.get('start', 2000)
    end = data.get('end', 2050)
    result = scan_devices(start, end)
    emit('scan_result', result)


@socketio.on('get_connected_devices')
def on_get_connected_devices():
    connected = get_connected_devices()
    emit('connected_devices_list', connected)


@socketio.on('connect_device')
def on_connect(data):
    port = data.get('port')
    result = connect_device(port)
    if result['success']:
        emit('device_connected', {'port': port, 'path': result['path'], 'name': result['name']})
    else:
        emit('device_error', {'port': port, 'error': result['error']})


@socketio.on('send_command')
def on_send(data):
    path = data.get('path')
    cmd = data.get('command')
    result = send_command(path, cmd)
    if result['success']:
        emit('device_output', {'path': path, 'output': result['output']})
    else:
        emit('device_error', {'path': path, 'error': result['error']})


@socketio.on('disconnect_device')
def on_disconnect_device(data):
    path = data.get('path')
    result = disconnect_device(path)
    if result['success']:
        emit('device_disconnected', {'path': path})


@socketio.on('rename_device')
def on_rename_device(data):
    path = data.get('path')
    new_name = data.get('name', path)
    result = rename_device(path, new_name)
    emit('device_renamed', {'path': path, 'name': new_name})


# ---------------------------------------------------------------------------
# Embedded HTTP server helpers.  Flask-SocketIO already wrapped app.wsgi_app
# with its middleware, so a plain Werkzeug server can serve both the REST API
# and the Socket.IO polling transport.
# ---------------------------------------------------------------------------

_http_server = None
_http_lock = threading.Lock()


def start_http_server(host='127.0.0.1', port=5000):
    """Start the web server in a daemon thread.

    Returns True if this process now owns the server, False if the port is
    already taken (another eNSP-MCP instance is serving).
    """
    global _http_server
    with _http_lock:
        if _http_server is not None:
            return True
        try:
            from werkzeug.serving import make_server
            server = make_server(host, port, app, threaded=True)
        except OSError:
            return False
        _http_server = server
    thread = threading.Thread(
        target=server.serve_forever, name='ensp-http', daemon=True
    )
    thread.start()
    log(f'Web UI / API listening on http://{host}:{port}')
    return True


def run_http_server(host='127.0.0.1', port=5000):
    """Run the web server in the current (main) thread."""
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True)
    log(f'Web UI / API listening on http://{host}:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    run_http_server(
        host=os.environ.get('ENSP_HOST', '127.0.0.1'),
        port=int(os.environ.get('ENSP_PORT', '5000')),
    )
