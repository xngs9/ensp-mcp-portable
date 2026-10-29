# Upstream: https://github.com/llz-2002/ensptomcpfortrae (author: llz-2002).
"""Single entry point for the portable eNSP MCP server.

Modes:
  eNSP-MCP.exe                  start the Web UI / HTTP API and open a browser
  eNSP-MCP.exe --server         same, without opening a browser
  eNSP-MCP.exe --mcp            run the stdio MCP server; the embedded web
                                server is started automatically in a background
                                thread (unless --no-server is given)
"""

import argparse
import asyncio
import os
import sys
import threading
import time
import webbrowser

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5000


def log(message):
    # stdout belongs to the MCP JSON-RPC stream; diagnostics go to stderr.
    sys.stderr.write(f'[eNSP-MCP] {message}\n')
    sys.stderr.flush()


def setup_utf8_stdio():
    for stream_name in ('stdin', 'stdout'):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding='utf-8')
        except Exception:
            pass


def probe_server(host, port, timeout=0.5):
    """Return True if an eNSP HTTP API answers at host:port."""
    import urllib.request
    # Bypass any system HTTP proxy: this is a localhost call.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://{host}:{port}/api/devices', timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_server(host, port):
    """Make sure a web server is serving on host:port."""
    import app as ensp_app
    if ensp_app.start_http_server(host, port):
        return True
    if probe_server(host, port):
        log(f'{host}:{port} already serves the eNSP API, reusing it')
        return True
    log(f'{host}:{port} is occupied but is not the eNSP API')
    return False


def watchdog(host, port, stop_event):
    """Take over the port if the instance that owned it exits."""
    import app as ensp_app
    while not stop_event.wait(5.0):
        if probe_server(host, port, timeout=0.5):
            continue
        log(f'web server on {host}:{port} went away, trying to take over')
        if ensp_app.start_http_server(host, port):
            log('web server restarted in this process')


def run_mcp(host, port, start_server=True):
    setup_utf8_stdio()
    os.environ['ENSP_SERVER_URL'] = f'http://{host}:{port}'
    if start_server:
        ensure_server(host, port)
        stop_event = threading.Event()
        threading.Thread(
            target=watchdog,
            args=(host, port, stop_event),
            name='ensp-watchdog',
            daemon=True,
        ).start()
    from mcp_server import run_mcp_server
    asyncio.run(run_mcp_server())


def run_selftest(host, port):
    """Check the embedded server and scan for eNSP devices without any AI."""
    import json
    import urllib.request
    import app as ensp_app

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    if not ensp_app.start_http_server(host, port):
        if not probe_server(host, port):
            log(f'selftest FAILED: cannot listen on {host}:{port}')
            return 1
        log(f'selftest: reusing the server already on {host}:{port}')

    if not probe_server(host, port):
        log('selftest FAILED: server did not answer /api/devices')
        return 1
    log('selftest: HTTP server OK')

    try:
        url = f'http://{host}:{port}/api/devices/scan?start=2000&end=2050'
        with opener.open(url, timeout=60) as resp:
            devices = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        log(f'selftest FAILED while scanning: {exc}')
        return 1

    if devices:
        log(f'selftest: found {len(devices)} eNSP device(s)')
        for device in devices:
            log(f"  port {device.get('port')}  {device.get('path')}")
        return 0

    log('selftest: server works, but no eNSP devices were found on 2000-2050')
    log('selftest: open eNSP and start the devices, then run this again')
    return 2


def run_server(host, port, open_browser=True):
    import app as ensp_app
    if open_browser:
        def open_later():
            time.sleep(1.0)
            try:
                webbrowser.open(f'http://{host}:{port}/')
            except Exception:
                pass
        threading.Thread(target=open_later, daemon=True).start()
    try:
        ensp_app.run_http_server(host, port)
    except OSError as exc:
        log(f'cannot listen on {host}:{port}: {exc}')
        log('another program may be using the port; try --port with a free one')
        sys.exit(1)


def _stdin_is_tty():
    try:
        return sys.stdin.isatty()
    except Exception:
        return True


def main():
    parser = argparse.ArgumentParser(
        description='eNSP MCP server: Web UI + stdio MCP in one executable'
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--mcp', action='store_true',
        help='run as a stdio MCP server for AI clients',
    )
    mode.add_argument(
        '--server', action='store_true',
        help='run the Web UI / HTTP API (default)',
    )
    mode.add_argument(
        '--selftest', action='store_true',
        help='check the server and scan for eNSP devices, then exit',
    )
    parser.add_argument(
        '--no-server', action='store_true',
        help='with --mcp: do not start the embedded web server',
    )
    parser.add_argument(
        '--no-browser', action='store_true',
        help='with --server: do not open a browser',
    )
    parser.add_argument(
        '--host', default=os.environ.get('ENSP_HOST', DEFAULT_HOST),
        help=f'listen address (default {DEFAULT_HOST})',
    )
    parser.add_argument(
        '--port', type=int,
        default=int(os.environ.get('ENSP_PORT', str(DEFAULT_PORT))),
        help=f'listen port (default {DEFAULT_PORT})',
    )
    args = parser.parse_args()

    if args.selftest:
        sys.exit(run_selftest(args.host, args.port))
    elif args.mcp:
        run_mcp(args.host, args.port, start_server=not args.no_server)
    elif args.server or args.no_browser or _stdin_is_tty():
        run_server(args.host, args.port, open_browser=not args.no_browser)
    else:
        # A client launched us with pipes but no --mcp.  Treat that as MCP
        # mode; a human double-clicking the exe still gets a console (TTY)
        # and therefore the Web UI.
        log('stdin is piped and no mode was given; running as stdio MCP')
        run_mcp(args.host, args.port, start_server=not args.no_server)


if __name__ == '__main__':
    main()
